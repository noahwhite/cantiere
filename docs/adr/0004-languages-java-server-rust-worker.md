# ADR-0004: Java and Quarkus for the server; Rust for worker and guest; TypeScript and React for the web UI

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-2, OSS-5, SB-1, UX-2, UX-7

## Context

The three tiers (ADR-0003) do different work.
`cantiere-server` is an API, workflow and integration service: REST, WebSocket, gRPC to workers, OIDC and passkeys, Postgres, GitHub webhooks.
`cantiere-worker` drives KVM tooling (Firecracker API, TAP devices, nftables, vsock) and runs the egress, git and model proxies that hold real credentials while parsing TLS, git packs and GraphQL from an untrusted sandbox.
`cantiere-guest` runs inside every sandbox image and must have no runtime dependencies on the image's toolchains.
The maintainers already run Officina on Quarkus.

## Decision

- **Java 25 with Quarkus** for `cantiere-server`:
  - `quarkus-grpc` for the worker stream (ADR-0003);
  - `quarkus-oidc` and `quarkus-security-webauthn` for sign-in (ADR-0016);
  - jOOQ and Flyway on Postgres (ADR-0005); jOOQ rather than Hibernate because DBOS commits a step's writes and its checkpoint atomically only through its JDBC-family step factories (ADR-0006);
  - DBOS Transact Java for durable workflows (ADR-0006);
  - `quarkus-opentelemetry` (ADR-0018).
- **Rust** for `cantiere-worker` and `cantiere-guest`, as one Cargo workspace producing static musl binaries. Core crates:

| Need | Crate |
| --- | --- |
| Firecracker API | [`fctools`](https://crates.io/crates/fctools), confirmed in Phase 0; fallback is a client generated from Firecracker's published `firecracker.yaml` OpenAPI spec. Either sits behind a `Vmm` trait. |
| Network namespaces, TAP, routes | [`rtnetlink`](https://crates.io/crates/rtnetlink) |
| nftables | [`nftables`](https://crates.io/crates/nftables) (typed JSON rule sets, applied atomically through `nft`) |
| vsock | `tokio-vsock` |
| gRPC | `tonic` |
| TLS and per-session CA | `rustls`, `rcgen` |
| HTTP proxies and model gateway | `hyper` |
| Git proxy and commit recreation | `gix` |
| SSH commit signatures | `ssh-key` (SSHSIG) |
| OCI images | `oci-spec`, `oci-client` |
| ACP client | [`agent-client-protocol`](https://crates.io/crates/agent-client-protocol) (ADR-0009) |

- **TypeScript with React** for the web UI, built with Vite through Quarkus Quinoa and served from the server, so the UI ships with no separate web server.
- **Protocol Buffers** for the server-worker and worker-guest protocols and the event schema (ADR-0009), with `buf` for linting and breaking-change checks. These contracts are the only coupling between the Java and Rust code.
- Tailscale is not linked into the worker; `tailscaled` runs as a separate process (ADR-0011).

## Consequences

- Contributors work in three languages, split by tier: Java for the server, Rust for the worker and guest, TypeScript for the UI. No code is shared across the Java-Rust boundary except generated protobuf types.
- Policy decisions live only in the server (ADR-0015), so no rule engine needs a Java and a Rust implementation.
- The worker's proxies get compile-time data-race freedom and no GC pauses, and the guest is a small static binary, which helps snapshot density.
- The Firecracker client comes from a pre-1.0 community crate or a generated client; the `Vmm` trait contains either choice.
- The protobuf contracts are the stable plugin surface that OSS-5 later documents and tests.

## Alternatives considered

- **Go for all three tiers:** one language and an official Firecracker SDK, but the server would leave the maintainers' Officina stack, and the credential-holding proxies would lose Rust's race-freedom guarantees.
- **Java for the worker:** no mature libraries for Firecracker, netlink, nftables or vsock, and a JVM in the guest works against density.
- **TypeScript everywhere:** matches some agent SDKs, but weak for host networking and VM work and heavy to ship into every sandbox.
