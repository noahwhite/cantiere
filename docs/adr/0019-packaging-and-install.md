# ADR-0019: Ship worker and guest as static binaries and the server as a self-contained Java app, with systemd units; Compose only for the control plane

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-2, COST-4, COST-5, SEC-1

## Context

OSS-2 asks for a one-command single-host install.
The worker manages KVM, TAP devices, nftables and block devices, which needs host privileges; running it inside a container would require exactly the privileged-container setup SEC-1 removes from sandboxes.

## Decision

- Releases publish, for linux/amd64 and linux/arm64 and signed with Sigstore cosign:
  - static `cantiere-worker` and `cantiere-guest` binaries (Rust, musl);
  - `cantiere-server` as a Quarkus fast-jar bundled with a `jlink` Java runtime, so hosts need no JDK, and as a container image built from the same artifact;
  - a kernel and base rootfs for sandboxes.
- The server runs on the JVM, not as a GraalVM native image: startup time does not matter for a long-running service, and native images restrict the reflection that DBOS and gRPC rely on. Native images can be revisited later without changing the API.
- `install.sh` (single host) checks for `/dev/kvm`, installs the binaries and systemd units, provisions Postgres (local package or a URL to an existing one), installs OpenBao as a systemd service with its storage in a separate Postgres database (or takes the address of an existing OpenBao, ADR-0010), creates the storage pool for sandbox disks, and registers the local worker with a join token.
- OpenBao auto-unseals with its built-in static-key seal by default, from a key file readable only by the OpenBao service user, so a host restart needs no manual step. That key protects the secrets against a leaked Postgres dump, not against root on the server host; operators with a KMS use an OpenBao KMS seal plugin instead. Backups need the Postgres dump and, stored separately, the unseal key.
- The worker runs as root under systemd with a restricted capability set and drops privileges per helper where possible; the server runs as an unprivileged user.
- The installer configures the UI hostname and a separate wildcard hostname for sandbox origins (ADR-0013). Let's Encrypt issues [wildcard certificates only through DNS-01](https://letsencrypt.org/docs/challenge-types/), so the installer asks for either a DNS-provider API credential (stored in the secret store and used for DNS-01 issuance and renewal) or an operator-supplied wildcard certificate and key. With neither, it stops with an error rather than installing without sandbox origins.
- A Docker Compose file is provided for the server plus Postgres and MinIO only, for users who prefer it; workers always run on the host. On that path the MinIO volume is durable state and is backed up with the Postgres dump (ADR-0005).
- A reference OpenTofu module provisions a Hetzner dedicated server and runs the installer (OSS-2).

## Consequences

- Worker hosts must be bare metal or VMs with nested virtualization exposed; ADR-0007 records the hardware constraint.

## Alternatives considered

- **Everything in Compose:** one file, but forces a privileged worker container.
- **Server as a GraalVM native image:** smaller and faster to start, but adds reflection configuration for DBOS and gRPC and a slower build, for no benefit to a long-running service.
- **Kubernetes:** out of proportion for a single host; a Helm chart may follow when the hosted option exists.
