# ADR-0012: Per-deployment GitHub App, optional user linking, and Verified commits signed through a forwarded agent

- Status: Proposed - accept when validation check 1 below passes, with checks 2 and 3 passing or their fallbacks in use (Phase 1, slice 1; they need the git proxy)
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

**Authoring mode (GH-7).** Per persona and per session: `bot` (default) or `user`. Reviewer personas are always `bot`. PRs and comments use the matching token; commits use the matching commit identity below.

**Commit identity (GH-7, GH-8).** A GitHub App cannot hold a signing key, so `bot`-mode commits come from a machine user the deployment owns: the setup wizard asks the operator to create one and to link it like any user (GH-6).
It needs no access to any repo, because GitHub verifies a signature against the committer's account, not repo membership.
PRs and comments in `bot` mode still come from the app.
In `user` mode, commits come from the linked user.
Either identity commits with its account's ID-based GitHub no-reply address (`<id>+<login>@users.noreply.github.com`), which GitHub ties to the account, so verification does not depend on which emails a user has made public or verified, and the app needs no email permission.
Some accounts created before July 2017 still use `<login>@users.noreply.github.com` until their email privacy setting is changed ([email addresses reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference)), so linking asks the user to turn email privacy off and on once if needed, and after each push the proxy reads the head commit's verification through the commits API and reports a `no_user` or `unverified_email` result in the timeline.
A `bot`-mode session with a linked user credits that user with a `Co-authored-by` trailer.

**Signing through a forwarded agent (GH-8, SEC-7).** At session start of a persona with write access, the worker generates an SSH signing key for the session's commit identity, has the server record its fingerprint and a title `cantiere-<session-id>`, and registers it on that account with the identity's user token (`POST /user/ssh_signing_keys`, through the app's user permission for SSH signing keys).
The private key stays in the worker; the guest reaches it through the session's SSH agent socket (ADR-0010), and its git config sets the identity's name and email, `gpg.format=ssh`, `user.signingkey` to the public key, and `commit.gpgsign=true`.
The coding agent commits with plain `git commit`, which signs through the SSH agent, so commits are signed when they are made and their SHAs never change.
The SSH agent signs with this key only requests in git's `git` signature namespace and writes the hash of each signed payload to the audit log (ADR-0015); it never uses the SSH-to-hosts key for such requests.
At session end the SSH agent dies, and the worker deletes the key from GitHub and discards it.
The server also lists each commit identity's signing keys (`GET /user/ssh_signing_keys`) and deletes every key titled `cantiere-<session-id>` whose session has ended, so a worker that crashed before or after registering a key cannot leave it registered.
Reviewer, QA and other read-only personas get no signing key, since they cannot push.

**Push checks (SEC-7).** When the guest pushes the session branch, the git proxy:

1. Rejects anything not on the session branch, and runs the secret scan (ADR-0010).
2. Rejects the push unless every commit the push adds to the session branch (reachable from the new head, but not from the branch's previous head on GitHub or from the base tip the server recorded when it created the branch) is signed by the session's signing key, has the session's commit identity as author and committer, and, in `bot` mode with a linked user, carries that user's `Co-authored-by` trailer.
3. Pushes with the installation token in `bot` mode or the user's token in `user` mode.

Every commit a session adds to its branch, and therefore every commit in its PR, is signed; there is no unsigned fallback (SEC-7; the project owner decided this on 2026-10-08).
Each refused push is written to the audit log (ADR-0015).

## Validation checks

1. A per-session key registered on the machine user signs guest commits through the agent, and the pushed commits, with the machine user's no-reply address as committer, show Verified as the machine user.
2. The same holds in `user` mode, with the key registered through the linked user's token, and the commits show Verified as the user.
3. Commits pushed while a session key was registered stay Verified after the key is deleted from GitHub (GitHub records verification at push time and keeps it when keys are [rotated or revoked](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification); deletion is not documented).

If check 1 fails, the git proxy refuses `bot`-mode pushes, and Phase 1 does not exit until check 1 passes, because `bot` is the default mode (GH-7) and test 11 requires Verified bot commits.
If check 2 fails, `user` mode falls back to machine-user commits with the user as co-author, as GH-8 already allows.
If check 3 fails, each identity gets one long-lived signing key instead, generated at link time, held in the secret store and loaded into the session's agent; it is still never in the sandbox, but signatures it made stay valid until the key is rotated.

## Consequences

- No GitHub credential or signing key ever enters a sandbox; the guest holds only the agent socket.
- Git works as in a terminal: commits are signed when made, SHAs do not change at push, and there is no staging branch or commit recreation.
- `bot`-mode commits show the deployment's machine user, not the app, as author and committer.
- The SSH agent is a signing oracle for the session's lifetime: code in the sandbox can get commits signed that the proxy never sees. Such a commit verifies only as the session's identity, and only if pushed to GitHub before the key is deleted at session end (check 3). Egress goes only through the worker's proxies (ADR-0007), and every signature is audited, so the audit log shows any signature that matches no pushed commit.
