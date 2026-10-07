# ADR-0014: Model access goes through a worker-side gateway; subscription logins stay the user's own

- Status: Accepted
- Date: 2026-10-07
- Requirements: COST-1, COST-2, COST-3, RT-3, ID-2; open question "Do Claude Code and Codex subscription terms allow headless use from a self-hosted multi-session server?"; Phase 0 item "test broker-held subscription credentials"

## Context

Cantiere does not resell or proxy model access as a service; each user brings their own credentials (README).
Model spend must be metered per session and hard-capped (COST-1, COST-2), and denied models must be unreachable (RT-3).

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

- The gateway runs on the worker per session and does four things:
  - injects the real key (Anthropic, OpenAI, Bedrock, Vertex, or any OpenAI-compatible endpoint such as DeepSeek, Moonshot, OpenRouter or a local vLLM);
  - rejects requests for denied models (RT-3);
  - reads token usage from responses and prices it from a per-model price table (input, output, cache read and cache write per million tokens) kept in the config repo (ADR-0017), producing authoritative `cost` events (COST-1); a model with no price entry is refused, so API-key spend is never unmetered;
  - enforces budgets with reservations (COST-2): the server grants each session a budget lease from an atomic per-tenant daily counter in Postgres; before forwarding a request the gateway reserves its worst-case cost (input tokens plus `max_tokens` output, at table prices) from the lease, refuses the request if the reservation does not fit, and releases the unused part when the response's usage is known. When the lease and the daily counter are spent the session pauses to the inbox. Spend can therefore never exceed the cap, except by provider-side usage the response does not report, which is reconciled on the next request.
- Keys belong to the deployment or to individual users; per-user keys are used only for that user's sessions.

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
  - Credential isolation: in subscription sessions the guest environment sets none of `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` or `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`, which either outrank `CLAUDE_CODE_OAUTH_TOKEN` or would send the traffic to the gateway. The adapter launches `claude` with `--setting-sources user` and `--strict-mcp-config --mcp-config <blueprint MCP file>`, so the target repository's `.claude/settings.json` (its `env` block, `apiKeyHelper` and hooks) and `.mcp.json` do not load; Cantiere writes the user settings from the blueprint, and blueprint MCP servers load only through `--mcp-config`. Before the first turn the adapter runs `claude auth status` and fails the session closed unless `authMethod` is `oauth_token`. This check guards the launch only: Claude Code reloads changed settings mid-session, so guest code can still add an `apiKeyHelper` to the user settings, just as it can read the token (Consequences). The adapter re-checks the credential source in the `system/init` event on every resume and pauses the session if it has changed.
  - The adapter never passes `--bare`, because bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`.
  - The token can make only model requests, so claude.ai connectors and Remote Control are unavailable in subscription sessions; MCP servers configured by the blueprint still work.
- Cantiere never routes subscription traffic through the gateway, never intercepts it (`pass` mode in ADR-0011), and never uses it with the Agent SDK.
- ChatGPT: the user's sign-in follows OpenAI's self-hosted flow, and the token is passed to the ACP agent in that subscriber's sessions (`codex-acp`, which runs the Codex `app-server`, or opencode).
- Spend for subscription sessions is a notional API-equivalent figure from runtime-reported usage (Claude Code `result` events, ACP `usage_update`), priced from the same table and marked as runtime-reported (ADR-0009). Provider usage windows are tracked separately, and budgets apply to the notional figure.
- This answers the Phase 0 question about broker-held subscription credentials: Cantiere stores the subscriber's own `setup-token` in the secret store and places it in the guest environment of that subscriber's sessions; it never proxies, refreshes or shares it. Whether this counts as intermediating under Anthropic's terms is an accepted residual risk that needs the project owner's sign-off before subscription mode ships. The alternative with no stored token is a per-session `/login` through native-terminal take-over (ADR-0013). COST-3's exception to ID-2 is permanent for subscription mode, and the docs say so.
- Subscription mode is disabled by default; the operator enables it after reading the vendor terms, linked from the setting.
- The model deny list (RT-3) cannot be enforced outside the sandbox in subscription mode, because that traffic is not intercepted; only the adapter enforces it.

## Consequences

- API-key sessions get hard budget enforcement outside the sandbox, at the cost of rejecting a request near the cap whose worst case does not fit even if its real cost would; subscription sessions get best-effort enforcement only (the adapter interrupts at the cap, the gateway cannot).
- A subscription token in a compromised sandbox is exposed for its lifetime (up to a year for `setup-token`), or until the subscriber removes it in their Claude account settings. The token is in the `claude` process environment, so anything that runs in the guest, including the agent's own shell commands and code from the target repository, can read it; turning off project settings and repository MCP servers (above) removes only the paths that run before the first turn. Mitigations are egress allowlisting (ADR-0011), the git proxy's secret scan (ADR-0010), and the single-subscriber restriction. The scrubber catches only literal and known-pattern copies, not encoded ones.
- `pass` domains, including subscription endpoints, are opaque to the proxy, so guest code can send data there with credentials of its own (ADR-0011). Each `pass` entry is an operator-accepted exfiltration channel and is listed in the approval diff.
- Subscription sessions do not load the target repository's Claude Code settings, hooks or `.mcp.json`; a repository that relies on them needs the equivalent in its blueprint.
- Subscription mode needs the subscriber about once a year to renew the token; a missed renewal stops that subscriber's subscription sessions, not API-key sessions.
- Concurrency limits for subscription use are not defined by the vendors; Cantiere exposes a per-user concurrent-session cap for subscription mode.
