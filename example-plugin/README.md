# example-plugin

The reference [Agent Plugin](https://agent-plugins.org/) for this repository —
copy it with `just new-plugin <name>` to start anything new. Repo-wide
conventions live in [`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`AGENTS.md`](../AGENTS.md).

```text
example-plugin/
├── plugin.json                       # required portable manifest
├── skills/
│   └── summarize/
│       ├── SKILL.md                  # instructions + frontmatter
│       ├── scripts/word_count.py     # stdlib-only PEP 723 script
│       └── references/               # loaded on demand
├── mcp.json                          # remote MCP server entry (streamable-http)
├── LICENSE                           # travels with the plugin when it is copied out
├── CHANGELOG.md                      # tracks `version` in plugin.json
└── README.md
```

This mirrors the `my-plugin` layout on [agent-plugins.org](https://agent-plugins.org/).
Agent Plugins 1.0.0 defines exactly two component locations — `skills/` and `mcp.json` —
so beyond `plugin.json` and these docs, only reverse-domain extension directories
(for example `com.example.client/`) are allowed.

## What each part demonstrates

**`plugin.json`** — the closed manifest schema: required `$schema` and `name`
plus allowed metadata. Nothing else may appear at the top level.

**`skills/summarize/`** — one [Agent Skill](https://agentskills.io/specification):
`SKILL.md` holds the instructions, `scripts/word_count.py` is a self-contained
[PEP 723](https://peps.python.org/pep-0723/) script (no install step, directory stays
copyable), and `references/` holds material the agent loads only when needed.

**`mcp.json`** — a `streamable-http` entry. A client never launches this server;
it only connects to the `url`, which must be HTTPS and must not embed
credentials. Replace the placeholder URL with a server you run or use. Plugins
that need no MCP server omit the file (`just new-plugin <name> --no-mcp`).

## Try it locally

```bash
# uv resolves the script's inline dependencies on first run
./skills/summarize/scripts/word_count.py <<< "hello world"
```

## Using this as a template

Prefer `just new-plugin <name>`, which does all the renaming for you. See
[Creating a plugin](../CONTRIBUTING.md#creating-a-plugin) for the full walkthrough.

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification
- MCP protocol — https://modelcontextprotocol.io/specification/
