# aha-feature

An [Agent Plugin](https://agent-plugins.org/) that bundles the `aha-feature` skill with
the Aha! remote MCP server it depends on.

```text
aha-feature/
├── plugin.json                      # required portable manifest
├── mcp.json                         # Aha! remote MCP server (streamable-http)
├── LICENSE
├── CHANGELOG.md
└── skills/
    └── aha-feature/
        ├── SKILL.md
        ├── scripts/                 # stdlib-only PEP 723 scripts (lint, render, verify, export)
        ├── references/
        ├── assets/
        └── evals/                   # trigger queries for tuning the description
```

## What it does

Elicits, elaborates, and verifies Aha! features, epics, and requirements as spec-driven
records. Aha! stays the system of record: the skill reads and writes through the Aha! MCP
server, checks requirements against EARS and quality gates, and can export a feature to
Spec Kit, OpenSpec, or Kiro layouts on demand. See
[`skills/aha-feature/SKILL.md`](skills/aha-feature/SKILL.md).

## Setup: point the plugin at your Aha! account

Aha! serves MCP from your company subdomain, and the Agent Plugins specification does not
expand variables in `url`, so the manifest ships a placeholder. **Before using the plugin,
edit [`mcp.json`](mcp.json) and replace `your-company` with your Aha! subdomain:**

```json
"url": "https://acme.aha.io/api/v1/mcp"
```

Authentication is client-managed: the first connection opens an OAuth sign-in in your
browser. There is no API key to configure, and none belongs in this plugin — the
specification forbids credentials in `mcp.json`. An Aha! account administrator must enable
AI functionality and MCP access for your account.

## Install

Add the marketplace, then install just this plugin:

```text
/plugin marketplace add markbsigler/agent-plugins
/plugin install aha-feature@agent-plugins
```

## Requirements

- An Agent Plugins client that supports skills and `streamable-http` MCP servers.
- Python 3.11+ for the bundled scripts (standard library only), run with `uv run --script`
  or `python3`. Export needs `git`.

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification
- MCP protocol — https://modelcontextprotocol.io/specification/
