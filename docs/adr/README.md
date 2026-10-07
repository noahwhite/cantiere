# Architecture decision records

Process and format: [ADR-0001](0001-record-architecture-decisions.md).
The architecture these decisions add up to is in [architecture.md](../architecture.md).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-thin-control-plane-reuse-components.md) | Thin control plane, reuse components, no platform fork | Accepted |
| [0003](0003-control-plane-worker-guest-topology.md) | Control plane, worker, guest agent; workers dial out | Accepted |
| [0004](0004-languages-java-server-rust-worker.md) | Java and Quarkus server, Rust worker and guest, TypeScript and React UI, protobuf contracts | Accepted |
| [0005](0005-postgres-and-object-store.md) | Postgres the only database, S3-compatible blobs, `tenant_id` everywhere | Accepted |
| [0006](0006-durable-execution-dbos.md) | Sessions and workflows on DBOS Transact Java | Accepted |
| [0007](0007-sandbox-backend-firecracker.md) | Firecracker microVMs on bare-metal workers | Proposed - Phase 0 validation |
| [0008](0008-blueprints-and-snapshots.md) | Blueprints to OCI images to warmed snapshot templates | Accepted |
| [0009](0009-runtime-adapters-and-event-schema.md) | Claude Code over its native headless protocol, other agents over ACP, one event schema | Accepted |
| [0010](0010-credentials-stay-outside-the-sandbox.md) | Credentials applied at the worker boundary, not inside the sandbox | Accepted |
| [0011](0011-network-egress-and-tailnet-access.md) | Default-deny egress on the host, per-session proxy, ephemeral tailnet nodes | Accepted |
| [0012](0012-github-app-identity-and-commit-signing.md) | GitHub App, user linking, push-time commit recreation and signing | Proposed - Phase 1 slice 1 checks |
| [0013](0013-live-session-transport-and-takeover.md) | Live streams over vsock and the worker channel; command palette; take-over, including the native terminal UI | Accepted |
| [0014](0014-model-credentials-gateway-and-subscriptions.md) | Model gateway for API keys; subscription logins stay the user's own | Accepted |
| [0015](0015-policy-engine-and-audit-log.md) | One policy decision point, hash-chained audit log | Accepted |
| [0016](0016-web-ui-and-operator-auth.md) | Passkeys or OIDC, multi-user-ready identity | Accepted |
| [0017](0017-configuration-repository.md) | Personas, workflows, blueprints and skills in versioned config repos | Accepted |
| [0018](0018-observability-opentelemetry.md) | OpenTelemetry for the platform; timeline is product data | Accepted |
| [0019](0019-packaging-and-install.md) | Static worker and guest binaries, self-contained Java server, systemd; Compose for the control plane only | Accepted |

Accepted statuses take effect when the PR that adds them merges; Proposed ADRs flip to Accepted in the PR that records their validation results.
