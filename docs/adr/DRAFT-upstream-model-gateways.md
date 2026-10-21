# DRAFT ADR: Upstream model gateways behind the session gateway

- Status: Draft - not proposed yet, no sequence number assigned; the project owner is still deciding whether to adopt it
- Date: 2026-10-21
- Requirements: COST-1, COST-2, RT-3, SEC-2, ID-1, ID-4; proposed requirement below
- Builds on: ADR-0014 as amended by open PR #15 (proxy process confinement and budget bounds); if that PR changes before merging, this draft is revisited

## Context

Some organisations route all model traffic through a gateway of their own, such as LiteLLM, Cloudflare AI Gateway, Portkey or OpenRouter, and do not hand out raw provider keys.
For them, the session gateway (ADR-0014) has no provider key to inject, so a mandated gateway is an adoption blocker.
An upstream gateway also gives what Cantiere does not try to: org-wide spend across tools, data-loss prevention, negotiated pricing, failover and central key ownership.

ADR-0014 already accepts any OpenAI-compatible endpoint and forwards each provider's API unchanged, so a public upstream that preserves a provider's API shape is close to working today.
Four things are not decided:

- how a provider entry names an upstream's address, auth header and extra headers;
- how the session proxy process reaches an upstream on a private address, given PR #15 drops every non-global range, the host's own addresses and the platform services before any allow rule, then adds declared private upstreams to the allow rules;
- what happens when an upstream answers with a different model than the one reserved and checked, for example after failover;
- what happens when an upstream refuses a request for its own budget, since its error passes through unchanged and a runtime may retry it.

Cantiere's own gateway is not replaced: metering, reservations and the deny list stay in the session proxy process, because COST-2 depends on reserving the worst case before forwarding (ADR-0014).

## Decision

**Provider entries can name an upstream.**
A provider entry in the config repo (ADR-0017) gains an optional `upstream` block:

```yaml
providers:
  - name: anthropic-via-corp
    api_shape: anthropic-messages   # anthropic-messages | openai-chat | openai-responses | bedrock | vertex | openai-compatible
    upstream:
      base_url: https://ai-gw.corp.example/anthropic
      network: public               # public | private
      address: null                 # required for private: IP address and port, never a name
      server_name: null             # private only: TLS name to verify when address is an IP
      auth: {header: Authorization, scheme: Bearer}   # the value comes from the persona's secrets entry for this provider
      headers: {x-gw-team: platform}
      attribution: {x-gw-metadata: "session={session_id};persona={persona};issue={issue}"}
      model_signal: {header: x-gw-resolved-model}       # or: body; where the upstream names the model that answered
      model_aliases:
        claude-opus-5-5: {upstream: corp/claude-opus-5-5, fallbacks: [claude-sonnet-5-5]}
        claude-sonnet-5-5: {upstream: corp/claude-sonnet-5-5}
      usage_report: null            # optional: upstream usage API for daily reconciliation
      refusals: [{status: 429, error_code: budget_exceeded}]
```

```yaml
# persona
secrets: [{provider: anthropic-via-corp, ref: "openbao://kv/models#corp-gw"}]
```

- The secret reference stays in the persona, as for any provider (ADR-0010, ADR-0014, ID-3), so per-persona and per-user upstream keys work as provider keys do; config validation rejects a persona that selects an upstream provider without declaring its secret.
- The guest still holds a placeholder for the provider's own credential header; the gateway removes that header and sets the declared `auth` header with the persona's resolved value (ADR-0010, ID-1).
- `headers` are static, non-secret values; config validation rejects any value that looks like a secret reference or matches a known token pattern.
- `attribution` templates may use only `session_id`, `persona`, `issue`, `tenant_id` and `user_id`, filled by the server, never by the guest; each header is capped at 1 KB.
- Header names in `headers` and `attribution` cannot be credential, hop-by-hop or `Host` headers, and the gateway strips guest-supplied headers with the same names on `inspect` and `inject` traffic (ADR-0011).
- `model_aliases` is keyed by the runtime's model name and gives the upstream's name for it and, optionally, fallbacks.
  Each fallback is itself a runtime model name with its own price entry, deny-list status and alias entry, so every model the upstream may answer with is priced and checked under one key.
  An alias rewrites the request's model (the body field, or the URL path for Bedrock and Vertex) to the upstream's name; that rewrite is an exception to unchanged passthrough (below).
- An entry may set per-model price overrides for negotiated prices; config-repo prices still win over seeded ones, and a model with no price is still refused (ADR-0014).

**Reaching the upstream.**

- `network: public`: the upstream's host name joins the proxy process's own outbound allowlist, not the guest's: the resolver answers it only for queries from the proxy process, so the guest cannot reach the upstream except through the gateway.
  The port must be 443.
- `network: private`: the entry declares one IP address and port, and `server_name` when the certificate does not name the IP.
  The session chain and the proxy user's output rules accept new TCP connections to exactly that address and port from the proxy process's user, placed after the drops for the host's own addresses, the metadata address and the server, OpenBao, Postgres and the object store, and before the drop for non-global ranges.
  The guest never matches it, because its traffic only reaches the proxy process.
  For declared private upstreams this replaces PR #15's rule that the non-global drop comes before any rule that allows a new connection, in the session chain and in the gateway-only unit's output rules.
- Config validation rejects a private upstream whose address is a host address of any Cantiere host, the metadata address, or the address of a platform service, so an upstream cannot be co-located on an address the platform protects.
- TLS is required in both modes; the certificate is verified against the system roots plus the operator's upstream trust roots, which PR #15 already passes in `Init`.
- A private upstream needs an operator approval in the config repo's approval diff, listed separately like `pass` domains (ADR-0011, ADR-0017).

**The model that answered is checked before anything is relayed.**

- An upstream is trusted the way a provider is: the gateway cannot prove which model ran, only what the upstream reports.
  A provider's `model` field is that report for a direct provider, but an upstream may echo the requested alias after failing over (LiteLLM does by default), so it is not enough.
- Each upstream entry therefore declares `model_signal`: the response header, or the body field for the entry's API shape, in which the upstream names the deployment that answered, such as LiteLLM's `x-litellm-model-id` header or its body `model` with `return_raw_model_name` set.
  The value is matched against the alias's upstream name and its fallbacks' upstream names.
- The gateway reads the signal from the response headers, the first stream event (Anthropic `message_start`, OpenAI Chat Completions' first chunk, Responses `response.created`) or the body of a non-streamed response, before relaying any byte to the guest.
- If the signal names a model other than the requested one or its declared fallbacks, or is missing, the gateway aborts the response, charges the full reservation, records a `model_mismatch` event and pauses the session to the inbox.
  A pricier model could otherwise spend past the reservation, and a denied model would otherwise reach the guest (RT-3).
- An API shape whose responses name no model, such as Bedrock and Vertex, is allowed behind an upstream only with a header `model_signal`; config validation rejects it otherwise.
- Operators who want upstream failover declare it with fallbacks in `model_aliases`; every fallback must be priced and allowed, and the reservation uses the highest rate across the requested model and its fallbacks.

**Upstream refusals pause the session.**

- A response that matches an entry in `refusals` (status plus error code or type for the entry's API shape) is replaced with the gateway's own `cantiere_upstream_refused` error, HTTP 402, in the provider's error format, and the adapter pauses the session to the inbox with the upstream's reason.
  Conformance test 9's no-retry check covers it.
- Upstreams add two exceptions to unchanged passthrough, next to `cantiere_budget_exceeded` (ADR-0014): the alias rewrite of the request's model, and this refusal replacement.
- Other upstream errors, including 5xx and unmatched 429, pass through as a provider's would.

**Reconciliation and key limits.**

- The daily reconciliation compares recorded cost per upstream key with the upstream's usage API where `usage_report` is set; without it the UI says reconciliation is unavailable for that key.
- The docs recommend a hard budget on each upstream key, which is the provider-side key limit COST-2 relies on as a backstop, and which many providers do not offer directly.
- Spend through an upstream is shown as estimated, because the upstream's bill is the invoice (COST-1, UX-1).

**Scope.**

- The server's gateway-only mode (ADR-0014) uses the same provider entries; a private upstream there is allowed by the same address rule in its unit's output chain.
- Subscription mode is unchanged: its traffic never goes through the gateway.
- Upstreams that join the tailnet, such as Tailscale Aperture, stay out of scope (ADR-0014).

## Proposed requirement

To be numbered on acceptance, in the Cost section of requirements.md, priority S, Phase 2:

> A model provider entry can name an upstream gateway, public or on a declared private address, with its own auth header, static and attribution headers, model aliases with priced fallbacks, a per-response model signal and refusal mapping; metering, budgets and the deny list stay on the session gateway and are checked against the model the upstream reports answering; spend through an upstream is labelled estimated (ADR-NNNN).

## Validation checks

1. Claude Code runs end to end through a public Anthropic-shape upstream with a placeholder in the guest; the upstream key never enters the guest; usage is metered from the passed-through response.
2. opencode runs end to end through a public OpenAI-shape upstream.
3. A private upstream declared by address is reachable from the proxy process; the guest's direct connection to that address is dropped and logged; an undeclared private address is still dropped; a declared address equal to a platform or host address is rejected at config validation.
4. A response whose `model_signal` names a model other than the requested one or its declared fallbacks, or lacks the signal, is aborted before any byte reaches the guest, charged its full reservation, and pauses the session.
   This is tested against each conformance-suite upstream by forcing an undeclared failover inside it, which must be detected even when the response's own `model` field still shows the requested alias.
5. A mapped upstream refusal pauses the session, and the runtime does not retry it.
6. Attribution headers reach the upstream with server-filled values; guest-supplied headers with the same names are stripped.

## Consequences

- Organisations with a mandated gateway can adopt Cantiere without giving it raw provider keys.
- A stolen upstream key works only where the upstream is reachable and within the upstream's own budget for it, which for a private upstream means inside the operator's network.
- Cantiere's spend figures become estimates against the upstream's invoice.
  Caps stay hard in COST-2's sense only as far as the upstream reports the answering model truthfully in its `model_signal`, the same trust ADR-0014 places in a provider's usage and model fields; the upstream key's own budget is the backstop.
- Only upstreams that expose a per-response model signal are supported.
- An upstream that rewrites or drops a provider's usage fields fails validation check 1 or 2 and is unsupported for that API shape.
- Refusal mappings and usage APIs are per-upstream configuration that operators maintain; Cantiere ships tested defaults only for the upstreams in its conformance suite.
- Failover inside the upstream is visible only as declared fallbacks; undeclared failover pauses sessions.

## Alternatives considered

- **Configuration only, no ADR:** enough for a public upstream that preserves API shapes, but it leaves private upstreams, response-model checks and upstream refusals undecided.
- **Reach private upstreams through the session's tailnet node:** tailnet traffic bypasses the proxy and the policy engine, and the guest would get the same reach (ADR-0011).
- **Run the proxy process outside the session namespace when an upstream is private:** removes the network confinement ADR-0014 gives a component that parses sandbox-controlled traffic.
- **Take metering from the upstream's usage reports:** asynchronous and after the fact, so the reservation COST-2 needs is impossible.
- **Translate between API shapes so one upstream serves every runtime:** contradicts ADR-0014's unchanged passthrough and makes every provider change a gateway change.

## Open questions for the owner

1. Ship public upstreams first and private ones later, or both in Phase 2?
2. Refuse co-located upstreams on Cantiere host addresses (this draft), or allow one declared port on a host address?
3. Pause on any undeclared model mismatch (this draft), or allow mismatches priced at or below the reservation?
4. PR #15 adds declared private upstreams to the allow rules but places the non-global drop before every allow rule, so its own text contradicts itself; fix that in PR #15, or leave the override above to this draft?
