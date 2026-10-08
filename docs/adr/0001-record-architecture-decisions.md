# ADR-0001: Record architecture decisions

- Status: Accepted
- Date: 2026-10-07

## Context

Cantiere is in its design phase, and Phase 0 exits on "sandbox backend chosen, ADR merged".
Decisions made now (isolation boundary, credential flow, data model) are expensive to reverse once code depends on them, and outside contributors need to see why they were made.

## Decision

Record each significant architecture decision as a Markdown file in `docs/adr/`, named `NNNN-kebab-title.md` with a four-digit sequence number.
Each ADR has a status line, a date, the requirement IDs it serves (from `docs/requirements.md`), and the sections Context, Decision, Consequences and Alternatives considered.

Statuses:

- **Proposed:** written and open for review, or accepted in direction but waiting on named evidence (for example a Phase 0 spike result).
- **Accepted:** merged and in force.
- **Superseded by ADR-NNNN:** replaced; the file stays, with a link to its replacement.

An ADR is accepted by merging the PR that sets its status to Accepted.
ADRs are never edited to change a decision after acceptance; a new ADR supersedes the old one.
Typos, links and clarifications that do not change the decision may be edited in place.

`docs/adr/README.md` indexes every ADR with its status.

## Consequences

- Every PR that changes a decided boundary must cite the ADR it follows or add one that supersedes it.
- Proposed ADRs carry their validation criteria, so the spike that settles them has a written exit test.

## Alternatives considered

- **Decisions inside `docs/requirements.md`:** mixes what with why and loses history when the doc is edited.
- **GitHub Discussions or issues:** not versioned with the code and not reviewable as a diff.
