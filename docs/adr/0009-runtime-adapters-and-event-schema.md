# ADR-0009: Claude Code runs over its native headless protocol, every other agent over ACP, and both emit one event schema

- Status: Accepted
- Date: 2026-10-07
- Requirements: RT-1, RT-2, RT-3, RT-6, UX-2, UX-3, UX-5, COST-1, KN-1

## Context

Cantiere hosts existing agent CLIs rather than an agent loop of its own (ADR-0002).
The platform needs one timeline, mid-run messages, interrupts, resume, cost and the user's slash commands for every runtime.

The constraints that shape the adapters:

- Claude subscription sign-in is allowed only in the unmodified Claude Code binary; products and Agent SDK integrations must use API keys ([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). Claude Code's own [ACP adapter](https://github.com/zed-industries/claude-agent-acp) is built on the Agent SDK, so driving Claude Code through ACP would rule out subscription mode (ADR-0014).
- Other vendors' subscriptions are not tied to their own CLI the same way: ChatGPT sign-in is supported in opencode and in Codex (ADR-0014).
- The [Agent Client Protocol](https://agentclientprotocol.com/) (ACP, JSON-RPC over stdio) is implemented by [dozens of agents](https://agentclientprotocol.com/overview/agents), including opencode, Codex (through the [`codex-acp`](https://github.com/agentclientprotocol/codex-acp) adapter), Kimi CLI, goose and Gemini CLI.
- Sub-agent orchestration ("agents mode") does not need to come from the runtime: Cantiere's child sessions and workflows (WF-1, WF-2, ADR-0006) provide it for any runtime.

## Decision

`cantiere-guest` (Rust, ADR-0004) has exactly two adapters behind one trait:

```rust
#[async_trait]
pub trait Runtime {
    async fn start(&mut self, spec: SessionSpec) -> Result<()>;      // model, effort, persona prompt, workdir
    async fn send(&mut self, msg: UserMessage) -> Result<()>;        // UX-3; text may be a slash command
    async fn interrupt(&mut self) -> Result<()>;
    fn events(&mut self) -> EventStream;                             // normalized cantiere.events.v1, RT-2
    async fn checkpoint(&mut self) -> Result<NativeState>;           // native transcript for resume
    async fn resume(&mut self, state: NativeState) -> Result<()>;
}
```

| Adapter | Phase | Surface | Mid-run input | Resume | Commands advertised by |
| --- | --- | --- | --- | --- | --- |
| `claude-code` | 1 | `claude -p --input-format stream-json --output-format stream-json --verbose` ([headless](https://code.claude.com/docs/en/headless)) | Queued by Claude Code for the next turn; `interrupt` ends the current turn | `--resume <transcript.jsonl>` | `slash_commands` in the `system/init` event |
| `acp` | 2 | Any ACP agent over stdio, using the [`agent-client-protocol`](https://crates.io/crates/agent-client-protocol) crate | Queued by the adapter and sent as the next `session/prompt`; `session/cancel` interrupts | `session/load` or `session/resume` when the agent advertises it | `available_commands_update` |

**ACP agents are configuration, not code.**
Each agent is an entry in the sandbox template (ADR-0008) and the config repo (ADR-0017):

```yaml
agents:
  opencode:
    command: [opencode, acp]
    state_paths: [~/.local/share/opencode]   # checkpointed for resume
  codex:
    command: [codex-acp]
    state_paths: [~/.codex/sessions]
```

A persona selects one (`runtime: acp`, `agent: opencode`, plus model and credentials, ADR-0014).
Adding an ACP agent is a template and config change; the conformance suite below runs against it before it is offered.

**Slash commands.**

- Users' skills, custom commands, plugin commands and MCP prompts reach the sandbox through the skills drive and the repo checkout (ADR-0008), so they run exactly as in a terminal.
- The adapter emits a `commands_available` event from the runtime's own advertisement (table above), and the UI's `/` palette is built from it (ADR-0013). Cantiere keeps no command list of its own.
- A message starting with `/` is passed to the runtime unchanged. Claude Code expands it in headless mode, including built-ins that work without a terminal (`/compact`, `/clear`, `/context`, `/model <name>`, `/config key=value` and others); ACP agents receive it as prompt text, which is how ACP defines command dispatch.
- Built-ins whose job belongs to the platform are platform actions, not runtime commands: resume and rewind are session history and checkpoints, `/agents` is child sessions, `/permissions` is policy (ADR-0015), and `/login` is never needed because credentials are injected (ADR-0010, ADR-0014). The palette shows these as Cantiere actions.
- Commands that only work in a terminal are reachable through native-terminal take-over (ADR-0013).

**Rules for both adapters.**

- CLIs are installed at pinned versions in the template and run unmodified as an unprivileged `agent` user.
- CLI permission prompts are turned off inside the sandbox; the ACP adapter answers `session/request_permission` with allow and records it on the timeline. The VM, egress proxy and policy engine are the controls (ADR-0010, ADR-0011, ADR-0015). Repo-defined hooks in target repos run as normal repo code, inside the boundary.
- Model and effort are set per session from persona defaults; denied models (RT-3) are rejected by the adapter and again at the model gateway (ADR-0014), so an API-key session cannot bypass the deny list. Subscription sessions bypass the gateway, so there the adapter is the only check (ADR-0014).
- Native transcripts (Claude Code's JSONL, an ACP agent's `state_paths`) are checkpointed to the object store after every turn so a session can resume on another sandbox. An ACP agent that supports neither `session/load` nor `session/resume` restarts with a summary of the previous transcript.
- **Event schema** `cantiere.events.v1` (protobuf, ADR-0004): `message`, `thinking_summary`, `tool_call`, `tool_result`, `command` (argv, cwd, exit code, output reference), `file_edit` (path, unified diff), `plan` (checklist), `cost` (model, input, output and cache tokens, USD), `commands_available` (name, description, input hint, source), `status`, `question` (needs human), `error`. Every event carries `session_id`, `seq`, timestamp, runtime and a `trust` tag (`trusted`, `untrusted`) for SEC-6.
- `cost` events come from the model gateway when the session uses it; otherwise from the runtime (Claude Code `result` usage, ACP `usage_update`), marked as runtime-reported (ADR-0014).
- Unknown native events are kept as `raw` with the original JSON so nothing is lost when a runtime adds features.
- A conformance suite replays recorded native streams through each adapter, and for ACP through each configured agent, and checks the normalized output; it becomes the public test kit under OSS-5.

## Consequences

- One native adapter keeps the full Claude Code feature set and subscription mode; one ACP adapter covers every other agent, so supporting a new agent rarely means new code (RT-1).
- Other models (DeepSeek, Kimi, Qwen, local vLLM) are reached through an ACP agent such as opencode whose provider base URL points at the model gateway (ADR-0014); Cantiere needs no per-model code.
- Mid-run messages queue for the next turn on both adapters; no runtime is steered mid-turn, and the UI says so.
- ACP agents differ in which optional capabilities they implement (session loading, usage reporting, commands); the adapter reads the `initialize` capabilities and the UI hides what an agent lacks.

## Alternatives considered

- **Build our own harness on an open-source agent framework:** gives full control, but cannot run Claude on a subscription (only Claude Code can), and duplicates work the CLIs and their communities already do.
- **A native adapter per CLI (Codex `app-server`, `opencode serve`):** richer per-CLI features, such as Codex mid-turn steering, at the cost of one adapter and one conformance target per CLI, against protocols their vendors label experimental or leave undocumented.
- **Claude Code through ACP as well:** one adapter for everything, but Claude Code's ACP adapter is built on the Agent SDK and therefore API-key only.
