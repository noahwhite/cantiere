# Cantiere architecture - milestone 1

Milestone 1 is Phase 0 (spike) plus Phase 1 (single-session MVP) of [the requirements](requirements.md).
Its exit is one Officina story implemented through PR from the web UI, with no terminal container.
Each decision below links to its ADR in [docs/adr](adr/README.md).

## Principles

1. **The sandbox holds nothing worth stealing.** Credentials are applied at the worker boundary on the way out (ADR-0010); the only documented exception is a user's own subscription login (ADR-0014).
2. **Controls are construction, not prompts.** Permissions live in the VM boundary, the egress proxy, the git proxy and one policy engine (ADR-0007, ADR-0011, ADR-0015).
3. **Host existing CLIs unmodified.** Cantiere owns sessions, isolation, credentials and workflows, not the agent loop (ADR-0002, ADR-0009).
4. **One database.** Postgres for state and workflows, an object store for blobs (ADR-0005, ADR-0006).
5. **Single host first, hosted control plane possible.** Workers dial out and every record carries a tenant ID (ADR-0003, OSS-6).

## Components

```mermaid
flowchart TB
    subgraph clients[Clients]
        web[Web UI - React SPA]
        cli[cantiere CLI]
        gh_hooks[GitHub App webhooks]
    end

    subgraph cp["cantiere-server (control plane, Java + Quarkus)"]
        api[REST API + WebSocket]
        sess[Session and workflow engine - DBOS on Postgres]
        sched[Scheduler]
        pol[Policy engine + audit log]
        integ[Integrations - GitHub App, Linear in Phase 2]
        broker[Secret resolver + token minting]
        tl[Timeline store]
    end

    pg[(Postgres)]
    obj[(S3-compatible store)]
    secrets[(Secret store - OpenBao, BWS)]

    subgraph worker["cantiere-worker (Rust, bare-metal host, one per box)"]
        vmm[Firecracker + jailer]
        build[Blueprint builder + templates]
        subgraph netns["per-session network namespace"]
            dns[Allowlist resolver]
            subgraph sp["session proxy process - unprivileged"]
                proxy[Egress proxy - pass / inspect / inject]
                gitp[Git proxy - own branch only, signature checks]
                gw[Model gateway - keys, deny list, metering, budget]
            end
            ts[Ephemeral tailscaled]
        end
    end

    subgraph vm["Sandbox microVM (one per session)"]
        guest[cantiere-guest - Rust, runtime adapter, PTYs, tunnels]
        agent[Claude Code, or an ACP agent - opencode, Codex, Kimi CLI]
        dockerd[dockerd - Testcontainers, Postgres, Playwright]
        repos["/workspace/repo on session branch"]
    end

    ext[GitHub, model APIs, registries, Linear, dev hosts]

    web --> api
    cli --> api
    gh_hooks --> integ
    api --- sess
    sess --- sched
    sess --- pol
    cp --- pg
    tl --- obj
    broker --- secrets
    worker -- "outbound gRPC stream (ADR-0003)" --> cp
    guest <-- vsock --> worker
    agent --> guest
    vm -- "TAP: DNS, 80/443, tailnet only" --> netns
    proxy --> ext
    gitp --> ext
    gw --> ext
    ts --> ext
```

| Component | Owns | ADRs |
| --- | --- | --- |
| `cantiere-server` (Java, Quarkus) | API, UI, session workflows, scheduling, policy, audit, timeline, GitHub App, secret resolution | 0003, 0005, 0006, 0012, 0015, 0016 |
| `cantiere-worker` (Rust) | VMs, templates, network namespaces, per-session proxy processes (egress proxy, git proxy, model gateway), commit signing agent, stream relay | 0007, 0008, 0010, 0011, 0012, 0013, 0014 |
| `cantiere-guest` (Rust) | Runtime adapters (Claude Code native, ACP), event normalization, slash-command discovery, PTYs, editor and VNC tunnels, git identity and signing setup | 0009, 0012, 0013 |
| Config repo | Personas, org blueprint layer, skills reference, workflows later | 0017 |
| Target repos | `.agent/blueprint.yaml`, `CLAUDE.md` / `AGENTS.md` | 0008, 0009 |

The web UI and the CLI (IN-3, IN-4) use the same public REST API, described with OpenAPI and authenticated by session cookie or personal access token (ADR-0016).

## Session lifecycle

```mermaid
sequenceDiagram
    actor U as Operator
    participant S as cantiere-server
    participant W as cantiere-worker
    participant G as cantiere-guest (microVM)
    participant X as GitHub / model API

    U->>S: Start session (prompt, repos, persona)
    S->>S: Start session workflow, check budget and policy
    S->>X: Mint installation token (repo_ids, persona permissions)
    S->>W: Assign session + resolved secrets (in memory)
    W->>W: Clone template disks, set up netns, CA, proxies
    W->>G: Restore snapshot, connect over vsock
    G->>W: git fetch via git proxy, create session branch
    G->>G: Start runtime adapter (Claude Code, or ACP agent from Phase 2)
    loop Each turn
        G->>W: Model request with placeholder key
        W->>X: Inject key, check deny list, meter usage
        G-->>S: Events (scrubbed by worker) to timeline
        U-->>S: Message / take-over / approval
        S-->>G: Delivered at next turn (message or /command)
    end
    G->>W: git push (session branch)
    W->>W: Policy check, secret scan, signature check
    W->>X: Verified commits (machine user or linked user) + PR (bot or linked user)
    S->>U: Inbox: PR ready
    S->>W: Tear down VM, revoke tokens, flush artifacts
```

## Trust boundaries

| Boundary | What crosses it | Control |
| --- | --- | --- |
| Guest to worker | vsock streams; TAP traffic for DNS, 80/443 and declared tailnet | Firecracker + jailer; nftables default drop in a namespace the guest cannot see (ADR-0007, ADR-0011) |
| Worker to session proxy process | That session's secrets, CA key and budget lease; start and end records of credentialed requests and denials back | `SOCK_SEQPACKET` socket pair created by the worker, no tokens; worker pushes, process only reports a closed set of records and policy requests, each validated as untrusted, with backpressure on rate; re-adoption by worker nonce, kernel credentials and stored pidfd; per-session user distinct from the VM's, no capabilities, seccomp allowlist, Landlock, empty mount namespace, non-dumpable, resource limits on its own systemd scope; values in memory only (ADR-0010, ADR-0014) |
| Session proxy process to internet | Proxied requests with injected credentials | Output chain for the proxy user: default drop, non-global ranges and platform addresses dropped except declared private model upstreams, TCP 80 and 443 only to resolver answers for allowlisted names; no Unix, netlink or vsock sockets (ADR-0014); allowlist resolver, SNI/Host allowlist, method/path policy, git branch rule, audit (ADR-0010, ADR-0011, ADR-0015) |
| Worker to server | One outbound authenticated gRPC stream | Per-worker credential, revocable; secrets only per session in memory (ADR-0003) |
| Browser to server | HTTPS, WebSocket | Passkey or OIDC session, PATs for CLI (ADR-0016) |
| Browser to sandbox content | Editor, terminal and browser view served from the guest | Separate per-session origin with a capability token, no Cantiere cookies, strict CSP (ADR-0013) |
| Webhooks to server | GitHub events | Signature check, approved installations only (ADR-0012) |

Untrusted content (issue text, PR comments, web pages, tool output) is tagged on the timeline from Phase 1, and the policy engine refuses to let it satisfy high-impact rules from Phase 2 (SEC-6).

## Requirement coverage for milestone 1

| Requirements | ADRs |
| --- | --- |
| SB-1, SB-6, SEC-1 | 0007 |
| SB-2, SB-3, SB-4, SB-5, RT-4 | 0008 |
| RT-1 (partial: Claude Code only; opencode and Codex in Phase 2), RT-2, RT-3, RT-6, KN-1 | 0009, 0008 |
| IN-3, IN-4 | 0016 and the public API above |
| GH-1, GH-2, GH-3, GH-5, GH-6, GH-7, GH-8, GH-9 | 0012, 0010 |
| UX-1, UX-2, UX-3, UX-4, UX-5 | 0013, 0009, 0005 |
| SEC-2, SEC-3 | 0011 |
| SEC-4, SEC-5 | 0015, 0010 |
| SEC-7 | 0012 |
| ID-1, ID-2, ID-3, ID-4 | 0010 |
| COST-1, COST-2, COST-3 | 0014 |
| COST-4 | 0007 |
| OBS-1 | 0006, 0003 |
| OBS-2, OBS-3 | 0018, 0005 |
| OSS-1 | 0017 |
| OSS-2 | 0019 |
| OSS-3 | 0002 |
| OSS-4 | 0016 |
| OSS-6 | 0003, 0005 |

## Phase 0 spike plan

Phase 0 is timeboxed to one week, so it answers the questions that need only Firecracker, a guest image and the CLIs.
The proxy-dependent checks run in the first Phase 1 slice, before ADR-0012 and the proxy parts of ADR-0010 and ADR-0011 are relied on.
Each item's pass condition is written in its ADR.

| # | When | Question | Pass condition | ADR |
| --- | --- | --- | --- | --- |
| 0 | Phase 0 | Build vs reuse | OpenHands runtime, Coder, E2B runtime and microsandbox measured against items 1 to 4; results recorded in ADR-0007 | 0002, 0007 |
| 1 | Phase 0 | Restore time | < 2 s p50, < 30 s p99 to guest-ready | 0007 |
| 2 | Phase 0 | Officina suites in a guest | `officina` and `officina-site` tests incl. Testcontainers and Playwright pass | 0007 |
| 3 | Phase 0 | Density | 10 concurrent sessions on 16 cores / 64 GB without OOM | 0007 |
| 4 | Phase 0 | Escape and isolation | With nftables only, root in guest cannot reach the host, peers or metadata; only DNS and ports 80 and 443 to the worker leave the namespace; all drops logged | 0007, 0011 |
| 5 | Phase 0 | Clone identity | Unique entropy, machine ID and network identity per restored clone | 0007 |
| 6 | Phase 0 | Firecracker client | `fctools` drives create, snapshot, restore, balloon and jailer launch for items 1 to 5; otherwise a client generated from `firecracker.yaml` | 0004, 0007 |
| 6a | Phase 0 | Subscription auth signals | With the pinned Claude Code version and a `setup-token` in `CLAUDE_CODE_OAUTH_TOKEN`, `claude auth status` reports `authMethod` `oauth_token`; during a working session the token value is unchanged and no credential is written to the CLI's credential store; with the token revoked or expired, the stream-json output's authentication-failure signal is recorded and the adapter pauses the session instead of failing it | 0009, 0014 |
| 7 | Phase 0 | Headless Claude Code end to end | One Claude Code session takes a prompt to a pushed branch with events streaming, and a user skill dispatched as `/name` runs. The push goes to a throwaway repo with a temporary spike-only credential; it does not validate ADR-0010, which items 8, 10 and 11 do | 0009 |
| 8 | Phase 1, slice 1 | CA, proxy trust and domain allowlist | Claude Code, `git`, `gh`, Docker pulls, Maven and npm work through the proxy with the per-session CA; non-allowlisted domains are denied and every denial is logged | 0010, 0011 |
| 9 | Phase 1, slice 1 | Model gateway | Claude Code, and each ACP agent before it is enabled for API-key sessions, runs end to end against the gateway in the unprivileged session proxy process with a placeholder key; requests reach the provider unchanged apart from the credential; usage metered and priced from the config-repo price table; a budget refusal returns HTTP 402 with error type `cantiere_budget_exceeded`, the runtime does not retry it, and the adapter pauses the session to the inbox; a worker restart mid-stream leaves the stream running, the worker re-adopts the process through `Resync`, its cost is recorded exactly once, and no new model request is forwarded until the worker is back; the runtime's requests at the pinned version pass the gateway's endpoint, beta, service-tier and usage rules | 0014 |
| 9a | Phase 1, slice 1 | Proxy process confinement | From inside the proxy process, with a test build that runs attacker code after `Init`: no file can be opened, no Unix, netlink or vsock socket can be created, `unshare`, `io_uring_setup`, `ptrace` and `execve` kill the process, connections to a non-global address, a platform address or a non-allowlisted global address are dropped, the VM's Firecracker sockets are unreachable and the VM user cannot read the process's memory, a crash leaves no core file, and memory, task and journal-size limits stop the process or its writes without affecting other sessions; a pushed decompression bomb is refused; a declared private model upstream is reachable and no other private address is; a session that writes more records than one journal file holds keeps running, and every record reaches the server exactly once; the gateway-only service resolves names only through its resolver and cannot connect to a global address outside the resolver's set; the Compose gateway starts under its Docker profile, and once it has created its sockets, `execve` and Unix socket creation kill it | 0014 |
| 9b | Phase 1, slice 1 | Budget bounds | Against the gateway: batch, file, fine-tuning and background requests are refused; a request with no output limit is reserved at the model's maximum output or refused; a Chat Completions stream without `include_usage`, an unlisted beta value, audio or video input or output, and an image for a model whose price entry does not list images are refused; a stream aborted before its usage is charged its full reservation; `n` and provider-run tool caps are reserved; a request with a document is reserved at the model's maximum input, and each provider-run tool use adds the model's maximum input; for a recorded corpus of each runtime's requests, the input bound is never below the provider's reported input tokens | 0014 |
| 10 | Phase 1, slice 1 | GitHub API policy | Session token cannot update refs, merge, or mutate other repos via REST or GraphQL | 0010 |
| 11 | Phase 1, slice 1 | Commit signing | Bot commits signed through the session agent show Verified as the machine user; user commits show Verified as the user, or, if ADR-0012 check 2 fails, user mode falls back to Verified machine-user commits with the user as co-author (GH-8); unsigned commits are refused | 0012 |
| 12 | Phase 1, slice 1 | Durable step atomicity | A DBOS step that writes a row through the jOOQ step factory and is killed before returning leaves both the row and the checkpoint, or neither | 0006 |
| 13 | Phase 1, slice 1 | OpenBao dynamic credentials | A PostgreSQL role and a MySQL user issued with a TTL equal to the session maximum stop working, and their open connections are closed, at session end by server revocation and at expiry with the server stopped, including for a guest that reconnects in a loop during revocation; SSH through the worker agent works during the session and fails after it ends, even with the certificate copied out of the guest | 0010 |

The original Phase 0 item "test broker-held subscription credentials" is answered by research instead of a test: Cantiere stores the subscriber's own `setup-token` and places it in their sessions' guest environment, without proxying it, as a residual terms risk the project owner accepted for the first release (ADR-0014).

## Open questions after these ADRs

- [x] Memory: keep file-based `MEMORY.md` or move to a store with a review UI (RT-5, Phase 3). Resolved: file-based and versioned in Git; memory edits arrive as PRs (KN-4), so the PR is the review UI (RT-5). Not needed for milestone 1; skills and memory mount read-only from the pinned skills commit (ADR-0008).
- [ ] Which Hetzner dedicated model and location runs the first worker (16 cores / 64 GB or larger); Hetzner Cloud cannot host workers (ADR-0007).
- [ ] Workflow script language for WF-2 (Phase 2), built on ADR-0006 primitives.
- [ ] Which ACP agents the Phase 2 template ships (opencode and `codex-acp` at minimum), and whether each passes the ADR-0009 conformance suite.
