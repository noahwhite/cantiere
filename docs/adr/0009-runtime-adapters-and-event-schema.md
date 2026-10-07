# ADR-0009: Runtime adapters drive unmodified agent CLIs through their native headless protocols and emit one event schema

- Status: Accepted
- Date: 2026-10-07
- Requirements: RT-1, RT-2, RT-3, RT-6, UX-2, UX-3, UX-5, COST-1, KN-1

## Context

Cantiere hosts existing CLIs rather than an agent loop of its own (ADR-0002).
Each CLI has a different headless surface, and the platform needs one timeline, mid-run messages, interrupts, resume and cost.
Anthropic's terms allow subscription sign-in only for the unmodified Claude Code binary, and direct product integrations to API keys ([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)); driving the CLI directly keeps both modes open (ADR-0014).

## Decision

Adapters are Go code inside `cantiere-guest`, one per runtime, implementing:

```go
type Runtime interface {
    Start(ctx, SessionSpec) error          // model, effort, persona prompt, workdir
    Send(ctx, UserMessage) error           // UX-3
    Interrupt(ctx) error
    Events() <-chan *eventsv1.Event        // normalized, RT-2
    Checkpoint(ctx) (NativeState, error)   // runtime transcript for resume
    Resume(ctx, NativeState) error
}
```

| Runtime | Surface | Mid-run input | Resume |
| --- | --- | --- | --- |
| Claude Code | `claude -p --input-format stream-json --output-format stream-json --verbose` ([headless](https://code.claude.com/docs/en/headless)) | Queued for the next turn; `interrupt` ends the current turn | `--resume <transcript.jsonl>` |
| Codex CLI | `codex app-server` JSON-RPC over stdio ([app-server](https://learn.chatgpt.com/docs/app-server)) | `turn/steer` appends to the running turn | `thread/resume` |
| opencode | `opencode serve` HTTP API + SSE `/event` ([server](https://opencode.ai/docs/server/)) | `prompt_async`; joins the running loop (from source, undocumented) | Session ID |

Rules:

- CLIs are installed at pinned versions in the template and run unmodified as an unprivileged `agent` user.
- CLI permission prompts are turned off inside the sandbox; the VM, egress proxy and policy engine are the controls (ADR-0010, ADR-0011, ADR-0015). Repo-defined hooks in target repos run as normal repo code, inside the boundary.
- Model and effort are set per session from persona defaults; denied models (RT-3) are rejected by the adapter and again at the model gateway (ADR-0014), so an API-key session cannot bypass the deny list. Subscription sessions bypass the gateway, so there the adapter is the only check (ADR-0014).
- Native transcripts are checkpointed to the object store after every turn so a session can resume on another sandbox.
- **Event schema** `cantiere.events.v1` (protobuf, ADR-0004): `message`, `thinking_summary`, `tool_call`, `tool_result`, `command` (argv, cwd, exit code, output reference), `file_edit` (path, unified diff), `plan` (checklist), `cost` (model, input, output and cache tokens, USD), `status`, `question` (needs human), `error`. Every event carries `session_id`, `seq`, timestamp, runtime and a `trust` tag (`trusted`, `untrusted`) for SEC-6.
- Unknown native events are kept as `raw` with the original JSON so nothing is lost when a CLI adds features.
- Adapters that need a vendor SDK only available in TypeScript or Python run as a child process speaking this contract over stdio.
- A conformance suite replays recorded native streams through each adapter and checks the normalized output; it becomes the public test kit under OSS-5.

## Consequences

- Adding a CLI is an adapter plus template entry, not a fork (RT-1).
- The Codex adapter depends on `app-server`, which OpenAI still labels experimental; the adapter falls back to `codex exec --json` with `exec resume` per turn (no mid-turn steering) if a pinned version breaks.
- Mid-run messages behave per runtime (steer vs queue); the UI states which.
