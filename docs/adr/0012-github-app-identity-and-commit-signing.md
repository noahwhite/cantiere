# ADR-0012: Per-deployment GitHub App, optional user linking, and Verified commits signed through a forwarded agent

- Status: Proposed - accept when validation check 1 below passes, with checks 2 and 3 passing or their fallbacks in use (Phase 1, slice 1; they need the git proxy)
- Date: 2026-10-07
- Requirements: GH-1, GH-2, GH-3, GH-5, GH-6, GH-7, GH-8, GH-9, SEC-5, SEC-7, UX-6

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
Either identity commits with an email address GitHub has verified on its account: when the identity is linked, the server lists them through the app's read-only user permission for email addresses (`GET /user/emails`), the user (for the machine user, the operator in the setup wizard) picks one (the account's no-reply address if GitHub lists it), and the choice is stored with the link.
If the account blocks pushes that expose a private address, GitHub rejects the push, and the timeline says to pick another address.
The server rechecks that the stored address is still verified on the account at session start and before each push: at session start a failed check of a linked user's address runs a `user`-mode session with machine-user commits and the user as co-author (GH-8), a failed check of the machine user's address stops any session that would commit as it from starting and alerts the operator, and before a push it makes the proxy refuse the push, with the timeline saying why, so a commit with an unverified address is never published.
Whether GitHub shows a signed commit as Verified depends on the account (its address and its registered keys), so the proxy guarantees the signature and identity, and after each push it reads the head commit's verification through the commits API and reports any other result, such as `no_user` or `unverified_email`, in the timeline and the audit log.
A `bot`-mode session with a linked user credits that user with a `Co-authored-by` trailer.

**Signing through a forwarded agent (GH-8, SEC-7).** At session start of a persona with write access, the worker generates an SSH signing key for the session's commit identity, has the server record its fingerprint, and registers it on that account under the title `cantiere-<session-id>` (a label only; keys are always matched by fingerprint) with the identity's user token (`POST /user/ssh_signing_keys`, through the app's user permission for SSH signing keys).
The private key stays in the worker; the guest reaches it through the session's SSH agent socket (ADR-0010), and its git config sets the identity's name and email, `gpg.format=ssh`, `user.signingkey` to the public key, and `commit.gpgsign=true`.
The coding agent commits with plain `git commit`, which signs through the SSH agent, so commits are signed when they are made and their SHAs never change.
The SSH agent signs with this key only requests in git's `git` signature namespace and writes the hash of each signed payload to the audit log (ADR-0015); it never uses the SSH-to-hosts key for such requests.
At session end the SSH agent dies, and the worker deletes the key from GitHub and discards it.
The server also lists each commit identity's signing keys (`GET /user/ssh_signing_keys`) and deletes every key whose fingerprint it recorded for a session that has ended, so a worker that crashed before or after registering a key cannot leave it registered.
Reviewer, QA and other read-only personas get no signing key, since they cannot push.

**Unlinking (GH-9).** Unlinking an identity, which its user or the operator can do, is a durable workflow (ADR-0006):

1. The server marks the link `unlinking` and stops handing the identity's access tokens to sessions; from then on only this workflow refreshes the token, through the serialized refresher, whenever a step needs a valid one, so a delayed step still gets one; a new session that needs the link waits in the inbox until it is linked again (for the machine user, the operator is alerted), and the link cannot be re-created until this workflow ends, so step 4 can never revoke a newer link. If the refresh fails because the user already revoked the app at GitHub, steps 3 and 4 are skipped, and the UI lists the recorded keys for the user to delete in their GitHub settings.
2. The server sends a pause message to every running session that uses the link: `user`-mode sessions of that user, `bot`-mode sessions that credit that user as co-author, and, for the machine user, every session that commits as it. Each session workflow interrupts the current turn and holds its input queue, as for take-over (ADR-0013); the worker drops the identity's access token from its proxies and its signing key, if the session holds one, from the SSH agent; and the session waits in the inbox with the reason (UX-6). A session whose worker is unreachable pauses when the worker reconnects, since the message is durable.
3. The server deletes the signing keys whose fingerprints it recorded for the identity (per-session keys, or under the check 3 fallback its long-lived key, also removed from the secret store), never the account's own keys. It retries failed deletions for a bounded time, then goes on to step 4 and lists any key it could not delete for the user to delete in their GitHub settings, so a failing deletion never delays revocation.
4. The server revokes the app's authorization for the account (`DELETE /applications/{client_id}/grant`, with an access token the workflow refreshed), which invalidates the refresh token and every access token already handed to a worker, so steps 3 and 4 never wait for step 2 to be confirmed. Step 3 runs first because deleting a key needs the identity's token. The workflow then deletes the stored refresh token and removes the link.

The inbox item offers to end the session or, once the same GitHub account (matched by its account ID) is linked again, to resume it; linking a different account offers only ending it, so paused work is never credited to another account.
Resume runs only at that point, before the runtime continues, and what it does depends on the session's commit identity, not its authoring mode:

- A session that commits as the unlinked identity (a `user`-mode session whose commits are the user's own, or any session that commits as an unlinked machine user) had its key deleted in step 3, so on resume the worker registers a new session key, and its unpushed commits are recreated (below) to be signed with it and to carry the identity's current chosen address, which may differ after re-linking, as author and committer email.
- A session that commits as the machine user and only credits the user (`bot` mode, or `user` mode under the check 2 or address fallbacks) keeps the machine user's key and needs no new one; if the user's chosen address changed, its unpushed commits are recreated (below) with their `Co-authored-by` trailers naming the new address, as push check 2 requires. Its inbox item also offers to resume at once without credit: the session then credits no one until it ends, even if the user links again, so push check 2 requires no trailer, and unpushed commits keep the trailers they already have.

Recreation runs in the guest: in topological order over the commits push check 2 would count, the adapter recreates each with `git commit-tree -S`, keeping its tree and author name and date, changing only the address or trailer above, and mapping its parents to their recreated copies.
It then moves the branch to the new head and tells the runtime the SHAs changed.
Unlike a rebase, this reapplies no changes, so every tree, merge included, and every commit is kept exactly.
Nothing already pushed is touched.

**Push checks (SEC-7).** When the guest pushes the session branch, the git proxy:

1. Rejects anything not on the session branch, and runs the secret scan (ADR-0010).
2. Rejects the push unless every commit the push adds to the session branch (reachable from the new head, but not from the branch's previous head or from the base branch's current tip, both read from GitHub at push time) is signed by a key the server recorded for this session and has not deleted (a worker restart that generates a new key keeps the earlier ones valid until session end) or, under the check 3 fallback, by the identity's long-lived key, has the session's commit identity as author and committer, and, whenever the machine user commits in a session that credits a linked user (`bot` mode, or `user` mode under the check 2 or address fallbacks), carries that user's `Co-authored-by` trailer with their current chosen address.
3. Pushes with the installation token in `bot` mode or the user's token in `user` mode.

Every commit a session adds to its branch is signed; commits that others push to the branch, for example a human PR branch the session is steering (GH-4), are outside the guarantee, like base history below; there is no unsigned fallback (SEC-7; the project owner decided this on 2026-10-08).
Each refused push is written to the audit log (ADR-0015).
The guarantee covers the commits a session adds; commits already on the base branch are the repository's own history and are outside it, including if the base branch is later rewound so that one of them reappears in the PR.

## Validation checks

1. A per-session key registered on the machine user signs guest commits through the agent, and the pushed commits, with the machine user's chosen verified address as committer, show Verified as the machine user.
2. The same holds in `user` mode, with the key registered through the linked user's token, and the commits show Verified as the user.
3. Commits pushed while a session key was registered stay Verified after the key is deleted from GitHub (GitHub records verification at push time and keeps it when keys are [rotated or revoked](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification); deletion is not documented).

If check 1 fails, the git proxy refuses `bot`-mode pushes, and Phase 1 does not exit until check 1 passes, because `bot` is the default mode (GH-7) and test 11 requires Verified bot commits.
If check 2 fails, `user` mode falls back to machine-user commits with the user as co-author, as GH-8 already allows.
If check 3 fails, each identity gets one long-lived signing key instead, generated at link time, held in the secret store and loaded into the session's agent; it is still never in the sandbox, but signatures it made stay valid until the key is rotated.

## Consequences

- No GitHub credential or signing key ever enters a sandbox; the guest holds only the agent socket.
- Git works as in a terminal: commits are signed when made, SHAs do not change at push, and there is no staging branch or commit recreation at push.
- Unlinking pauses every session that uses the identity; resuming one may recreate its unpushed commits (a new key or address), the only case where Cantiere changes a local commit's SHA.
- `bot`-mode commits show the deployment's machine user, not the app, as author and committer.
- The SSH agent is a signing oracle for the session's lifetime: code in the sandbox can get commits signed that the proxy never sees. Such a commit verifies only as the session's identity, and only if pushed to GitHub before the key is deleted at session end (check 3). Egress goes only through the worker's proxies (ADR-0007), and every signature is audited, so signatures that match no pushed commit, which ordinary amends and local rebases also leave, can be reviewed.
