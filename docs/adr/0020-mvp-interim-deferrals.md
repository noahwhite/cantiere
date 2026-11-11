# ADR-0020: The MVP ships a narrowed slice of milestone 1, with each deferral named and bounded

- Status: Accepted
- Date: 2026-11-11
- Requirements: SB-1, SB-2, SB-3, RT-4, GH-1, GH-3, GH-6, UX-2, UX-4, UX-5, SEC-2, SEC-7, ID-1, COST-1, COST-2, COST-3, OBS-2, OSS-1, OSS-2, OSS-4

## Context

Milestone 1 (architecture.md) is specified by ADR-0002 to ADR-0019, and no code exists yet.
The first deliverable is an MVP: from the web UI, a prompt starts a session in a Firecracker microVM, Claude Code runs headless, the timeline streams live, the operator can send a message and take over a shell, signed commits reach the session branch, a PR opens as the app bot, and the VM is destroyed.
Building everything those ADRs specify before the first session runs would delay the evidence several of them wait on (ADR-0007, ADR-0012).
Leaving parts out without a record would let the gaps become permanent.

## Decision

The MVP follows ADR-0002 to ADR-0019 as written, except for the deferrals in the table below.
This ADR supersedes none of them: each deferral is a named, temporary gap, and the deferred behaviour is still the decision.

**Limits that hold while any deferral is open.**

- One operator, who is also the Claude subscriber (ADR-0014).
- The server and UI listen only on the operator's tailnet.
- Sessions run only against repositories on an allowlist in the server's configuration, all owned by the operator.
- Sessions use Claude subscription mode only.
- No tagged release is described as ready for other deployments.

**Not deferred.**

- **Signed commits (SEC-7, ADR-0012).** Every commit a session adds is signed through the session's SSH agent, the key never enters the sandbox, and the git proxy refuses any push that fails push checks 1 and 2. There is no unsigned path in the MVP.
- No GitHub credential enters the sandbox; fetch and push go through the git proxy, which allows push only to the session branch (ADR-0010).
- Default-deny egress on the host with the allowlist resolver and the egress proxy matching SNI (ADR-0011).
- `policy.Decide` in front of every privileged action, the hash-chained audit log (ADR-0015), and secret scrubbing at the worker (ADR-0010).
- The three-tier topology, the protobuf contracts, `tenant_id` on every record, and the session as a DBOS workflow (ADR-0003, ADR-0004, ADR-0005, ADR-0006).
- `Origin` and CSRF checks on every state-changing request and WebSocket upgrade (ADR-0016).

**Deferrals.**

| # | Deferred | ADR | MVP behaviour | Ends before |
| --- | --- | --- | --- | --- |
| 1 | Per-session signing keys registered through a linked identity, and the verified-address recheck | 0012 | The operator creates the machine user, registers one signing key on it and stores the private key in the secret store. The worker loads it into each session's SSH agent, which is the mechanism ADR-0012 gives as its check 3 fallback. The commit address is set in server configuration. After each push the server reads the head commit's verification and reports any result other than Verified. | A second commit identity exists, or validation checks 1 and 3 are run |
| 2 | User linking, `user` authoring mode, unlinking | 0012 | `bot` mode only: commits as the machine user, PRs and comments as the app. No `Co-authored-by` trailer is added or allowed. | A second user exists |
| 3 | App manifest setup, installation webhooks, installation approval in the UI | 0012 | The operator registers the app by hand. The app key lives in the secret store. Approved installations and repositories are the server's allowlist. No webhook endpoint is exposed. | Phase 2 (IN-2 needs webhooks) |
| 4 | The confined per-session proxy process | 0014 | The git proxy and the egress proxy run inside the worker process. | Any session holds a model API key, or runs against a repository the operator does not own |
| 5 | `inspect` and `inject` egress modes, the per-session CA, the GitHub API route catalog | 0010, 0011 | The egress proxy implements `pass` only. The guest holds no HTTP API credential, `github.com` and `api.github.com` are not on the guest's allowlist, and the server opens the PR at the end of the session after a policy decision. | A session needs an HTTP API from inside the sandbox |
| 6 | The model gateway and API-key sessions | 0014 | Subscription mode only, so spend is the runtime-reported notional figure and budgets are best effort. A session does not start with a token past its recorded expiry, and an authentication failure pauses it. Renewal reminders and the renewal UI are absent; the operator replaces the token in the secret store. | A second user exists, or a session needs a budget cap that holds |
| 7 | OpenBao, dynamic credentials, SSH-to-hosts certificates | 0010, 0019 | Bitwarden Secrets Manager only, read-only, for the app key, the signing key and the subscription token. | A persona declares a database, cloud or SSH credential |
| 8 | Snapshot templates, the BuildKit build microVM, `blueprint.yaml`, rebuilds | 0007, 0008 | One template, built by a script in this repository that the operator runs, containing no code from a target repository. Sessions cold boot from reflink clones of its disks. ADR-0007 stays Proposed. | A target repository needs its own toolchain or setup commands; ADR-0007 is accepted only on its Phase 0 measurements |
| 9 | The deployment config repo, persona files, the skills drive | 0017, 0008 | One persona built into the server's configuration, with its repository allowlist, egress domains and GitHub permission set. Target repositories supply only `CLAUDE.md`. | A second persona exists |
| 10 | Passkey and OIDC sign-in | 0016 | The `users` table holds one owner. The browser signs in with a personal access token, stored hashed, and receives the session cookie ADR-0016 describes. | The UI is reachable from outside the operator's tailnet |
| 11 | code-server, the browser view, native-terminal take-over, the command palette, shell recording, sandbox origins | 0013, 0019 | Take-over is the human shell PTY, and it pauses the runtime as ADR-0013 describes. No guest-served web content exists, so no sandbox origin or wildcard certificate is needed. | Phase 1 exit |
| 12 | OTLP export | 0018 | Structured logs to the journal, carrying the session ID. Session content goes only to the timeline. | Phase 1 exit |
| 13 | `install.sh`, signed release artifacts, arm64 builds, the OpenTofu module, the Compose file | 0019 | systemd units and a documented manual install on one amd64 host. | The first release offered to other deployments |

**Rules for ending a deferral.**

- A deferral ends in the PR that delivers the deferred behaviour, which also removes its row from this table.
- A change that would cross a row's "Ends before" condition while the row is still open is refused in review.
- No row may be added to this table after this ADR is accepted; a new gap needs its own ADR.
- When the table is empty, this ADR's status becomes Superseded by the ADR or PR that removed the last row.

## Consequences

- The MVP's security claims are narrower than architecture.md's: a compromised worker process holds the session's GitHub token and the long-lived signing key (rows 1 and 4), and spend is not capped by construction (row 6). The limits above are what make that acceptable.
- The operator must create a machine user account and register a signing key on it before the first session can push (row 1).
- Signatures made with the long-lived key stay valid until the operator rotates it, as ADR-0012 notes for its fallback.
- Phase 1 does not exit while rows 1, 4, 5, 6, 8, 11 or 12 are open, because its exit depends on tests 8 to 11 of architecture.md.
- Requirements that milestone 1 lists and the MVP has not built yet, such as the CLI (IN-4), are unbuilt scope, not deferrals; this ADR covers only places where shipped behaviour differs from an accepted decision.

## Alternatives considered

- **Unsigned commits in the MVP:** removes the machine user and the SSH agent from the first slice, but contradicts the 2026-10-08 decision that there is no unsigned fallback, and the project owner rejected it again on 2026-11-11.
- **Amend each affected ADR:** keeps every decision in one place, but ADR-0001 forbids editing an accepted decision, and it would present temporary gaps as the design.
- **Build milestone 1 in full before running a session:** no deviations to track, but the first evidence for ADR-0007 and ADR-0012 arrives months later.
- **Worker-side push with no git proxy, and nftables with no egress proxy:** less code, but both replace mechanisms ADR-0010 and ADR-0011 already specify, so the MVP builds the minimal conforming version of each instead.
