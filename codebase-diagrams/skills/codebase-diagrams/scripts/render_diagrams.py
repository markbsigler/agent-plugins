#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Batch check or render Mermaid .mmd files with the Mermaid CLI (mmdc).

Uses mmdc if it is on PATH, otherwise runs @mermaid-js/mermaid-cli through npx
(pinned, no global install).

Environment overrides: RENDER_WIDTH (3200), RENDER_HEIGHT (2400), RENDER_SCALE (2),
RENDER_BG (white), RENDER_PUPPETEER_CONFIG (path to a puppeteer JSON config, for
example one containing {"args": ["--no-sandbox"]} when Chromium cannot start in a
container or CI).

Exit codes:
  0  all diagrams rendered (or passed --check)
  1  one or more diagrams failed to render (the mmdc error is printed)
  2  bad usage, missing directory, no .mmd files, or neither mmdc nor npx available
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Pinned so renders stay reproducible when mmdc is not installed and npx fetches it.
MERMAID_CLI_VERSION = "11.12.0"
MAX_ERROR_LINES = 8


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="render_diagrams.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "diagram_directory",
        nargs="?",
        default="docs/diagrams",
        help="directory holding the .mmd files (default: docs/diagrams)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only check that each diagram parses and renders; write nothing to the "
        "diagram directory",
    )
    return parser


def find_mmdc() -> list[str] | None:
    """Return the command that runs mmdc, or None when neither mmdc nor npx exists."""
    if shutil.which("mmdc"):
        return ["mmdc"]
    if shutil.which("npx"):
        return ["npx", "--yes", f"@mermaid-js/mermaid-cli@{MERMAID_CLI_VERSION}"]
    return None


def render_one(
    mmdc: list[str], source: Path, output: Path, options: list[str]
) -> subprocess.CompletedProcess[str]:
    """Render one diagram and return the finished process."""
    # `mmdc` is the fixed command from find_mmdc(); every other argument is a path or a
    # value from this process's own environment, passed as a list (never through a shell).
    return subprocess.run(  # noqa: S603
        [*mmdc, "-i", str(source), "-o", str(output), *options],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def main(argv: list[str] | None = None) -> int:
    """Check or render every diagram; return the process exit code."""
    args = build_parser().parse_args(argv)
    diagram_dir = Path(args.diagram_directory)

    width = os.environ.get("RENDER_WIDTH", "3200")
    height = os.environ.get("RENDER_HEIGHT", "2400")
    scale = os.environ.get("RENDER_SCALE", "2")
    background = os.environ.get("RENDER_BG", "white")
    options = [
        "--width",
        width,
        "--height",
        height,
        "--backgroundColor",
        background,
        "--scale",
        scale,
    ]
    if puppeteer_config := os.environ.get("RENDER_PUPPETEER_CONFIG"):
        options += ["-p", puppeteer_config]

    mmdc = find_mmdc()
    if mmdc is None:
        print(
            "error: need mmdc or Node.js (npx). Install Node.js 18+, "
            "or run: npm install -g @mermaid-js/mermaid-cli",
            file=sys.stderr,
        )
        return 2
    if not diagram_dir.is_dir():
        print(f"error: directory not found: {diagram_dir}", file=sys.stderr)
        return 2
    files = sorted(diagram_dir.glob("*.mmd"))
    if not files:
        print(f"error: no .mmd files found in {diagram_dir}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as scratch:
        if args.check:
            out_dir, extension = Path(scratch), "svg"
            print(f"Checking {len(files)} diagrams in {diagram_dir} (nothing is written there)")
        else:
            out_dir, extension = diagram_dir, "png"
            print(
                f"Rendering {len(files)} diagrams from {diagram_dir} "
                f"({width}x{height}, scale {scale}, bg {background})"
            )

        succeeded = failed = 0
        for source in files:
            result = render_one(mmdc, source, out_dir / f"{source.stem}.{extension}", options)
            if result.returncode == 0:
                print(f"  ok      {source.name}")
                succeeded += 1
            else:
                print(f"  FAILED  {source.name}", file=sys.stderr)
                lines = (result.stdout + result.stderr).splitlines()[:MAX_ERROR_LINES]
                for line in lines:
                    print(f"          {line}", file=sys.stderr)
                failed += 1

    print(f"Done: {succeeded} succeeded, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
