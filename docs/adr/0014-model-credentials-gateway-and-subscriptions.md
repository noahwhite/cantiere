# ADR-0014: Model access goes through a worker-side gateway; subscription logins stay the user's own

- Status: Accepted
- Date: 2026-10-07
- Requirements: COST-1, COST-2, COST-3, RT-3, ID-2; open question "Do Claude Code and Codex subscription terms allow headless use from a self-hosted multi-session server?"; Phase 0 item "test broker-held subscription credentials"

## Context

Cantiere does not resell or proxy model access as a service; each user brings their own credentials (README).
Model spend must be metered per session and hard-capped (COST-1, COST-2), and denied models must be unreachable (RT-3).

The terms differ by vendor:

- [Anthropic](https://code.claude.com/docs/en/legal-and-compliance): subscription OAuth is for ordinary use of the unmodified Claude Code binary, which an end user may sign in to even where a platform hosts it. Products, including Agent SDK integrations, must use API keys. Developers "may not collect, store, or intermediate Claude.ai credentials or session tokens".
- OpenAI: "Sign in with ChatGPT" for open-source, self-hosted apps (preview) explicitly supports [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms.md) and passing the token to a Codex `app-server` child process.

## Decision

**API-key mode (default).**

- Each runtime's base URL points at the worker's model gateway: `ANTHROPIC_BASE_URL`, Codex `model_providers` base URL, and opencode provider `baseURL`. The sandbox holds only a placeholder key.
- The gateway runs on the worker per session and does four things:
  - injects the real key (Anthropic, OpenAI, Moonshot, Bedrock, Vertex, or any OpenAI-compatible endpoint);
  - rejects requests for denied models (RT-3);
  - reads token usage from responses to produce authoritative `cost` events (COST-1);
  - refuses new requests once the session or daily budget is spent, which pauses the session to the inbox (COST-2).
- Keys belong to the deployment or to individual users; per-user keys are used only for that user's sessions.

**Subscription mode (opt-in, single-subscriber deployments only, COST-3).**

- Available only where the subscriber is the deployment's operator and the sandboxes run on infrastructure only they control, which matches Anthropic's "user signs in to the unmodified binary" allowance and OpenAI's "remote runtime only that user controls" wording most closely. Multi-user deployments cannot enable it.
- Claude: the subscriber generates their own token with `claude setup-token` and stores it in their own secret-store scope. Cantiere places it in the environment of that subscriber's sessions, for the unmodified `claude` binary only. Storing the token is unavoidable for disposable sandboxes; this residual terms risk is stated in the setting's description.
- Cantiere never routes subscription traffic through the gateway, never intercepts it (`pass` mode in ADR-0011), and never uses it with the Agent SDK.
- Codex: the user's ChatGPT sign-in follows OpenAI's self-hosted flow, and the token is passed to the `app-server` child process.
- Spend for subscription sessions is a notional API-equivalent figure from runtime `cost` events. Provider usage windows are tracked separately, and budgets apply to the notional figure.
- This answers the Phase 0 question: the broker will **not** hold or inject Claude subscription credentials, because that would intermediate them. COST-3's exception to ID-2 is permanent for subscription mode, and the docs say so.
- Subscription mode is disabled by default; the operator enables it after reading the vendor terms, linked from the setting.
- The model deny list (RT-3) cannot be enforced outside the sandbox in subscription mode, because that traffic is not intercepted; only the adapter enforces it.

## Consequences

- API-key sessions get hard budget enforcement outside the sandbox; subscription sessions get best-effort enforcement only (the adapter interrupts at the cap, the gateway cannot).
- A subscription token in a compromised sandbox is exposed for its lifetime (up to a year for `setup-token`). Mitigations are egress allowlisting (ADR-0011), the git proxy's secret scan (ADR-0010), and the single-subscriber restriction. The scrubber catches only literal and known-pattern copies, not encoded ones.
- Concurrency limits for subscription use are not defined by the vendors; Cantiere exposes a per-user concurrent-session cap for subscription mode.
