# ADR-0006: Sessions and workflows run as durable workflows on DBOS Transact (Java), in-process on Postgres

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
| [DBOS Transact Java](https://github.com/dbos-inc/dbos-transact-java) v1.0 ([July 2026](https://dbos.dev/blog/new-in-dbos-july-2026)) | Yes | Postgres | Yes | `recv` with timeout, events | MIT |
| [JobRunr](https://github.com/jobrunr/jobrunr) OSS | Yes | Postgres | No (jobs only) | No | LGPL-3.0 |
| [Temporal](https://docs.temporal.io/self-hosted-guide/embedded-server) | Dev/test only | Postgres plus its own services | Yes | Signals | MIT |
| Restate | No, separate server | Own log | Yes | Awakeables | BSL 1.1 server |
| Hatchet | No, separate engine | Postgres | Yes | `WaitForEvent` | MIT |

## Decision

Use **DBOS Transact Java** inside `cantiere-server` (Quarkus, ADR-0004), on the deployment's Postgres.
DBOS ships a Spring Boot starter and no Quarkus integration, so it is used as a plain library: one DBOS instance is configured and launched from a CDI producer at startup, and workflow classes are CDI beans registered with it.

- Each session is one durable workflow: schedule -> provision sandbox -> run turns -> wait for input, approval, take-over or budget -> finalize -> tear down. Every external effect (worker command, GitHub call, Linear update) is a step with an idempotency key.
- Human input, approvals and take-over hand-back are durable messages (`send`/`recv`) addressed to the session workflow, so the inbox (UX-6) is a view over workflows waiting on a human.
- Child sessions (WF-1, Phase 2) are child workflows; workflow scripts with `agent()`, `parallel()`, `pipeline()` and human gates (WF-2) compile onto the same primitives.
- Stall and loop detection (WF-7) and budget stops (COST-2) are timers and messages on the session workflow.
- DBOS keeps its own system tables without a `tenant_id` column; every workflow input and workflow ID carries the tenant, which is the one documented exception to ADR-0005's tenancy rule.
- The engine is used only behind a small internal `durable` module so it can be replaced without touching session logic.
- Steps that write Cantiere's own tables run through DBOS's jOOQ step factory (`PostgresStepFactory`), which commits the step's writes and its checkpoint in one transaction, rather than inside a Quarkus `@Transactional` boundary. DBOS's annotation-based transactional steps exist only for Spring, so they are not used. A Phase 1 slice 1 test proves this: a step that writes a row and is killed before returning leaves either both the row and the checkpoint or neither.

## Consequences

- No extra service to install or back up; a server restart resumes every workflow from its last completed step and re-attaches to sandboxes through the worker stream (ADR-0003).
- DBOS Transact Java reached 1.0 in July 2026 and has a small community; the internal module boundary and Temporal-compatible concepts keep a migration path open, and Temporal's Java SDK is the most mature alternative if one is needed.
- Steps must be idempotent, which is enforced in review and tests.

## Alternatives considered

- **Hand-rolled state machine on a job queue (JobRunr, Quartz):** workable for Phase 1 sessions, but Phase 2 child workflows and human gates would mean building a workflow engine.
- **Temporal:** the strongest engine, but production needs its own multi-service cluster, against OSS-2.
