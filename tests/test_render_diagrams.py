"""Tests for codebase-diagrams/scripts/render_diagrams.py, using a stub Mermaid CLI."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from discovery import REPO_ROOT

SCRIPT = (
    REPO_ROOT
    / "codebase-diagrams"
    / "skills"
    / "codebase-diagrams"
    / "scripts"
    / "render_diagrams.py"
)

# The stubs are executable scripts found through PATH, which Windows does not support.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="stubs need POSIX shebangs")

# Stand-in for mmdc: logs its arguments, fails on diagrams containing BROKEN, and otherwise
# writes the requested output file.
STUB = f"""#!{sys.executable}
import os
import sys

with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
source = args[args.index("-i") + 1]
output = args[args.index("-o") + 1]
if "BROKEN" in open(source, encoding="utf-8").read():
    for n in range(1, 21):
        print(f"parse error detail line {{n}}", file=sys.stderr)
    sys.exit(1)
open(output, "w", encoding="utf-8").close()
"""

# npx stand-in: records the call, drops `--yes <package>`, then behaves like the stub above.
NPX_STUB = f"""#!{sys.executable}
import os
import sys

with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write("npx " + " ".join(sys.argv[1:]) + "\\n")
os.execv(sys.argv[0] + "-stub", [sys.argv[0] + "-stub", *sys.argv[3:]])
"""


def make_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Env:
    """A throwaway PATH of stub tools plus a diagram directory."""

    def __init__(self, root: Path) -> None:
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "stub.log"
        self.diagrams = root / "diagrams"
        self.diagrams.mkdir()

    def add_stub(self, name: str) -> None:
        if name == "npx":
            make_executable(self.bin / "npx-stub", STUB)
            make_executable(self.bin / "npx", NPX_STUB)
        else:
            make_executable(self.bin / name, STUB)

    def diagram(self, name: str, content: str = "flowchart TD\n  A --> B\n") -> Path:
        path = self.diagrams / f"{name}.mmd"
        path.write_text(content, encoding="utf-8")
        return path

    def run(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {"PATH": str(self.bin), "STUB_LOG": str(self.log)}
        # Forward coverage's subprocess hooks; PATH is isolated but coverage must still start.
        env.update({k: v for k, v in os.environ.items() if k.startswith(("COVERAGE", "COV_CORE"))})
        env.update(extra_env or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def logged_calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


@pytest.fixture
def env(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.add_stub("mmdc")
    return e


def test_help_exits_zero_and_documents_exit_codes(env: Env) -> None:
    result = env.run("--help")
    assert result.returncode == 0
    assert "--check" in result.stdout
    assert "Exit codes" in result.stdout


def test_unknown_option_is_a_usage_error(env: Env) -> None:
    result = env.run("--bogus")
    assert result.returncode == 2
    assert "unrecognized arguments: --bogus" in result.stderr


def test_second_directory_is_a_usage_error(env: Env) -> None:
    result = env.run(str(env.diagrams), "other")
    assert result.returncode == 2
    assert "unrecognized arguments: other" in result.stderr


def test_missing_directory_exits_two(env: Env) -> None:
    result = env.run(str(env.diagrams / "nope"))
    assert result.returncode == 2
    assert "directory not found" in result.stderr


def test_directory_without_diagrams_exits_two(env: Env) -> None:
    result = env.run(str(env.diagrams))
    assert result.returncode == 2
    assert "no .mmd files" in result.stderr


def test_missing_mermaid_cli_and_npx_exits_two(tmp_path: Path) -> None:
    bare = Env(tmp_path)  # no stubs: neither mmdc nor npx is on PATH
    bare.diagram("a")
    result = bare.run(str(bare.diagrams))
    assert result.returncode == 2
    assert "mmdc or Node.js" in result.stderr


def test_renders_every_diagram_to_png(env: Env) -> None:
    env.diagram("a")
    env.diagram("b")
    result = env.run(str(env.diagrams))
    assert result.returncode == 0
    assert (env.diagrams / "a.png").exists()
    assert (env.diagrams / "b.png").exists()
    assert "2 succeeded, 0 failed" in result.stdout


def test_failure_exits_one_but_still_renders_the_rest(env: Env) -> None:
    env.diagram("good")
    env.diagram("bad", "BROKEN")
    result = env.run(str(env.diagrams))
    assert result.returncode == 1
    assert (env.diagrams / "good.png").exists()
    assert not (env.diagrams / "bad.png").exists()
    assert "FAILED  bad.mmd" in result.stderr
    assert "1 succeeded, 1 failed" in result.stdout


def test_error_output_is_trimmed(env: Env) -> None:
    env.diagram("bad", "BROKEN")
    result = env.run(str(env.diagrams))
    assert "parse error detail line 1" in result.stderr
    assert "parse error detail line 20" not in result.stderr


def test_check_mode_writes_nothing_to_the_diagram_directory(env: Env) -> None:
    env.diagram("a")
    result = env.run("--check", str(env.diagrams))
    assert result.returncode == 0
    assert sorted(p.name for p in env.diagrams.iterdir()) == ["a.mmd"]
    assert ".svg" in env.logged_calls()[0]


def test_check_mode_reports_failures(env: Env) -> None:
    env.diagram("bad", "BROKEN")
    result = env.run("--check", str(env.diagrams))
    assert result.returncode == 1
    assert "FAILED  bad.mmd" in result.stderr


def test_puppeteer_config_is_passed_through(env: Env) -> None:
    env.diagram("a")
    env.run(str(env.diagrams), extra_env={"RENDER_PUPPETEER_CONFIG": "puppeteer.json"})
    assert "-p puppeteer.json" in env.logged_calls()[0]


def test_no_puppeteer_flag_by_default(env: Env) -> None:
    env.diagram("a")
    env.run(str(env.diagrams))
    assert "-p " not in env.logged_calls()[0]


def test_render_settings_come_from_environment(env: Env) -> None:
    env.diagram("a")
    env.run(
        str(env.diagrams),
        extra_env={"RENDER_WIDTH": "100", "RENDER_HEIGHT": "50", "RENDER_SCALE": "3"},
    )
    call = env.logged_calls()[0]
    assert "--width 100" in call
    assert "--height 50" in call
    assert "--scale 3" in call


def test_falls_back_to_pinned_npx_without_global_install(tmp_path: Path) -> None:
    e = Env(tmp_path)
    e.add_stub("npx")
    e.diagram("a")
    result = e.run(str(e.diagrams))
    assert result.returncode == 0
    assert (e.diagrams / "a.png").exists()
    npx_call = e.logged_calls()[0]
    assert npx_call.startswith("npx --yes @mermaid-js/mermaid-cli@")
    assert "latest" not in npx_call
