# ADR-0014: Model access goes through a per-session gateway process on the worker; subscription logins stay the user's own

- Status: Accepted
- Date: 2026-10-07
- Updated: 2026-10-21 - the gateway runs in a per-session unprivileged proxy process, and the build-vs-reuse evaluation of existing gateways is recorded
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
  - reads token usage from responses and prices it from a per-model price table (input, output, cache read and cache write per million tokens) kept in the config repo (ADR-0017), producing authoritative `cost` events (COST-1); a model with no price entry is refused, so API-key spend is never unmetered;
  - enforces budgets with reservations (COST-2): the server grants each session a budget lease from an atomic per-tenant daily counter in Postgres; before forwarding a request the gateway reserves its worst-case cost (input tokens plus `max_tokens` output, at table prices) from the lease, refuses the request if the reservation does not fit, and releases the unused part when the response's usage is known. When the lease and the daily counter are spent the session pauses to the inbox. Spend can therefore never exceed the cap, except by provider-side usage the response does not report, which is reconciled on the next request.
- The gateway forwards each provider's own API (Anthropic Messages, OpenAI Chat Completions and Responses, Bedrock, Vertex, OpenAI-compatible endpoints) without translating it.
  Apart from swapping the placeholder for the real credential and choosing the upstream, request and response bytes pass through unchanged, including unknown fields and `anthropic-beta` headers.
  Streams are relayed as they arrive; usage is read from the stream while relaying it, not by buffering it.
- A budget refusal gets its own error type, `cantiere_budget_exceeded`, with HTTP status 402 and a body in the provider's own error format; the adapter pauses the session to the inbox on it.
  Conformance test 9 (architecture.md) checks, for Claude Code and for each ACP agent before it is enabled for API-key sessions, that the runtime treats this refusal as final and does not retry it; if a runtime retries 402, the status is changed for all runtimes in a superseding ADR.
- The price table in the config repo may be seeded from LiteLLM's MIT-licensed `model_prices_and_context_window.json`, credited in `NOTICE`; config-repo entries always win, and the missing-price rule above is unchanged.
- Keys belong to the deployment or to individual users; per-user keys are used only for that user's sessions.

**Where the gateway runs: a per-session proxy process.**

- For each session the worker starts one proxy process, `cantiere-worker proxy`, a subcommand of the same static binary (ADR-0019), inside the session's network namespace.
  That process hosts the model gateway together with the session's egress proxy (ADR-0011) and git proxy (ADR-0010), so the choke point those decisions share stays one process.
- The process runs as a per-session unprivileged user with no capabilities, under a seccomp filter, with no access to `/dev/kvm`, the jailer, nftables, the worker's gRPC stream or other sessions.
  The worker creates its listening sockets in the namespace and passes them in, so it needs no privilege to bind ports 80 and 443.
- The worker sends the process only that session's secret values, the per-session CA key and the budget lease, over one end of a Unix socket pair created at start, using the protobuf contracts of ADR-0004.
  Values stay in the process's memory, never on disk, in argv or in its environment (ID-4).
  Lease top-ups arrive on the same socket.
- The worker keeps its own end of each socket in systemd's file descriptor store for the worker service (`FileDescriptorStoreMax`), so the socket stays open across `systemctl restart`, an upgrade or a crash and restart; on start the worker takes each socket back and re-adopts the running proxy through it (OBS-1).
  After a full stop the store is emptied, so on start the worker stops each proxy it cannot re-adopt and starts a new one, as after a proxy crash (below).
- Every request that injects a credential, which includes every model request, is recorded before it is forwarded.
  The process sends a start record (a random 128-bit request ID, the session, the destination and, for a model request, the model and its reservation) and forwards the request only after the server has stored the record and accepted it through the worker.
  The server accepts a start only while the session is running and its lease covers the reservation, and rejects it otherwise, so a session that ended while the worker was down cannot start a model call after reconnecting.
  Start records are idempotent by request ID: the process resends an unanswered start after a reconnect, and the server returns its first decision only while the session is still running; once the session has ended it rejects every start, including a resend of one it had accepted, and records that request as not forwarded.
  If the caller has gone away before the decision arrives, the process sends an end record marked not forwarded, which releases the reservation.
- When a request ends, the process appends an end record with the same request ID (status and, for a model request, the usage and cost) to a per-session journal file, then sends it; the worker reads the journal when it adopts or restarts the process and resends what the server has not acknowledged, and the server ignores a second end record for the same request ID.
  The process scrubs every record with the session's secret values, using the worker's scrubber (ADR-0010), before writing it, so the journal holds only request IDs, statuses, usage, cost and scrubbed denial details, never secrets or request or response bodies, and the worker deletes it when the session's records are all acknowledged.
  The worker scrubs and relays both records to the server as before (ADR-0010, ADR-0015).
- Each denial is an individual record, written to the same journal and sent the same way, without a start record (ADR-0011, SEC-2).
  The journal has a fixed size cap.
  Accepting a start reserves journal space for that request's end record, so an in-flight request can always record its usage and cost.
  When the rest of the journal is full, the process stops reading new requests from every guest connection, open or new, until the worker has drained it; no new request means no new denial, so a guest cannot exhaust the process's memory or disk during a worker outage, and no denial or end record is summarised or dropped.
- The process runs in its own systemd scope outside the worker's cgroup, like the session's VM (ADR-0003), so restarting or upgrading the worker does not cut in-flight model streams.
  While the worker or the server is unreachable, no start record can be accepted, so the process forwards no new credentialed request; streams already in flight finish and write their end records to the journal.
- If the process exits, the session's egress stops, because nftables still redirects only to it (fail-closed).
  The worker restarts it with the session's secrets and the remaining lease, after collecting its journal.
  The server counts the full reservation of every request that has a start record and no end record as spent, so a crash can over-count spend but never under-count it, and every such request still has its start record in the audit log.
- Model calls the server makes itself, outside any session (KN-2, KN-3, KN-4), go through the same binary run beside the server in gateway-only mode, with a lease from a per-tenant system budget; the server passes it keys over a Unix socket in the same way.
- The usage parsers, pricing, reservation logic and passthrough proxy are separate crates that do not depend on Cantiere's session types, so the gateway can be released on its own later without a rewrite.

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

- API-key sessions get hard budget enforcement outside the sandbox, at the cost of rejecting a request near the cap whose worst case does not fit even if its real cost would; subscription sessions get best-effort enforcement only (the adapter interrupts at the cap, the gateway cannot).
- A bug in the code that parses sandbox-controlled TLS, HTTP, GraphQL or model streams reaches one session's proxy process, that session's secrets and its remaining lease, not the worker's host privileges or other sessions.
- The worker and the proxy process need a small protocol for secrets, lease top-ups and start and end records, plus a per-session journal file for end records, and each session costs one more process of a few MB.
- Every credentialed request waits for one round trip to the server before it is forwarded, and stops being forwarded while the worker or server is unreachable; model calls already in flight are not affected.
- Cantiere maintains the gateway itself: each provider's usage format, including streamed and cache-token usage, and the price table must track provider changes.
  Because requests are not translated, a new provider parameter or beta header needs no gateway change unless it changes how usage is reported.
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
