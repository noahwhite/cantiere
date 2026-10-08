# ADR-0008: Blueprints build OCI images that become warmed Firecracker snapshot templates

- Status: Accepted
- Date: 2026-10-07
- Requirements: SB-1, SB-2, SB-3, SB-4, SB-5, SB-6, RT-4, RT-6

## Context

Every session must start in seconds from an environment declared in the repo (SB-1, SB-2), across several repos (SB-4), with its own branch and worktree (SB-5).
Firecracker snapshots cover memory and VM state but not disks (ADR-0007), so the pipeline owns disk images too.

## Decision

**Blueprint format.** `.agent/blueprint.yaml` in each repo, plus an org layer in the config repo (ADR-0017):

```yaml
version: 1
base: ghcr.io/cantiere/base:ubuntu-24.04   # or a Dockerfile path
toolchains: {java: "25", node: "24"}
services: [docker]                          # dockerd in the guest
egress: [repo.maven.apache.org, registry.npmjs.org]   # a request; see trust rules below
build_secrets: [github-packages]            # names of org-granted bindings, never refs
initialize: ["./mvnw -q dependency:go-offline"]
maintenance: ["./mvnw -q dependency:go-offline"]   # nightly refresh
warm: ["docker pull postgres:17"]
mcp_servers: [issue-tracker]                # names of org-granted servers; definitions live in the org layer
```

The schema is versioned and published (ADR-0017); unknown keys are errors.

**Trust split between layers.** A target repo is less trusted than the config repo, because anyone who can merge to it controls its blueprint.

- Only the org layer in the config repo defines secret bindings, each as `{name, ref, hosts, repos}`: which secret is injected, for which hosts, and for which repos. A repo layer can only name a binding granted to that repo; it can never contain a secret reference or choose the host a secret is sent to.
- Only the org layer defines Claude Code runtime configuration: `claude.settings` (the user settings) and `mcp_servers`, each server as `{name, command or url, repos}`. A repo layer can only name an org-defined server granted to that repo; it can never contain an MCP command or URL, a hook, or a settings value.
- A repo layer's `egress` entries outside the org layer's list are requests. Each new repo-domain pair takes effect only after an operator approves it in the UI, shown as a diff like persona widening (ADR-0017), and the approval is audited (ADR-0015).
- A pending request does not block the build; the domain stays denied, and the denial is logged with the pending request.

**Build pipeline** (in `cantiere-worker`):

1. Resolve layers: org layer, then each repo's layer, sorted by repo name; the template key is a hash of the resolved layers, the repo set and the base image digest. Repo commits are not part of the key: the template's checkout is only a warm starting point, and every session fetches the latest (step 3 of session start).
2. Build an OCI image with BuildKit (base, toolchains, `cantiere-guest`, runtime CLIs at pinned versions) and flatten it to an ext4 root image. BuildKit runs inside a dedicated build microVM, never on the worker host, because Dockerfile `RUN` steps are repo-controlled code.
3. Boot it in Firecracker with build-only egress, clone the repos, run `initialize` and `warm`, start dockerd, then quiesce the guest agent. Build secrets never enter the VM: the worker proxy injects them as headers for their declared hosts (ADR-0010), so nothing lands in RAM, `settings.xml` or `.npmrc` before the snapshot.
4. Take a full snapshot (memory plus device state) and freeze the root and Docker data disks next to it as the **template**.
5. Record the template; keep the last good template on failure and alert (SB-3).

Rebuilds run on push to a blueprint file on the default branch, on config repo change, and nightly with `maintenance` (SB-3).
Templates for the repo sets that personas and saved session templates declare are prebuilt; a session with a new repo set triggers a build and waits for it once, and later sessions with that set restore from the template.
Templates are stored on the worker and, from Phase 3, in object storage for other workers.

**Session start:**

1. Reflink-clone the template disks, restore the snapshot with lazy memory loading.
2. The guest agent reconnects over vsock, reseeds identity (ADR-0007 item 5), and receives the session manifest.
3. For each repo: `git fetch` through the git proxy (ADR-0010), create branch `cantiere/<session-id>-<slug>` from the requested base, and check it out in `/workspace/<repo>` (SB-5).
4. Attach the skills and memory image (built from the pinned skills commit) read-only: the template carries a placeholder drive, because Firecracker cannot add drives after restore, and the worker swaps its backing file before the guest mounts it; the guest lays it out per runtime convention (RT-4).
5. Create the runtime home inside the VM (`~/.claude`, `CODEX_HOME`); isolation between sessions is the VM itself (RT-6).

## Consequences

- Session start cost is restore plus fetch, independent of dependency install time, once a template exists for the repo set.
- Secrets used at build time never reach the template; a template is safe to copy between workers.
- Blueprints are an open format other tools can adopt; Devin's blueprint and the devcontainer spec are inputs, not dependencies.

## Alternatives considered

- **devcontainer.json as the format:** widely known, but has no notion of warm, maintenance, egress or build-secret scoping; an importer can map it later.
- **Cold boot plus setup per session:** simple, but misses SB-1 for any real repo.
