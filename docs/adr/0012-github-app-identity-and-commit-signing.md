# ADR-0012: Per-deployment GitHub App, optional user linking, and Verified commits without keys in the sandbox

- Status: Proposed - accept when validation checks 1 and 3 below pass, with check 2 passing or its fallback in use (Phase 1, slice 1; they need the git proxy)
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
3. Recreates each commit with the same tree:
   - `bot` mode: one `POST /repos/{owner}/{repo}/git/commits` call per commit with the installation token and no author, committer or signature, so GitHub signs it as the app and shows it Verified ([commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)); a linked user is credited with a `Co-authored-by` trailer;
   - `user` mode: the worker builds each commit object itself (with `gix`), with the user as author and committer and a `gpgsig` SSH signature computed with the user's SSH signing key (`ssh-key`), and pushes the objects over git with the user's token. GitHub verifies SSH commit signatures from git pushes; its commits API documents its `signature` field as PGP only, so that API is not used here. The key is generated at link time, stored in the secret store, and registered on the user's account through the app's user permission for SSH signing keys. The worker signs only commit objects it is itself creating for this push.
4. Moves the session branch to the recreated head, deletes the staging branch, and returns the new SHAs.

In `bot` mode this costs one API call per commit, independent of the number of files, which stays well inside GitHub's content-creation rate limits.
The guest performs pushes through its own `git push` wrapper, which holds the repository lock for the push. After a successful push it rebases any commits made in the meantime onto the recreated head; the trees are identical, so the rebase cannot conflict.

## Validation checks

1. Recreated bot commits show Verified, keep the original tree (file modes, symlinks), and the guest branch update leaves a clean working tree.
2. The app can register a user SSH signing key with a user token, and worker-built commits signed with that key and pushed over git show Verified as the user, with the original tree.
3. Pushes to `cantiere-staging/*` are allowed by the target repo's rulesets, and staging branches do not trigger CI (the reference workflow ignores the prefix).

Every commit on a session branch, and therefore in any PR, is signed; there is no unsigned fallback (SEC-7; the project owner decided this on 2026-10-08).
The only unsigned commits that reach GitHub are the originals on the `cantiere-staging/<session-id>` branch from step 2, which exists only to upload objects, is never opened as a PR and is deleted in step 4.
If a push fails after step 2, the worker deletes the staging branch before returning the error.
In case the worker crashes instead, the server durably records each staging branch, with a timestamp from the server's clock, before every push to it (a later push in the same session refreshes the record), so a crash between the two leaves a record with no branch, never a branch with no record.
The git proxy starts steps 2 to 4 only after the server, reading its own clock, confirms the record is less than 30 minutes old.
On its monotonic clock, the proxy discards a confirmation it has not used within one minute of sending the request, and aborts steps 2 to 4 if the session branch has not moved within 30 minutes of starting.
Before reporting an abort or error, the proxy reads the session branch: if it already points at the recreated head, the push has succeeded and the proxy returns the new SHAs, even if deleting the staging branch failed, leaving that branch to the sweep.
Only the step 2 upload needs the staging ref; once step 2 completes, the objects are on GitHub, so a sweep during steps 3 or 4, or during a move still in flight after an abort, cannot change the outcome.
Every hour, the server deletes each `cantiere-staging/*` branch whose record is more than 90 minutes old; this leaves 30 minutes of margin after the latest a push can end, and does not rely on worker state.
A push stalled past these bounds may lose its staging branch to the sweep before the session branch moves; it then fails with the session branch unchanged, so the guest retries from the same head.
After the sweep no unsigned commit stays on any branch, though GitHub may keep the uploaded objects unreferenced until its own garbage collection.
If check 1 fails, the git proxy refuses bot-mode pushes, and Phase 1 does not exit until bot commits pass check 1, because `bot` is the default mode (GH-7) and test 11 requires Verified bot commits.
Each refused push is written to the audit log (ADR-0015).
If check 2 fails, `user` mode falls back to bot commits with the user as co-author, as GH-8 already allows.

## Consequences

- No GitHub credential or signing key ever enters a sandbox.
- Local SHAs change after each push in both modes; tools that cache SHAs across a push must re-read the branch, and the adapter adds a timeline note when it happens.
- The user's signing key never signs anything the sandbox chose to have signed, only commits the worker builds from audited pushes.
