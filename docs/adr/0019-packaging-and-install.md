# ADR-0019: Ship static binaries with systemd units; Compose only for the control plane

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-2, COST-4, COST-5, SEC-1

## Context

OSS-2 asks for a one-command single-host install.
The worker manages KVM, TAP devices, nftables and block devices, which needs host privileges; running it inside a container would require exactly the privileged-container setup SEC-1 removes from sandboxes.

## Decision

- Releases publish static `cantiere-server`, `cantiere-worker` and `cantiere-guest` binaries for linux/amd64 and linux/arm64, signed with Sigstore cosign, plus a kernel and base rootfs for sandboxes.
- `install.sh` (single host) checks for `/dev/kvm`, installs the binaries and systemd units, provisions Postgres (local package or a URL to an existing one), creates the storage pool for sandbox disks, and registers the local worker with a join token.
- The worker runs as root under systemd with a restricted capability set and drops privileges per helper where possible; the server runs as an unprivileged user.
- The installer configures the UI hostname and a separate wildcard hostname for sandbox origins (ADR-0013), with certificates via ACME.
- A Docker Compose file is provided for the server plus Postgres and MinIO only, for users who prefer it; workers always run on the host.
- A reference OpenTofu module provisions a Hetzner dedicated server and runs the installer (OSS-2).

## Consequences

- Worker hosts must be bare metal or VMs with nested virtualization exposed; ADR-0007 records the hardware constraint.

## Alternatives considered

- **Everything in Compose:** one file, but forces a privileged worker container.
- **Kubernetes:** out of proportion for a single host; a Helm chart may follow when the hosted option exists.
