"""Validates the marketplace catalog that lets users install one plugin from this repo."""

from __future__ import annotations

import pytest
from discovery import REPO_ROOT, discover_plugins, load_json

CATALOG = REPO_ROOT / ".github" / "plugin" / "marketplace.json"
# example-plugin is the template for new plugins, not something to distribute.
UNLISTED = {"example-plugin"}


@pytest.fixture(scope="module")
def catalog() -> dict:
    return load_json(CATALOG)


def test_catalog_has_required_fields(catalog: dict) -> None:
    assert catalog["name"] == "agent-plugins"
    assert catalog["owner"]["name"]
    assert isinstance(catalog["plugins"], list)


def test_every_distributable_plugin_is_listed(catalog: dict) -> None:
    listed = {entry["name"] for entry in catalog["plugins"]}
    expected = {p.name for p in discover_plugins()} - UNLISTED
    assert listed == expected


def test_template_plugin_is_not_listed(catalog: dict) -> None:
    assert UNLISTED.isdisjoint(entry["name"] for entry in catalog["plugins"])


def test_plugin_names_are_unique(catalog: dict) -> None:
    names = [entry["name"] for entry in catalog["plugins"]]
    assert len(names) == len(set(names))


def test_entries_match_their_plugin_manifest(catalog: dict) -> None:
    for entry in catalog["plugins"]:
        # Sources are relative to the repo root, the marketplace root.
        assert entry["source"] == f"./{entry['name']}"
        manifest = load_json(REPO_ROOT / entry["name"] / "plugin.json")
        assert manifest["name"] == entry["name"]
        assert manifest["version"] == entry["version"]
        assert manifest["description"] == entry["description"]
