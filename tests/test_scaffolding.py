"""Regression tests for the plugin scaffolding.

Since this repo has no CI, these tests are the only thing preventing a
scaffolding regression -- keep them.

The pure-function tests below are fast. The end-to-end test that actually
scaffolds into the repo root is marked ``slow``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from discovery import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _scaffold import (
    InvalidNameError,
    rewrite_file,
    rewrite_text,
    validate_plugin_name,
)


class TestSinglePassRewrite:
    """`rewrite_text` must never re-scan text it just inserted."""

    def test_replacement_output_is_not_rescanned(self) -> None:
        """Regression: a name containing the template name was rewritten twice."""
        result = rewrite_text("example-plugin/skills/x", {"example-plugin": "my-example-plugin"})
        assert result == "my-example-plugin/skills/x"

    def test_longer_keys_win_over_shorter_overlapping_keys(self) -> None:
        replacements = {"ab": "X", "abc": "Y"}
        assert rewrite_text("abc", replacements) == "Y"

    def test_empty_replacements_is_identity(self) -> None:
        assert rewrite_text("unchanged", {}) == "unchanged"

    def test_keys_are_matched_literally_not_as_regex(self) -> None:
        assert rewrite_text("a.c", {"a.c": "ok"}) == "ok"
        assert rewrite_text("abc", {"a.c": "bad"}) == "abc"

    def test_rewrite_file_updates_a_file_in_place_preserving_lf(self, tmp_path: Path) -> None:
        path = tmp_path / "sample.txt"
        path.write_bytes(b"hello example-plugin\nsecond line\n")

        rewrite_file(path, {"example-plugin": "acme-tools"})

        assert path.read_bytes() == b"hello acme-tools\nsecond line\n"

    def test_rewrite_file_is_a_no_op_when_nothing_matches(self, tmp_path: Path) -> None:
        path = tmp_path / "sample.txt"
        original = b"nothing to see here\n"
        path.write_bytes(original)

        rewrite_file(path, {"example-plugin": "acme-tools"})

        assert path.read_bytes() == original


class TestNameValidation:
    """Plugin names follow Agent Plugins §5.5."""

    @pytest.mark.parametrize("name", ["my-plugin", "acme.tools", "lint3r", "a"])
    def test_valid_plugin_names_are_accepted(self, name: str) -> None:
        validate_plugin_name(name)

    @pytest.mark.parametrize(
        "name", ["My-Plugin", "-start", "end-", "has--double", "too..many", ""]
    )
    def test_invalid_plugin_names_are_rejected(self, name: str) -> None:
        with pytest.raises(InvalidNameError):
            validate_plugin_name(name)

    def test_overlong_plugin_names_are_rejected(self) -> None:
        with pytest.raises(InvalidNameError, match="1-64 characters"):
            validate_plugin_name("a" * 65)


import new_plugin  # noqa: E402


def _run_new_plugin_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke `new_plugin.py` as a real subprocess, exactly as documented."""
    return subprocess.run(  # noqa: S603
        ["uv", "run", "python", "scripts/new_plugin.py", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the scaffolding script's `REPO_ROOT` at a scratch directory.

    `TEMPLATE` is bound at import time from the *real* REPO_ROOT, so
    scaffolding still copies genuine template content -- only the destination
    moves into the scratch directory, so these tests run fast, in-process,
    and never touch the real repo.
    """
    monkeypatch.setattr(new_plugin, "REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def scaffolded(fake_repo: Path):
    """Scaffold a plugin directly (in-process) under the scratch repo root."""
    del fake_repo  # depended on only for its REPO_ROOT monkeypatch side effect

    def _make(name: str, *extra: str) -> int:
        return new_plugin.main([name, *extra])

    return _make


def _call_main(argv: list[str]) -> int:
    """Call `new_plugin.main(argv)`, normalizing an argparse `SystemExit`.

    argparse calls `sys.exit()` directly for parse errors -- for example, a
    name starting with `-` looks like an option rather than the positional
    `name` argument -- which raises `SystemExit` through `main()` instead of
    returning an int. A subprocess invocation absorbs this into a normal
    process exit code; calling `main()` in-process does not, so both are
    normalized to the same shape here.
    """
    try:
        return new_plugin.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


class TestNewPluginScaffolding:
    """Test `new_plugin.main`'s scaffolding output directly, in-process."""

    def test_scaffold_contains_only_spec_defined_locations(
        self, fake_repo: Path, scaffolded
    ) -> None:
        """A scaffolded plugin ships only what Agent Plugins 1.0.0 defines."""
        name = "my-example-plugin"
        assert scaffolded(name) == 0

        plugin = fake_repo / name
        top_level = {p.name for p in plugin.iterdir()}
        assert top_level == {
            "plugin.json",
            "mcp.json",
            "skills",
            "README.md",
            "CHANGELOG.md",
            "LICENSE",
        }

    def test_scaffold_rewrites_the_template_name_everywhere(
        self, fake_repo: Path, scaffolded
    ) -> None:
        name = "my-example-plugin"
        assert scaffolded(name) == 0

        plugin = fake_repo / name
        assert json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["name"] == name
        mcp = json.loads((plugin / "mcp.json").read_text(encoding="utf-8"))
        assert f"/{name}/" in mcp["mcpServers"]["example-server"]["url"]
        assert f"{name}-{name}" not in (plugin / "README.md").read_text(encoding="utf-8")

    def test_dotted_plugin_names_are_accepted(self, fake_repo: Path, scaffolded) -> None:
        assert scaffolded("acme.tools") == 0
        assert (fake_repo / "acme.tools" / "plugin.json").is_file()

    def test_rejects_invalid_names_without_creating_anything(self, fake_repo: Path) -> None:
        for bad in ("Bad-Name", "-leading", "has--double"):
            assert _call_main([bad]) != 0, f"{bad!r} should have been rejected"
            assert not (fake_repo / bad).exists(), f"{bad!r} left a directory behind"

    def test_fails_without_creating_anything_when_the_directory_already_exists(
        self, fake_repo: Path, scaffolded
    ) -> None:
        (fake_repo / "acme-tools").mkdir()
        assert scaffolded("acme-tools") != 0

    def test_manifest_has_todo_placeholders_and_no_template_metadata(
        self, fake_repo: Path, scaffolded
    ) -> None:
        """The template's own metadata must not leak into a new plugin."""
        name = "acme-tools"
        assert scaffolded(name) == 0

        manifest = json.loads((fake_repo / name / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["name"] == name
        assert "homepage" not in manifest
        assert "repository" not in manifest
        assert manifest["author"]["name"] == "TODO"

    def test_no_mcp_scaffold_has_no_mcp_json_or_stale_docs(
        self, fake_repo: Path, scaffolded
    ) -> None:
        """`--no-mcp` must not leave a README describing the removed `mcp.json`."""
        name = "acme-tools"
        assert scaffolded(name, "--no-mcp") == 0

        plugin = fake_repo / name
        assert not (plugin / "mcp.json").exists()

        readme = (plugin / "README.md").read_text(encoding="utf-8")
        assert "example-server" not in readme
        assert "streamable-http" in readme  # the "adding an MCP server later" pointer

    def test_a_file_that_cannot_be_decoded_as_utf8_is_skipped_not_fatal(
        self, fake_repo: Path, scaffolded, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rewritable-suffix file with non-UTF-8 content must not crash the scaffold.

        `rewrite_file` opens every matching file as UTF-8 text; a stray
        binary asset with one of those suffixes must be left untouched
        rather than aborting the whole scaffold.
        """
        real_rewrite_file = new_plugin.rewrite_file

        def _raise_for_one_file(path: Path, replacements: dict[str, str]) -> None:
            if path.name == "word_count.py":
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "simulated binary content")
            real_rewrite_file(path, replacements)

        monkeypatch.setattr(new_plugin, "rewrite_file", _raise_for_one_file)
        assert scaffolded("acme-tools") == 0
        assert (fake_repo / "acme-tools" / "plugin.json").is_file()


@pytest.mark.slow
def test_new_plugin_cli_works_as_documented() -> None:
    """One real subprocess invocation, exactly as `just new-plugin` documents it.

    Everything else in this module calls `main()` directly for speed; this
    test alone verifies the actual `uv run python scripts/new_plugin.py`
    entrypoint -- shebang, argv handling, and process exit code -- works.
    """
    name = "zz-cli-smoke-probe"
    destination = REPO_ROOT / name
    try:
        result = _run_new_plugin_cli(name)
        assert result.returncode == 0, result.stderr
        assert (destination / "plugin.json").is_file()
    finally:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
