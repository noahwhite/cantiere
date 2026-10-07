# ADR-0013: Live streams multiplex over vsock and the worker channel; take-over pauses the runtime

- Status: Accepted
- Date: 2026-10-07
- Requirements: UX-2, UX-3, UX-4, UX-5, UX-7, SEC-1

## Context

The session view shows chat, plan, live terminal, diffs, a browser view and a timeline (UX-2), lets a human send messages (UX-3), take over the shell or an editor and hand back (UX-4), and replay finished sessions (UX-5).
ADR-0003 forbids any route from the sandbox to the server.

## Decision

**Transport.** Inside the guest, `cantiere-guest` multiplexes streams (events, PTYs, editor and VNC TCP tunnels) over one vsock connection with yamux. The worker relays them over its gRPC stream to the server. The server fans out to browsers over WebSocket, authenticated with the user session (ADR-0016). Each stream has an ID, and the browser subscribes per session.

**Terminal.** The agent's commands appear as `command` events with output (ADR-0009), rendered as a terminal-style view. A separate human shell is a PTY in the guest, rendered with xterm.js.

**Editor.** code-server runs in the guest bound to localhost and is reached through the tunnel; there is no direct network path.
Guest-served content is attacker-controllable, so it never shares an origin with the Cantiere UI or API:

- It is served from a separate per-session origin (`<session-id>.sandbox.<deployment-domain>`, a separate registrable domain where possible) that holds no Cantiere cookies.
- Access uses a short-lived, single-session capability token that the UI mints and passes once; the sandbox origin sets its own cookie scoped to that host only.
- The proxy strips `Set-Cookie` for other hosts, `Service-Worker-Allowed`, and CORS headers from guest responses, and sets a strict CSP with `frame-ancestors` limited to the Cantiere UI origin.
- The capability token grants editor and terminal access to that one session and nothing in the API.

**Browser view.** Agent browsers run in an Xvfb display in the guest; x11vnc exposes it through the tunnel, and the UI embeds noVNC. Phase 1 is view-only, and interaction comes with take-over.

**Take-over (UX-4).**

1. The human presses take over.
2. The session workflow (ADR-0006) interrupts the current turn and holds the input queue.
3. Shell, editor and browser input are enabled for the human.
4. On hand back, the adapter sends the runtime a message summarizing the human's changes (`git diff` and the commands run) and resumes.

Every take-over and hand-back is a timeline event.

**Replay (UX-5).** Events stay in the timeline (ADR-0005). The human shell PTY is recorded as asciicast v2 in the object store. Diffs are reconstructable from `file_edit` events and the branch.

## Consequences

- Live traffic adds two hops (vsock, then the worker channel); terminal latency is acceptable at this scale and is measured in Phase 0.
- Because there is no inbound path to sandboxes, sharing a live view means sharing a Cantiere session view, never a sandbox URL.
- Deployments need a wildcard DNS record and certificate for the sandbox origin; the installer sets both up (ADR-0019).
