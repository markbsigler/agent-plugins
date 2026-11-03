# codebase-diagrams

An [Agent Plugin](https://agent-plugins.org/) that maps a codebase's architecture as
validated Mermaid diagrams. It bundles one skill and needs no MCP server.

```text
codebase-diagrams/
├── plugin.json                      # required portable manifest
├── LICENSE
├── CHANGELOG.md
└── skills/
    └── codebase-diagrams/
        ├── SKILL.md
        ├── scripts/render_diagrams.py   # PEP 723, stdlib-only; checks and renders .mmd files
        ├── references/                  # diagram catalog, Mermaid standards, color themes
        ├── assets/                      # example diagram and README template
        └── evals/                       # trigger queries for tuning the description
```

## What it does

Analyzes a codebase proportionally to its size, drafts only what it verified, validates
each Mermaid diagram, and renders PNG files. See
[`skills/codebase-diagrams/SKILL.md`](skills/codebase-diagrams/SKILL.md).

## Requirements

- Python 3.11+ for the render script, run with `uv run --script` or `python3`.
- Rendering needs Node.js 18+. The script uses `mmdc` if installed, otherwise
  `npx @mermaid-js/mermaid-cli`. Writing diagrams needs no tools.

```bash
uv run --script skills/codebase-diagrams/scripts/render_diagrams.py --check docs/diagrams
uv run --script skills/codebase-diagrams/scripts/render_diagrams.py docs/diagrams
```

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification
- Mermaid — https://mermaid.js.org/
