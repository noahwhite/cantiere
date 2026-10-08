# ADR-0007: Firecracker microVMs on bare-metal workers are the sandbox backend

- Status: Proposed - accept when the Phase 0 validation below passes
- Date: 2026-10-07
- Requirements: SB-1, SB-6, SB-7, SEC-1, SEC-2, COST-4; Phase 0 exit "sandbox backend chosen, ADR merged"

## Context

Each session needs a VM-grade boundary (SEC-1), boot from a snapshot in under 30 s (SB-1), a working Docker daemon for Testcontainers, Postgres and Playwright (SB-6), pause and resume later (SB-7), and 10 concurrent sessions on a 16-core / 64 GB host (COST-4).

| Option | VM boundary | Docker inside | Snapshot / pause | Fit |
| --- | --- | --- | --- | --- |
| [Firecracker](https://github.com/firecracker-microvm/firecracker) v1.17 | Yes, minimal VMM | Yes, dockerd in guest ([BuildBuddy precedent](https://www.buildbuddy.io/docs/rbe-microvms)) | Full snapshots GA, lazy restore via userfaultfd | Chosen |
| [Cloud Hypervisor](https://github.com/cloud-hypervisor/cloud-hypervisor) v53 | Yes | Yes | Yes, plus CoW restore and live migration | Fallback |
| [gVisor](https://gvisor.dev/docs/tutorials/docker-in-gvisor/) | No, userspace kernel | Workarounds (`--iptables=false`), weak port publishing | Checkpoint/restore | Rejected: not VM-grade, Testcontainers friction |
| [Kata](https://github.com/kata-containers/kata-containers/blob/main/docs/Limitations.md) 4.2 | Yes | Yes | No checkpoint/restore | Rejected: no pause/resume, adds a CRI layer |
| [E2B runtime](https://github.com/e2b-dev/runtime) | Firecracker | Undocumented | Yes | Reference design, not deployed: single-host package is "evaluation", multi-node is commercial |
| microsandbox (libkrun) | Yes | Example exists | Yes | Rejected for now: self-declared beta |
| OpenHands, Coder | Container or template-defined | - | - | Not sandbox backends (ADR-0002) |

## Decision

- Sandboxes are **Firecracker microVMs** launched by `cantiere-worker` through the Firecracker jailer (chroot, seccomp, cgroups v2, unprivileged UID per VM). The worker drives Firecracker's REST API through a `Vmm` trait; the client crate is chosen in Phase 0 (ADR-0004).
- Worker hosts are **bare metal with `/dev/kvm`**: [Hetzner Cloud has no nested virtualization](https://docs.hetzner.com/cloud/servers/faq/), so Officina's workers are Hetzner dedicated servers; the control plane may run anywhere.
- The guest runs a Cantiere-built kernel with overlayfs, netfilter, bridge, veth and cgroup v2, so `dockerd` runs inside the VM against its own ext4 data disk (`/var/lib/docker`), never the host's.
- Disks per session are copy-on-write clones of template images (ADR-0008): reflink copies on an XFS pool in Phase 1, behind a `DiskStore` interface so an NBD overlay with diff export (E2B's approach) can replace it for pause/resume and multi-host moves.
- Memory density uses balloon free-page reporting; per-VM CPU, memory and disk quotas are set from the persona (COST-4).
- The backend sits behind a `SandboxProvider` interface (OSS-3); Cloud Hypervisor is the documented fallback if virtio-fs, hotplug or live migration become requirements.
- No local-development provider without KVM is offered in Phase 1; contributors without KVM use a remote dev worker.

## Phase 0 validation (all must pass to accept)

Record the same measurements for the OpenHands runtime, Coder, the E2B runtime and microsandbox where they apply, so the build-vs-reuse choice in ADR-0002 rests on numbers.

1. Template restore to guest-agent-ready under 2 s p50 and 30 s p99 on the target host, from a snapshot with Docker warmed.
2. Officina's `officina` and `officina-site` test suites, including Testcontainers and Playwright, pass inside one guest.
3. 10 concurrent sessions running those suites on a 16-core / 64 GB host without OOM, with per-session CPU and memory caps holding.
4. From root inside a guest, attempts to reach the host, other guests or the metadata network, or to send anything other than DNS and TCP 80 and 443 to the worker, all fail and are logged, with ADR-0011's host nftables rules in place; the proxy's domain allowlist is tested in Phase 1 (architecture test 8).
5. Restored clones get unique entropy, machine IDs and network identity (VMGenID / VMClock handling verified).
6. The `fctools` crate drives create, snapshot, restore, balloon and jailer launch for items 1 to 5 at the pinned Firecracker version; otherwise the worker uses a client generated from `firecracker.yaml` and this item records why.

## Consequences

- Workers cannot be cheap cloud VMs; Hetzner dedicated servers are the unit of capacity.
- Cantiere owns the image, kernel, disk and snapshot pipeline (ADR-0008), using E2B's Apache-2.0 code as reference.
- Snapshot restore resets vsock and TCP connections, so the guest agent reconnects after every restore by design.
