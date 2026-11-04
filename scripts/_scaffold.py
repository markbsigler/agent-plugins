"""Shared helpers for the plugin scaffolding script.

Name validation and text rewriting live here so ``new_plugin.py`` stays a thin
command-line wrapper that is easy to test.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Agent Plugins v1.0.0 §5.5: 1-64 chars, lowercase alphanumeric plus hyphen
# and period, starting and ending alphanumeric, with no `--` or `..`.
PLUGIN_NAME_PATTERN = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

MAX_NAME_LENGTH = 64


class InvalidNameError(ValueError):
    """Raised when a plugin name violates its constraints."""


def validate_plugin_name(name: str) -> None:
    """Validate a plugin name against the Agent Plugins specification.

    Raises:
        InvalidNameError: If ``name`` violates the specification.
    """
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise InvalidNameError(
            f"plugin name must be 1-{MAX_NAME_LENGTH} characters, got {len(name)}"
        )
    if not PLUGIN_NAME_PATTERN.match(name):
        raise InvalidNameError(
            f"{name!r} is not a valid plugin name.\n"
            "Use lowercase letters, digits, hyphens, and periods; start and end "
            "with an alphanumeric character; no '--' or '..'."
        )


def rewrite_text(text: str, replacements: dict[str, str]) -> str:
    """Apply ``replacements`` to ``text`` in a single pass.

    Each source region is rewritten at most once, so text produced by one
    replacement is never re-scanned by another. Applying replacements
    sequentially would corrupt output whenever a replacement *value* contains
    a replacement *key* -- for example, rewriting ``example-plugin`` to
    ``my-example-plugin`` and then rewriting ``example-plugin`` inside the
    result.

    Longer keys are matched first so overlapping keys resolve unambiguously.
    """
    if not replacements:
        return text
    keys = sorted(replacements, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(key) for key in keys))
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def rewrite_file(path: Path, replacements: dict[str, str]) -> None:
    """Apply :func:`rewrite_text` to a file in place, preserving LF endings."""
    original = path.read_text(encoding="utf-8")
    updated = rewrite_text(original, replacements)
    if updated != original:
        path.write_text(updated, encoding="utf-8", newline="\n")
