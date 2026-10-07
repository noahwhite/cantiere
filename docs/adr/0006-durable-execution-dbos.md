# ADR-0006: Sessions and workflows run as durable workflows on DBOS Transact (Go), in-process on Postgres

- Status: Accepted
- Date: 2026-10-07
- Requirements: OBS-1, WF-1, WF-2, WF-4, WF-7, UX-3, UX-6, COST-2

## Context

A session is a long-running process with waits on humans (messages, approvals, take-over), on budgets, and on workers.
OBS-1 requires that a control-plane restart loses nothing and running sandboxes reattach; Phase 2 adds child sessions and resumable multi-step workflows with human gates (WF-1, WF-2, WF-4).
Choosing the execution model now avoids writing the session lifecycle twice.
ADR-0005 limits stateful dependencies to Postgres.

| Option | In-process | Store | Child workflows | Durable human wait | License |
| --- | --- | --- | --- | --- | --- |
| [DBOS Transact Go](https://github.com/dbos-inc/dbos-transact-golang) v1.5 | Yes | Postgres | Yes | `Recv` with timeout, events | MIT |
| [River](https://github.com/riverqueue/river) OSS | Yes | Postgres | No (jobs only) | No (River Pro, paid) | MPL-2.0 |
| [Temporal](https://docs.temporal.io/self-hosted-guide/embedded-server) | Dev/test only | Postgres plus its own services | Yes | Signals | MIT |
| Restate | No, separate server | Own log | Yes | Awakeables | BSL 1.1 server |
| Hatchet | No, separate engine | Postgres | Yes | `WaitForEvent` | MIT |

## Decision

Use **DBOS Transact Go** inside `cantiere-server`, on the deployment's Postgres.

- Each session is one durable workflow: schedule -> provision sandbox -> run turns -> wait for input, approval, take-over or budget -> finalize -> tear down. Every external effect (worker command, GitHub call, Linear update) is a step with an idempotency key.
- Human input, approvals and take-over hand-back are durable messages (`Send`/`Recv`) addressed to the session workflow, so the inbox (UX-6) is a view over workflows waiting on a human.
- Child sessions (WF-1, Phase 2) are child workflows; workflow scripts with `agent()`, `parallel()`, `pipeline()` and human gates (WF-2) compile onto the same primitives.
- Stall and loop detection (WF-7) and budget stops (COST-2) are timers and messages on the session workflow.
- DBOS keeps its own system tables without a `tenant_id` column; every workflow input and workflow ID carries the tenant, which is the one documented exception to ADR-0005's tenancy rule.
- The engine is used only behind a small internal `durable` package so it can be replaced without touching session logic.

## Consequences

- No extra service to install or back up; a server restart resumes every workflow from its last completed step and re-attaches to sandboxes through the worker stream (ADR-0003).
- DBOS Transact Go reached 1.x in 2026 and has a small community; the internal package boundary and Temporal-compatible concepts keep a migration path open.
- Steps must be idempotent, which is enforced in review and tests.

## Alternatives considered

- **Hand-rolled state machine on River OSS:** workable for Phase 1 sessions, but Phase 2 child workflows and human gates would mean building a workflow engine.
- **Temporal:** the strongest engine, but production needs its own multi-service cluster, against OSS-2.
