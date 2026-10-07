# ADR-0011: Default-deny egress enforced on the host, with a per-session proxy and ephemeral tailnet nodes

- Status: Accepted
- Date: 2026-10-07
- Requirements: SEC-1, SEC-2, SEC-3, SEC-6, ID-4

## Context

SEC-2 requires default-deny egress with per-blueprint allowlists, enforced outside the sandbox, with every denial logged.
SEC-3 requires dev-host reach over Tailscale only for personas that declare it.
Credential injection (ADR-0010) and model metering (ADR-0014) need the same choke point.

## Decision

**Network layout per session** (the E2B pattern, see ADR-0007):

- Each VM gets its own network namespace on the worker with one TAP device; the guest sees a fixed link-local address and the worker as its only gateway.
- Host nftables in that namespace drops everything by default, then allows: DNS to the worker's resolver; TCP 80 and 443 redirected to the worker's egress proxy; the tailnet range to the session's Tailscale node, if declared.
- No route exists to the host, other namespaces, the cloud metadata address, or the worker's private networks.

**Resolver.** The worker answers DNS only for names on the session's allowlist and returns `NXDOMAIN` for the rest, which closes DNS-tunnel exfiltration and gives an early, logged denial.

**Egress proxy** (Rust, part of `cantiere-worker`, transparent):

- Reads SNI (TLS) or `Host` (HTTP) and matches it against the session's allowlist: the union of the org and repo blueprint `egress` lists and the persona's list.
- Each allowed domain has one mode:
  - `pass`: splice TLS through untouched.
  - `inspect`: terminate TLS with the per-session CA and apply method and path rules.
  - `inject`: like `inspect`, plus credential injection (ADR-0010).
- Denials and policy rejections become timeline events with `trust` context and audit entries.
- The proxy resolves the allowed name itself through the worker resolver and dials that address; the destination IP the guest used is ignored, so an allowlisted SNI cannot be pointed at an arbitrary host.
- On `inspect` and `inject` domains the proxy strips credentials the guest supplies itself (`Authorization`, `Proxy-Authorization`, cookies, basic auth in URLs), so code cannot push or publish to an attacker's account through an allowed host.
- `pass` mode is opaque, so any `pass` domain that accepts uploads is an exfiltration path; domains with write APIs (`github.com`, package registries) are `inspect` or `inject` by default, and `pass` is reserved for read-only endpoints.
- Envoy's SNI forward proxy is still alpha, and smokescreen needs explicit proxy settings, so the proxy is written in Rust on `hyper` and `rustls` rather than adopted (ADR-0004).

**Tailnet (SEC-3).** For personas that declare `tailnet: {tags: [...]}`, the worker starts a kernel-mode `tailscaled` inside the session's network namespace. It owns that namespace's TUN device, keeps its state in memory (`--state=mem:`), and joins with a single-use, pre-tagged ephemeral auth key minted through a Tailscale OAuth client. nftables routes the guest's tailnet traffic from the TAP to the TUN. Userspace networking mode is not used, because it creates no TUN device and only offers SOCKS5 and HTTP proxies. The node is removed at session end. The guest reaches only what the tag's ACL allows, and the auth key never enters the guest.

`tailscaled` is the upstream Go client run as a separate process; the Rust worker launches and supervises it and links no Tailscale code.
[`tailscale-rs`](https://github.com/tailscale/tailscale-rs) was considered and rejected for now: it is an experimental preview with no compatibility guarantees, offers only in-process TCP and UDP sockets (no TUN device for arbitrary guest traffic), and lacks MagicDNS.
Revisit when it supports TUN mode and MagicDNS.

## Consequences

- Root inside the guest cannot change any of this; the rules live in a namespace the guest cannot see.
- Package registries and Docker registries must be listed in blueprints; the first runs will surface missing entries as logged denials.
- Non-HTTP egress (for example SSH to a dev host) is possible only over the tailnet, so it is always persona-declared and ACL-bounded.
