# ADR-0010: Credentials stay outside the sandbox and are applied at the worker boundary

- Status: Accepted
- Date: 2026-10-07
- Requirements: ID-1, ID-2, ID-3, ID-4, GH-5, GH-6, SEC-4, SEC-5, SEC-7, COST-3

## Context

ID-2 asks for short-lived, session-scoped credentials inside the sandbox.
A short-lived token in a compromised sandbox is still usable for its lifetime and for any action its scope allows, and some scopes cannot be narrowed enough: GitHub installation tokens cannot be limited to one branch, and user tokens cannot be limited to a persona's permissions (GH-6).
Every sandbox already reaches the outside world only through the worker (ADR-0011), so the worker can apply credentials on the way out instead.
[Cloudflare Sandboxes](https://developers.cloudflare.com/changelog/post/2026-04-13-sandbox-outbound-workers-tls-auth/index.md), [Fly tokenizer](https://github.com/superfly/tokenizer) and microsandbox use the same pattern.

## Decision

The default is that **no credential enters the sandbox**; the sandbox holds placeholders, and the worker injects real credentials after a policy check (ADR-0015).

| Credential | Mechanism | In sandbox |
| --- | --- | --- |
| Model API keys, Bedrock and Vertex credentials | Model gateway on the worker, reached through the runtime's base URL setting (ADR-0014) | Placeholder |
| GitHub installation and linked-user tokens for git | Git smart-HTTP proxy on the worker; `url.insteadOf` maps `https://github.com/` to it | Nothing |
| GitHub, Linear and other HTTP API tokens | TLS-intercepting egress proxy swaps the placeholder header for the real token per host, and checks method and path against the persona | Placeholder |
| Commit signing keys (SEC-7) | Commits are recreated and signed at push time by the git proxy (ADR-0012) | Nothing |
| Tailscale (SEC-3) | Ephemeral node runs on the worker in the session's network namespace (ADR-0011) | Nothing |
| Credentials with no injectable HTTP header (SSH to hosts, database passwords, S3 SigV4 for R2) | Minted per session, shortest TTL the provider allows, narrowest scope, declared by the persona | Yes, short-lived (ID-2) |
| Claude or ChatGPT subscription logins (COST-3) | The user's own login, used only by the unmodified CLI (ADR-0014) | Yes, documented exception |

Mechanics:

- **Secret store (ID-1):** `SecretStore` interface with Bitwarden Secrets Manager first, then Vault and Infisical. The server resolves only the references the persona declares (ID-3), at session start and on refresh, and streams the values to the worker over the authenticated worker channel (ADR-0003). Values live in worker memory for the session and are never written to disk.
- **Minting (ID-2, GH-5):** the server mints GitHub installation tokens per session with `repository_ids` and `permissions` narrowed to the persona ([API](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)), refreshes them before their 1-hour expiry, and revokes them at session end.
- **GitHub API policy (inject mode on `api.github.com`):** method and path alone are not enough, because one write token can update any ref or merge any PR. The proxy therefore:
  - allows only an explicit route catalog per persona, with every route bound to the session's repos (owner and repo segments checked);
  - never allows ref, contents or Git Data writes through the API (all code reaches GitHub through the git proxy), and never allows PR merge endpoints with a session's token (merge is a server action gated by WF-4, ADR-0015);
  - allows PR creation and update only with `head` equal to the session branch;
  - parses GraphQL request bodies and allows only queries and an explicit list of named mutations with the same repo and branch bindings; anything unparseable is denied.
  The installer also recommends a repository ruleset on each target repo's default branch (PR and review required, the app not in the bypass list), so the platform invariant holds even if the proxy is wrong.
- **Git proxy:** allows fetch of the session's repos, and push only to the session's branch (SB-5); rejects force-push to anything but that branch, rejects pushes containing any known secret value of the session, and records every push in the audit log (SEC-5). Reviewer and QA sessions get fetch only (SEC-4).
- **Per-session CA:** the worker creates an ephemeral CA per session; only its certificate enters the guest trust store (`NODE_EXTRA_CA_CERTS`, `CODEX_CA_CERTIFICATE`, `SSL_CERT_FILE` and the system store); its private key never leaves the worker. Processes warmed in the snapshot (for example `dockerd`, whose Go runtime caches the system pool) do not see a CA added after restore, so the guest agent installs the CA and then restarts those daemons before the session starts; Phase 0 measures the cost.
- **Scrubbing (ID-4):** the worker knows every secret value and placeholder of the session and scrubs them, plus known token patterns, from events, terminal recordings and artifacts before they leave the worker. Secrets are never passed in argv or written to files by Cantiere.

## Consequences

- A compromised sandbox can act only through the proxies, within its persona's policy, and only while the session runs.
- This exceeds ID-2; the requirement is met by construction and ID-2's "short-lived in sandbox" applies only to the non-HTTP row above.
- The worker becomes the most sensitive component on a host; it runs outside every sandbox, and its proxies are covered by fuzz and policy tests.
- Tools that pin certificates or ignore proxy and CA settings break; Phase 0 verifies the three CLIs, `git`, `gh`, Docker pulls and the Officina toolchains.
