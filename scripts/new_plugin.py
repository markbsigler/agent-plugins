#!/usr/bin/env python3
"""Scaffold a new plugin by copying the ``example-plugin`` example.

Usage:
    just new-plugin acme-tools
    uv run python scripts/new_plugin.py acme-tools

Copies the template and rewrites the identifiers so the result passes
``just check`` immediately -- except for the metadata you are expected to
personalise (description, author, MCP server URL), which the manifest tests
deliberately flag until you edit them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from _scaffold import (
    REPO_ROOT,
    InvalidNameError,
    rewrite_file,
    validate_plugin_name,
)

TEMPLATE = REPO_ROOT / "example-plugin"
TEMPLATE_PLUGIN = "example-plugin"

TEXT_SUFFIXES = {".py", ".json", ".toml", ".md", ".txt", ".yaml", ".yml", ""}


def main(argv: list[str] | None = None) -> int:
    """Create the new plugin directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Name of the new plugin (also the directory name).")
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Omit mcp.json (skills-only plugin).",
    )
    args = parser.parse_args(argv)

    name: str = args.name
    try:
        validate_plugin_name(name)
    except InvalidNameError as exc:
        return _fail(str(exc))

    destination = REPO_ROOT / name
    if destination.exists():
        return _fail(f"{destination.relative_to(REPO_ROOT)} already exists")

    shutil.copytree(
        TEMPLATE,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "*.egg-info"),
    )

    if args.no_mcp:
        (destination / "mcp.json").unlink(missing_ok=True)

    # Single pass per file: replacement output is never re-scanned, so a name
    # containing "example-plugin" cannot corrupt itself.
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            try:
                rewrite_file(path, {TEMPLATE_PLUGIN: name})
            except UnicodeDecodeError:
                continue  # binary asset; leave untouched

    if args.no_mcp:
        # The template README documents mcp.json; rewriting it in place would
        # leave stale instructions for a file that was just removed.
        (destination / "README.md").write_text(_no_mcp_readme(name), encoding="utf-8", newline="\n")

    _reset_manifest(destination / "plugin.json", name)
    _print_next_steps(name, with_mcp=not args.no_mcp)
    return 0


def _no_mcp_readme(name: str) -> str:
    """Generate a minimal, accurate README for a skills-only plugin."""
    return f"""# {name}

An [Agent Plugin](https://agent-plugins.org/) with skills only and no MCP servers.

```text
{name}/
├── plugin.json          # required portable manifest
└── skills/
    └── ...               # add your Agent Skills here
```

## Using this plugin

Copy this directory to wherever your Agent Plugins client discovers plugins.
The client reads `plugin.json` and every `skills/*/SKILL.md` and ignores
everything else.

## Adding an MCP server later

Add an `mcp.json` at this plugin's root. It connects to servers that run
elsewhere (`streamable-http`) or launches a local command (`stdio`); see
[`example-plugin/mcp.json`](../example-plugin/mcp.json) for the shape.

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification
"""


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _reset_manifest(manifest_path: Path, name: str) -> None:
    """Clear template metadata the author must fill in."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.1.0"
    manifest["description"] = f"TODO: describe what {name} does."
    manifest["author"] = {"name": "TODO"}
    manifest.pop("homepage", None)
    manifest.pop("repository", None)
    manifest["keywords"] = []
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def _print_next_steps(name: str, *, with_mcp: bool) -> None:
    print(f"Created {name}/")
    print()
    print("Next steps:")
    print(f"  1. Edit {name}/plugin.json      (description, author, keywords, license)")
    print(f"  2. Rename/replace skills in {name}/skills/")
    if with_mcp:
        print(f"  3. Edit {name}/mcp.json         (point it at your MCP server)")
        print("  4. just check")
    else:
        print("  3. just check")


if __name__ == "__main__":
    raise SystemExit(main())
