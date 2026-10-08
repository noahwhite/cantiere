# ADR-0018: OpenTelemetry for platform telemetry; the timeline is product data, not logs

- Status: Accepted
- Date: 2026-10-07
- Requirements: OBS-2, OBS-3, OBS-4, COST-1, UX-5

## Context

Two different streams exist: platform telemetry (is the system healthy) and session history (what the agent did).
Mixing them puts agent output into a log vendor and makes replay depend on log retention.

## Decision

- Server, worker and guest emit **OpenTelemetry** traces, metrics and logs over OTLP to a configurable endpoint, with resource attributes `service.name`, `deployment.environment` and `cantiere.tenant_id` (OBS-2). Grafana Cloud for Officina.
- A session gets one trace; the session ID is a span attribute on every span and log line, so platform logs link to the session view.
- **Session content** (prompts, tool output, diffs, terminal bytes) goes only to the timeline store (ADR-0005), after secret scrubbing (ADR-0010), never to OTLP logs.
- Spend (COST-1) is computed from timeline cost events and also exported as metrics by persona and model (never by user content).
- Stuck-session and health alerts are defined on metrics (OBS-4, Phase 3) and are not a Phase 1 requirement.

## Consequences

- Telemetry vendors see no code or prompts, which keeps the self-hosted trust story intact.
