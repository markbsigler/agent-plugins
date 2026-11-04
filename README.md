<div align="center">

# Agent Plugins Collection

*Portable Agent Skills and MCP server configuration, built to the Agent Plugins specification*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Agent Plugins spec](https://img.shields.io/badge/Agent%20Plugins-v1.0.0-6f42c1?style=flat-square)](https://agent-plugins.org/specification)
[![uv](https://img.shields.io/badge/tooling-uv-de5fe9?style=flat-square)](https://docs.astral.sh/uv/)

</div>

A collection of [Agent Plugins](https://agent-plugins.org/): portable packages of
[Agent Skills](https://agentskills.io/specification) and
[MCP](https://modelcontextprotocol.io/specification/) server configuration that a
compatible AI agent client can load. Each plugin lives in its own top-level directory and
is built to the [Agent Plugins Specification v1.0.0](https://agent-plugins.org/specification).

## Plugins

| Plugin | Contents | MCP |
| --- | --- | --- |
| [`aha-feature`](./aha-feature) | Skill that elicits, elaborates, and verifies Aha! features, epics, and requirements as spec-driven records | Aha! (remote, OAuth) — set your subdomain in [`mcp.json`](./aha-feature/mcp.json) |
| [`codebase-diagrams`](./codebase-diagrams) | Skill that writes and renders color-coded Mermaid architecture diagrams | none |
| [`example-plugin`](./example-plugin) | Reference pattern for new plugins | placeholder remote server |

## Install a plugin

This repo is a plugin marketplace
([`.github/plugin/marketplace.json`](./.github/plugin/marketplace.json)), so a client can add
it once and install any single plugin from it:

```text
/plugin marketplace add markbsigler/agent-plugins
/plugin install aha-feature@agent-plugins
```

- **VS Code:** open **Customizations → Browse → Configure Marketplaces**, add
  `markbsigler/agent-plugins`, then pick the plugin.
- **Copilot CLI:** `copilot plugin marketplace add markbsigler/agent-plugins`, then
  `copilot plugin install aha-feature@agent-plugins`.
- **Manually:** clone the repo and point your client at one plugin directory, for example
  **Chat: Install Plugin from Source** in VS Code.

Each plugin's README lists its requirements and any setup, such as pointing `aha-feature`
at your Aha! account.

A client reads three things from a plugin and ignores everything else:

| Path | What the client does with it |
| --- | --- |
| `plugin.json` | Identity and metadata — required |
| `skills/*/SKILL.md` | Loads each skill so the agent can invoke it |
| `mcp.json` | Connects to the MCP servers listed there |

## Layout

```text
agent-plugins/
├── <plugin>/                    # any top-level directory with a plugin.json
│   ├── plugin.json              #   required portable manifest
│   ├── mcp.json                 #   MCP server connections (optional)
│   └── skills/<skill>/          #   Agent Skills (PEP 723 scripts)
├── example-plugin/              # the pattern every new plugin is scaffolded from
├── .github/plugin/              # marketplace.json catalog
├── schemas/1.0.0/               # vendored Agent Plugins JSON Schemas
├── scripts/                     # cross-platform helpers behind the justfile
├── tests/                       # repo-level validation (auto-discovers plugins)
├── justfile                     # task runner: run `just` to list recipes
└── pyproject.toml, uv.lock      # tooling config, one lockfile
```

## Development

The only prerequisite is [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/markbsigler/agent-plugins.git && cd agent-plugins
uv tool install rust-just     # installs `just` from PyPI (all platforms)
just install                  # installs remaining tools + syncs the environment
just check                    # lint + format + types + spelling + tests + security
```

Start a new plugin with `just new-plugin <name>`; the scaffold, tests, and publishing steps
are in [CONTRIBUTING.md](./CONTRIBUTING.md). Everything runs on macOS, Linux, and Windows.

## Project docs

| Document | Purpose |
| --- | --- |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Setup, toolchain, creating a plugin, PR checklist |
| [`AGENTS.md`](./AGENTS.md) | Conventions and rationale — read before changing a plugin |
| [`SECURITY.md`](./SECURITY.md) | Reporting vulnerabilities; credential policy |
| [`CHANGELOG.md`](./CHANGELOG.md) | Repository changes |

## References

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification
- MCP protocol — https://modelcontextprotocol.io/specification/
