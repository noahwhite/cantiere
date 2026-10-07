# ADR-0004: Go for server, worker and guest; TypeScript and React for the web UI

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-2, OSS-5, SB-1, UX-2, UX-7

## Context

The backend talks to KVM tooling (Firecracker API, TAP devices, nftables, vsock), runs long-lived streams, and must ship as static binaries for a one-command install (OSS-2).
The guest agent runs inside every sandbox image and must have no runtime dependencies on the image's toolchains.

## Decision

- **Go** for `cantiere-server`, `cantiere-worker` and `cantiere-guest`: one module, static binaries, a mature Firecracker SDK, first-class gRPC, and an ecosystem (containerd, gVisor, Tailscale, smokescreen) built in it.
- **TypeScript with React** for the web UI, built with Vite and embedded into the server binary at release time, so the UI ships with no separate web server.
- **Protocol Buffers** for the server-worker and worker-guest protocols and the event schema (ADR-0009), with `buf` for linting and breaking-change checks.
- Runtime adapters that must embed a vendor SDK only available in TypeScript or Python run as a child process of `cantiere-guest` speaking the same protobuf contract over stdio (ADR-0009).

## Consequences

- Contributors need Go and TypeScript; no third language in the core.
- The protobuf contracts are the stable plugin surface that OSS-5 later documents and tests.

## Alternatives considered

- **Rust:** strong for the guest and VMM-adjacent code, but slower to build the API, workflow and integration surface that is most of the code.
- **TypeScript everywhere:** matches the agent SDKs, but weaker for the host networking and VM work and heavier to ship into every sandbox.
- **Python:** same objections as TypeScript, plus packaging.
