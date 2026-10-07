# ADR-0017: Personas, workflows, blueprints and skills live in versioned config repos

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-1, OSS-3, RT-3, RT-4, ID-3, SB-2, KN-1

## Context

OSS-1 forbids Officina-specific code in core, yet Officina's personas, workflows and skills are the first real workload.
Configuration that changes agent permissions is security-relevant and should be reviewed like code.

## Decision

Cantiere reads configuration from Git, at a pinned commit, in two places:

1. **Deployment config repo** (one per deployment, for example `officina-cantiere-config`):
   - `personas/*.yaml`: runtime, model and effort defaults, model deny list (RT-3), required secrets by reference (ID-3), GitHub permission set and authoring mode (GH-5, GH-7), egress domains, Tailscale tags (SEC-3), budgets (COST-2);
   - `workflows/` (Phase 2);
   - `skills/` or a reference to an external skills repo, mounted read-only into sandboxes (RT-4);
   - `blueprints/org.yaml`: the org-level blueprint layer.
2. **Target repos**: `.agent/blueprint.yaml` per repo (SB-2, ADR-0008) and the repo's own `CLAUDE.md` / `AGENTS.md` (KN-1).

Rules:

- The server tracks the config repo's default branch and records the commit each session ran with; a session never sees config changes mid-run.
- Changes that widen a persona's permissions are shown as a diff in the UI before they take effect.
- All config files have JSON Schemas published from this repo, and the server rejects invalid config with a precise error rather than starting with defaults.
- Secrets are only ever references (`bws://<uuid>`, `vault://path#key`), never values.

## Consequences

- Officina's personas and workflows ship in an Officina config repo, satisfying OSS-1, and become the reference example for others.
- Permission changes get Git history and review for free.

## Alternatives considered

- **Settings stored in the database and edited in the UI:** convenient, but unreviewed and unversioned for security-relevant settings.
