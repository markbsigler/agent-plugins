# Changelog

All notable changes to the repository tooling are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each plugin keeps its own
`CHANGELOG.md` and version in `plugin.json`.

## [Unreleased]

### Added

- Plugin marketplace catalog at `.github/plugin/marketplace.json`, so a single plugin can be
  installed from the repo, with tests that keep it in sync with each `plugin.json`.
- `aha-feature` and `codebase-diagrams` plugins, migrated from
  [markbsigler/skills](https://github.com/markbsigler/skills).
- Branch coverage with an 80% gate, covering `scripts/` and the migrated skill
  scripts (including subprocess-run scripts).
- `.editorconfig` and this changelog.
- Spec-conformance tests for MCP `command`, `env`, duplicate headers, and symlinks, and a
  test that plugins contain only spec-defined top-level entries.

### Changed

- Streamlined `README.md` to an overview, plugin list, and install steps; moved the plugin
  walkthrough, toolchain, and MCP configuration guidance into `CONTRIBUTING.md`.
- Renamed the repository from `plugins` to `agent-plugins`.
- Broadened the ruff rule set (builtins, logging, pylint, refurb, perflint, tryceratops,
  and more) and raised the dev tooling Python floor to 3.12.
- Removed the GitHub Actions CI workflow; checks run locally via `just check` and
  pre-commit.
- `just new-plugin --no-server` is now `--no-mcp`; `just sync` runs a plain `uv sync`.

### Removed

- The FastMCP server pattern: `example-plugin/servers/`, the `new-server`, `inspect-server`,
  `run-server`, and `image-*` recipes, the uv workspace, and podman tooling. `servers/` is not
  a location the Agent Plugins specification defines and would ship inside every installed
  plugin.
