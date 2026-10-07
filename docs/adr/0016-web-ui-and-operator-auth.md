# ADR-0016: Operator authentication with passkeys or OIDC; multi-user-ready identity model

- Status: Accepted
- Date: 2026-10-07
- Requirements: OSS-4, OSS-6, UX-7, GH-6, IN-4

## Context

Phase 1 has one human operator, but GitHub user linking (GH-6), approvals (WF-4) and audit actors (SEC-5) all need a stable user identity, and multi-user with roles comes later (OSS-4).

## Decision

- The server owns a `users` table (per tenant) from day one; the Phase 1 install creates one owner user.
- Sign-in is **WebAuthn passkeys** by default, or **OIDC** against an external IdP when configured; no passwords.
- Browser sessions use an HTTP-only, `SameSite=Strict`, host-only cookie on the UI origin; no guest-served content is ever served from that origin (ADR-0013). The CLI (IN-4) and API use personal access tokens with scopes, stored hashed, shown once.
- **Cross-site requests:** sandbox origins are often same-site with the UI (`<session-id>.sandbox.example.com` beside `ui.example.com`), so `SameSite=Strict` alone does not stop guest-served JavaScript from sending the cookie. Every state-changing request and every WebSocket upgrade must carry an `Origin` equal to the UI origin (falling back to `Sec-Fetch-Site: same-origin` when `Origin` is absent) and, for state-changing requests, a CSRF token bound to the session; otherwise it is rejected. This applies whether or not the sandbox origin is on a separate registrable domain.
- Linked GitHub accounts (ADR-0012) hang off the user record, not the session.
- Authorization in Phase 1 is "owner can do everything"; every handler still calls an `authorize(user, action, resource)` hook so roles add without touching handlers.
- The UI is a responsive single-page app (ADR-0004) designed mobile-first for the session list, inbox and approvals (UX-7).

## Consequences

- No credential-reset email flow is needed; passkey loss is recovered with a CLI command on the host.

## Alternatives considered

- **Reverse-proxy auth only (Tailscale, Cloudflare Access):** fine as an extra layer, but leaves no user identity for linking, approvals and audit.
- **Username and password:** weaker and needs reset flows.
