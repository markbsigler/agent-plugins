"""Tests for the aha-feature skill script, aha_feature.py."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import Any

import aha_feature
import aha_html
import pytest

FEATURE = """---
record: APP-12
name: Release Notes Agent
workspace: APP
aha-domain: example.aha.io
profile: agent
link-prefixes: APP, PLAT
---

# Field: Description

> [!NOTE]
> **Scope:** drafts release notes from merged changes; publishing stays with people. See APP-S-1.

**As a** release manager, **I want** an agent that drafts release notes from merged changes, \
**so that** each release ships with accurate notes and I spend my time on review instead of collation.

### Agent Definition

| Element | Definition |
|---|---|
| Role | Drafts release notes for one product from merged pull requests. Can't publish its own notes. |
| Triggers | A release branch is cut (P0). A release manager asks in a session (P1). |
| Context | Merged pull requests, linked Aha! features, and the release record (PLAT-4). |
| Read actions | Pull requests, Aha! features, and the previous notes. |
| Write actions | Draft notes in the release record. Open a review request. |
| Autonomy | Drafting runs without approval. A person approves the notes before publishing. |
| Guardrails | Only merged changes. No customer names. Every note links to its change. |
| Stops and escalates when | A change has no linked feature.<br>The draft exceeds 200 entries. |
| Outputs | Draft notes, a change-to-note trace, and an escalation package when it stops. |
| Handoffs | Approved notes go to the publishing pipeline (PLAT-9). |
| Out of scope | Publishing notes. Marketing copy. Translations. |

### Workflow

1. Collect the merged changes for the release.
2. Draft one note per change.
3. Open a review request. A person approves.

### Definition of Done

- AC-1 to AC-3 pass.
- Pilot: 10 releases with at least 90% of notes accepted without edits.

# Field: Summary

Release notes are assembled by hand from merged changes. The Release Notes Agent drafts them from \
the changes themselves, links each note to its change, and leaves approval and publishing with people.

# Field: Business Problem

Release managers collate notes by hand from pull requests and features, and notes miss changes. \
Not yet measured: time spent per release and notes corrected after publishing.

# Field: Business Value

**Less effort:** at least 50% less time per release, measured against the baseline.

# Field: Use Case(s)

| ID | Use case | Priority |
|---|---|---|
| UC-1 | Draft release notes from merged changes | P0 |
| UC-2 | Route the draft for approval | P1 |

# Field: Acceptance Criteria

### AC-1. Draft from merged changes

- **Given** a release branch with merged pull requests,
- **When** the agent drafts the notes,
- **Then** each merged change has exactly one note that links to it.

### AC-2. Approval before publishing

- **Given** a draft,
- **When** a person approves it,
- **Then** the notes move to the publishing pipeline, and an unapproved draft never does.

### AC-3. Audit

- **Given** any draft,
- **When** it is audited,
- **Then** every read and write is traceable to identity and time.

# Field: Dependencies (upstream)

- Source control API: merged pull requests.
- Publishing pipeline (PLAT-9): accepts approved notes.

# Requirement: APP-12-1 Drafting

Draft one note per merged change.

- **FR-1 (P0):** WHEN a release branch is cut, the agent SHALL draft one note for each merged change.
- **FR-2 (P0):** The agent SHALL link each note to its change.
- **NFR-1 (P1):** WHEN a release has up to 200 changes, the agent SHALL finish the draft within 2 minutes.

Covers: UC-1. Verified by AC-1.

# Requirement: APP-12-2 Approval and audit

- **FR-3 (P0):** IF a draft has no approval, THEN the agent SHALL NOT send it to the publishing pipeline.
- **FR-4 (P1, ADDED):** The agent SHALL record every read and write with identity and time in the audit log.

Covers: UC-2. Verified by AC-2, AC-3.

# To-Do: Confirm the entry limit

Decide whether 200 entries is the right stop limit. (OQ-1)
"""


def variant(old: str, new: str, text: str = FEATURE) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


def rules(text: str, gate: str = "elaborated", profile: str | None = None) -> dict[str, str]:
    """Return {rule: most severe severity} for the findings on a bundle."""
    found: dict[str, str] = {}
    for finding in aha_feature.lint(aha_feature.parse_bundle(text), gate, profile):
        found.setdefault(finding.rule, finding.severity)
    return found


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)  # noqa: S603, S607
    return path


def aha_record(**overrides: Any) -> dict[str, Any]:
    """A feature as read_records returns it with the default Markdown text format."""
    record: dict[str, Any] = {
        "id": "APP-12",
        "name": "Release Notes Agent",
        "url": "https://example.aha.io/features/APP-12",
        "record_type": "feature",
        "project": {"reference_prefix": "APP"},
        "workflow_kind": {"name": "New Capability"},
        "workflow_status": {"name": "Under consideration"},
        "release": {"id": "APP-R-5", "name": "Spring"},
        "initiative": {"id": "APP-S-1", "name": "Automation"},
        "epic": {"id": "APP-E-2", "name": "Agents"},
        "assigned_to_user": None,
        "tags": ["AI"],
        "attachments": [{"id": "1"}],
        "description": (
            "**As a** release manager, **I want** drafted notes, **so that** I review.\n\n"
            "### **Agent Definition**\n"
            "| Element      | Definition                    |\n"
            "|--------------|-------------------------------|\n"
            "| Role         | Drafts notes.                 |\n"
            "|              | \\\\                           |\n"
            "|              | Second paragraph.             |\n"
            "| Out of scope | See [APP-7](https://example.aha.io/records/APP-7"
            "?reference-class=Feature&visible-fields=icon%2Cref) and "
            "[PLAT-9](https://example.aha.io/records/PLAT-9?reference-class=Feature). |\n"
            "\\\\\n"
        ),
        "custom_fields": [
            {"name": "Acceptance Criteria", "type": "note", "value": "### **AC-1. Draft**"},
            {"name": "Summary", "type": "note", "value": "<p>Drafts <strong>notes</strong>.</p>"},
            {"name": "Customer Value", "type": "array", "value": ["Reduce Cost", "Reduce Risk"]},
            {"name": "Differentiator", "type": "string", "value": {"name": "Comparative"}},
            {"name": "Priority", "type": "number", "value": 2.0},
            {"name": "Target date", "type": "date", "value": None},
            {"name": "Odd field", "type": "note", "value": "Kept last."},
            "not a field",
        ],
        "requirements": {
            "records": [
                {"id": "APP-12-1", "name": "Drafting", "description": "Draft notes."},
                {"id": "APP-12-2", "name": "Audit", "description": None},
            ]
        },
        "to_dos": {
            "records": [
                {"id": "APP-TODO-4", "name": "Confirm limits", "status": "pending", "body": "Why?"},
                {"id": "APP-TODO-5", "name": "Name owner", "description": "<p>Owner</p>"},
            ]
        },
    }
    record.update(overrides)
    return record


def write_json(path: Path, record: dict[str, Any], trailing: str = "") -> Path:
    payload = json.dumps({"success": True, "result": {"results": [record]}})
    path.write_text(payload + trailing, encoding="utf-8")
    return path


# --- Bundles ------------------------------------------------------------------------


def test_parse_bundle_reads_meta_sections_and_lines() -> None:
    bundle = aha_feature.parse_bundle(FEATURE)

    assert bundle.record == "APP-12"
    assert bundle.name == "Release Notes Agent"
    assert [section.label for section in bundle.sections][-3:] == [
        "Requirement: APP-12-1 Drafting",
        "Requirement: APP-12-2 Approval and audit",
        "To-Do: Confirm the entry limit",
    ]
    description = bundle.sections[0]
    assert FEATURE.split("\n")[description.line - 1] == "# Field: Description"
    assert FEATURE.split("\n")[description.body_line - 1] == "> [!NOTE]"
    assert bundle.get_field("use cases") is bundle.get_field("Use Case(s)")
    assert bundle.find_requirement(None, "Approval and Audit") is bundle.requirements()[1]
    assert bundle.find_requirement("APP-12-1", "other") is bundle.requirements()[0]
    assert bundle.find_todo("confirm the entry limit") is bundle.todos()[0]
    assert bundle.prefixes() == frozenset({"APP", "PLAT"})


def test_parse_bundle_ignores_delimiters_in_code_and_handles_new_requirements() -> None:
    text = (
        "# Field: Notes\n\n```\n# Field: Not a section\n```\n\n"
        "# Requirement: new Catalog\n\nBody\n\n# Requirement: Plain name\n\n# Record Settings\n\nx"
    )

    bundle = aha_feature.parse_bundle(text)

    assert [(s.kind, s.title, s.ref) for s in bundle.sections] == [
        ("field", "Notes", None),
        ("requirement", "Catalog", None),
        ("requirement", "Plain name", None),
        ("settings", "Settings", None),
    ]
    assert "# Field: Not a section" in bundle.sections[0].body
    assert bundle.meta == {}


def test_format_bundle_round_trips() -> None:
    bundle = aha_feature.parse_bundle(FEATURE)

    again = aha_feature.parse_bundle(aha_feature.format_bundle(bundle))

    assert again.meta == bundle.meta
    assert [(s.kind, s.title, s.ref, s.body) for s in again.sections] == [
        (s.kind, s.title, s.ref, s.body) for s in bundle.sections
    ]
    assert aha_feature.Section("settings", "Settings").heading() == "# Settings"


# --- Lint ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate", aha_feature.GATES)
def test_reference_feature_passes_every_gate(gate: str) -> None:
    assert aha_feature.lint(aha_feature.parse_bundle(FEATURE), gate) == []


def test_analysis_reads_the_specification() -> None:
    spec = aha_feature.analyze(aha_feature.parse_bundle(FEATURE), "agent")

    assert [s.sid for s in spec.statements()] == ["FR-1", "FR-2", "NFR-1", "FR-3", "FR-4"]
    assert spec.statements()[4].change == "ADDED"
    assert spec.requirements[0].scope == "Draft one note per merged change."
    assert spec.requirements[1].verified_ac == {2, 3}
    assert spec.use_cases[2].priority == "P1"
    assert spec.criteria[1].clauses["then"] == [
        "each merged change has exactly one note that links to it."
    ]
    assert spec.out_of_scope == ["Publishing notes.", "Marketing copy.", "Translations."]
    assert spec.user_story is not None
    assert spec.user_story["persona"] == "release manager"
    assert spec.done is not None
    assert spec.done.startswith("- AC-1 to AC-3 pass.")


STRUCTURE_CASES = [
    (
        "**As a** release manager, **I want**",
        "A release manager wants",
        "elaborated",
        "STR001",
        "error",
    ),
    (
        "### Agent Definition\n\n| Element | Definition |",
        "### Agent roles\n\n| Thing | Detail |",
        "elaborated",
        "STR002",
        "error",
    ),
    ("| Handoffs |", "| Hand-off notes |", "elaborated", "STR003", "warning"),
    ("| Handoffs |", "| Hand-off notes |", "ready", "STR003", "error"),
    ("| Role |", "| Purpose text |", "seed", "STR003", "error"),
    (
        "Publishing notes. Marketing copy. Translations.",
        "Publishing notes.",
        "seed",
        "STR004",
        "info",
    ),
    (
        "Publishing notes. Marketing copy. Translations.",
        "Publishing notes.",
        "ready",
        "STR004",
        "error",
    ),
    ("### Definition of Done", "### Exit", "elaborated", "STR005", "warning"),
    (
        "# Field: Summary\n\nRelease notes",
        "# Field: Summary\n\n\n# Field: Old\n\nRelease notes",
        "elaborated",
        "STR006",
        "warning",
    ),
    ("Not yet measured: time", "Missing: time", "elaborated", "STR008", "warning"),
    (
        "identity and time in the audit log",
        "identity and time in the log",
        "ready",
        "STR010",
        "warning",
    ),
    ("within 2 minutes", "within a short time", "elaborated", "STR010", "info"),
]


@pytest.mark.parametrize(("old", "new", "gate", "rule", "severity"), STRUCTURE_CASES)
def test_structure_rules(old: str, new: str, gate: str, rule: str, severity: str) -> None:
    assert rules(variant(old, new), gate).get(rule) == severity


def test_structure_rules_for_empty_and_long_fields() -> None:
    empty = variant(FEATURE.split("# Field: Description\n")[1].split("# Field: Summary")[0], "\n")
    assert rules(empty)["STR001"] == "error"
    no_requirements = FEATURE.split("# Requirement:")[0]
    assert rules(no_requirements)["STR007"] == "error"
    long_summary = variant(
        "Release notes are assembled", "Long " * 300 + "Release notes are assembled"
    )
    assert rules(long_summary)["STR009"] == "warning"
    product = rules(FEATURE, "ready", "product")
    assert product["STR003"] == "error"
    assert product["STR010"] == "warning"


def test_non_goals_section_counts_as_out_of_scope() -> None:
    text = variant(
        "| Out of scope | Publishing notes. Marketing copy. Translations. |\n",
        "\n#### Non-goals\n\n- Publishing\n- Marketing\n\n### Other\n\n",
    )

    spec = aha_feature.analyze(aha_feature.parse_bundle(text), "agent")

    assert spec.out_of_scope == ["Publishing", "Marketing"]


EARS_CASES = [
    ("The agent SHALL link", "The agent should link", "EARS002", "error"),
    ("The agent SHALL link", "The agent links", "EARS002", "error"),
    ("The agent SHALL link", "The agent shall link", "EARS003", "warning"),
    ("WHEN a release branch", "When a release branch", "EARS003", "warning"),
    (", THEN the agent SHALL NOT", ", the agent SHALL NOT", "EARS005", "warning"),
    (
        "WHEN a release branch is cut,",
        "WHEN a release branch is cut, WHILE frozen,",
        "EARS006",
        "warning",
    ),
    (
        "The agent SHALL link each note",
        "The agent SHALL link each note WHERE linking is on",
        "EARS006",
        "warning",
    ),
    (
        "SHALL link each note to its change.",
        "SHALL link each note and SHALL tag it.",
        "EARS007",
        "warning",
    ),
    ("SHALL link each note", "SHALL quickly link each note", "EARS008", "warning"),
    ("**FR-2 (P0):**", "**FR-2:**", "EARS009", "warning"),
    ("**FR-2 (P0):**", "**FR-1 (P0):**", "EARS010", "error"),
    ("**FR-2 (P0):**", "**FR-2 (P0, URGENT):**", "EARS011", "warning"),
]


@pytest.mark.parametrize(("old", "new", "rule", "severity"), EARS_CASES)
def test_ears_rules(old: str, new: str, rule: str, severity: str) -> None:
    assert rules(variant(old, new)).get(rule) == severity


def test_requirement_without_statements() -> None:
    text = variant("- **FR-3 (P0):**", "FR-3 (P0) as prose:")
    text = variant("- **FR-4 (P1, ADDED):**", "FR-4 as prose:", text)

    assert rules(text, "seed")["EARS001"] == "warning"
    assert rules(text)["EARS001"] == "error"


def test_table_statements_and_continuation_lines() -> None:
    text = variant(
        "- **FR-3 (P0):** IF a draft has no approval,",
        "| ID | Priority | Statement |\n|---|---|---|\n"
        "| **FR-3** | P0 | IF a draft has no approval, THEN the agent SHALL NOT publish it. |\n\n"
        "- **FR-5 (P1):** IF a draft has no approval,",
    )
    text = variant(
        "- **FR-4 (P1, ADDED):** The agent SHALL record",
        "- **FR-4 (P1, ADDED):** The agent SHALL record\n  every change and",
        text,
    )

    spec = aha_feature.analyze(aha_feature.parse_bundle(text), "agent")

    statements = {s.sid: s for s in spec.statements()}
    assert statements["FR-3"].priority == "P0"
    assert (
        statements["FR-3"].text
        == "IF a draft has no approval, THEN the agent SHALL NOT publish it."
    )
    assert statements["FR-4"].text.startswith("The agent SHALL record every change and every read")


TRACE_CASES = [
    ("Covers: UC-1. Verified by AC-1.", "Verified by AC-1.", "TRC001", "error"),
    ("Covers: UC-1. Verified by AC-1.", "Covers: UC-1.", "TRC002", "error"),
    ("Covers: UC-1. Verified by AC-1.", "Covers: UC-1, UC-9. Verified by AC-1.", "TRC003", "error"),
    ("Covers: UC-1. Verified by AC-1.", "Covers: UC-1. Verified by AC-1, AC-9.", "TRC004", "error"),
    ("Covers: UC-1. Verified by AC-1.", "Covers: UC-2. Verified by AC-1.", "TRC005", "warning"),
    ("Verified by AC-2, AC-3.", "Verified by AC-2.", "TRC006", "warning"),
    (
        "Covers: UC-1. Verified by AC-1.",
        "Covers: UC-1; PRD FR-1 to FR-3. Verified by AC-1.",
        "TRC007",
        "info",
    ),
    ("- AC-1 to AC-3 pass.", "- AC-1 to AC-5 pass.", "TRC008", "warning"),
    (
        "Covers: UC-1. Verified by AC-1.",
        "Covers: UC-1; FR-1, FR-9. Verified by AC-1.",
        "TRC009",
        "warning",
    ),
]


@pytest.mark.parametrize(("old", "new", "rule", "severity"), TRACE_CASES)
def test_traceability_rules(old: str, new: str, rule: str, severity: str) -> None:
    assert rules(variant(old, new)).get(rule) == severity


def test_traceability_ranges_and_all_use_cases() -> None:
    text = variant(
        "Covers: UC-1. Verified by AC-1.", "Covers: all use cases.\nVerified by: AC-1 to AC-3."
    )
    spec = aha_feature.analyze(aha_feature.parse_bundle(text), "agent")

    assert spec.requirements[0].covers_all
    assert spec.requirements[0].verified_ac == {1, 2, 3}
    assert aha_feature.expand_ids("FR-8 to FR-11, FR-14, NFR-2 and FR-3 to FR-1", "FR") == {
        8,
        9,
        10,
        11,
        14,
        3,
    }
    assert aha_feature.expand_ids("AC-1 \u2013 AC-3", "AC") == {1, 2, 3}
    assert "TRC005" not in rules(text, "ready")


CRITERIA_CASES = [
    (
        "- **Then** every read and write is traceable",
        "- every read and write is traceable",
        "AC001",
        "error",
    ),
    ("### AC-3. Audit", "### AC-2. Audit", "AC002", "error"),
    ("### AC-3. Audit", "### AC-4. Audit", "AC002", "info"),
    ("- **When** it is audited,", "- **When** it is audited quickly,", "AC004", "warning"),
    ("| UC-2 | Route the draft for approval | P1 |", "| UC-1 | Again | P1 |", "UC001", "error"),
    (
        "| UC-2 | Route the draft for approval | P1 |",
        "| UC-2 | Route the draft for approval | Soon |",
        "UC002",
        "warning",
    ),
]


@pytest.mark.parametrize(("old", "new", "rule", "severity"), CRITERIA_CASES)
def test_criteria_and_use_case_rules(old: str, new: str, rule: str, severity: str) -> None:
    assert rules(variant(old, new)).get(rule) == severity


def test_criteria_and_use_cases_without_ids() -> None:
    criteria = FEATURE.split("# Field: Acceptance Criteria\n\n")[1].split("\n# Field:")[0]
    cases = FEATURE.split("# Field: Use Case(s)\n\n")[1].split("\n# Field:")[0]
    text = variant(criteria, "Given a draft, when approved, then published.\n")
    text = variant(cases, "Drafting and routing.\n", text)

    found = rules(text)

    assert found["AC003"] == "error"
    assert found["UC003"] == "error"


def test_criteria_continuations_and_bullet_use_cases() -> None:
    text = variant(
        "- **Then** every read and write is traceable",
        "- **Then** every read\n  and write is traceable",
    )
    text = variant(
        "- **When** it is audited,", "- **When** it is audited,\n- **And** exported,", text
    )
    text = variant("| UC-1 | Draft release notes from merged changes | P0 |", "", text)
    text = variant(
        "|---|---|---|\n", "|---|---|---|\n\n- **UC-1:** Draft release notes (P0)\n", text
    )

    spec = aha_feature.analyze(aha_feature.parse_bundle(text), "agent")

    assert spec.criteria[3].clauses["when"] == ["it is audited,", "exported,"]
    assert spec.criteria[3].clauses["then"][0].startswith("every read and write")
    assert spec.use_cases[1].priority == "P0"


WRITING_CASES = [
    (
        "leaves approval and publishing with people",
        "seamlessly leaves approval with people",
        "elaborated",
        "WRT001",
        "warning",
    ),
    (
        "Draft one note per merged change.",
        "Draft one note per merged change by March 2027.",
        "elaborated",
        "WRT002",
        "warning",
    ),
    (
        "Draft one note per merged change.",
        "Draft one note per change (to confirm).",
        "elaborated",
        "WRT003",
        "info",
    ),
    (
        "Draft one note per merged change.",
        "Draft one note per change, TBD.",
        "ready",
        "WRT003",
        "error",
    ),
]


@pytest.mark.parametrize(("old", "new", "gate", "rule", "severity"), WRITING_CASES)
def test_writing_rules(old: str, new: str, gate: str, rule: str, severity: str) -> None:
    assert rules(variant(old, new), gate).get(rule) == severity


def test_lint_rejects_unknown_gate_and_profile() -> None:
    bundle = aha_feature.parse_bundle(FEATURE)

    with pytest.raises(ValueError, match="unknown gate"):
        aha_feature.lint(bundle, "done")
    with pytest.raises(ValueError, match="unknown profile"):
        aha_feature.lint(bundle, "seed", "service")


def test_findings_are_ranked_and_formatted() -> None:
    text = variant("The agent SHALL link", "The agent should link")
    text = variant("Draft one note per merged change.", "Draft one note (to confirm).", text)
    bundle = aha_feature.parse_bundle(text)

    findings = aha_feature.lint(bundle)
    report = aha_feature.format_findings(bundle, findings, "elaborated", "agent")

    assert [f.severity for f in findings] == ["error", "info"]
    assert findings[0].line is not None
    assert findings[0].as_dict()["rule"] == "EARS002"
    assert report.splitlines()[0] == (
        "APP-12 Release Notes Agent (gate: elaborated, profile: agent): 1 error(s), 0 warning(s), 1 info"
    )
    assert f"(line {findings[0].line})" in report


# --- Aha! JSON ----------------------------------------------------------------------


def test_record_to_bundle_normalizes_aha_markdown() -> None:
    bundle = aha_feature.record_to_bundle(aha_record())

    assert bundle.meta == {
        "record": "APP-12",
        "name": "Release Notes Agent",
        "workspace": "APP",
        "aha-domain": "example.aha.io",
        "url": "https://example.aha.io/features/APP-12",
        "profile": "agent",
        "initiative": "APP-S-1 Automation",
        "goals": "",
        "key-results": "",
        "link-prefixes": "APP, PLAT",
    }
    description = bundle.field_text("Description")
    assert "| Role | Drafts notes.<br>Second paragraph. |" in description
    assert "| Out of scope | See APP-7 and PLAT-9. |" in description
    assert "\\\\" not in description
    assert bundle.field_text("Summary") == "Drafts **notes**."
    assert [s.title for s in bundle.fields()] == [
        "Description",
        "Summary",
        "Acceptance Criteria",
        "Odd field",
    ]
    assert [(s.ref, s.title, s.body) for s in bundle.requirements()] == [
        ("APP-12-1", "Drafting", "Draft notes."),
        ("APP-12-2", "Audit", ""),
    ]
    assert [(s.title, s.body) for s in bundle.todos()] == [
        ("Confirm limits", "Why?"),
        ("Name owner", "Owner"),
    ]
    settings = bundle.sections[-1].body
    for row in (
        "| Type | New Capability |",
        "| Release | APP-R-5 Spring |",
        "| Attachments | 1 |",
        "| Customer Value | Reduce Cost, Reduce Risk |",
        "| Differentiator | Comparative |",
        "| Priority | 2.0 |",
        "| Target date |  |",
        "| APP-TODO-4 | Confirm limits | pending |",
    ):
        assert row in settings


def test_record_to_bundle_reads_html_fields() -> None:
    record = aha_record(
        description='<div data-callout-box-type="noteBlock"><p>Note</p></div><p>Body</p>',
        project=None,
        url="",
        workflow_kind={"name": "Enabling Capability"},
    )

    bundle = aha_feature.record_to_bundle(record)

    assert bundle.field_text("Description") == "> [!NOTE]\n> Note\n\nBody"
    assert bundle.meta["profile"] == "platform"
    assert bundle.meta["workspace"] == "APP"
    assert "aha-domain" not in bundle.meta


def test_guess_profile() -> None:
    assert aha_feature.guess_profile("Shared Foundation", "New Capability") == "platform"
    assert aha_feature.guess_profile("Test Agent", "") == "agent"
    assert aha_feature.guess_profile("Invoice export", "Improved Capability") == "product"


def test_json_loading_shapes(tmp_path: Path) -> None:
    path = write_json(tmp_path / "dump.txt", aha_record(), trailing='\n\n{"duplicate": true}')
    listing = {"result": {"results": {"records": [{"id": "APP-1"}, {"id": "APP-2"}]}}}

    assert aha_feature.load_bundle(str(path)).record == "APP-12"
    assert aha_feature.iter_records(listing) == [{"id": "APP-1"}, {"id": "APP-2"}]
    assert aha_feature.iter_records({"id": "APP-3"}) == [{"id": "APP-3"}]
    assert aha_feature.iter_records(5) == []
    assert aha_feature.parse_json_text("saved output:\n[1, 2]") == [1, 2]
    assert aha_feature.select_record([{"id": "APP-1"}, {"id": "APP-2"}], "APP-2") == {"id": "APP-2"}
    with pytest.raises(ValueError, match="no JSON"):
        aha_feature.parse_json_text("plain text")
    with pytest.raises(ValueError, match="no records"):
        aha_feature.select_record([])
    with pytest.raises(ValueError, match="APP-9 not found"):
        aha_feature.select_record([{"id": "APP-1"}], "APP-9")


def test_merge_continuation_rows_keeps_real_rows() -> None:
    lines = [
        "| A | B |",
        "|---|---|",
        "|  | first row has an empty first cell |",
        "| x | y |",
        "|  | more |",
        "|  | \\\\ |",
        "",
        "| loose | row |",
    ]

    assert aha_feature.merge_continuation_rows(lines) == [
        "| A | B |",
        "|---|---|",
        "|  | first row has an empty first cell |",
        "| x | y<br>more |",
        "",
        "| loose | row |",
    ]


# --- Render, fingerprint, and verify ------------------------------------------------


def test_render_bundle_with_field_ids(tmp_path: Path) -> None:
    metadata = tmp_path / "fields.json"
    metadata.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "fields": [
                        {"name": "Description", "field_id": "description"},
                        {"name": "Use Case(s)", "field_id": "use_cases"},
                        {"name": "No id"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = aha_feature.parse_bundle(FEATURE)

    payload = aha_feature.render_bundle(
        bundle, bundle.link_context(), aha_feature.load_field_ids(str(metadata))
    )

    fields = {entry["name"]: entry for entry in payload["fields"]}
    assert fields["Description"]["field_id"] == "description"
    assert fields["Use Case(s)"]["field_id"] == "use_cases"
    assert fields["Summary"]["field_id"] is None
    assert 'data-callout-box-type="noteBlock"' in fields["Description"]["html"]
    assert (
        'href="https://example.aha.io/initiatives/APP-S-1?reference-class=Initiative'
        '&amp;visible-fields=icon%2Cref"' in (fields["Description"]["html"])
    )
    assert (
        'href="https://example.aha.io/records/PLAT-9?reference-class=Feature'
        '&amp;visible-fields=icon%2Cref"' in (fields["Description"]["html"])
    )
    assert payload["requirements"][0]["ref"] == "APP-12-1"
    assert payload["to_dos"][0]["name"] == "Confirm the entry limit"
    assert payload["fingerprint"] == aha_feature.fingerprint(bundle)


def live_layout_record() -> dict[str, Any]:
    """APP-12 as re-read in HTML before writing, with column widths set in the Aha! editor."""
    sticky = "Editor__table Editor__table--sticky-header"

    def table(header: list[str], widths: list[str]) -> str:
        columns = "".join(f'<col style="width:{width}">' for width in widths)
        cells = "".join(f"<th><p>{cell}</p></th>" for cell in header)
        return (
            f'<table class="{sticky}"><colgroup>{columns}</colgroup>'
            f"<thead><tr>{cells}</tr></thead><tbody></tbody></table>"
        )

    return {
        "id": "APP-12",
        "name": "Release Notes Agent",
        "description": "<p>Intro</p>" + table(["Element", "Definition"], ["18%", "82%"]),
        "custom_fields": [
            {
                "name": "Use Case(s)",
                "type": "note",
                "value": table(["ID", "Use case", "Priority"], ["6%", "70%", "24%"]),
            },
            {"name": "Summary", "type": "note", "value": "<p>No tables.</p>"},
            {"name": "Theme", "type": "string", "value": "<p>Ignored.</p>"},
        ],
        "requirements": {
            "records": [{"id": "APP-12-1", "description": table(["Step", "Owner"], ["30%", "70%"])}]
        },
        "to_dos": {"records": [{"name": "Confirm the entry limit", "body": "Plain text."}]},
    }


def test_render_keeps_live_table_layouts() -> None:
    layouts = aha_feature.record_layouts(live_layout_record())
    bundle = aha_feature.parse_bundle(FEATURE)

    payload = aha_feature.render_bundle(bundle, bundle.link_context(), None, layouts)

    assert sorted(layouts) == [
        ("field", aha_feature.field_key("Description")),
        ("field", aha_feature.field_key("Use Case(s)")),
        ("requirement", "APP-12-1"),
    ]
    fields = {entry["name"]: entry["html"] for entry in payload["fields"]}
    assert (
        '<table class="Editor__table Editor__table--sticky-header"><colgroup>'
        '<col style="width:18%"><col style="width:82%"></colgroup>'
    ) in fields["Description"]
    assert (
        '<col style="width:6%"><col style="width:70%"><col style="width:24%">'
        in (fields["Use Case(s)"])
    )
    assert "<colgroup>" not in fields["Acceptance Criteria"]
    assert [layout.widths for layout in layouts[("requirement", "APP-12-1")].unused()] == [
        ("30%", "70%")
    ]
    plain = aha_feature.render_bundle(bundle, bundle.link_context())
    assert "<colgroup>" not in plain["fields"][0]["html"]
    assert plain["fingerprint"] == payload["fingerprint"]


def test_cli_render_layout_from(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    feature = tmp_path / "feature.md"
    feature.write_text(FEATURE, encoding="utf-8")
    before = write_json(tmp_path / "before.json", live_layout_record())
    payload_path = tmp_path / "payload.json"

    code, _, err = run(
        ["render", str(feature), "--layout-from", str(before), "-o", str(payload_path)], capsys
    )

    assert code == 0
    assert "width:18%" in json.loads(payload_path.read_text(encoding="utf-8"))["fields"][0]["html"]
    assert (
        "warning: requirement 'APP-12-1': no table with header 'step | owner';"
        " its column widths (30%, 70%) and classes will reset"
    ) in err
    other = write_json(tmp_path / "other.json", {**live_layout_record(), "id": "APP-99"})
    code, _, err = run(["render", str(feature), "--layout-from", str(other)], capsys)
    assert code == 2
    assert "APP-12" in err


def reread(bundle: aha_feature.Bundle) -> aha_feature.Bundle:
    """Simulate writing the rendered HTML to Aha! and reading it back."""
    payload = aha_feature.render_bundle(bundle, bundle.link_context())
    fields = {entry["name"]: entry["html"] for entry in payload["fields"]}
    record = aha_record(
        description=fields.pop("Description"),
        custom_fields=[
            {"name": name, "type": "note", "value": html} for name, html in fields.items()
        ],
        requirements=[
            {"id": item["ref"], "name": item["name"], "description": item["html"]}
            for item in payload["requirements"]
        ],
        to_dos=[{"name": item["name"]} for item in payload["to_dos"]],
    )
    return aha_feature.record_to_bundle(record)


def test_fingerprint_survives_the_round_trip_through_aha_html() -> None:
    bundle = aha_feature.parse_bundle(FEATURE)
    numbered = variant("# Requirement: APP-12-2 Approval", "# Requirement: new Approval")

    assert aha_feature.fingerprint(reread(bundle)) == aha_feature.fingerprint(bundle)
    assert aha_feature.fingerprint(aha_feature.parse_bundle(numbered)) == aha_feature.fingerprint(
        bundle
    )
    changed = aha_feature.parse_bundle(variant("within 2 minutes", "within 3 minutes"))
    assert aha_feature.fingerprint(changed) != aha_feature.fingerprint(bundle)
    assert aha_feature.fingerprint(bundle).startswith("sha256:")


def test_visible_text_ignores_formatting() -> None:
    markdown = "### **Title**\n\n> [!NOTE]\n> See [APP-1](https://example.aha.io/records/APP-1) <https://x.io>\n\n| a | b |\n|---|---|\n| c\\|d | e |"

    assert aha_feature.visible_text(markdown) == "Title See APP-1 https://x.io a b c d e"
    assert aha_feature.visible_text("\u201cquoted\u201d \u2013 it\u2019s") == '"quoted" - it\'s'


def test_compare_bundles_reports_matches_changes_and_gaps() -> None:
    expected = aha_feature.parse_bundle(FEATURE + "\n# Settings\n\nignored\n")
    actual = reread(aha_feature.parse_bundle(variant("within 2 minutes", "within 3 minutes")))
    actual.sections = [s for s in actual.sections if s.title != "Business Value"]

    results = {result.label: result for result in aha_feature.compare_bundles(expected, actual)}

    assert results["Field: Description"].status == "ok"
    assert results["Field: Business Value"].status == "missing"
    drafting = results["Requirement: APP-12-1 Drafting"]
    assert drafting.status == "changed"
    assert "expected '2', found '3'" in drafting.detail
    assert (
        results["To-Do: Confirm the entry limit"].detail == "name matched; the re-read has no body"
    )
    assert "Settings" not in results


def test_describe_difference_limits_notes() -> None:
    detail = aha_feature.describe_difference("a b c d e f", "a x c y e z", limit=2)

    assert detail.count("expected") == 2


# --- Export -------------------------------------------------------------------------


def source_for(text: str = FEATURE, slug: str | None = None) -> aha_feature.ExportSource:
    bundle = aha_feature.parse_bundle(text)
    spec = aha_feature.analyze(bundle, "agent")
    return aha_feature.ExportSource(spec, aha_feature.fingerprint(bundle), "2026-01-15", slug)


def test_speckit_export(tmp_path: Path) -> None:
    (tmp_path / "specs" / "004-older").mkdir(parents=True)
    (tmp_path / "specs" / "notes").mkdir()

    files = aha_feature.speckit_files(source_for(), tmp_path, None)

    path, content = next(iter(files.items()))
    assert path == tmp_path / "specs" / "005-release-notes-agent" / "spec.md"
    assert content.startswith("<!-- Exported from Aha! APP-12 Release Notes Agent")
    assert "**Feature Branch**: `005-release-notes-agent`" in content
    assert "### User Story 1 - Draft release notes from merged changes (Priority: P1)" in content
    assert "As a release manager, I want to draft release notes from merged changes" in content
    assert "1. **Given** a release branch with merged pull requests, **When** the agent" in content
    assert (
        "### Edge Cases\n\n- A change has no linked feature.\n- The draft exceeds 200 entries."
        in content
    )
    assert "- **FR-3**: IF a draft has no approval" in content
    assert "### Non-Functional Requirements" in content
    assert "- **SC-001**: AC-1 to AC-3 pass." in content
    assert "## Assumptions" in content
    assert "## Out of Scope" in content
    assert "| FR-1 | P0 | APP-12-1 Drafting | UC-1 | AC-1 |" in content
    assert "## Confirm before building" in content


def test_speckit_export_without_use_cases_or_done(tmp_path: Path) -> None:
    cases = FEATURE.split("# Field: Use Case(s)\n\n")[1].split("\n# Field:")[0]
    text = variant(cases, "\n")
    text = variant("### Definition of Done", "### Exit", text)
    text = variant("- **FR-1 (P0):**", "- **NFR-9 (P0):**", text)

    content = next(iter(aha_feature.speckit_files(source_for(text), tmp_path, 7).values()))

    assert "### User Story 1 - Release Notes Agent (Priority: P3)" in content
    assert "As a release manager, I want an agent that drafts release notes" in content
    assert "[NEEDS CLARIFICATION: Aha! has no Definition of Done]" in content


def test_openspec_export(tmp_path: Path) -> None:
    files, warnings = aha_feature.openspec_files(source_for(), tmp_path, None, None, False)

    base = tmp_path / "openspec" / "changes" / "add-release-notes-agent"
    assert set(files) == {
        base / ".openspec.yaml",
        base / "proposal.md",
        base / "specs" / "release-notes-agent" / "spec.md",
    }
    assert warnings == []
    metadata = files[base / ".openspec.yaml"]
    assert metadata.startswith("schema: spec-driven\ncreated: 2026-01-15\nx-aha-record: APP-12\n")
    proposal = files[base / "proposal.md"]
    assert "- Drafting: Draft one note per merged change. (APP-12-1; FR-1, FR-2, NFR-1)" in proposal
    assert (
        "- `release-notes-agent`: An agent that drafts release notes from merged changes"
        in proposal
    )
    delta = files[base / "specs" / "release-notes-agent" / "spec.md"]
    assert (
        "## Purpose\n\nAn agent that drafts release notes from merged changes, for a release manager."
        in delta
    )
    assert "### Requirement: FR-3 Approval and audit\nIF a draft has no approval" in delta
    assert "#### Scenario: FR-3 as specified\n- **WHEN** a draft has no approval\n" in delta
    assert "#### Scenario: AC-3 Audit\n- **GIVEN** any draft\n- **WHEN** it is audited\n" in delta
    assert "MODIFIED" not in delta


def test_openspec_export_for_an_existing_capability(tmp_path: Path) -> None:
    text = variant("**FR-2 (P0):**", "**FR-2 (P0, MODIFIED):**")
    text = variant("**FR-3 (P0):**", "**FR-3 (P0, REMOVED):**", text)
    text = variant("Covers: UC-1. Verified by AC-1.", "Covers: UC-1.", text)
    long_statement = "The agent SHALL keep " + "every detail " * 45 + "in the log."
    text = variant(
        "The agent SHALL record every read and write with identity and time in the audit log.",
        long_statement,
        text,
    )

    files, warnings = aha_feature.openspec_files(
        source_for(text, "notes"), tmp_path, "change-notes", "release/notes", True
    )
    _, new_files_warnings = aha_feature.openspec_files(
        source_for(text), tmp_path, None, None, False
    )

    delta = files[
        tmp_path
        / "openspec"
        / "changes"
        / "change-notes"
        / "specs"
        / "release"
        / "notes"
        / "spec.md"
    ]
    proposal = files[tmp_path / "openspec" / "changes" / "change-notes" / "proposal.md"]
    assert "## Purpose" not in delta
    assert "## MODIFIED Requirements\n\n### Requirement: FR-2 Drafting" in delta
    assert (
        "## REMOVED Requirements\n\n### Requirement: FR-3 Approval and audit\n**Reason**:" in delta
    )
    assert "#### Scenario: FR-2 holds" in delta
    assert "### New Capabilities\n\n\n### Modified Capabilities\n\n- `release/notes`:" in proposal
    assert "- **BREAKING** Approval and audit" in proposal
    assert any("over 500 characters" in warning for warning in warnings)
    assert any("no scenario" in warning for warning in warnings)
    assert any("--existing-capability" in warning for warning in new_files_warnings)


def test_kiro_export(tmp_path: Path) -> None:
    files = aha_feature.kiro_files(source_for(), tmp_path)

    path, content = next(iter(files.items()))
    assert path == tmp_path / ".kiro" / "specs" / "release-notes-agent" / "requirements.md"
    assert "# Requirements Document\n\n## Introduction" in content
    assert "### Out of scope\n\n- Publishing notes." in content
    assert "### Requirement 2: Approval and audit" in content
    assert (
        "**User Story:** As a release manager, I want to route the draft for approval, so that"
        in content
    )
    assert "1. IF a draft has no approval, THEN the agent SHALL NOT send it" in content
    assert "(FR-4, P1)" in content
    assert "- AC-2 Approval before publishing: **Given** a draft" in content


def test_kiro_export_handles_sparse_requirements(tmp_path: Path) -> None:
    text = (
        FEATURE.split("# Requirement: APP-12-2")[0] + "# Requirement: new Extra\n\nNo statements.\n"
    )
    text = variant("**NFR-1 (P1):**", "**NFR-1:**", text)
    text = variant("**As a** release manager", "**As an** operator", text)

    content = next(iter(aha_feature.kiro_files(source_for(text), tmp_path).values()))

    assert "**User Story:** As an operator, I want an agent that drafts" in content
    assert "1. [Add EARS statements to this requirement in Aha!]" in content
    assert "(NFR-1)" in content


def test_git_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = init_repo(tmp_path / "repo")

    assert aha_feature.git_root(repo) is not None
    assert aha_feature.git_root(tmp_path) is None

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("git not found")

    monkeypatch.setattr("aha_feature.subprocess.run", broken)
    assert aha_feature.git_root(repo) is None


# --- Command line -------------------------------------------------------------------


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = aha_feature.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_bundle_and_lint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dump = write_json(tmp_path / "dump.json", aha_record())
    output = tmp_path / "bundle.md"

    assert run(["bundle", str(dump), "-o", str(output)], capsys)[0] == 0
    assert output.read_text(encoding="utf-8").startswith("---\nrecord: APP-12\n")
    code, out, _ = run(["bundle", str(dump)], capsys)
    assert code == 0
    assert "# Requirement: APP-12-1 Drafting" in out

    feature = tmp_path / "feature.md"
    feature.write_text(FEATURE, encoding="utf-8")
    assert run(["lint", str(feature)], capsys)[0] == 0
    code, out, _ = run(["lint", str(output), "--gate", "elaborated", "--format", "json"], capsys)
    report = json.loads(out)
    assert code == 1
    assert report["summary"]["error"] > 0
    warned = tmp_path / "warned.md"
    warned.write_text(variant("**FR-2 (P0):**", "**FR-2:**"), encoding="utf-8")
    assert run(["lint", str(warned)], capsys)[0] == 0
    assert run(["lint", str(warned), "--fail-on", "warning"], capsys)[0] == 1
    code, out, _ = run(["lint", "--list-rules"], capsys)
    assert code == 0
    assert "EARS002" in out
    assert run(["lint"], capsys)[0] == 2


def test_cli_render_fingerprint_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feature = tmp_path / "feature.md"
    feature.write_text(FEATURE, encoding="utf-8")
    metadata = tmp_path / "fields.json"
    metadata.write_text(
        json.dumps({"fields": [{"name": "Description", "field_id": "description"}]}),
        encoding="utf-8",
    )
    payload_path = tmp_path / "payload.json"

    code, _, err = run(
        ["render", str(feature), "-o", str(payload_path), "--fields-metadata", str(metadata)],
        capsys,
    )
    assert code == 0
    assert "no field_id for 'Summary'" in err
    assert json.loads(payload_path.read_text(encoding="utf-8"))["record"] == "APP-12"

    code, out, _ = run(["fingerprint", str(feature)], capsys)
    assert out.strip() == aha_feature.fingerprint(aha_feature.parse_bundle(FEATURE))
    code, out, _ = run(["fingerprint", str(feature), "--format", "json"], capsys)
    assert json.loads(out)["parts"][0]["part"] == "field:Description"

    good = write_json(tmp_path / "good.json", aha_record())
    monkeypatch.setattr("sys.stdin", io.StringIO(good.read_text(encoding="utf-8")))
    code, out, _ = run(["fingerprint", "-"], capsys)
    assert code == 0

    simple = tmp_path / "simple.md"
    simple.write_text(
        "---\nrecord: APP-12\n---\n\n# Requirement: APP-12-1 Drafting\n\nDraft notes.\n",
        encoding="utf-8",
    )
    code, out, _ = run(["verify", str(simple), str(good)], capsys)
    assert code == 0
    assert "OK      Requirement: APP-12-1 Drafting" in out
    assert "1 of 1 sections match." in out
    code, out, _ = run(["verify", str(feature), str(good)], capsys)
    assert code == 1


def test_cli_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    feature = tmp_path / "feature.md"
    feature.write_text(FEATURE, encoding="utf-8")
    repo = init_repo(tmp_path / "repo")
    plain = tmp_path / "plain"
    plain.mkdir()

    code, out, _ = run(
        ["export", str(feature), "--format", "kiro", "--repo", str(repo), "--date", "2026-01-15"],
        capsys,
    )
    assert code == 0
    assert "Nothing was committed." in out
    written = repo / ".kiro" / "specs" / "release-notes-agent" / "requirements.md"
    assert "on 2026-01-15" in written.read_text(encoding="utf-8")
    code, _, err = run(["export", str(feature), "--format", "kiro", "--repo", str(repo)], capsys)
    assert code == 2
    assert "Use --force" in err
    assert (
        run(["export", str(feature), "--format", "kiro", "--repo", str(repo), "--force"], capsys)[0]
        == 0
    )
    code, out, _ = run(
        ["export", str(feature), "--format", "speckit", "--repo", str(repo), "--dry-run"], capsys
    )
    assert code == 0
    assert "==> " in out
    assert not (repo / "specs").exists()
    code, _, err = run(
        ["export", str(feature), "--format", "openspec", "--repo", str(repo), "--slug", "notes"],
        capsys,
    )
    assert code == 0
    assert (repo / "openspec" / "changes" / "add-notes" / "proposal.md").exists()

    draft = tmp_path / "draft.md"
    draft.write_text(variant("The agent SHALL link", "The agent should link"), encoding="utf-8")
    code, _, err = run(
        ["export", str(draft), "--format", "openspec", "--repo", str(repo), "--dry-run"], capsys
    )
    assert code == 0
    assert "export it as a draft only" in err

    code, _, err = run(["export", str(feature), "--format", "kiro", "--repo", str(plain)], capsys)
    assert code == 2
    assert "not inside a git work tree" in err
    code, _, err = run(
        ["export", str(feature), "--format", "kiro", "--repo", str(tmp_path / "missing")], capsys
    )
    assert code == 2
    assert "not a directory" in err


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(["lint", str(tmp_path / "missing.md")], capsys)

    assert code == 2
    assert err.startswith("error:")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert run(["bundle", str(bad)], capsys)[0] == 2
    assert aha_html.markdown_to_html("x") == "<p>x</p>"


# --- Elicitation --------------------------------------------------------------------


def statuses(text: str) -> dict[str, str]:
    bundle = aha_feature.parse_bundle(text)
    return {d.name: d.status for d in aha_feature.assess_matrix(bundle, "agent")}


def test_matrix_reports_a_complete_feature() -> None:
    bundle = aha_feature.parse_bundle(FEATURE)

    dimensions = aha_feature.assess_matrix(bundle, "agent")
    report = aha_feature.format_matrix(bundle, dimensions)

    assert {d.status for d in dimensions} == {"complete"}
    assert dimensions[0].as_dict()["found"][0] == "user story for release manager"
    assert report.splitlines()[0] == (
        "APP-12 Release Notes Agent: elicitation matrix (5 complete, 0 partial, 0 missing)"
    )
    assert report.splitlines()[-1] == "All five dimensions are answered."


MATRIX_CASES = [
    ("Not yet measured: time", "{{baseline}}", "Value & Persona", "partial"),
    (
        (
            "Release managers collate notes by hand from pull requests and features, and notes miss "
            "changes. Not yet measured: time spent per release and notes corrected after publishing."
        ),
        "{{problem}}",
        "Value & Persona",
        "partial",
    ),
    (
        "Publishing notes. Marketing copy. Translations.",
        "Publishing notes.",
        "Scope & Boundaries",
        "partial",
    ),
    ("**NFR-1 (P1):**", "**FR-9 (P1):**", "Tech & Data", "partial"),
    (
        "- **FR-3 (P0):** IF a draft has no approval, THEN the agent SHALL NOT send",
        "- **FR-3 (P0):** The agent SHALL send",
        "Edge Cases",
        "complete",
    ),
    ("at least 50% less time", "less time", "Success Metrics", "complete"),
]


@pytest.mark.parametrize(("old", "new", "dimension", "status"), MATRIX_CASES)
def test_matrix_dimensions(old: str, new: str, dimension: str, status: str) -> None:
    assert statuses(variant(old, new))[dimension] == status


def test_matrix_finds_missing_dimensions() -> None:
    sparse = (
        "---\nrecord: APP-30\nname: Export\n---\n\n# Field: Description\n\n"
        "Exports invoices.\n\n# Field: Acceptance Criteria\n\n### AC-1. Export\n\n- **Given** x\n"
    )

    found = statuses(sparse)
    report = aha_feature.format_matrix(
        aha_feature.parse_bundle(sparse),
        aha_feature.assess_matrix(aha_feature.parse_bundle(sparse), "product"),
    )

    assert set(found.values()) == {"missing"}
    assert "Elicit next: 1. Value & Persona, 2. Scope & Boundaries" in report
    assert "fill: Definition of Done, Business Value targets, Goals and Key results" in report


def test_matrix_edge_cases_without_failure_modes() -> None:
    text = variant(
        "- **FR-3 (P0):** IF a draft has no approval, THEN the agent SHALL NOT send",
        "- **FR-3 (P0):** The agent SHALL send",
    )
    text = variant("| Stops and escalates when |", "| Escalation path |", text)
    text = variant("| Guardrails |", "| Rules |", text)
    text = variant("an unapproved draft never does", "it is shown", text)

    assert statuses(text)["Edge Cases"] == "partial"


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ("", ("unknown", "read the record's initiative, goals, and key results")),
        (
            "initiative: APP-S-1 Automation\ngoals: \nkey-results: \n",
            ("linked", "initiative APP-S-1 Automation"),
        ),
        (
            "initiative: \ngoals: \n",
            ("not linked", "ask for a goal or initiative, or confirm it stays unlinked"),
        ),
        (
            "alignment: unlinked (confirmed by J. Doe)\n",
            ("confirmed unlinked", "unlinked (confirmed by J. Doe)"),
        ),
    ],
)
def test_goal_alignment(meta: str, expected: tuple[str, str]) -> None:
    bundle = aha_feature.parse_bundle(variant("profile: agent\n", f"profile: agent\n{meta}"))

    assert aha_feature.goal_alignment(bundle) == expected


def test_record_to_bundle_records_goal_alignment() -> None:
    linked = aha_feature.record_to_bundle(
        aha_record(goals=[{"id": "APP-G-1", "name": "Adoption"}, {}], key_results=[])
    )
    unlinked = aha_feature.record_to_bundle(aha_record(initiative=None))

    assert linked.meta["initiative"] == "APP-S-1 Automation"
    assert linked.meta["goals"] == "APP-G-1 Adoption"
    assert linked.meta["key-results"] == ""
    assert aha_feature.goal_alignment(unlinked)[0] == "not linked"


ELICITATION = """
# Elicitation

| # | Dimension | Status | Answers and sources |
|---|---|---|---|
| 1 | Value & Persona | complete | Release manager; from the request |
"""


def test_elicitation_section_is_a_working_section() -> None:
    bundle = aha_feature.parse_bundle(FEATURE + ELICITATION)

    payload = aha_feature.render_bundle(bundle, bundle.link_context())

    assert bundle.sections[-1].label == "Elicitation"
    assert "# Elicitation" in aha_feature.format_bundle(bundle)
    assert payload["elicitation"].startswith("| # | Dimension |")
    assert "Elicitation" not in [entry["name"] for entry in payload["fields"]]
    assert aha_feature.fingerprint(bundle) == aha_feature.fingerprint(
        aha_feature.parse_bundle(FEATURE)
    )
    assert all(
        r.label != "Elicitation" for r in aha_feature.compare_bundles(bundle, reread(bundle))
    )
    assert aha_feature.lint(bundle, "ready") == []


def test_elicitation_record_must_match_the_matrix() -> None:
    stale = aha_feature.parse_bundle(
        FEATURE
        + ELICITATION
        + "| 2 | Scope & Boundaries | deferred | Workflow open |\n"
        + "| 4 | Edge Cases | missing (round 1) | - |\n"
    )
    reordered = aha_feature.parse_bundle(
        FEATURE + "\n# Elicitation\n\n| # | Status | Dimension |\n|---|---|---|\n"
        "| 5 | Partial; targets open | Success Metrics |\n"
    )
    template = TEMPLATE.read_text(encoding="utf-8")
    overclaimed = aha_feature.parse_bundle(
        template.replace("{{answered, deferred, or missing}}", "answered (user, round 1)")
    )

    stale_findings = [f for f in aha_feature.lint(stale) if f.rule == "ELC001"]
    reordered_findings = [f for f in aha_feature.lint(reordered, "seed") if f.rule == "ELC001"]
    overclaimed_findings = [f for f in aha_feature.lint(overclaimed) if f.rule == "ELC001"]

    assert aha_feature.elicitation_statuses(stale) == {
        1: "complete",
        2: "deferred",
        4: "missing (round 1)",
    }
    assert [(f.severity, f.where) for f in stale_findings] == [("warning", "Elicitation")]
    assert "'missing (round 1)' for 4. Edge Cases" in stale_findings[0].message
    assert "finds it complete" in stale_findings[0].message
    assert [f.severity for f in reordered_findings] == ["info"]
    assert "5. Success Metrics" in reordered_findings[0].message
    assert len(overclaimed_findings) == 1
    assert "finds it missing" in overclaimed_findings[0].message
    assert aha_feature.elicitation_statuses(aha_feature.parse_bundle(FEATURE)) == {}


def test_placeholders_fail_lint_and_count_as_empty() -> None:
    summary = (
        "Release notes are assembled by hand from merged changes. The Release Notes Agent drafts them "
        "from the changes themselves, links each note to its change, and leaves approval and "
        "publishing with people."
    )
    text = variant(summary, "{{One paragraph: problem, what it does, what stays with people.}}")

    found = rules(text)

    assert found["WRT004"] == "error"
    assert found["STR006"] == "warning"
    assert not aha_feature.filled("{{who}} {{why}}")
    assert aha_feature.filled("{{who}} release managers")


def test_cli_matrix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    feature = tmp_path / "feature.md"
    feature.write_text(FEATURE, encoding="utf-8")
    dump = write_json(tmp_path / "dump.json", aha_record())

    code, out, _ = run(["matrix", str(feature)], capsys)
    assert code == 0
    assert "All five dimensions are answered." in out
    code, out, _ = run(["matrix", str(dump), "--format", "json", "--profile", "product"], capsys)
    report = json.loads(out)
    assert code == 1
    assert report["goal_alignment"] == {
        "status": "linked",
        "detail": "initiative APP-S-1 Automation",
    }
    assert report["dimensions"][0]["name"] == "Value & Persona"


TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "aha-feature"
    / "skills"
    / "aha-feature"
    / "assets"
    / "feature-bundle-template.md"
)


def test_template_is_a_valid_unanswered_bundle() -> None:
    bundle = aha_feature.parse_bundle(TEMPLATE.read_text(encoding="utf-8"))

    dimensions = aha_feature.assess_matrix(bundle, "agent")
    found = rules(TEMPLATE.read_text(encoding="utf-8"))

    assert bundle.sections[0].label == "Elicitation"
    assert [s.title for s in bundle.requirements()][1] == "Security, audit, and limits"
    assert {d.status for d in dimensions} == {"missing"}
    assert aha_feature.goal_alignment(bundle)[0] == "not linked"
    assert found["WRT004"] == "error"
    assert "EARS002" not in found


def test_bulleted_workflow_counts() -> None:
    numbered = "### Workflow\n\n1. Collect the merged changes for the release.\n2. Draft one note per change.\n3. Open a review request. A person approves."
    bulleted = "### Workflow\n\n- Collect changes.\n- Draft notes.\n\n### Next"

    assert statuses(variant(numbered, bulleted))["Scope & Boundaries"] == "complete"
    assert (
        statuses(variant(numbered, "### Workflow\n\n### Next"))["Scope & Boundaries"] == "partial"
    )
    assert aha_feature.answered("Ready")
    assert not aha_feature.answered("Ready {{when}}")


# --- Regressions found by testing on real records ----------------------------------


def test_defined_tier_terms_are_not_overclaims() -> None:
    text = variant(
        "| Autonomy | Drafting runs without approval.",
        "| Autonomy | T1 Read-only: drafts only. T3 Autonomous: publishes allowlisted notes. "
        "Drafting runs without approval.",
    )
    text = variant("### AC-3. Audit", "### AC-3. Autonomous publishing audit", text)
    adverb = variant("leaves approval and publishing with people", "publishes autonomously", text)
    listed = variant("profile: agent\n", "profile: agent\ndefined-terms: quickly\n", text)
    listed = variant("SHALL link each note", "SHALL quickly link each note", listed)

    assert "WRT001" not in rules(text)
    assert rules(adverb)["WRT001"] == "warning"
    assert "EARS008" not in rules(listed)
    assert aha_feature.defined_terms(aha_feature.parse_bundle(listed)) >= {
        "read-only",
        "autonomous",
        "quickly",
    }


def test_decision_due_dates_are_allowed() -> None:
    due = variant(
        "Draft one note per merged change.",
        "Draft one note per merged change, as decided under SD-3 (due 6 Nov 2026).",
    )
    delivery = variant("Draft one note per merged change.", "Draft notes by 6 Nov 2026.")

    assert "WRT002" not in rules(due)
    assert rules(delivery)["WRT002"] == "warning"


@pytest.mark.parametrize(
    "label", ["Exit criteria (targets to confirm)", "Success criteria", "Done when"]
)
def test_definition_of_done_synonyms(label: str) -> None:
    text = variant("### Definition of Done", f"### {label}")

    assert "STR005" not in rules(text)
    assert statuses(text)["Success Metrics"] == "complete"


def test_workflow_steps_with_bold_lead_ins_count() -> None:
    text = variant(
        "1. Collect the merged changes for the release.",
        "1. **On release:** collect the merged changes for the release.",
    )

    assert statuses(text)["Scope & Boundaries"] == "complete"
