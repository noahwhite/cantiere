# Cantiere

Self-hosted platform for running teams of coding agents.

Every Linear ticket, PR mention or Slack request gets its own disposable sandbox with scoped, short-lived credentials.
Watch, steer and take over each session from your browser.
Claude Code, Codex and opencode plug in as runtimes.

> **Status: design phase.**
> There is no runnable code yet.
> Watch or star the repo to follow along.

## Why

Hosted coding agents keep your code, credentials and model spend on someone else's infrastructure, and the features teams need to run them seriously (self-hosting, network controls, audit) sit behind enterprise plans.
Cantiere ("construction site" in Italian) is the open alternative: you run the control plane and the sandboxes, and you bring your own model credentials.

## Planned features

- **Triggers:** Linear issues, GitHub PR and issue mentions, Slack, the web UI and an API.
- **Disposable sandboxes:** one isolated microVM or container per session, built from a declared repo environment and thrown away afterwards.
- **Scoped credentials:** brokers mint short-lived, least-privilege tokens per session, so long-lived secrets never enter a sandbox.
- **Pluggable runtimes:** existing agent CLIs (Claude Code, Codex CLI, opencode) run headless behind a common adapter; adding one is an adapter, not a fork.
- **Live sessions:** stream the agent's terminal and browser, send it instructions mid-run, or take over the shell yourself.
- **GitHub App:** each deployment registers its own app and acts only on approved installations; users can link their GitHub account so PRs are authored and signed as them.
- **Review loops:** reviewer agents check work before a PR is opened, and the agent answers PR feedback.
- **Cost control:** per-session model spend metering and budgets.

## Architecture

```
 Triggers (Linear, GitHub, Slack, Web, API)
                   |
            Control plane --- Credential brokers (GitHub, cloud, model APIs)
                   |
     Worker sandboxes (microVM per session)
       runtime adapter + agent CLI + repo env
```

## Model usage

Cantiere does not resell or proxy model access.
Each user signs in to their agent CLI with their own API key, subscription or cloud provider credential.
Use of each runtime is subject to its vendor's terms.

## Requirements exports

[docs/requirements.md](docs/requirements.md) is the source of the requirements; `docs/requirements.docx` and `docs/requirements.pdf` are generated from it.
After editing `docs/requirements.md`, run `scripts/export-requirements.sh` and commit the regenerated exports with it.
CI runs `scripts/export-requirements.sh --check`, which fails when the text of either export differs from a fresh export.
The script downloads pinned pandoc, Typst and pypdf versions, checked by SHA-256, into `cantiere-export-tools` under `$XDG_CACHE_HOME` (default `~/.cache`), and runs on Linux x86_64 or aarch64 with `curl`, `tar`, `xz`, `sha256sum` and `python3` with its `venv` module.

## Contributing

The project isn't accepting code contributions yet; issues and design feedback are welcome.
Once it does, contributions will require a [DCO](https://developercertificate.org/) sign-off (`git commit -s`).

## License

[Apache License 2.0](LICENSE).
The Cantiere name and logo are not covered by the license; see [NOTICE](NOTICE).
