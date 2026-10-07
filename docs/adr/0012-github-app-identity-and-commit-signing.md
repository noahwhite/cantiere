# ADR-0012: Per-deployment GitHub App, optional user linking, and Verified commits without keys in the sandbox

- Status: Proposed - accept when the validation checks below pass (Phase 1, slice 1; they need the git proxy)
- Date: 2026-10-07
- Requirements: GH-1, GH-2, GH-3, GH-5, GH-6, GH-7, GH-8, SEC-5, SEC-7

## Context

The requirements already settle the identity model: each deployment registers its own public GitHub App, acts only on operator-approved installations, and optionally lets users link their accounts so their sessions author PRs and commits as them (GH-1 to GH-8).
This ADR records how that is built on top of ADR-0010, where no GitHub credential enters the sandbox.

## Decision

**App setup (GH-1, GH-2).** The setup wizard posts a shipped app manifest to GitHub's manifest flow, receives the app ID, private key and webhook secret, and writes them straight to the secret store; the app is created as public.

**Installations (GH-3).** Installation webhooks create pending records (account, installation ID, repos, permissions); the operator approves an installation and optionally a repo subset in the UI. Events from unapproved installations are dropped and logged.

**Session tokens (GH-5).** Per ADR-0010: minted per session from the installation that owns each target repo, narrowed with `repository_ids` and the persona's permission set, held by the worker. Reviewer and QA personas get read-only permission sets.

**User linking (GH-6).** The user authorizes the app through its user authorization flow, and the server stores the refresh token in the secret store under that user. User access tokens are requested with `repository_id` where GitHub supports it ([docs](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)). That parameter is not accepted on refresh, so it is defense in depth only: the token is applied only by the worker proxies, whose policy enforces the persona's permissions (ADR-0010). GitHub rotates the refresh token on every use, so one serialized refresher per user (a Postgres advisory lock in the server) refreshes and stores it, and sessions only ever receive access tokens.

**Authoring mode (GH-7).** Per persona and per session: `bot` (default) or `user`. Reviewer personas are always `bot`. PRs and comments use the matching token.

**Verified commits at push time (GH-8, SEC-7).** The agent commits locally, unsigned; nothing in the sandbox can obtain a signature. When the guest pushes the session branch, the git proxy:

1. Rejects merge commits and anything not on the session branch, and runs the secret scan (ADR-0010).
2. Pushes the original objects to a short-lived staging branch `cantiere-staging/<session-id>` with the installation token, so every blob and tree already exists on GitHub.
3. Recreates each commit with one `POST /repos/{owner}/{repo}/git/commits` call that reuses the existing tree SHA:
   - `bot` mode: with the installation token and no author, committer or signature, so GitHub signs it as the app and shows it Verified ([commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)); a linked user is credited with a `Co-authored-by` trailer;
   - `user` mode: with the user's token, the user as author and committer, and a `signature` the worker computes with the user's SSH signing key. The key is generated at link time, stored in the secret store, and registered on the user's account through the app's user permission for SSH signing keys. The worker signs only commit objects it is itself creating for this push.
4. Moves the session branch to the recreated head, deletes the staging branch, and returns the new SHAs.

This costs one API call per commit, independent of the number of files, which stays well inside GitHub's content-creation rate limits.
The guest performs pushes through its own `git push` wrapper, which holds the repository lock for the push. After a successful push it rebases any commits made in the meantime onto the recreated head; the trees are identical, so the rebase cannot conflict.

## Validation checks

1. Recreated bot commits show Verified, keep the original tree (file modes, symlinks), and the guest branch update leaves a clean working tree.
2. The app can register a user SSH signing key with a user token, and commits created with a worker-computed `signature` show Verified as the user.
3. Pushes to `cantiere-staging/*` are allowed by the target repo's rulesets, and staging branches do not trigger CI (the reference workflow ignores the prefix).

If check 1 fails, `bot` mode falls back to plain pushes of unsigned bot commits, with a repository ruleset that does not require signatures for the app.
If check 2 fails, `user` mode falls back to bot commits with the user as co-author, as GH-8 already allows.

## Consequences

- No GitHub credential or signing key ever enters a sandbox.
- Local SHAs change after each push in both modes; tools that cache SHAs across a push must re-read the branch, and the adapter adds a timeline note when it happens.
- The user's signing key never signs anything the sandbox chose to have signed, only commits the worker builds from audited pushes.
