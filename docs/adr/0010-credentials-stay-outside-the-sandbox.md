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
| Commit signing keys (SEC-7) | The worker generates a signing key per session, registers it on the commit identity's GitHub account, and signs through the session's SSH agent socket; the key is deleted from GitHub and discarded at session end, or, if ADR-0012 check 3 fails, one long-lived key per identity is held in the secret store and loaded into the agent (ADR-0012) | Agent socket only |
| SSH to hosts | The worker generates a key pair per session, OpenBao's SSH engine signs a certificate for it with the persona's principals and a TTL of the session's maximum duration, and the worker exposes an SSH agent to the guest as a socket over vsock (`SSH_AUTH_SOCK`). The agent dies and the key is discarded at session end, so a copied certificate is useless without the key. | Agent socket only |
| Tailscale (SEC-3) | Ephemeral node runs on the worker in the session's network namespace (ADR-0011) | Nothing |
| Credentials with no injectable HTTP header or agent (database passwords, cloud credentials through an OpenBao plugin) | Minted per session by OpenBao, with a lifetime no longer than the session's maximum duration and revoked at session end; narrowest scope; declared by the persona. A credential type that cannot be bounded and revoked this way is not supported. | Yes, short-lived (ID-2) |
| Claude or ChatGPT subscription logins (COST-3) | The user's own login, used only by the unmodified CLI (ADR-0014) | Yes, documented exception |

Mechanics:

- **Secret store (ID-1):** a `SecretStore` interface in the server. The server is the only component that talks to a store; it resolves only the references the persona declares (ID-3), at session start and on refresh, and streams the values to the worker over the authenticated worker channel (ADR-0003). Values live in worker memory for the session and are never written to disk.
  - **OpenBao is the first implementation** (`openbao://<mount>/<path>#<key>`). It is the only store that can also mint credentials (below). The installer sets it up as its own service with its storage in the deployment's Postgres, in a separate database owned by a separate role (ADR-0005, ADR-0019), or points at an existing OpenBao. The server authenticates with AppRole and a policy limited to Cantiere's mounts.
  - **Bitwarden Secrets Manager** (`bws://<uuid>`) is a read-only static-secret implementation for existing Bitwarden users. HashiCorp Vault and Infisical can follow behind the same interface.
- **Dynamic credentials (ID-2):** credentials in the "Yes, short-lived" row are minted by OpenBao secrets engines, not by Cantiere code: the database engine (PostgreSQL, MySQL) for database roles. Neither engine's default revocation closes open connections (MySQL's `DROP USER` explicitly does not), so Cantiere sets custom revocation statements that block new logins first, then end the role's connections, then drop it; ending connections before blocking logins would let a holder of the still-valid password reconnect between the two steps. For PostgreSQL that is `ALTER ROLE ... NOLOGIN`, `pg_terminate_backend` (which needs `pg_signal_backend` for OpenBao's connection role) and `DROP ROLE`. For MySQL it is `ALTER USER ... ACCOUNT LOCK`, then an operator-installed `SQL SECURITY DEFINER` procedure that issues `KILL CONNECTION` for each of the user's rows in `performance_schema.processlist`, then `DROP USER`; the procedure's definer holds `SELECT` on `performance_schema.processlist` (to query it), `PROCESS` (to see other users' rows) and `CONNECTION_ADMIN` (to kill them), and OpenBao's connection user needs only `EXECUTE` on it. SSH certificates are not revocable once issued, which is why SSH uses the agent row above instead. Cloud engines such as AWS are OpenBao external plugins an operator may install. Each lease's TTL is the session's maximum duration; the server revokes the session's leases at session end, and OpenBao revokes them on expiry if the server cannot. A credential type with no engine or plugin is not supported for direct use. With Bitwarden as the only store, no direct credentials are available.
- **Minting (ID-2, GH-5):** the server mints GitHub installation tokens per session with `repository_ids` and `permissions` narrowed to the persona ([API](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)), refreshes them before their 1-hour expiry, and revokes them at session end.
- **GitHub API policy (inject mode on `api.github.com`):** method and path alone are not enough, because one write token can update any ref or merge any PR. The proxy therefore:
  - allows only an explicit route catalog per persona, with every route bound to the session's repos (owner and repo segments checked);
  - never allows ref, contents or Git Data writes through the API (all code reaches GitHub through the git proxy), and never allows PR merge endpoints with a session's token (merge is a server action gated by WF-4, ADR-0015);
  - allows PR creation and update only with `head` equal to the session branch;
  - parses GraphQL request bodies and allows only queries and an explicit list of named mutations with the same repo and branch bindings; anything unparseable is denied.
  The installer also recommends a repository ruleset on each target repo's default branch (PR and review required, the app not in the bypass list), so the platform invariant holds even if the proxy is wrong.
- **Git proxy:** allows fetch of the session's repos, and push only to the session's branch (SB-5); rejects force-push to anything but that branch, rejects pushes containing any known secret value of the session, and records every push in the audit log (SEC-5). Reviewer and QA sessions get fetch only (SEC-4).
- **Per-session CA:** the worker creates an ephemeral CA per session; only its certificate enters the guest trust store (`NODE_EXTRA_CA_CERTS`, `CODEX_CA_CERTIFICATE`, `SSL_CERT_FILE` and the system store); its private key never leaves the worker. Processes warmed in the snapshot (for example `dockerd`, whose Go runtime caches the system pool) do not see a CA added after restore, so the guest agent installs the CA and then restarts those daemons before the session starts; Phase 0 measures the cost.
- **Direct credentials and SEC-4:** the rows marked "Yes" above and the SSH agent do not pass through the proxies or `policy.Decide`, so for them SEC-4 is enforced by scope alone. Each direct credential type declares its access level (`read` or `write`) in the config repo, and persona validation rejects any reviewer or QA persona that requests a `write` credential (ADR-0015).
- **Scrubbing (ID-4):** the worker knows every secret value and placeholder of the session and scrubs them, plus known token patterns, from events, terminal recordings and artifacts before they leave the worker. Secrets are never passed in argv or written to files by Cantiere.

## Consequences

- OpenBao is a second service to run and upgrade, and its unseal key protects every stored secret (ADR-0019).

- A compromised sandbox can act only through the proxies, within its persona's policy, and only while the session runs, except with direct credentials and over the tailnet, where it can do whatever that credential's scope or the tag's ACL allows until session end.
- This exceeds ID-2; the requirement is met by construction and ID-2's "short-lived in sandbox" applies only to the non-HTTP row above.
- The worker becomes the most sensitive component on a host; it runs outside every sandbox, and its proxies are covered by fuzz and policy tests.
- ID-1 names OpenBao as the first implementation and the only one that mints dynamic credentials, Bitwarden Secrets Manager for static secrets, and Vault or Infisical as possible later stores, matching this decision.
- S3 SigV4 credentials for Cloudflare R2 have no OpenBao engine, so sessions cannot use R2 directly until a plugin exists.
- Tools that pin certificates or ignore proxy and CA settings break; Phase 0 and the first Phase 1 slice verify Claude Code, `git`, `gh`, Docker pulls and the Officina toolchains.

## Alternatives considered

- **Bitwarden Secrets Manager first:** already in use by the maintainers, but it stores static values only, so every short-lived credential type would need minting code in Cantiere.
- **HashiCorp Vault:** the same engines, but under the Business Source License; OpenBao is its MPL-2.0 fork under the Linux Foundation.
