"""Validates every plugin manifest in the repo against the Agent Plugins spec.

Each test here is parametrized across *all* discovered plugins (see
``conftest.py``), so a newly added plugin directory is validated
automatically without editing this file.

Validation is layered:

1. The canonical JSON Schemas vendored in ``schemas/`` (structural truth).
2. Extra semantic rules the schema cannot express, such as the URL and
   filesystem-containment requirements in the specification prose.

The specification text at https://agent-plugins.org/specification is
authoritative where it and the schema disagree.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import jsonschema
import pytest
from discovery import (
    MCP_SCHEMA_ID,
    PLUGIN_SCHEMA_ID,
    SCHEMAS_DIR,
    discover_plugins,
    load_json,
)

# Placeholder values inherited from the example-plugin template. A real plugin must
# replace these, so we fail loudly rather than publishing "Your Name".
TEMPLATE_PLACEHOLDERS = ("Your Name", "your-org", "example.com")


def _validator(schema_name: str) -> jsonschema.protocols.Validator:
    schema = load_json(SCHEMAS_DIR / schema_name)
    return jsonschema.Draft202012Validator(schema)


def _format_errors(errors: list[jsonschema.ValidationError]) -> str:
    return "\n".join(f"  {list(e.path) or '<root>'}: {e.message}" for e in errors)


def test_repo_contains_at_least_one_plugin() -> None:
    """Guard against the discovery glob silently matching nothing."""
    assert discover_plugins(), "no */plugin.json found; discovery glob may be wrong"


def test_schema_files_are_vendored() -> None:
    assert (SCHEMAS_DIR / "plugin.schema.json").is_file()
    assert (SCHEMAS_DIR / "mcp.schema.json").is_file()


def test_plugin_json_conforms_to_canonical_schema(plugin_dir: Path) -> None:
    manifest = load_json(plugin_dir / "plugin.json")
    errors = sorted(_validator("plugin.schema.json").iter_errors(manifest), key=lambda e: e.path)
    assert not errors, f"{plugin_dir.name}/plugin.json:\n{_format_errors(errors)}"


def test_plugin_declares_the_targeted_spec_version(plugin_dir: Path) -> None:
    manifest = load_json(plugin_dir / "plugin.json")
    assert manifest["$schema"] == PLUGIN_SCHEMA_ID


def test_plugin_name_matches_directory_name(plugin_dir: Path) -> None:
    """Not required by the spec, but strongly recommended and enforced here."""
    manifest = load_json(plugin_dir / "plugin.json")
    assert manifest["name"] == plugin_dir.name, (
        f"manifest name {manifest['name']!r} should match directory {plugin_dir.name!r}"
    )


def test_plugin_metadata_has_no_unedited_template_placeholders(plugin_dir: Path) -> None:
    manifest = load_json(plugin_dir / "plugin.json")
    if manifest["name"] == "example-plugin":
        pytest.skip("example-plugin is the template itself")
    found = [
        placeholder
        for placeholder in TEMPLATE_PLACEHOLDERS
        if placeholder in str(manifest.values())
    ]
    assert not found, f"{plugin_dir.name}/plugin.json still contains template values: {found}"


def test_mcp_urls_are_not_template_placeholders(plugin_dir: Path) -> None:
    """A plugin must point at its own deployed server, not the example URL."""
    if plugin_dir.name == "example-plugin":
        pytest.skip("example-plugin is the template itself")
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    for name, server in load_json(mcp_path)["mcpServers"].items():
        url = server.get("url", "")
        assert "example.com" not in url, (
            f"{plugin_dir.name}/mcp.json server {name!r} still points at the template "
            f"URL {url!r}; set it to your deployed server's URL"
        )


def test_mcp_json_conforms_to_canonical_schema(plugin_dir: Path) -> None:
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")
    config = load_json(mcp_path)
    errors = sorted(_validator("mcp.schema.json").iter_errors(config), key=lambda e: e.path)
    assert not errors, f"{plugin_dir.name}/mcp.json:\n{_format_errors(errors)}"
    assert config["$schema"] == MCP_SCHEMA_ID


def test_mcp_remote_urls_are_absolute_https_without_userinfo_or_fragment(
    plugin_dir: Path,
) -> None:
    """Spec §7.2.1: non-loopback remote endpoints must use HTTPS."""
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    for name, server in load_json(mcp_path)["mcpServers"].items():
        if server["type"] not in {"streamable-http", "sse"}:
            continue
        parsed = urlsplit(server["url"])
        assert parsed.scheme in {"http", "https"}, f"{name}: URL must be absolute HTTP(S)"
        assert "@" not in parsed.netloc, f"{name}: URL must not contain userinfo"
        assert parsed.fragment == "", f"{name}: URL must not contain a fragment"
        if parsed.hostname not in loopback_hosts:
            assert parsed.scheme == "https", f"{name}: non-loopback URL must use HTTPS"


def _resolves_inside(plugin_dir: Path, value: str) -> bool:
    """Return whether a plugin-relative path stays inside the plugin root."""
    return (plugin_dir / value).resolve().is_relative_to(plugin_dir.resolve())


def test_mcp_stdio_commands_stay_inside_the_plugin_root(plugin_dir: Path) -> None:
    """Spec §4.1: package paths must resolve within the plugin root.

    Checked unconditionally for anything path-like. A previous version only
    validated commands beginning with ``./``, so ``../../../usr/bin/env``
    silently passed -- the vendored schema explicitly defers filesystem
    containment to this layer.
    """
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    for name, server in load_json(mcp_path)["mcpServers"].items():
        if server["type"] != "stdio":
            continue

        command = server["command"]
        # Spec §7.2.1: `command` is either a bare executable name resolved via
        # PATH, or a plugin-relative path beginning with `./`. Anything else --
        # notably `../` or an absolute path -- is invalid.
        is_bare_name = "/" not in command and "\\" not in command
        if not is_bare_name:
            assert command.startswith("./"), (
                f"{name}: command {command!r} must be a bare executable name or "
                "a plugin-relative path beginning with './'"
            )
            assert _resolves_inside(plugin_dir, command), (
                f"{name}: command {command!r} escapes the plugin root"
            )
            assert (plugin_dir / command).exists(), f"{name}: command {command!r} does not exist"


def test_mcp_stdio_cwd_stays_inside_its_root(plugin_dir: Path) -> None:
    """Spec §7.2.1: `cwd` is plugin-relative, or rooted at a plugin variable.

    A previous version never examined `cwd` at all, so `./../../etc` passed.
    """
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    for name, server in load_json(mcp_path)["mcpServers"].items():
        if server["type"] != "stdio" or "cwd" not in server:
            continue

        cwd = server["cwd"]
        for variable in ("${PLUGIN_ROOT}", "${PLUGIN_DATA}"):
            if cwd == variable:
                break
            if cwd.startswith(f"{variable}/"):
                remainder = cwd[len(variable) + 1 :]
                assert _resolves_inside(plugin_dir, remainder), (
                    f"{name}: cwd {cwd!r} escapes {variable}"
                )
                break
        else:
            assert cwd.startswith("./"), (
                f"{name}: cwd {cwd!r} must start with './', '${{PLUGIN_ROOT}}', "
                "or '${PLUGIN_DATA}'"
            )
            assert _resolves_inside(plugin_dir, cwd), f"{name}: cwd {cwd!r} escapes the plugin root"


def test_mcp_headers_contain_no_obvious_secrets(plugin_dir: Path) -> None:
    """Spec §7.2.1: headers are visible package data, never a secret channel."""
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    suspicious = ("authorization", "api-key", "apikey", "token", "secret", "password")
    for name, server in load_json(mcp_path)["mcpServers"].items():
        for header in server.get("headers", {}):
            assert header.lower() not in suspicious, (
                f"{name}: header {header!r} looks like a credential; "
                "authentication is client-managed in Agent Plugins v1"
            )


def test_mcp_stdio_command_is_a_single_token_without_placeholders(plugin_dir: Path) -> None:
    """Spec §7.2.1: `command` is one executable token and is never expanded."""
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    for name, server in load_json(mcp_path)["mcpServers"].items():
        if server["type"] != "stdio":
            continue
        command = server["command"]
        assert not any(ch.isspace() for ch in command), (
            f"{name}: command {command!r} must be a single token; put arguments in `args`"
        )
        assert "${" not in command, f"{name}: command {command!r} is never placeholder-expanded"


def test_mcp_stdio_env_avoids_reserved_names_and_secrets(plugin_dir: Path) -> None:
    """Spec §9.2: clients own PLUGIN_ROOT/PLUGIN_DATA; `env` is visible package data."""
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    suspicious = ("key", "token", "secret", "password", "credential")
    for name, server in load_json(mcp_path)["mcpServers"].items():
        for variable, value in server.get("env", {}).items():
            assert variable.upper() not in {"PLUGIN_ROOT", "PLUGIN_DATA"}, (
                f"{name}: env must not set the client-managed variable {variable!r}"
            )
            if any(word in variable.lower() for word in suspicious):
                assert "${PLUGIN_" in value or not value, (
                    f"{name}: env {variable!r} looks like a credential; never embed secrets"
                )


def test_mcp_headers_are_unique_case_insensitively(plugin_dir: Path) -> None:
    """Spec §7.2.1: the same header under different casing makes the entry invalid."""
    mcp_path = plugin_dir / "mcp.json"
    if not mcp_path.exists():
        pytest.skip("plugin declares no MCP servers")

    for name, server in load_json(mcp_path)["mcpServers"].items():
        names = [header.lower() for header in server.get("headers", {})]
        assert len(names) == len(set(names)), f"{name}: duplicate header names: {names}"


def test_plugin_contains_no_symlink_escaping_the_plugin_root(plugin_dir: Path) -> None:
    """Spec §4.1: every package path must resolve within the plugin root."""
    root = plugin_dir.resolve()
    skip = {".venv", "node_modules", ".git", "__pycache__"}
    escaping = [
        str(path.relative_to(plugin_dir))
        for path in plugin_dir.rglob("*")
        if path.is_symlink()
        and not skip.intersection(path.relative_to(plugin_dir).parts)
        and not path.resolve().is_relative_to(root)
    ]
    assert not escaping, f"{plugin_dir.name}: symlinks resolve outside the plugin root: {escaping}"


# Spec §4.2/§6.1 define `plugin.json`, `skills/`, and `mcp.json`; LICENSE, CHANGELOG, and
# README are the conventional package docs. §8.2 allows reverse-domain extension directories.
SPEC_TOP_LEVEL = {"plugin.json", "skills", "mcp.json", "README.md", "CHANGELOG.md", "LICENSE"}
EXTENSION_NAMESPACE = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")
IGNORED_TOP_LEVEL = {".DS_Store", "__pycache__"}


def test_plugin_top_level_contains_only_spec_defined_entries(plugin_dir: Path) -> None:
    """Agent Plugins 1.0.0 defines no other component locations (e.g. no `servers/`)."""
    unexpected = sorted(
        entry.name
        for entry in plugin_dir.iterdir()
        if entry.name not in SPEC_TOP_LEVEL | IGNORED_TOP_LEVEL
        and not (entry.is_dir() and EXTENSION_NAMESPACE.match(entry.name))
    )
    assert not unexpected, (
        f"{plugin_dir.name}: top-level entries outside the Agent Plugins spec: {unexpected}. "
        "Keep server source and other non-package files outside the plugin directory."
    )
