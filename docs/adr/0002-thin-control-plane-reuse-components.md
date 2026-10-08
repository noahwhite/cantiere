# ADR-0002: Build a thin control plane and reuse components, not a fork of an existing platform

- Status: Accepted
- Date: 2026-10-07
- Requirements: RT-1, RT-2, OSS-1, OSS-3, OSS-6; open question "Build on OpenHands' runtime and UI, or a thin new control plane over Coder/Firecracker?"

## Context

The requirements name OpenHands, Coder, E2B and microsandbox as starting points.
Cantiere's differentiators are the parts none of them own: hosting existing agent CLIs (not its own agent loop), per-session credential brokering, workflows with human gates, and a ticket-driven operating model.

| Candidate | What it would give | Why it is not the base |
| --- | --- | --- |
| OpenHands | Sandbox runtime, web UI, resolver | Built around its own agent loop and action model; external CLIs would be guests in someone else's event model, and every upstream refactor would land on our core |
| Coder | Terraform-defined workspaces, network controls | A long-lived developer-workspace product; per-session disposable sandboxes, brokers and workflows would all be built on top of a model that does not fit them |
| E2B self-host | Firecracker sandboxes with an SDK | Infrastructure is built for a hosted multi-tenant service (see ADR-0007 for the sandbox decision) |

## Decision

Build a new, deliberately thin control plane that owns sessions, scheduling, workflows, brokers, policy, audit and the timeline.
Reuse proven components at well-defined seams instead of forking a platform:

| Seam | Reused component | Owned by Cantiere |
| --- | --- | --- |
| Isolation | Firecracker (ADR-0007) | Sandbox provider interface, image and snapshot pipeline (ADR-0008) |
| Agent loop | Claude Code headless; any ACP agent (opencode, Codex, Kimi CLI, goose, Gemini CLI) | Runtime adapters and event schema (ADR-0009) |
| Terminal and editor | xterm.js, code-server | Session transport (ADR-0013) |
| Durable execution | Library on Postgres (ADR-0006) | Session and workflow definitions |
| Secrets | External secret store | Broker, injection and policy (ADR-0010) |

Every seam that a user may want to swap (sandbox backend, secret store, issue tracker, chat, object store) is an interface in the component that owns it (a Java interface in the server, a Rust trait in the worker) with at least one first-party implementation in Phase 1 (OSS-3); the secret store has two, OpenBao and Bitwarden Secrets Manager (ADR-0010).

## Consequences

- More code to write up front than a fork, but no upstream to track and no foreign agent loop in the core.
- The control plane stays small enough to audit, which matters because it holds every credential.
- OpenHands and Coder remain useful as references and benchmarks; Phase 0 still measures them so the choice is evidenced.

## Alternatives considered

- **Fork OpenHands:** fastest demo, slowest path to a CLI-hosting platform; rejected above.
- **Coder plus a scheduler on top:** environment only, no orchestration; rejected above.
