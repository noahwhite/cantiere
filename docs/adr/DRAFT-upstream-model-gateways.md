# DRAFT ADR: Upstream model gateways behind the session gateway

- Status: Draft - not proposed yet, no sequence number assigned; the project owner is still deciding whether to adopt it
- Date: 2026-10-21
- Requirements: COST-1, COST-2 (amended below), RT-3, SEC-2, ID-1, ID-3, ID-4; proposed requirement below
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
      model_signal: {header: x-litellm-model-id}        # or: body field; where the upstream identifies what answered
      model_aliases:
        claude-opus-5-5: {upstream: corp/claude-opus-5-5, signal_values: [opus-eu-1], fallbacks: [claude-sonnet-5-5]}
        claude-sonnet-5-5: {upstream: corp/claude-sonnet-5-5, signal_values: [sonnet-eu-1]}
      usage_report: null            # optional: upstream usage API for daily reconciliation
      refusals: [{status: 429, error_code: budget_exceeded}]   # only errors the upstream returns before calling a model
      pre_invocation_errors: [{status: 401}]                     # optional: other errors returned before calling a model
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
- `model_aliases` is keyed by the runtime's model name and gives the upstream's name for it, the `model_signal` values that identify it, and, optionally, fallbacks.
  Each fallback is itself a runtime model name with its own price entry, deny-list status and alias entry, so every model the upstream may answer with is priced and checked under one key.
  An alias rewrites the request's model (the body field, or the URL path for Bedrock and Vertex) to the upstream's name; that rewrite is an exception to unchanged passthrough (below).
- An entry may set per-model price overrides for negotiated prices; config-repo prices still win over seeded ones, and a model with no price is still refused (ADR-0014).

**Reaching the upstream.**

- `network: public`: the upstream's host name joins the proxy process's own outbound allowlist, not the guest's: the resolver answers it only for queries from the proxy process, so the guest cannot reach the upstream except through the gateway.
  The port must be 443.
- `network: private`: the entry declares one IP address and port, and `server_name` when the certificate does not name the IP.
  The session chain and the proxy user's output rules accept new TCP connections to exactly that address and port from the proxy process's user, placed after the drops for the host's own addresses, the metadata address and the server, OpenBao, Postgres and the object store, and before the drop for non-global ranges.
  The guest never matches it, because its traffic only reaches the proxy process.
  For declared private upstreams this replaces PR #15's rule that the non-global drop comes before any rule that allows a new connection, in the session chain, in the gateway-only unit's output rules and in the Compose gateway's `DOCKER-USER` rules.
- Config validation rejects a private upstream whose address is a host address of any Cantiere host, the metadata address, or the address of a platform service, so an upstream cannot be co-located on an address the platform protects.
- TLS is required in both modes; the certificate is verified against the system roots plus the operator's upstream trust roots, which PR #15 already passes in `Init`.
- A private upstream needs an operator approval in the config repo's approval diff, listed separately like `pass` domains (ADR-0011, ADR-0017).

**The model that answered is checked before anything is relayed.**

- An upstream is trusted the way a provider is: the gateway cannot prove which model ran, only what the upstream reports.
  A provider's `model` field is that report for a direct provider, but an upstream's body `model` need not name what ran: LiteLLM, for example, returns the requested name when it switches between deployments inside one model group.
- Each upstream entry therefore declares `model_signal`: the response header, or the body field for the entry's API shape, in which the upstream identifies what answered, such as LiteLLM's [`x-litellm-model-id`](https://docs.litellm.ai/docs/proxy/response_headers), the ID of the deployment that served the request.
  Each alias and fallback lists the exact values that identify it in `signal_values` (for LiteLLM, deployment IDs the operator pins with `model_info.id`), and config validation rejects an alias or fallback without one, and any value listed under more than one model key in the provider entry, so each value identifies exactly one price entry.
  The signal is matched against those values, not against the upstream names.
- The gateway reads the signal from the response headers, the first stream event (Anthropic `message_start`, OpenAI Chat Completions' first chunk, Responses `response.created`) or the body of a non-streamed response, before relaying any byte to the guest.
- The check applies to successful responses only, because upstreams such as LiteLLM [send the signal only on successful responses](https://github.com/BerriAI/litellm/issues/17083); error responses follow the rules under the next heading.
- If a successful response's signal is missing or matches none of the requested model's or its declared fallbacks' `signal_values`, the gateway aborts the response, charges the full reservation, records a `model_mismatch` event and pauses the session to the inbox.
  A pricier model would otherwise keep spending past the reservation, and a denied model would otherwise reach the guest (RT-3).
- An API shape whose responses name no model, such as Bedrock and Vertex, is allowed behind an upstream only with a header `model_signal`; config validation rejects it otherwise.
- Operators who want upstream failover declare it with fallbacks in `model_aliases`; every fallback must be priced and allowed.
  The reservation is the largest of the ADR-0014 worst cases computed for the request against the requested model and against each declared fallback, each with its own price entry, maximum output, tier thresholds, tokenizer, modalities, provider-run tools and price switches; a request that the rules for any of them would refuse is refused.

**Upstream refusals pause the session; other errors are charged unless declared pre-invocation.**

- A response that matches an entry in `refusals` (status plus error code or type for the entry's API shape) is replaced with the gateway's own `cantiere_upstream_refused` error, HTTP 402, in the provider's error format, and the adapter pauses the session to the inbox with the upstream's reason.
  Conformance test 9's no-retry check covers it.
- Upstreams add two exceptions to unchanged passthrough, next to `cantiere_budget_exceeded` (ADR-0014): the alias rewrite of the request's model, and this refusal replacement.
- An error does not prove that no model ran: an upstream can fail after a billed call, or block a response with a post-call guardrail or data-loss check.
  So only errors the operator declares as returned before any model call, the `refusals` and `pre_invocation_errors` entries, release their reservation, and only when the response reports no usage and carries no `model_signal`; otherwise it is charged like any other error.
  A releasing `pre_invocation_errors` match also pauses the session to the inbox, as a refusal does.
  Once a releasing match has paused the session, later matches from requests still in flight are charged like any other error, not released, so a mis-declared mapping releases at most one reservation per session before a person sees it; across sessions, a hard budget on the upstream key bounds the total where the operator sets one, and otherwise nothing does.
  A mapping must not match an error shape the upstream also returns after a model call, such as a guardrail block shared by pre-call and post-call checks; Cantiere's shipped mappings are verified by the conformance suite, and operator-added mappings are listed separately in the config repo's approval diff (ADR-0017).
  Every other upstream error, including 5xx and unmatched 429, passes through unchanged and is charged at its reported usage priced at the most expensive of the requested model and its declared fallbacks, since the model check covers successful responses only, so an error's signal, when present, is not trusted to select a price, or at its full reservation when it reports none, under ADR-0014's rule for a request whose final usage never arrives.
  An error whose `model_signal` is present but matches none of the requested model's or its declared fallbacks' `signal_values` is a mismatch: it is charged the larger of its full reservation and its reported usage priced at the most expensive declared model, records `model_mismatch` and pauses the session; a matching signal is still not used to select a lower price.

**Reconciliation and key limits.**

- The daily reconciliation compares recorded cost per upstream key with the upstream's usage API where `usage_report` is set; without it the UI says reconciliation is unavailable for that key.
- The docs recommend a hard budget on each upstream key, which is the provider-side key limit COST-2 relies on as a backstop, and which many providers do not offer directly.
  Without one, the key-budget backstops named under Consequences do not apply.
- Spend through an upstream is shown as estimated, because the upstream's bill is the invoice (COST-1, UX-1); undeclared upstream errors are charged in full, so recorded spend can exceed the invoice.

**Scope.**

- The server's gateway-only mode (ADR-0014) uses the same provider entries.
  A private upstream there is allowed by the same address rule in its systemd unit's output chain; in the Compose deployment (ADR-0019), the shipped `DOCKER-USER` rules accept forwarded new TCP connections from the gateway's network to exactly the declared address and port, after the drops for host, metadata and platform-service addresses and before the non-global drop.
- Subscription mode is unchanged: its traffic never goes through the gateway.
- Upstreams that join the tailnet, such as Tailscale Aperture, stay out of scope (ADR-0014).

## Proposed requirement

To be numbered on acceptance, in the Cost section of requirements.md, priority S, Phase 2:

> A model provider entry can name an upstream gateway, public or on a declared private address, with its own auth header, static and attribution headers, model aliases with priced fallbacks, a per-response model signal and refusal mapping; metering, budgets and the deny list stay on the session gateway and are checked against the model the upstream reports answering; spend through an upstream is labelled estimated (ADR-NNNN).

Adopted with it, COST-2's exception clause gains the cases this draft cannot cap:

> ... or, through an upstream gateway (ADR-NNNN), a model the upstream does not report truthfully, an undeclared failover that ends in an error with no model signal, or a release mapping that matches an error returned after a model call (at most one reservation per session).

## Validation checks

1. Claude Code runs end to end through a public Anthropic-shape upstream with a placeholder in the guest; the upstream key never enters the guest; usage is metered from the passed-through response.
2. opencode runs end to end through a public OpenAI-shape upstream.
3. A private upstream declared by address is reachable from the proxy process and from the gateway-only server under systemd and under Compose; the guest's direct connection to that address is dropped and logged; an undeclared private address is still dropped; a declared address equal to a platform or host address is rejected at config validation.
4. A successful response whose `model_signal` matches none of the requested model's or its declared fallbacks' `signal_values`, or lacks the signal, is aborted before any byte reaches the guest, charged its full reservation, and pauses the session.
   Config validation rejects a signal value listed under two model keys.
   This is tested against each conformance-suite upstream by forcing an undeclared failover inside it, which must be detected even when the response's own `model` field still shows the requested alias.
5. A mapped upstream refusal that carries no `model_signal` becomes `cantiere_upstream_refused`, releases its reservation and pauses the session, and the runtime does not retry it; a mapped error that reports usage is charged, not released; matching errors from requests in flight after a releasing match has paused the session are charged, not released; an error carrying a signal outside the declared `signal_values` is charged its full reservation and pauses the session; for each conformance-suite upstream the suite drives every post-call failure path it offers (a post-call guardrail or data-loss block, and a failure after a billed call) and asserts that none matches a shipped release mapping; an undeclared upstream 5xx without usage is charged its full reservation.
6. Attribution headers reach the upstream with server-filled values; guest-supplied headers with the same names are stripped.
7. A request with no output limit, whose declared fallback has a larger maximum output or a higher tier price than the requested model, reserves the fallback's worst case.

## Consequences

- Organisations with a mandated gateway can adopt Cantiere without giving it raw provider keys.
- A stolen upstream key works only where the upstream is reachable and within the upstream's own budget for it where one is set, which for a private upstream means inside the operator's network.
- Cantiere's spend figures become estimates against the upstream's invoice.
  Caps stay hard in COST-2's sense only as far as the upstream reports the answering model truthfully in its `model_signal`, the same trust ADR-0014 places in a provider's usage and model fields, and as far as the release mappings match only errors returned before a model call.
  Error responses without a signal are priced against the declared models, so an undeclared failover that ends in such an error is under-charged and not detected; the upstream key's own budget, where set, is the backstop.
  A truthful signal that names an undeclared model, on a successful or an error response, is detected and pauses the session, but that request has already run at the undeclared model's price, so its cost can exceed its reservation, like a price the price table does not list yet (ADR-0014); daily reconciliation detects it where `usage_report` is set, and the upstream key's budget, where set, bounds it.
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
4. PR #15 adds declared private upstreams to the allow rules but places the non-global drop before every allow rule, so its own text contradicts itself, and its Compose `DOCKER-USER` rules have no private-upstream exception at all; fix both in PR #15, or leave the overrides above to this draft?
