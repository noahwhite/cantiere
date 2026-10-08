# ADR-0003: Three-tier topology - control plane, worker, guest agent - with workers dialing out

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-6, COST-4, COST-5, OBS-1, SEC-1, SEC-2

## Context

Phase 1 runs on one host, but OSS-6 requires that the control plane can later run apart from the sandboxes without a data migration, and COST-5 adds worker hosts by registration.
The sandbox must never reach the control plane or a secret store directly (SEC-1, ID-2).

## Decision

Cantiere has three runtime components, all built from one repository:

| Component | Runs where | Responsibilities |
| --- | --- | --- |
| `cantiere-server` (control plane) | One process per deployment | API, web UI, sessions, scheduling, workflows (ADR-0006), integrations, timeline, policy and audit (ADR-0015), secret-store access |
| `cantiere-worker` | One per worker host (KVM required) | Sandbox lifecycle (ADR-0007), images and snapshots (ADR-0008), per-session egress proxy, git proxy and credential injection (ADR-0010, ADR-0011), stream relay |
| `cantiere-guest` | PID 1 helper inside each sandbox | Runtime adapter host (ADR-0009), PTYs, file and process control; talks only to its worker over vsock |

Communication rules:

- The worker dials out to the server over one long-lived authenticated gRPC stream (HTTP/2, TLS) and receives work on it; the server never connects to a worker.
- A worker registers with a one-time join token and then holds a per-worker credential the server can revoke.
- The guest talks only to its own worker over vsock; the sandbox has no route to the server.
- Credentials needed by a session are sent from server to worker per session over that stream, held in worker memory, and never written to disk or sent into the guest (ADR-0010).
- Each VM runs in its own systemd scope outside the worker's cgroup, so restarting or upgrading the worker does not kill sandboxes; on start the worker re-adopts running VMs through their jailer API sockets and asks the server for those sessions' secrets again.
- While the server stream is down, the worker spools scrubbed events to a bounded local spool and replays them in order on reconnect; when the spool is full, the session pauses.
- Policy is fail-closed: if the server cannot be reached, the worker denies privileged actions, and honors only cached decisions for read-only actions until their TTL ends.
- On a single host, server and worker are separate processes on the same machine using the same protocol, so the single-host install exercises the multi-host path.

Every control-plane record carries a `tenant_id` (ADR-0005), and the worker protocol carries it too; Phase 1 uses one fixed tenant.

## Consequences

- A hosted control plane later is a deployment change: customer workers already dial out and keep secrets resolved per session.
- Outbound-only workers work behind NAT and need no inbound firewall rules.
- Live streams (terminal, editor) traverse guest -> worker -> server -> browser, adding one hop; ADR-0013 covers the transport.
- The server is a single process in Phase 1 (no HA); OBS-1 is met by durable state, not replication.

## Alternatives considered

- **Server calls workers:** simpler RPC but needs inbound reachability and breaks the hosted option.
- **Guest calls server directly:** gives the most exposed component a route to the most privileged one.
- **One combined binary for single-host:** saves a process but leaves the multi-host path untested until Phase 3.
