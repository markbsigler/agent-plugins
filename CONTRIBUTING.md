# Contributing

Thanks for contributing. This is the single guide for working in this repository:
setup, the toolchain, how to build a plugin, and the pull request process.
[`AGENTS.md`](./AGENTS.md) is the source of truth for conventions and the reasons behind
them — the `uv`-only toolchain, the spec-defined plugin layout, PEP 723 skill scripts, and
the portability rules that keep the repo working on Windows. Read it before changing a
plugin.

## Contents

- [Setup](#setup)
- [Ground rules](#ground-rules)
- [Toolchain](#toolchain)
- [Creating a plugin](#creating-a-plugin)
- [Configuring an MCP server](#configuring-an-mcp-server)
- [Pull requests](#pull-requests)
- [Reporting bugs](#reporting-bugs)

## Setup

**The only prerequisite is [`uv`](https://docs.astral.sh/uv/)** — it bootstraps everything
else, including `just`.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then, on any platform:

```bash
git clone https://github.com/markbsigler/agent-plugins.git && cd agent-plugins
uv tool install rust-just     # installs `just` from PyPI (all platforms)
just install                  # installs remaining tools + syncs the environment
just check                    # lint + format + types + spelling + tests + security
```

`just install` is idempotent. `just doctor` reports the status of every tool without
changing anything and is the first thing to run when something misbehaves. `just` lists
every recipe.

## Ground rules

**Use the scaffolding.** Run `just new-plugin <name>` rather than hand-building a plugin
directory. It applies the naming rules and keeps the layout spec-conformant.

**`just check` must pass.** There is no CI on this repository, so the test suite and
pre-commit hooks are the only enforcement. Run `just install-hooks` once so checks run on
every commit. Tests enforce an 80% branch-coverage gate.

**Don't put logic in the `justfile`.** Recipes must stay shell-agnostic so they work on
Windows. Anything needing a loop, conditional, or cleanup handler goes in `scripts/*.py`.
`tests/test_portability.py` enforces this.

**Never commit credentials.** `mcp.json` `headers` and `env` are visible package data, not
a secrets mechanism. Agent Plugins v1 has no portable credential field; authentication is
client-managed.

**Keep tests at the repo root.** Plugin tests live in `tests/`. Plugins never import from each other.

## Toolchain

All Python tooling runs through [`uv`](https://docs.astral.sh/uv/) — no `venv`, `pip`,
`pyenv`, or `poetry`. One root `uv.lock` pins the dev tooling.

| Tool | Purpose | Required? | Recipe |
| --- | --- | --- | --- |
| [`uv`](https://docs.astral.sh/uv/) | Packaging + environment | **Required** | `just sync` |
| [`just`](https://just.systems/) | Task runner (PyPI: `rust-just`) | **Required** | `just --list` |
| [`ruff`](https://docs.astral.sh/ruff/) | Lint + format | **Required** | `just lint` / `just fmt` |
| [`ty`](https://docs.astral.sh/ty/) | Type check | **Required** | `just typecheck` |
| [`taplo`](https://taplo.tamasfe.dev/) | TOML format | **Required** | `just fmt` |
| [`typos`](https://github.com/crate-ci/typos) | Spell check | **Required** | `just spell` |
| [`pytest`](https://docs.pytest.org/) | Tests + coverage | **Required** | `just test` |
| [`pre-commit`](https://pre-commit.com/) | Git hooks | **Required** | `just install-hooks` |
| [`trivy`](https://trivy.dev/) | Vulnerabilities, secrets, misconfig | Optional | `just security` |

Everything except `trivy` installs from PyPI through `uv`. Without `trivy` you can still
develop, test, and lint: `just security` skips cleanly. `just install` detects Homebrew,
apt, dnf, pacman, zypper, winget, scoop, or Chocolatey and prints manual instructions if it
finds none.

## Creating a plugin

### 1. Scaffold from the example

```bash
just new-plugin acme-tools
```

This copies [`example-plugin/`](./example-plugin) and rewrites every identifier. You get
a working plugin: manifest, `mcp.json`, and an example `summarize` skill.

```bash
just new-plugin acme-tools --no-mcp                 # skills-only plugin, no mcp.json
```

### 2. Fill in the TODOs

The scaffold leaves markers that the test suite **fails on** until you replace them. That
is the guardrail, not a bug.

| File | What to change |
| --- | --- |
| `acme-tools/plugin.json` | `description`, `author`, `keywords`, `license` |
| `acme-tools/mcp.json` | `url` → a server you run or use (the template `example.com` URL is rejected), or delete the file |
| `acme-tools/skills/` | Replace or rename the example `summarize` skill |
| `acme-tools/README.md` | Describe your plugin |

### 3. Write skills

A skill is a directory under `skills/` containing `SKILL.md` with YAML frontmatter. `name`
must match the directory name; `description` should say both *what* it does and *when* to
use it, since that is what an agent matches against.

```markdown
---
name: acme-lookup
description: Looks up an Acme part number and returns its specifications. Use when the user mentions an Acme part, SKU, or catalog number.
---

# Acme lookup

Run the bundled script and summarize the result:

    uv run --script scripts/lookup.py <part-number>
```

Show the `uv run --script` form in `SKILL.md`, since Windows does not honor shebangs.

Bundled scripts are self-contained [PEP 723](https://peps.python.org/pep-0723/) files.
Dependencies are declared inline and resolved by `uv`, so there is no install step and the
skill directory stays copyable:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
```

Mark scripts executable. The tests read git's index mode, so this works on every platform:

```bash
chmod +x scripts/lookup.py                      # macOS / Linux
git update-index --chmod=+x scripts/lookup.py   # any platform, incl. Windows
```

### 4. Test

```bash
just test          # everything, with the coverage gate
just test-fast     # skip subprocess/network round trips
```

Repo-level tests **auto-discover** every `*/plugin.json`, so a new plugin is validated
against the canonical JSON Schemas, the Agent Skills spec, and this repo's conventions with
no test edits. If you add a *new kind* of check, make it discovery-driven rather than
hardcoded to your plugin.

For verbose expected values, use
[`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/): write `snapshot()`, run
`just snapshot-fix`, then **review the diff** — a passing fix means code and test agree, not
that the value is correct.

### 5. Publish through the marketplace

The repo is also a plugin marketplace. Add a catalog entry for the new plugin to
[`.github/plugin/marketplace.json`](./.github/plugin/marketplace.json) (`name`, `description`,
`version`, and `source` of `./<plugin>`). `tests/test_marketplace.py` fails if an entry
drifts from its `plugin.json`, so bump both together.

## Configuring an MCP server

Agent Plugins 1.0.0 defines two component locations: `skills/` and `mcp.json`. A plugin
declares the MCP servers it needs in `mcp.json`; it does not bundle server source, and a
client never launches a `streamable-http` server, it only connects to the `url`. Host any
server you write in its own repository.

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "acme-api": {
      "type": "streamable-http",
      "url": "https://mcp.acme.example/acme-tools/mcp"
    }
  }
}
```

> [!IMPORTANT]
> The spec does not expand `${VAR}` in `url`, so one manifest cannot serve dev, staging, and
> production. It also defines no portable auth field: authentication is client-managed, and
> `headers` are visible package data, so credentials must never go there. The tests reject
> credential-looking header names, but never rely on that as your only safeguard.

Tests also fail when a plugin has a top-level entry the spec does not define (such as
`servers/`); client-specific extensions belong in a reverse-domain directory like
`com.example.client/`.

## Pull requests

Keep PRs focused on one plugin or one concern. In the description, say what the plugin does
and, if it uses an MCP server, where that server is hosted.

- [ ] `just check` passes
- [ ] The new-plugin checklist in [`AGENTS.md` §4](./AGENTS.md#4-checklist-for-a-new-plugin)
      is satisfied
- [ ] No `TODO` or template placeholders left in manifests
- [ ] The marketplace entry and `CHANGELOG.md` match any version bump
- [ ] `uv.lock` committed if dependencies changed

## Reporting bugs

Open an issue with the output of `just doctor`, your OS, and the exact command that failed.
For security issues, see [`SECURITY.md`](./SECURITY.md) instead.
