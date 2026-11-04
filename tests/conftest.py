"""Pytest hooks for the repo-level tests.

Discovery logic lives in ``discovery.py``; this module only wires it into
pytest so that any test taking a ``plugin_dir`` or ``skill_dir`` argument runs once per
discovered item. Adding a new plugin
therefore requires no test edits.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from discovery import REPO_ROOT, discover_plugins, discover_skills

# The aha-feature scripts import each other as top-level modules, as they do when run directly.
_AHA_FEATURE_SCRIPTS = REPO_ROOT / "aha-feature" / "skills" / "aha-feature" / "scripts"
if str(_AHA_FEATURE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_AHA_FEATURE_SCRIPTS))


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize discovery arguments across every plugin and skill."""
    if "plugin_dir" in metafunc.fixturenames:
        plugins = discover_plugins()
        metafunc.parametrize("plugin_dir", plugins, ids=_ids(plugins))
    if "skill_dir" in metafunc.fixturenames:
        skills = discover_skills()
        metafunc.parametrize("skill_dir", skills, ids=_ids(skills))
