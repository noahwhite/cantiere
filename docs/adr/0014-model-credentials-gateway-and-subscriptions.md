# ADR-0014: Model access goes through a per-session gateway process on the worker; subscription logins stay the user's own

- Status: Accepted
- Date: 2026-10-07
- Updated: 2026-10-21 - the gateway runs in a per-session unprivileged proxy process whose confinement, channel, policy exchange and budget bounds are specified, and the build-vs-reuse evaluation of existing gateways is recorded
- Requirements: COST-1, COST-2, COST-3, RT-3, ID-2, ID-4, OBS-1, KN-2; open question "Do Claude Code and Codex subscription terms allow headless use from a self-hosted multi-session server?"; Phase 0 item "test broker-held subscription credentials"

## Context

Cantiere does not resell or proxy model access as a service; each user brings their own credentials (README).
Model spend must be metered per session and hard-capped (COST-1, COST-2), and denied models must be unreachable (RT-3).
The gateway parses requests and response streams that the sandbox controls, and the worker that would otherwise host it is the most sensitive component on a host (ADR-0010).

The terms differ by vendor:

- [Anthropic](https://code.claude.com/docs/en/legal-and-compliance): subscription OAuth is for ordinary use of the unmodified Claude Code binary, which an end user may sign in to even where a platform hosts it. Products, including Agent SDK integrations, must use API keys. Developers "may not collect, store, or intermediate Claude.ai credentials or session tokens".
- OpenAI: "Sign in with ChatGPT" for open-source, self-hosted apps (preview) explicitly supports [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms.md) and passing the token to a Codex `app-server` child process. ChatGPT Plus/Pro sign-in is also supported in [opencode](https://opencode.ai/docs/providers/), so OpenAI subscriptions are not tied to OpenAI's own CLI.

## Decision

**API-key mode (default).**

- Each runtime's base URL points at the worker's model gateway: `ANTHROPIC_BASE_URL` for Claude Code, and the ACP agent's provider base URL for everything else (opencode provider `baseURL`, Codex `model_providers`). The sandbox holds only a placeholder key.
- This is how non-Anthropic and non-OpenAI models run: a persona picks an ACP agent and a model, and the gateway injects that provider's key. For example:

  ```yaml
  name: kimi-reviewer
  runtime: acp
  agent: opencode
  model: moonshot/kimi-k3
  secrets: [{provider: moonshot, ref: openbao://kv/models#moonshot}]
  github: {permissions: read, authoring: bot}
  budget: {session_usd: 5}
  ```

- The gateway does four things:
  - injects the real key (Anthropic, OpenAI, Bedrock, Vertex, or any OpenAI-compatible endpoint such as DeepSeek, Moonshot, OpenRouter or a local vLLM);
  - rejects requests for denied models (RT-3);
  - reads token usage from responses and prices it from a per-model price table (input, output, cache read and cache write per million tokens, plus the price-affecting options below) kept in the config repo (ADR-0017), producing authoritative `cost` events (COST-1); a model with no price entry is refused, so API-key spend is never unmetered;
  - enforces budgets with reservations (COST-2): the server grants each session a budget lease from an atomic per-tenant daily counter in Postgres; before forwarding a request the gateway reserves its worst-case cost (below) from the lease, refuses the request if the reservation does not fit, and releases the unused part when the response's usage is known.
    When the lease and the daily counter are spent the session pauses to the inbox.
- The worst case is computed from the request alone, and a request whose worst case cannot be computed is refused, so nothing the guest sends can cost more than its reservation:
  - Endpoints: each provider adapter allows only the synchronous inference and token-counting endpoints whose usage it parses, and model listing (for example Anthropic `POST /v1/messages` and `/v1/messages/count_tokens`, OpenAI `POST /v1/chat/completions` and `/v1/responses`, Bedrock `InvokeModel` and `Converse`, Vertex `generateContent` and `rawPredict`, each with its streaming form).
    Everything else is refused, including batches, files, fine-tuning, realtime sessions and Responses requests with `background: true`, because their cost is billed outside the response.
  - Input: a request that refers to input it does not carry (OpenAI `previous_response_id` or `conversation`, uploaded file IDs) is refused.
    Input tokens are counted with the model's tokenizer where the provider publishes it, and otherwise bounded at one token per UTF-8 byte of the request's text, including system prompt and tool definitions, plus the provider's published per-message and tool overhead; images and documents use the provider's published token formula.
    The bound is priced at the highest input price the request can trigger: a cache write at the longest duration it asks for, and a long-context tier once the bound crosses that tier's threshold.
  - Output: the request's output limit (`max_tokens`, `max_output_tokens` or `max_completion_tokens`), or the model's maximum output from the price table when the request sets none; a request without a limit for a model with no maximum output entry is refused.
    A choice count (`n`) multiplies the output bound.
  - Provider-run tools, such as web search, are allowed only when the price table prices them and the request caps their use (for example Anthropic's `max_uses`); the reservation includes that cap, and any other provider-run tool is refused.
  - Price switches: every `anthropic-beta` value and service tier a request sets must be listed in the price table, as price-neutral or with its price; an unlisted value is refused.
  - Usage: a stream that will carry no usage (OpenAI Chat Completions streaming without `stream_options.include_usage`) is refused, because the gateway does not change requests.
    A request whose final usage never arrives, because the caller or the provider ended it early, is charged its full reservation.
    Usage with a field the parser does not know is charged at least the full reservation and raises an operator alert.
  - A price the table does not list yet, such as a provider price change, is outside the reservation; the daily reconciliation against provider usage reports (below) detects it.
- The gateway forwards each provider's own API (Anthropic Messages, OpenAI Chat Completions and Responses, Bedrock, Vertex, OpenAI-compatible endpoints) without translating it.
  Apart from swapping the placeholder for the real credential and choosing the upstream, request and response bytes pass through unchanged, including unknown fields and listed `anthropic-beta` headers.
  Streams are relayed as they arrive; usage is read from the stream while relaying it, not by buffering it.
- A budget refusal gets its own error type, `cantiere_budget_exceeded`, with HTTP status 402 and a body in the provider's own error format; the adapter pauses the session to the inbox on it.
  Conformance test 9 (architecture.md) checks, for Claude Code and for each ACP agent before it is enabled for API-key sessions, that the runtime treats this refusal as final and does not retry it; if a runtime retries 402, the status is changed for all runtimes in a superseding ADR.
  The same test checks that the runtime's requests pass the rules above with the pinned runtime version, so a runtime upgrade that adds a beta value or drops `include_usage` is caught before it reaches users.
- The price table in the config repo may be seeded from LiteLLM's MIT-licensed `model_prices_and_context_window.json`, credited in `NOTICE`; config-repo entries always win, and the missing-price rule above is unchanged.
- Keys belong to the deployment or to individual users; per-user keys are used only for that user's sessions.
  Where a provider offers projects or workspaces with their own spend limits, operators give each persona, or each user with a per-user key, its own, which bounds what a stolen key can spend (Consequences).

**Where the gateway runs: a per-session proxy process.**

- For each session the worker starts one proxy process, `cantiere-worker proxy`, a subcommand of the same static binary (ADR-0019), inside the session's network namespace.
  That process hosts the model gateway together with the session's egress proxy (ADR-0011) and git proxy (ADR-0010), so the choke point those decisions share stays one process.
- The process never talks to OpenBao, the server or any other secret store, and holds no credential for them.
  Secrets reach it by the chain ADR-0010 already sets, each hop holding less: secret store to server (the only store client) to worker to proxy process.
- The usage parsers, pricing, reservation logic and passthrough proxy are separate crates that do not depend on Cantiere's session types, so the gateway can be released on its own later without a rewrite.

**Confinement of the proxy process.**

- The process runs as a per-session user that is distinct from the jailer's per-VM user of the same session (ADR-0007), so a VMM escape does not reach the process's memory and a compromised process does not reach the Firecracker API or vsock sockets.
  Both users come from a uid range reserved for Cantiere, and a uid is reused only after its scope is empty and no file it owns remains.
- The worker starts the process through a single-threaded spawn helper that it forks before starting any thread.
  The helper places the child in its own systemd scope outside the worker's cgroup, gives it a new mount namespace whose root is an empty read-only tmpfs (no `/proc`, `/sys`, `/dev`, `/run`, `/var` or `/home`), moves the descriptors it was given to fixed numbers, closes every other descriptor with `close_range`, sets `no_new_privs`, `RLIMIT_CORE` to 0 and `RLIMIT_FSIZE` to the journal cap, switches to the session's proxy user with no capabilities, and executes the binary from a descriptor with an empty environment and no arguments that carry values.
  The worker opens every descriptor close-on-exec and sets close-on-exec on each descriptor it takes back from systemd's store, so a process never inherits another session's channel or sockets.
- Before it reads `Init`, the process makes itself non-dumpable (`PR_SET_DUMPABLE` 0), so no core dump, `ptrace` or `/proc/<pid>/mem` read by the same user reaches its memory; applies a Landlock ruleset that grants no filesystem access; and installs its seccomp filter.
- The seccomp filter allows only the system calls the binary uses and kills the process on any other.
  It excludes `execve` and `execveat`, `ptrace`, `process_vm_readv` and `process_vm_writev`, `unshare`, `setns`, `mount`, `bpf`, `userfaultfd`, `keyctl`, `perf_event_open`, every `io_uring` call (seccomp cannot see the operations a ring submits), `clone` with namespace flags, and `socket` for any family other than `AF_INET` and `AF_INET6`, so the process cannot open Unix, netlink, packet or vsock sockets; `clone3` returns `ENOSYS`, because seccomp cannot inspect its flags.
  The filter is generated with the binary and tested against it (conformance test 9a).
- Secret values are kept in `memfd_secret` memory where the kernel provides it and in locked pages otherwise, and are zeroed on `SecretUpdate`, `SecretRevoke` and exit.
- The scope sets `MemoryMax`, `MemorySwapMax=0`, `TasksMax`, `CPUQuota` and `LimitNOFILE` from the worker configuration, `LimitCORE=0`, and an `OOMScoreAdjust` under which the kernel kills a session's proxy process before any VM or the worker; these resources count toward the session's quotas (COST-4).
  Inside them, the process caps concurrent guest connections, header and body sizes, GraphQL document size, and the bytes and compression ratio a pushed pack may inflate to during the secret scan; a request over a cap is refused with a `Denial`.
  An error or panic while handling one guest connection ends that connection, with its end record or denial, not the process.
- The namespace's output chain matches the proxy user's packets and drops them by default.
  Before any allow rule it drops every non-global address range (RFC 1918, `100.64.0.0/10`, loopback, link-local, unique local, IPv4-mapped and NAT64 prefixes, documentation and reserved ranges), the host's own addresses, and the addresses of the server, OpenBao, Postgres and the object store.
  It then allows DNS to the worker resolver, and TCP 80 and 443 only to addresses in a per-session set that the resolver fills with its answers for allowlisted names, each for the answer's TTL.
  The resolver refuses any answer in a non-global range, which closes DNS rebinding through an allowlisted wildcard, and refuses the names of platform services, since services behind a CDN share addresses with allowed sites.
  A model upstream on a private address, such as a local vLLM, is declared in the config repo with its address and port, and only those are added to the allow rules.
  The guest's traffic never uses this chain: it reaches the process through the redirect and the listening sockets (ADR-0011).

**Channel between the worker and the process.**

- Introduction needs no tokens: possession of the channel is the credential.
  The worker creates a `SOCK_SEQPACKET` Unix socket pair, so each message is one datagram and no restart can leave a partial frame, together with the namespace's listening sockets (so the process needs no privilege to bind ports 80 and 443) and the journal file (below), and passes them to the spawn helper.
  It keeps a pidfd for the process and sends `Init` as the first message; values stay in the process's memory, never on disk, in argv or in its environment (ID-4).
- The channel follows high-side and low-side rules: the worker is the high side and only pushes; the process is the low side and only reports.
  - Down (worker to process): `Init` (protocol version, session ID, a random instance ID, that session's secret values with their injection rules, the per-session CA key, the budget lease, the session's domain allowlist with each domain's mode, the upstream trust roots, the resolver address and the drain bound used on end of file), `SecretUpdate` and `SecretRevoke` (replace or remove one value, for refresh such as the hourly GitHub token and for revocation such as an unlinked user's token, ADR-0010, ADR-0012), `PolicyUpdate` (replaces the allowlist and modes and drops every cached decision, for example when an operator approves a repo-layer egress entry or a persona's permissions change), `LeaseTopUp`, `StartDecision`, `RecordAck`, `Resync` and `Stop`.
    A secret update applies to requests the process forwards after it, without restarting the process.
    On `SecretRevoke` the process drops the value and refuses every request that would use it and has not yet been forwarded, including requests waiting for a `StartDecision`; it sends an end record marked not forwarded for each request that has a start record, and a `Denial` for each that does not; requests already forwarded are not cut.
    The worker chooses what to send from the references the persona declares (ID-3); nothing the process sends changes which secrets it gets.
  - Up (process to worker): `Hello`, `StartRecord`, `EndRecord` and `Denial`, nothing else.
    No message lets the process name a secret, ask for a larger lease, change its own policy, or refer to another session.
  - The worker treats every upward message as untrusted input: it checks the schema, size and value ranges, accepts an `EndRecord` only for a request ID with a start record from this process, and scrubs records before relaying them (ADR-0010).
    A message that fails these checks stops the process, with the same effect as a crash (below), and raises an audit event.
  - Rate is handled by backpressure, not by stopping: the process limits its own start records and denials with per-session token buckets set below the worker's limits, and when a bucket is empty it stops reading guest requests rather than dropping or merging records; if the worker's limit is still exceeded, the worker stops reading the channel until the rate falls.
  - These checks cannot prove that a reservation or a usage report matches what was sent to or returned by the provider: the process holds the key and is the only component that sees the traffic.
    The budget cap therefore holds against the guest, not against a compromised proxy process, which could under-report and spend up to whatever the provider allows for that key (a gateway inside the worker would have the same limit, running as root).
    Two backstops do not depend on the process: operators set provider-side spend limits on each key where the provider offers them, and the server compares recorded cost per key each day with the provider's usage reports where available and raises an alert on a difference.
  - The messages are protobuf contracts (ADR-0004) with the session ID fixed by the channel, not taken from the message.

**Policy decisions and records.**

- Every model request, every request the process forwards on an `inspect` or `inject` domain, and every push is a policy action (ADR-0015).
  The domain allowlist and modes are data from `Init` and `PolicyUpdate`, applied by the process as the resolver applies them; method, path, operation and push rules are decided by the server's `policy.Decide`, never by the process.
- Before it forwards such a request, the process sends a start record: a random 128-bit request ID and the normalized action, which is the method, host and path, the GraphQL operation type and name for a GraphQL call, the ref with its old and new head SHAs for a push, and the model and reservation for a model request.
  The server decides, appends the audit row with the action, target, head SHA and decision (SEC-5), and returns the `StartDecision` through the worker; the process forwards the request only after an allow, and records a denied one as not forwarded.
- For a read-only action the decision may be cacheable, with a key (host, method and path pattern) and a TTL (ADR-0015).
  The process then decides matching requests from its cache without a round trip; it writes each one's start record to the journal before forwarding it and sends it afterwards, so the audit log still has every request.
  Cached decisions never cover a write, a push or a model request; they expire at their TTL, `PolicyUpdate` drops them, and while the worker or server is unreachable they are honoured only until their TTL ends (ADR-0003).
- The decision for a push carries the data ADR-0012's push checks need at that moment: the commit identity and its chosen address, the key fingerprints the server recorded for the session and has not deleted, the identity's long-lived key fingerprint where the fallback applies, and the user to credit.
  The server's address recheck before each push is part of that decision, so a failed recheck is a denial.
- The server accepts a start only while the session is running and, for a model request, while its lease covers the reservation, so a session that ended while the worker was down cannot start a model call after reconnecting.
  Start records are idempotent by request ID: the process resends an unanswered start after a `Resync` (below), and the server returns its first decision only while the session is still running; once the session has ended it rejects every start, including a resend of one it had accepted, and records that request as not forwarded.
  If the caller has gone away before the decision arrives, the process sends an end record marked not forwarded, which releases the reservation.
- When a request ends, the process appends an end record with the same request ID (status and, for a model request, the usage and cost) to a per-session journal file, then sends it; the worker reads the journal when it adopts or restarts the process and resends what the server has not acknowledged, and the server ignores a second end record for the same request ID.
  The process scrubs every record with the session's secret values, using the worker's scrubber (ADR-0010), before writing it, so the journal holds only request IDs, statuses, usage, cost and scrubbed denial details, never secrets or request or response bodies, and the worker deletes it when the session's records are all acknowledged.
  The worker scrubs and relays both records to the server as before (ADR-0010, ADR-0015).
- Each request the process refuses itself (allowlist, size caps) is an individual `Denial`, written to the same journal and sent the same way, without a start record (ADR-0011, SEC-2).
  The worker relays a session's records in batches, and the server appends each batch to the tenant's audit chain in one transaction, so a burst of denials takes the chain lock (ADR-0015) once per batch, not once per record.

**Journal.**

- The worker creates the journal with `O_NOFOLLOW` and `O_EXCL` in a root-owned per-session directory and passes the process a write-only, append-only descriptor; `RLIMIT_FSIZE` holds it to its size cap in the kernel, whatever the process does.
- Records in the journal are length-prefixed and checksummed frames.
  The worker parses the journal as untrusted input with the same checks as channel messages, stops at the first frame that fails them, raises an audit event, and leaves every request after that point to the server's rule for start records without end records (below).
- The process reads a request from a guest connection only after reserving journal space for one record about it, which becomes either its denial or its end record, so every request it has read can always be recorded.
  When no space is left, the process stops reading requests from every guest connection, open or new, until the worker has drained the journal, so a guest cannot exhaust the process's memory or disk during a worker outage, and no denial or end record is summarised or dropped.

**Lifecycle and re-adoption.**

- The process runs in its own systemd scope outside the worker's cgroup, like the session's VM (ADR-0003), so restarting or upgrading the worker does not cut in-flight model streams.
  While the worker or the server is unreachable, no start record can be accepted, so the process forwards no new request that needs a decision; streams already in flight finish and write their end records to the journal.
- The worker service sets `Restart=always`, `FileDescriptorStorePreserve=yes` and a `FileDescriptorStoreMax` of at least two per session at its maximum session count.
  It stores each session's channel end and the process's pidfd with `FDPOLL=0`, under a name that holds the session ID, the instance ID and the protocol version, so the store survives a restart, an upgrade, a crash and a worker that has run out of restart attempts.
  The worker removes a session's entries (`FDSTOREREMOVE`) only after it has stopped that process and collected its journal.
- On start the worker takes each entry back and re-adopts the process:
  - It sends `Resync` with a fresh random 128-bit nonce, since the process cannot see a worker restart on a channel that stayed open.
  - The process answers `Hello` with that nonce, its protocol version, session ID and instance ID, then resends its unanswered start records.
  - The worker accepts `Hello` only if the `SCM_CREDENTIALS` the kernel attaches (it sets `SO_PASSCRED` on its end) carry the session's proxy user and the pid of the stored pidfd, and that process is still alive, which rules out pid reuse; and only if the session ID, instance ID and protocol version match the stored name exactly.
    `SO_PEERCRED` is not used, because on a socket pair it reports the worker that created the pair.
  - A worker that does not speak the stored protocol version stops the process and starts a new one; it never accepts another version from a running process, so a compromised process cannot pick an older validator.
  - The worker then reads the journal and resends the end records the server has not acknowledged.
  On any failed check, and for any proxy scope whose entries are missing, the worker stops the process and starts a new one, as after a crash (below).
- The process sees end of file on the channel only when no copy of the worker's end is left, for example after the store was lost.
  It then stops accepting connections and reading requests, lets forwarded requests finish within the drain bound from `Init`, writes their end records, zeroes its secrets and exits.
- If the process exits, the session's egress stops, because nftables still redirects only to it (fail-closed).
  The worker restarts it with the session's secrets and the remaining lease, after collecting its journal.
  The server counts the full reservation of every request that has a start record and no end record as spent, so a crash can over-count spend but never under-count it, and every such request still has its start record in the audit log.
  Provider usage reports are not per request, so an over-counted reservation is not given back; because a failure in one connection does not end the process and rate excess throttles instead of stopping it, the guest can cause this only through a defect that kills the process.

**Gateway-only mode beside the server.**

- Model calls the server makes itself, outside any session (KN-2, KN-3, KN-4), go through the same binary run as its own systemd service, `cantiere-gateway`, under its own user, never the server's, so it cannot read the server's OpenBao AppRole credential; systemd starts it, not the server.
  It has a lease from a per-tenant system budget, and the same message set, budget rules and journal, with the server as the high side.
- It applies the same non-dumpable setting, Landlock ruleset, seccomp filter and secret memory as the session process.
  In place of the spawn helper, its unit gives it an empty read-only root with only the binary (`TemporaryFileSystem=/`), `PrivateDevices`, `ProtectProc=invisible`, `MemoryMax`, `TasksMax` and `LimitCORE=0`, and host nftables output rules for its user drop the same address ranges as the session chain and allow TCP 443 only, plus declared private upstreams.
- A Java process cannot hand a socket pair to a process it did not start, so the gateway listens on a Unix socket in a directory only the server's user can open, accepts one connection at a time, and accepts it only if `SO_PEERCRED` reports the server's user; on a connected socket, unlike a socket pair, `SO_PEERCRED` reports the peer.
  Java's Unix-domain channels are stream sockets, so messages are length-prefixed; a server restart closes the connection, and the next one starts with `Resync` and `Hello` as a re-adoption does.
  While no server is connected the gateway forwards no new request; requests in flight finish and write their end records to the journal.
- The server sends model requests to a second Unix socket in the same directory.
- In the Compose deployment (ADR-0019) the gateway is its own container: a non-root user, a read-only root filesystem, every capability dropped, the same seccomp filter as a Docker seccomp profile, memory and process limits, and a network with internet egress only, not the network that reaches Postgres, OpenBao or MinIO; its two sockets are on a volume shared only with the server container.

**Subscription mode (opt-in, single-subscriber deployments only, COST-3).**

- Available only where the subscriber is the deployment's operator and the sandboxes run on infrastructure only they control, which matches Anthropic's "user signs in to the unmodified binary" allowance and OpenAI's "remote runtime only that user controls" wording most closely. Multi-user deployments cannot enable it.
- Claude: the subscriber generates their own token with `claude setup-token` and stores it in their own secret-store scope. Cantiere places it in the environment of that subscriber's sessions as `CLAUDE_CODE_OAUTH_TOKEN`, for the unmodified `claude` binary only. Storing the token is unavoidable for disposable sandboxes; this residual terms risk is stated in the setting's description.
- Claude token lifecycle:
  - `claude setup-token` prints a one-year OAuth token and saves it nowhere; Claude Code reads it from `CLAUDE_CODE_OAUTH_TOKEN` in each session ([authentication](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token)). The docs do not describe refreshing it, so Cantiere treats it as fixed until renewed; conformance test 6a (architecture.md) checks this against the pinned CLI version. The interactive `/login` credential is not used: Claude Code refreshes it automatically and updates it in place in the CLI's credential store, so keeping it valid across disposable sandboxes would mean collecting the updated credential after every session.
  - When the subscriber stores the token, the UI requires its mint date, prefilled with today for the subscriber to confirm, and the server records mint date plus one year as the expected expiry next to the secret reference in Postgres; the token value itself lives only in the secret store. The recorded expiry is an estimate; the mid-session failure path below is the backstop for a token that stops working earlier.
  - Fourteen days and again three days before the expected expiry, the subscriber gets an inbox item and a push notification asking them to renew.
  - A subscription session does not start with a token past its expected expiry; it waits in the inbox with a renew action. It never falls back to API-key mode on its own, because that changes who pays.
  - If the token expires or is revoked mid-session, the adapter detects the authentication failure from the stream-json output (a `system/api_retry` event with `error` `authentication_failed`, or an error `result`; the exact signal for a revoked `setup-token` is pinned by conformance test 6a) and pauses the session to the inbox instead of failing it. After renewal the session resumes with `--resume` (ADR-0009) in a `claude` process started with the new token.
  - Renewal: the subscriber runs `claude setup-token` on their own machine and replaces the value in their scope through the UI, which writes it to the secret store without logging it. Running sessions keep the old token until they end or pause. Cantiere cannot revoke the old token; the subscriber removes it in their Claude account settings (Claude Code section), which is also the first step after a suspected theft.
  - Credential isolation: in subscription sessions the guest environment sets none of `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` or `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`, which either outrank `CLAUDE_CODE_OAUTH_TOKEN` or would send the traffic to the gateway. The adapter launches `claude` with `--setting-sources user` and `--strict-mcp-config --mcp-config <file generated from the org layer's mcp_servers>`, which holds only the servers the session's repo layers name and the org layer grants to those repos (ADR-0008). These flags keep the target repository's `.claude/settings.json` (its `env` block, `apiKeyHelper` and hooks) and `.mcp.json` from loading; Cantiere writes the user settings from the org layer's `claude.settings`, and blueprint MCP servers load only through `--mcp-config`; a repo layer cannot supply either (ADR-0008). Before the first turn the adapter runs `claude auth status` and fails the session closed unless `authMethod` is `oauth_token`. This check guards the launch only: Claude Code reloads changed settings mid-session, so guest code can still add an `apiKeyHelper` to the user settings, just as it can read the token (Consequences). The adapter re-checks the credential source in the `system/init` event on every resume and pauses the session if it has changed.
  - The adapter never passes `--bare`, because bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`.
  - The token can make only model requests, so claude.ai connectors and Remote Control are unavailable in subscription sessions; MCP servers configured by the blueprint still work.
- Cantiere never routes subscription traffic through the gateway, never intercepts it (`pass` mode in ADR-0011), and never uses it with the Agent SDK.
- ChatGPT: the user's sign-in follows OpenAI's self-hosted flow, and the token is passed to the ACP agent in that subscriber's sessions (`codex-acp`, which runs the Codex `app-server`, or opencode).
- Spend for subscription sessions is a notional API-equivalent figure from runtime-reported usage (Claude Code `result` events, ACP `usage_update`), priced from the same table and marked as runtime-reported (ADR-0009). Provider usage windows are tracked separately, and budgets apply to the notional figure.
- This answers the Phase 0 question about broker-held subscription credentials: Cantiere stores the subscriber's own `setup-token` in the secret store and places it in the guest environment of that subscriber's sessions; it never proxies, refreshes or shares it. Whether this counts as intermediating under Anthropic's terms is a residual risk the project owner accepted on 2026-10-08 for the first release of subscription mode; a change to Anthropic's terms or guidance reopens it. The alternative with no stored token is a per-session `/login` through native-terminal take-over (ADR-0013). COST-3's exception to ID-2 is permanent for subscription mode, and the docs say so.
- Subscription mode is disabled by default; the operator enables it after reading the vendor terms, linked from the setting.
- The model deny list (RT-3) cannot be enforced outside the sandbox in subscription mode, because that traffic is not intercepted; only the adapter enforces it.

## Consequences

- API-key sessions get hard budget enforcement outside the sandbox; subscription sessions get best-effort enforcement only (the adapter interrupts at the cap, the gateway cannot).
  "Hard" is in COST-2's sense: nothing the guest does, short of compromising the proxy process, can spend past the cap, apart from a price the price table does not list yet.
  The cost is refusals: a request near the cap whose worst case does not fit is refused even if its real cost would fit, input for providers without a published tokenizer is reserved at one token per byte, so such sessions are refused earlier near the cap, and batch, background, unbounded and usage-less requests are not available to API-key sessions at all.
- A compromise of the proxy process, through a bug in the code that parses sandbox-controlled TLS, HTTP, GraphQL, git packs or model streams, is outside the budget guarantee, as an escape into the worker would have been with an in-worker gateway.
  It does not reach the worker's host privileges, the VM, the platform's services or other sessions' processes, but it does reach every secret the session holds, and some of those reach further than the session:
  - A deployment-wide provider key works outside the gateway, from anywhere, up to the provider-side limit on that key, and spending to that limit stops the model calls of every session that uses the key; per-persona or per-user keys with their own provider spend limits (above) narrow this to one persona or user.
  - The session's installation token reaches the session's target repos with the persona's permissions until it expires within the hour.
  - In `user` mode, the linked user's access token reaches every repo both the user and the installation can, with the user's permissions, because GitHub does not keep the `repository_id` narrowing on refresh (ADR-0012), until it expires within eight hours.
  - The lease lets it spend no more through the gateway, but the keys above are not bound by the lease; provider limits and daily reconciliation bound and detect that spend (above).
- The worker and the proxy process need a small protocol for secrets, policy, lease top-ups and start and end records, plus a per-session journal file; each session costs one more process and one more uid.
- Every request that needs a policy decision and has no cached one waits for one round trip to the server before it is forwarded, and stops being forwarded while the worker or server is unreachable; model calls already in flight are not affected.
- Workers need Linux 5.13 or later for Landlock and systemd 254 or later for `FileDescriptorStorePreserve`; `memfd_secret` is used where the kernel enables it.
- Cantiere maintains the gateway itself: each provider's usage format, including streamed and cache-token usage, and the price table must track provider changes.
  Because requests are not translated, a new provider parameter needs no gateway change; a new beta value or service tier needs a price-table entry in the config repo, and a change to how usage is reported needs a code change.
- A subscription token in a compromised sandbox is exposed for its lifetime (up to a year for `setup-token`), or until the subscriber removes it in their Claude account settings. The token is in the `claude` process environment, so anything that runs in the guest, including the agent's own shell commands and code from the target repository, can read it; turning off project settings and repository MCP servers (above) removes only the paths that run before the first turn. Mitigations are egress allowlisting (ADR-0011), the git proxy's secret scan (ADR-0010), and the single-subscriber restriction. The scrubber catches only literal and known-pattern copies, not encoded ones.
- `pass` domains, including subscription endpoints, are opaque to the proxy, so guest code can send data there with credentials of its own (ADR-0011). Each `pass` entry is an operator-accepted exfiltration channel and is listed in the approval diff.
- Subscription sessions do not load the target repository's Claude Code settings, hooks or `.mcp.json`; a repository that relies on them needs the equivalent in the org layer of the blueprint (ADR-0008).
- Subscription mode needs the subscriber about once a year to renew the token; a missed renewal stops that subscriber's subscription sessions, not API-key sessions.
- Concurrency limits for subscription use are not defined by the vendors; Cantiere exposes a per-user concurrent-session cap for subscription mode.

## Alternatives considered

- **[Tailscale Aperture](https://tailscale.com/docs/aperture/how-aperture-works) as the model gateway** (evaluated 2026-10-13): Aperture holds provider keys centrally, authenticates callers by tailnet identity, and logs and meters usage.
  It is rejected as the gateway because:
  - It is a closed-source service hosted by Tailscale with no self-hosted option, and using your own provider keys outside its Personal plan needs a sales contract ([get started](https://tailscale.com/docs/aperture/get-started)).
  - Its [quotas](https://tailscale.com/docs/aperture/configuration) (per user, per node or shared) deduct the estimated cost after the response, and the last bucket in a chain can go negative; there is no worst-case reservation against a lease from Cantiere's daily counter, so COST-2's hard cap cannot be enforced.
  - Per-session attribution (COST-1) would mean mapping each ephemeral node's device ID back to its session and importing Aperture's usage records; Aperture's own session IDs come from the client inside the sandbox, so they cannot be trusted, and sessions without a tailnet node (ADR-0011) have no identity to call it with.
  - Provider keys would sit as literal values in Aperture's config instead of the secret store (ADR-0010).
  Aperture behind the worker's gateway, as one more upstream provider for deployments that already run it, is not covered by this decision.
  It would keep metering and budgets on the worker, but needs the worker itself on the tailnet; adding it takes a superseding ADR.
- **Gateway inside the worker process:** one process fewer and no worker-to-proxy protocol, but the code that parses sandbox-controlled traffic would run as root beside KVM, the jailer, nftables and every session's secrets.
- **Self-hosted open-source gateways** (evaluated 2026-10-21 against the gateway's required behaviour: unchanged passthrough, keys from OpenBao, per-session keys, reservation before forwarding, per-request cost, audit).
  None meets it in its free edition, and two requirements fail almost everywhere: reading provider keys from OpenBao without a restart, and an audit log, both either paid or missing.
  - [LiteLLM](https://github.com/BerriAI/litellm) `v1.106.1` (MIT, Python): reserves worst-case cost before forwarding by default, and `fail_closed_budget_enforcement` makes it refuse requests when spend cannot be checked, but its Vault integration and audit log need an enterprise licence; it caches keys for 60 s per worker process, so a deleted key keeps working on other workers; its unchanged-passthrough routes use one gateway-wide key resolved at load, so rotating it needs a restart; and its official image bundles the commercially licensed `enterprise/` code.
    It had a PyPI supply-chain compromise (`1.82.7`, `1.82.8`) and three CVEs in 2026.
  - [Bifrost](https://github.com/maximhq/bifrost) `transports/v2.3.2` (Apache-2.0, Go): Vault support and audit log are enterprise-only, and budgets are charged after the response with no reservation.
  - [agentgateway](https://github.com/agentgateway/agentgateway) `v1.6.0` (Apache-2.0, Rust, Linux Foundation): the best data plane of the set (unchanged passthrough, unbuffered streams, signed images, Postgres only), but budgets are charged after the response, there is no OpenBao client or audit log, and counters flush every 5 s.
    Combining it with a Cantiere budget service behind its external-authorization hook and OpenBao Agent was the closest composition and is rejected because agentgateway reads provider keys only inline from config or from files, so OpenBao Agent would have to render them to files (against ADR-0010), it adds three processes per deployment, the authorization hook sees only the first 8 KB of a request body by default, and settlement would come from asynchronous logs.
    It remains the fallback if this decision fails conformance test 9.
  - [Otari](https://github.com/mozilla-ai/otari) `v0.30.1` (Apache-2.0, Python): reserves worst-case cost in one atomic update and refuses unpriced models by default, which this decision's reservation follows, but it reads provider keys only from the environment at start, rebuilds requests through provider SDKs, and runs its own tools outside the session sandbox.
  - Agent Router (formerly Envoy AI Gateway) `v1.2.0`, Apache APISIX `3.19.0`, Kong Gateway OSS `3.9`, Portkey Gateway OSS, GoModel, Higress, TensorZero and Helicone's gateway fail more of it: paid secret-store support, no dollar budgets or per-caller keys in the free edition, Kubernetes-only production support, archived, or relicensed with a hosted-control-plane dependency.
