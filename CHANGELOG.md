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
- Branch coverage with an 80% gate, covering `scripts/`, the example server, and the
  migrated skill scripts (including subprocess-run scripts).
- `.editorconfig` and this changelog.
- Spec-conformance tests for MCP `command`, `env`, duplicate headers, and symlinks.

### Changed

- Renamed the repository from `plugins` to `agent-plugins`.
- Broadened the ruff rule set (builtins, logging, pylint, refurb, perflint, tryceratops,
  and more) and raised the dev tooling Python floor to 3.12.
- Removed the GitHub Actions CI workflow; checks run locally via `just check` and
  pre-commit.

### Security

- Upgraded authlib, dnspython, fastmcp, joserfc, and opentelemetry-api to clear CVEs.
