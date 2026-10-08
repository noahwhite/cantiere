# ADR-0015: Privileged actions pass one policy check and land in a hash-chained audit log

- Status: Accepted
- Date: 2026-10-07
- Requirements: SEC-4, SEC-5, SEC-6, WF-4, GH-5, GH-7, ID-3

## Context

Because credentials stay outside the sandbox (ADR-0010), privileged actions (push, PR open or merge, workflow dispatch, Linear status change, API calls through the worker's proxies, including cloud mutations) are executed or forwarded by the worker or server on the session's behalf.
That gives one enforcement point; it needs one place where the rules live and one record of what happened.
Three paths bypass it: a direct credential minted into the guest and the per-session SSH agent (both ADR-0010), and tailnet traffic (ADR-0011).
Actions on those paths are not decided here, and only the SSH agent's commit signatures are audited (ADR-0012); they are bounded by the credential's scope and lifetime and by the tailnet ACL, and persona validation limits which scopes and tags a persona may declare.

## Decision

- **Policy decision point:** a single `policy.Decide(action, session, persona, context)` in the server, called by the worker's proxies (ADR-0010) and by server-side actions before execution. Workers cache decisions for low-risk, high-rate actions (for example `GET` to an allowed API) per session.
- **Rules as data:** persona definitions in the config repo (ADR-0017) declare allowed actions, repos, branches, GitHub permissions, egress domains and budget; the engine evaluates those declarations plus fixed platform invariants. Phase 1 implements rules in Java in the server over the persona schema; workers only cache decisions and never evaluate rules, so no second implementation exists. A general policy language (Cedar or OPA) is deferred until a second rule author exists.
- **Fixed invariants** that no persona can override:
  - push only to the session's own branch (SB-5);
  - reviewer and QA personas get no write action on git or production systems (SEC-4): through the proxies by decision, and for direct credentials and tailnet tags by persona validation that rejects `write` scopes (ADR-0010, ADR-0011);
  - merge requires a recorded review on the current head plus a human approval (WF-4);
  - actions whose arguments came from untrusted content are marked and cannot satisfy a high-impact rule on their own (SEC-6, enforced from Phase 2).
- **Audit log:** an `audit_events` table, insert-only for the application role (no `UPDATE` or `DELETE` grants), each row carrying session, persona, actor (bot or linked user), action, target, head SHA, decision, and the SHA-256 of the previous row, so tampering is detectable. Appends are serialized per tenant: the writer locks the tenant's chain-head row (`SELECT ... FOR UPDATE`) in the same transaction as the insert, and each row has a monotonic `chain_seq` with `UNIQUE (tenant_id, chain_seq)` and `UNIQUE (tenant_id, prev_hash)`, so concurrent actions cannot fork the chain. A daily digest of the chain head is written to the object store.

## Consequences

- Prompt text is never a security control; a denied action is a policy result, recorded and surfaced on the timeline.
- Adding a new privileged integration means adding it to the action catalog, which forces a policy decision and an audit record.

## Alternatives considered

- **Rules enforced in each integration:** duplicated and easy to miss in new code.
- **OPA or Cedar from day one:** expressive, but a second language and runtime before there is more than one rule author.
