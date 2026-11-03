#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Lint, render, verify, and export Aha! feature specifications.

A bundle is a temporary Markdown file that holds the proposed content of one
Aha! feature: its text fields, its requirements, and its To-Dos. Aha! stays the
system of record. Bundles live in a temporary directory only while a change is
prepared, reviewed, and applied.

Subcommands:
  bundle       Turn an Aha! read_records JSON dump into a bundle.
  lint         Check EARS statements, traceability, gates, and writing rules.
  matrix       Score the five elicitation dimensions, to know what to ask before writing.
  render       Turn a bundle into Aha! Editor HTML payloads for manage_record.
  fingerprint  Hash the specification content so an approval binds to one version.
  verify       Compare an applied bundle with the record as re-read from Aha!.
  export       On request only: write Spec Kit, OpenSpec, or Kiro files into a git repository.

Examples:
  uv run aha-feature/scripts/aha_feature.py bundle "$WORK/APP-12.json" -o "$WORK/APP-12.md"
  uv run aha-feature/scripts/aha_feature.py lint "$WORK/APP-12.md" --gate elaborated
  uv run aha-feature/scripts/aha_feature.py render "$WORK/APP-12.md" --fields-metadata "$WORK/fields.json" --layout-from "$WORK/before.json"
  uv run aha-feature/scripts/aha_feature.py export "$WORK/APP-12.md" --format openspec --repo ~/src/app
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aha_html

GATES = ("seed", "elaborated", "ready")
PROFILES = ("agent", "platform", "product")
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}

FIELD_ORDER = (
    "Description",
    "Summary",
    "Business Problem",
    "Business Value",
    "Use Case(s)",
    "Acceptance Criteria",
    "Dependencies (upstream)",
    "Dependencies (downstream)",
    "Differentiator Justification",
    "Other important information",
)
SPEC_FIELDS = tuple(name for name in FIELD_ORDER if name != "Differentiator Justification")
TEXT_FIELD_TYPES = frozenset({"html", "note", "text"})

# Fields each gate expects, with the severity at the elaborated and ready gates.
GATE_FIELDS = {
    "Summary": ("warning", "error"),
    "Business Problem": ("warning", "error"),
    "Business Value": ("warning", "error"),
    "Use Case(s)": ("error", "error"),
    "Acceptance Criteria": ("error", "error"),
    "Dependencies (upstream)": ("warning", "error"),
}

# Rows the definition table needs, by feature profile.
PROFILE_ROWS = {
    "agent": (
        "Role",
        "Triggers",
        "Context",
        "Read actions",
        "Write actions",
        "Autonomy",
        "Guardrails",
        "Stops and escalates when",
        "Outputs",
        "Handoffs",
        "Out of scope",
    ),
    "platform": ("Role", "Consumers", "Capabilities", "Guardrails", "Out of scope"),
    "product": ("Users", "Entry points", "Behavior", "Permissions", "Out of scope"),
}
SEED_ROWS = {
    "agent": ("Role", "Out of scope"),
    "platform": ("Role", "Out of scope"),
    "product": ("Users", "Out of scope"),
}
ROW_ALIASES = {
    "stops and escalates when": ("stops when", "escalates when", "stop conditions"),
    "out of scope": ("non-goals", "not in scope", "out-of-scope"),
    "read actions": ("reads",),
    "write actions": ("writes",),
    "users": ("personas", "user roles"),
    "entry points": ("triggers",),
    "behavior": ("behaviour", "scope"),
    "permissions": ("access", "access control"),
    "consumers": ("callers",),
}
OUT_OF_SCOPE_NAMES = ("out of scope", "non-goals", "not in scope", "out-of-scope")
DEFINITION_HEADERS = frozenset({"element", "aspect", "attribute", "item"})

RULES = {
    "STR001": "Description has a user story: As a <role>, I want <capability>, so that <value>.",
    "STR002": "Description has a definition table (Element | Definition).",
    "STR003": "The definition table has the rows the profile needs.",
    "STR004": "Out of scope lists at least three things the feature won't do.",
    "STR005": "Description has a Definition of Done (or exit or success criteria).",
    "STR006": "The fields the gate needs aren't empty.",
    "STR007": "The feature has requirements.",
    "STR008": "Business Value targets have a baseline in Business Problem.",
    "STR009": "Summary is one short paragraph (1,200 characters or fewer).",
    "STR010": "Requirements cover security and measurable performance (and accessibility for UI).",
    "EARS001": "Each requirement has EARS statements with FR or NFR IDs.",
    "EARS002": "Each statement has SHALL.",
    "EARS003": "EARS keywords are in capitals (WHEN, WHILE, IF, THEN, WHERE, SHALL).",
    "EARS005": "IF has THEN.",
    "EARS006": "Clauses are in EARS order: WHERE, WHILE, WHEN or IF, then the response.",
    "EARS007": "Each statement has one SHALL.",
    "EARS008": "Statements avoid vague terms.",
    "EARS009": "Each statement has a priority (P0, P1, or P2).",
    "EARS010": "Statement IDs are unique.",
    "EARS011": "Statement markers are a priority and optionally ADDED, MODIFIED, or REMOVED.",
    "TRC001": "Each requirement ends with a Covers line.",
    "TRC002": "Each requirement has a Verified by line.",
    "TRC003": "Covers cites only defined use cases.",
    "TRC004": "Verified by cites only defined acceptance criteria.",
    "TRC005": "Every use case is covered by a requirement.",
    "TRC006": "Every acceptance criterion verifies a requirement.",
    "TRC007": "Covers doesn't cite an external PRD.",
    "TRC008": "The Definition of Done AC range matches the acceptance criteria.",
    "TRC009": "Covers cites only FR and NFR IDs that exist.",
    "AC001": "Each acceptance criterion has Given, When, and Then.",
    "AC002": "Acceptance criterion IDs are unique and sequential.",
    "AC003": "Acceptance Criteria uses AC-n headings.",
    "AC004": "Acceptance criteria avoid vague terms.",
    "UC001": "Use case IDs are unique.",
    "UC002": "Each use case has a priority.",
    "UC003": "Use Case(s) uses UC-n IDs.",
    "WRT001": "Text avoids overclaims.",
    "WRT002": "Text names records, not releases or dates.",
    "WRT003": "Open markers (to confirm, TBD) are resolved or tracked.",
    "WRT004": "Template placeholders ({{...}}) are filled in.",
    "ELC001": "The elicitation record agrees with the matrix.",
}


def _terms(terms: Iterable[str]) -> re.Pattern[str]:
    alternatives = sorted((re.escape(term) for term in terms), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])", re.IGNORECASE)


VAGUE_RE = _terms(
    (
        "fast",
        "quick",
        "quickly",
        "slow",
        "user-friendly",
        "easy",
        "easily",
        "intuitive",
        "simple",
        "simply",
        "robust",
        "efficient",
        "efficiently",
        "appropriate",
        "appropriately",
        "adequate",
        "adequately",
        "reasonable",
        "reasonably",
        "gracefully",
        "flexible",
        "sufficient",
        "sufficiently",
        "optimal",
        "optimally",
        "as needed",
        "as appropriate",
        "if possible",
        "where possible",
        "as soon as possible",
        "etc",
        "and so on",
        "and/or",
        "various",
        "normally",
        "usually",
        "typically",
        "scalable",
    )
)
OVERCLAIM_RE = _terms(
    (
        "autonomous",
        "autonomously",
        "seamless",
        "seamlessly",
        "eliminate",
        "eliminates",
        "instant",
        "instantly",
        "instantaneous",
        "drastically",
        "dramatically",
        "revolutionary",
        "revolutionize",
        "game-changing",
        "effortless",
        "effortlessly",
        "zero-touch",
        "fully automated",
        "guarantee",
        "guarantees",
        "guaranteed",
        "best-in-class",
        "world-class",
        "cutting-edge",
        "unparalleled",
        "unmatched",
        "magically",
    )
)
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
TIMING_RE = re.compile(
    r"\b20\d\d-\d\d-\d\d\b"
    rf"|\b{_MONTHS}\.? (?:\d{{1,2}}, )?20\d\d\b"
    rf"|\b\d{{1,2}} {_MONTHS}\.? 20\d\d\b"
    r"|\bQ[1-4] ?(?:FY)?'?\d{2,4}\b"
    r"|\bFY ?'?\d{2,4}\b"
    r"|\b\d{4}-(?:REL|Preview)\b"
)
OPEN_MARKER_RE = re.compile(
    r"\bto confirm\b|\bto be (?:confirmed|determined|decided)\b|\bTB[CD]\b"
    r"|NEEDS CLARIFICATION|\?\?",
    re.IGNORECASE,
)
WEAK_MODAL_RE = re.compile(r"\b(should|may|might|could|will|must|can)\b", re.IGNORECASE)
SHALL_RE = re.compile(r"\bSHALL\b")
TARGET_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\bat (?:least|most) \d|\b\d+x\b|\bzero\b", re.IGNORECASE)
BASELINE_RE = re.compile(
    r"\bbaselines?\b|\bnot (?:yet )?measured\b|\bmeasured\b|\btoday\b|\bcurrently\b", re.IGNORECASE
)
SECURITY_RE = re.compile(
    r"\bsecur|\bauthenticat|\bauthoriz|\bencrypt|\bsecrets?\b|\bleast[- ]privilege|\baudit",
    re.IGNORECASE,
)
MEASURE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:ms|milliseconds?|s|sec|seconds?|minutes?|hours?|%|rps|requests"
    r"|users|records|items|MB|GB|lines)\b|\bp9[59]\b",
    re.IGNORECASE,
)
ACCESSIBILITY_RE = re.compile(r"\bWCAG\b|\baccessib", re.IGNORECASE)

DELIMITER_RE = re.compile(
    r"^#[ \t]+(?P<kind>Field|Requirement|To-?Do|Elicitation|(?:Record[ \t]+)?Settings)\b"
    r"[ \t]*:?[ \t]*"
    r"(?P<title>.*?)[ \t]*$",
    re.IGNORECASE,
)
FENCE_LINE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
REQUIREMENT_REF_RE = re.compile(r"^(?P<ref>[A-Z][A-Z0-9]*-\d+-\d+)\s+(?P<name>.+)$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(?P<rest>.+)$")
STATEMENT_RE = re.compile(
    r"^(?P<id>N?FR-\d+)\s*(?:\((?P<meta>[^)]*)\))?\s*[:.\u2013\u2014-]?\s*(?P<text>.*)$"
)
ID_RE = re.compile(
    r"(?<![\w-])(?P<kind>UC|AC|FR|NFR)-(?P<start>\d+)"
    r"(?:\s*(?:to|through|\u2013|\u2014)\s*(?:(?P=kind)-)?(?P<end>\d+))?"
)
COVERS_RE = re.compile(
    r"\bCovers\s*:\s*(?P<covers>.*?)(?:\bVerified\s+by\b\s*:?\s*(?P<verified>.*))?$",
    re.IGNORECASE,
)
VERIFIED_RE = re.compile(r"^\W*Verified\s+by\b\s*:?\s*(?P<verified>.*)$", re.IGNORECASE)
AC_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+(?:\*\*)?|\*\*)\s*AC-(?P<num>\d+)\b\s*[.:)\u2013\u2014-]?\s*"
    r"(?P<title>.*?)\s*(?:\*\*)?\s*$"
)
CLAUSE_RE = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])?\s*(?P<kw>given|when|then|and|but)\b\s*[:,]?\s*(?P<text>.*)$",
    re.IGNORECASE,
)
USE_CASE_LINE_RE = re.compile(
    r"^(?:[-*+]\s+|#{1,6}\s+)?(?:\*\*)?UC-(?P<num>\d+)(?:\*\*)?\s*[.:)\u2013\u2014-]?\s*(?P<text>.*)$"
)
PRIORITY_RE = re.compile(r"\bP([0-3])\b")
DOD_RANGE_RE = re.compile(r"\bAC-(\d+)\s*(?:to|through|\u2013|\u2014|-)\s*(?:AC-)?(\d+)")
USER_STORY_RE = re.compile(
    r"\bAs an?\s+(?P<persona>.+?),?\s+I want\s+(?P<want>.+?),?\s+so that\s+(?P<so>.+?)"
    r"(?:\.(?=\s|$)|$)",
    re.IGNORECASE | re.DOTALL,
)
EARS_CLAUSE_RE = re.compile(
    r"^(?:WHEN|WHILE|IF|WHERE)\s+(?P<condition>.+?),\s*(?:THEN\s+)?"
    r"(?P<response>(?:the|The|THE)\s.+?\bSHALL\b.*)$",
    re.DOTALL,
)
REFERENCE_QUERY_RE = re.compile(r"\?reference-class=[^)\s\"']*")
MENTION_LINK_RE = re.compile(r"\[(?P<ref>[A-Z][A-Z0-9]*-[A-Z0-9-]+)\]\((?P<url>https?://[^)\s]+)\)")
AHA_URL_PREFIX_RE = re.compile(r"https?://[\w.-]+\.aha\.io/[\w/]+?/([A-Z][A-Z0-9]*)-")
SPACER_LINE_RE = re.compile(r"^\s*\\+\s*$")
# Tier or level names a record defines, such as "T3 Autonomous", aren't overclaims.
TIER_TERM_RE = re.compile(r"\bT\d\s+([A-Z][A-Za-z-]+)")
# A date right after a decision reference, such as "SD-18 (due 6 Nov 2026)", is a due date.
DECISION_REF_RE = re.compile(r"\b(?:SD|OQ)-\d+\b")
DONE_LABELS = ("definition of done", "exit criteria", "success criteria", "done when")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]*\}\}")
FAILURE_RE = re.compile(
    r"\b(?:fail\w*|errors?|invalid|reject\w*|denied|timeouts?|exceed\w*|missing|unavailable"
    r"|conflict\w*|duplicates?|retr(?:y|ies)|limits?|stops?|escalat\w*)\b",
    re.IGNORECASE,
)
PRIORITY_TOKENS = frozenset({"P0", "P1", "P2", "P3", "MUST", "SHOULD", "COULD", "WONT", "WON'T"})
CHANGE_TOKENS = frozenset({"ADDED", "MODIFIED", "REMOVED"})
IGNORED_TOKENS = frozenset({"HAVE", "PRIORITY"})
QUOTE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)


def field_key(name: str) -> str:
    """Normalize a field name so 'Use Case(s)' and 'Use Cases' compare equal."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def filled(text: str) -> bool:
    """Return whether text has content beyond template placeholders."""
    return re.search(r"\w", PLACEHOLDER_RE.sub("", text)) is not None


@dataclass
class Section:
    """One part of a bundle: a field, a requirement, a To-Do, or record settings."""

    kind: str
    title: str
    body: str = ""
    ref: str | None = None
    line: int = 0
    body_line: int = 0

    @property
    def label(self) -> str:
        if self.kind == "field":
            return f"Field: {self.title}"
        if self.kind == "requirement":
            return (
                f"Requirement: {self.ref} {self.title}"
                if self.ref
                else f"Requirement: {self.title}"
            )
        if self.kind == "todo":
            return f"To-Do: {self.title}"
        if self.kind == "elicitation":
            return "Elicitation"
        return "Settings"

    def heading(self) -> str:
        if self.kind == "field":
            return f"# Field: {self.title}"
        if self.kind == "requirement":
            return f"# Requirement: {self.ref or 'new'} {self.title}"
        if self.kind == "todo":
            return f"# To-Do: {self.title}"
        if self.kind == "elicitation":
            return "# Elicitation"
        return "# Settings"


@dataclass
class Bundle:
    """The proposed content of one Aha! feature."""

    meta: dict[str, str] = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)

    @property
    def record(self) -> str:
        return self.meta.get("record", "")

    @property
    def name(self) -> str:
        return self.meta.get("name", "")

    def get_field(self, name: str) -> Section | None:
        key = field_key(name)
        return next(
            (s for s in self.sections if s.kind == "field" and field_key(s.title) == key), None
        )

    def field_text(self, name: str) -> str:
        section = self.get_field(name)
        return section.body if section is not None else ""

    def fields(self) -> list[Section]:
        return [section for section in self.sections if section.kind == "field"]

    def requirements(self) -> list[Section]:
        return [section for section in self.sections if section.kind == "requirement"]

    def todos(self) -> list[Section]:
        return [section for section in self.sections if section.kind == "todo"]

    def elicitation(self) -> str:
        section = next((s for s in self.sections if s.kind == "elicitation"), None)
        return section.body if section is not None else ""

    def find_requirement(self, ref: str | None, title: str) -> Section | None:
        requirements = self.requirements()
        if ref:
            match = next((s for s in requirements if s.ref == ref), None)
            if match is not None:
                return match
        key = field_key(title)
        return next((s for s in requirements if field_key(s.title) == key), None)

    def find_todo(self, title: str) -> Section | None:
        key = field_key(title)
        return next((s for s in self.todos() if field_key(s.title) == key), None)

    def prefixes(self) -> frozenset[str]:
        values = [self.meta.get("link-prefixes", ""), self.meta.get("workspace", "")]
        if "-" in self.record:
            values.append(self.record.split("-", 1)[0])
        return aha_html.parse_prefixes(values)

    def link_context(
        self, domain: str | None = None, extra: Sequence[str] = ()
    ) -> aha_html.LinkContext:
        return aha_html.LinkContext(
            domain=domain or self.meta.get("aha-domain") or None,
            prefixes=self.prefixes() | aha_html.parse_prefixes(extra),
        )


def _new_section(match: re.Match[str], line: int) -> Section:
    kind = match.group("kind").lower().replace("-", "")
    title = match.group("title").strip()
    if kind == "field":
        return Section("field", title, line=line)
    if kind == "requirement":
        numbered = REQUIREMENT_REF_RE.match(title)
        if numbered is not None:
            return Section(
                "requirement", numbered.group("name").strip(), ref=numbered.group("ref"), line=line
            )
        if title.lower().startswith("new "):
            title = title[4:].strip()
        return Section("requirement", title, line=line)
    if kind == "todo":
        return Section("todo", title, line=line)
    if kind == "elicitation":
        return Section("elicitation", "Elicitation", line=line)
    return Section("settings", "Settings", line=line)


def _finish(section: Section, body: list[str]) -> Section:
    leading = 0
    while leading < len(body) and not body[leading].strip():
        leading += 1
    section.body = "\n".join(body[leading:]).strip()
    section.body_line = section.line + 1 + leading
    return section


def parse_bundle(text: str) -> Bundle:
    """Parse a bundle: optional front matter, then '# Field:', '# Requirement:' sections."""
    text = text.replace("\r\n", "\n")
    meta: dict[str, str] = {}
    first_line = 1
    front = FRONT_MATTER_RE.match(text)
    if front is not None:
        for raw in front.group(1).split("\n"):
            key, separator, value = raw.partition(":")
            if separator and key.strip() and not key.strip().startswith("#"):
                meta[key.strip().lower()] = value.strip()
        first_line += text[: front.end()].count("\n")
        text = text[front.end() :]
    sections: list[Section] = []
    current: Section | None = None
    body: list[str] = []
    fence: str | None = None
    for number, line in enumerate(text.split("\n"), start=first_line):
        marker = FENCE_LINE_RE.match(line)
        if marker is not None:
            token = marker.group(1)[0]
            fence = None if fence == token else (fence or token)
        delimiter = DELIMITER_RE.match(line) if fence is None and marker is None else None
        if delimiter is not None:
            if current is not None:
                sections.append(_finish(current, body))
            current = _new_section(delimiter, number)
            body = []
            continue
        body.append(line)
    if current is not None:
        sections.append(_finish(current, body))
    return Bundle(meta, sections)


def format_bundle(bundle: Bundle) -> str:
    """Write a bundle back to Markdown."""
    lines = ["---", *(f"{key}: {value}" for key, value in bundle.meta.items()), "---", ""]
    for section in bundle.sections:
        lines.extend([section.heading(), "", section.body.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def parse_json_text(text: str) -> Any:
    """Return the first JSON value in text; MCP output files can carry trailing data."""
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        raise ValueError("no JSON object found")
    value, _ = json.JSONDecoder().raw_decode(text, min(starts))
    return value


def iter_records(document: Any) -> list[dict[str, Any]]:
    """Return the records in a read_records response, a saved backup, or a bare record."""
    node = document
    for key in ("result", "results", "records"):
        if isinstance(node, dict) and key in node:
            node = node[key]
    if isinstance(node, dict):
        return [node]
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    return []


def select_record(records: list[dict[str, Any]], ref: str | None = None) -> dict[str, Any]:
    if not records:
        raise ValueError("no records found in the JSON input")
    if ref:
        for record in records:
            if ref in (str(record.get("id")), str(record.get("reference_num"))):
                return record
        raise ValueError(f"record {ref} not found in the JSON input")
    return next(
        (record for record in records if record.get("record_type") == "feature"), records[0]
    )


def merge_continuation_rows(lines: list[str]) -> list[str]:
    """Fold the extra rows Aha! exports for multi-paragraph table cells into one row."""
    output: list[str] = []
    in_body = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_body = False
            output.append(line)
            continue
        if aha_html.TABLE_SEPARATOR_RE.match(stripped):
            in_body = True
            output.append(line)
            continue
        cells = aha_html.split_table_row(stripped)
        previous = output[-1].strip() if output else ""
        continues = (
            in_body
            and cells[0] == ""
            and previous.startswith("|")
            and not aha_html.TABLE_SEPARATOR_RE.match(previous)
        )
        if not continues:
            output.append(line)
            continue
        additions = [cell if cell.strip("\\ ") else "" for cell in cells]
        if not any(additions[1:]):
            continue
        earlier = aha_html.split_table_row(previous)
        width = max(len(earlier), len(additions))
        merged = []
        for column in range(width):
            before = earlier[column] if column < len(earlier) else ""
            extra = additions[column] if column < len(additions) else ""
            merged.append(f"{before}<br>{extra}" if before and extra else before or extra)
        output[-1] = "| " + " | ".join(merged) + " |"
    return output


def _simplify_mention(match: re.Match[str]) -> str:
    target = aha_html.reference_from_url(match.group("url"))
    if target is not None and target[1] == match.group("ref"):
        return match.group("ref")
    return match.group(0)


def normalize_markdown(text: str) -> str:
    """Tidy Markdown exported by Aha!: table padding, spacer rows, and mention links."""
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = REFERENCE_QUERY_RE.sub("", text)
    text = MENTION_LINK_RE.sub(_simplify_mention, text)
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if SPACER_LINE_RE.match(line):
            lines.append("")
            continue
        if stripped.startswith("|"):
            cells = aha_html.split_table_row(stripped)
            if aha_html.TABLE_SEPARATOR_RE.match(stripped):
                line = "|" + "|".join(["---"] * len(cells)) + "|"
            else:
                line = "| " + " | ".join(cells) + " |"
        lines.append(line.rstrip())
    return "\n".join(merge_continuation_rows(lines)).strip()


def field_markdown(value: str) -> str:
    """Return a field value as normalized Markdown, converting HTML when needed."""
    text = aha_html.html_to_markdown(value) if aha_html.looks_like_html(value) else value
    return normalize_markdown(text)


def _records_of(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _name_of(value: Any) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else ""


def _ref_label(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return (
        f"{value.get('id') or value.get('reference_num') or ''} {value.get('name') or ''}".strip()
    )


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_scalar(item) for item in value)
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or json.dumps(value, sort_keys=True))
    return str(value)


def _table_cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def guess_profile(name: str, kind: str) -> str:
    lowered = name.lower()
    if "enabling" in kind.lower() or "platform" in lowered or "foundation" in lowered:
        return "platform"
    if "agent" in lowered:
        return "agent"
    return "product"


_CANONICAL = {field_key(name): index for index, name in enumerate(FIELD_ORDER)}


def record_to_bundle(record: dict[str, Any]) -> Bundle:
    """Turn one read_records feature (Markdown or HTML text fields) into a bundle."""
    ref = str(record.get("id") or record.get("reference_num") or "")
    name = str(record.get("name") or "")
    project = record.get("project")
    workspace = str(project.get("reference_prefix") or "") if isinstance(project, dict) else ""
    workspace = workspace or (ref.split("-", 1)[0] if "-" in ref else "")
    url = str(record.get("url") or "")
    host = urlsplit(url).hostname or ""
    kind = _name_of(record.get("workflow_kind"))
    raw_texts: list[str] = []
    fields: list[Section] = []
    settings: list[tuple[str, str]] = []
    description = record.get("description")
    if isinstance(description, str):
        raw_texts.append(description)
        fields.append(Section("field", "Description", field_markdown(description)))
    for custom in record.get("custom_fields") or []:
        if not isinstance(custom, dict):
            continue
        label = str(custom.get("name") or custom.get("key") or "")
        value = custom.get("value")
        if str(custom.get("type") or "") in TEXT_FIELD_TYPES and isinstance(value, str):
            raw_texts.append(value)
            fields.append(Section("field", label, field_markdown(value)))
        else:
            settings.append((label, _scalar(value)))
    fields.sort(key=lambda section: _CANONICAL.get(field_key(section.title), len(_CANONICAL)))
    requirements: list[Section] = []
    for item in _records_of(record.get("requirements")):
        text = item.get("description") if isinstance(item.get("description"), str) else ""
        raw_texts.append(str(text))
        item_ref = str(item.get("id") or item.get("reference_num") or "") or None
        requirements.append(
            Section("requirement", str(item.get("name") or ""), field_markdown(str(text)), item_ref)
        )
    todos: list[Section] = []
    todo_rows: list[str] = []
    for item in _records_of(record.get("to_dos")):
        body = item.get("body") if isinstance(item.get("body"), str) else item.get("description")
        todos.append(Section("todo", str(item.get("name") or ""), field_markdown(str(body or ""))))
        todo_rows.append(
            f"| {item.get('id') or ''} | {_table_cell(str(item.get('name') or ''))} "
            f"| {item.get('status') or ''} |"
        )
    rows = [
        ("Type", kind),
        ("Status", _name_of(record.get("workflow_status"))),
        ("Release", _ref_label(record.get("release"))),
        ("Initiative", _ref_label(record.get("initiative"))),
        ("Epic", _ref_label(record.get("epic") or record.get("master_feature"))),
        ("Assigned to", _name_of(record.get("assigned_to_user"))),
        ("Tags", ", ".join(str(tag) for tag in record.get("tags") or [])),
        ("Attachments", str(len(record.get("attachments") or []))),
        *settings,
    ]
    lines = ["| Setting | Value |", "|---|---|"]
    lines.extend(f"| {label} | {_table_cell(value)} |" for label, value in rows if label)
    if todo_rows:
        lines.extend(["", "| To-Do | Name | Status |", "|---|---|---|", *todo_rows])
    prefixes = {match.group(1) for match in AHA_URL_PREFIX_RE.finditer("\n".join(raw_texts))}
    if workspace:
        prefixes.add(workspace)
    meta = {"record": ref, "name": name}
    if workspace:
        meta["workspace"] = workspace
    if host:
        meta["aha-domain"] = host
    if url:
        meta["url"] = url
    meta["profile"] = guess_profile(name, kind)
    if any(key in record for key in ("initiative", "goals", "key_results")):
        meta["initiative"] = _ref_label(record.get("initiative"))
        for key in ("goals", "key_results"):
            labels = [_ref_label(item) for item in record.get(key) or []]
            meta[key.replace("_", "-")] = ", ".join(label for label in labels if label)
    if prefixes:
        meta["link-prefixes"] = ", ".join(sorted(prefixes))
    settings_section = Section("settings", "Settings", "\n".join(lines))
    return Bundle(meta, [*fields, *requirements, *todos, settings_section])


def read_text(source: str) -> str:
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def layout_key(section: Section) -> tuple[str, str]:
    """Key a bundle section to its live text: requirements by reference, others by name."""
    if section.kind == "requirement" and section.ref:
        return ("requirement", section.ref)
    return (section.kind, field_key(section.title))


def record_layouts(record: dict[str, Any]) -> dict[tuple[str, str], aha_html.TableLayouts]:
    """Read the table layouts of each text section in a record read as Aha! Editor HTML."""
    texts: list[tuple[tuple[str, str], Any]] = [
        (("field", field_key("Description")), record.get("description"))
    ]
    for custom in record.get("custom_fields") or []:
        if isinstance(custom, dict) and str(custom.get("type") or "") in TEXT_FIELD_TYPES:
            label = str(custom.get("name") or custom.get("key") or "")
            texts.append((("field", field_key(label)), custom.get("value")))
    for item in _records_of(record.get("requirements")):
        item_ref = str(item.get("id") or item.get("reference_num") or "")
        texts.append((("requirement", item_ref), item.get("description")))
    for item in _records_of(record.get("to_dos")):
        body = item.get("body") if isinstance(item.get("body"), str) else item.get("description")
        texts.append((("todo", field_key(str(item.get("name") or ""))), body))
    layouts: dict[tuple[str, str], aha_html.TableLayouts] = {}
    for key, value in texts:
        if isinstance(value, str) and aha_html.looks_like_html(value):
            tables = aha_html.table_layouts(value)
            if tables:
                layouts[key] = aha_html.TableLayouts(tables)
    return layouts


def load_bundle(source: str, record: str | None = None) -> Bundle:
    """Load a bundle file, or build one from an Aha! read_records JSON dump."""
    text = read_text(source)
    if text.lstrip()[:1] in ("{", "["):
        return record_to_bundle(select_record(iter_records(parse_json_text(text)), record))
    return parse_bundle(text)


# --- Specification analysis ---------------------------------------------------------


@dataclass
class Statement:
    """One EARS statement, such as '- **FR-8 (P0):** WHEN ..., the agent SHALL ...'."""

    sid: str
    text: str
    priority: str | None = None
    change: str | None = None
    unknown: list[str] = field(default_factory=list)
    line: int | None = None


@dataclass
class RequirementInfo:
    """What a requirement record says: its statements and its traceability line."""

    section: Section
    statements: list[Statement] = field(default_factory=list)
    scope: str = ""
    covers_uc: set[int] = field(default_factory=set)
    covers_all: bool = False
    covers_fr: set[str] = field(default_factory=set)
    prd: bool = False
    verified_ac: set[int] = field(default_factory=set)
    has_covers: bool = False
    has_verified: bool = False


@dataclass
class Criterion:
    """An acceptance criterion: AC-n with Given, When, and Then clauses."""

    number: int
    title: str
    clauses: dict[str, list[str]] = field(default_factory=dict)
    line: int | None = None
    last: str | None = None


@dataclass
class UseCase:
    number: int
    text: str
    priority: str | None = None


@dataclass
class Spec:
    """The parsed specification of one feature."""

    bundle: Bundle
    profile: str
    requirements: list[RequirementInfo]
    use_cases: dict[int, UseCase]
    duplicate_use_cases: list[int]
    criteria: dict[int, Criterion]
    duplicate_criteria: list[int]
    definition: dict[str, str]
    definition_found: bool
    user_story: dict[str, str] | None
    done: str | None
    out_of_scope: list[str]
    defined_terms: frozenset[str] = frozenset()

    def statements(self) -> list[Statement]:
        return [
            statement for requirement in self.requirements for statement in requirement.statements
        ]


def _line_number(section: Section, offset: int) -> int | None:
    return section.body_line + offset if section.body_line else None


def expand_ids(text: str, kind: str) -> set[int]:
    """Expand references such as 'FR-8 to FR-11, FR-14' into numbers."""
    numbers: set[int] = set()
    for match in ID_RE.finditer(text):
        if match.group("kind") != kind:
            continue
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        if end < start or end - start > 500:
            end = start
        numbers.update(range(start, end + 1))
    return numbers


def _parse_meta(meta: str | None) -> tuple[str | None, str | None, list[str]]:
    priority: str | None = None
    change: str | None = None
    unknown: list[str] = []
    for token in re.split(r"[,;/\s]+", meta or ""):
        upper = token.upper()
        if not token or upper in IGNORED_TOKENS:
            continue
        if upper in PRIORITY_TOKENS:
            priority = upper
        elif upper in CHANGE_TOKENS:
            change = upper
        else:
            unknown.append(token)
    return priority, change, unknown


def _statement(sid: str, meta: str | None, text: str, line: int | None) -> Statement:
    priority, change, unknown = _parse_meta(meta)
    return Statement(sid, text.strip(), priority, change, unknown, line)


def parse_requirement(section: Section) -> RequirementInfo:
    """Read EARS statements, scope text, and the Covers and Verified by lines."""
    info = RequirementInfo(section)
    current: Statement | None = None
    scope: list[str] = []
    for offset, raw in enumerate(section.body.split("\n")):
        line = _line_number(section, offset)
        unbolded = raw.replace("**", "").replace("__", "")
        bullet = BULLET_RE.match(unbolded)
        found: Statement | None = None
        if bullet is not None:
            candidate = STATEMENT_RE.match(bullet.group("rest").strip())
            if candidate is not None:
                found = _statement(
                    candidate.group("id"), candidate.group("meta"), candidate.group("text"), line
                )
        elif unbolded.lstrip().startswith("|"):
            cells = [cell.strip() for cell in aha_html.split_table_row(unbolded)]
            if cells and re.fullmatch(r"N?FR-\d+", cells[0]):
                text = cells[-1] if len(cells) > 1 else ""
                found = _statement(cells[0], " ".join(cells[1:-1]), text, line)
        if found is not None:
            info.statements.append(found)
            current = found
            continue
        if current is not None and raw[:1] in (" ", "\t") and raw.strip() and bullet is None:
            current.text = f"{current.text} {raw.strip()}"
            continue
        current = None
        plain = aha_html.plain_text(raw)
        covers = COVERS_RE.search(plain)
        verified = VERIFIED_RE.match(plain)
        if covers is not None:
            info.has_covers = True
            cited = covers.group("covers")
            info.covers_uc |= expand_ids(cited, "UC")
            info.covers_all = info.covers_all or bool(re.search(r"\ball use cases\b", cited, re.I))
            info.covers_fr |= {f"FR-{n}" for n in expand_ids(cited, "FR")}
            info.covers_fr |= {f"NFR-{n}" for n in expand_ids(cited, "NFR")}
            info.prd = info.prd or bool(re.search(r"\bPRD\b", cited))
            if covers.group("verified") is not None:
                info.has_verified = True
                info.verified_ac |= expand_ids(covers.group("verified"), "AC")
        elif verified is not None:
            info.has_verified = True
            info.verified_ac |= expand_ids(verified.group("verified"), "AC")
        elif plain and not info.statements and not raw.lstrip().startswith("|"):
            scope.append(plain)
    info.scope = " ".join(scope)
    return info


def parse_criteria(section: Section | None) -> tuple[dict[int, Criterion], list[int]]:
    criteria: dict[int, Criterion] = {}
    duplicates: list[int] = []
    if section is None:
        return criteria, duplicates
    current: Criterion | None = None
    for offset, raw in enumerate(section.body.split("\n")):
        heading = AC_HEADING_RE.match(raw)
        if heading is not None:
            number = int(heading.group("num"))
            title = aha_html.plain_text(heading.group("title")).rstrip("*").strip()
            current = Criterion(number, title, line=_line_number(section, offset))
            if number in criteria:
                duplicates.append(number)
            else:
                criteria[number] = current
            continue
        if current is None or not raw.strip():
            continue
        clause = CLAUSE_RE.match(aha_html.plain_text(raw))
        listed = re.match(r"^\s*(?:[-*+]|\d+[.)])\s", raw) is not None
        # A lowercase "and ..." on an unbulleted line continues the previous clause.
        if clause is not None and (listed or clause.group("kw")[0].isupper()):
            keyword = clause.group("kw").lower()
            if keyword in ("and", "but"):
                keyword = current.last or "then"
            current.clauses.setdefault(keyword, []).append(clause.group("text").strip())
            current.last = keyword
        elif current.last is not None:
            current.clauses[current.last][-1] += " " + aha_html.plain_text(raw)
    return criteria, duplicates


def parse_use_cases(section: Section | None) -> tuple[dict[int, UseCase], list[int]]:
    cases: dict[int, UseCase] = {}
    duplicates: list[int] = []
    if section is None:
        return cases, duplicates
    for raw in section.body.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("|"):
            cells = aha_html.split_table_row(stripped)
            match = re.fullmatch(r"UC-(\d+)", aha_html.plain_text(cells[0]))
            if match is None:
                continue
            number = int(match.group(1))
            text = aha_html.plain_text(cells[1]) if len(cells) > 1 else ""
            rest = " ".join(cells[2:])
        else:
            line = USE_CASE_LINE_RE.match(stripped)
            if line is None:
                continue
            number = int(line.group("num"))
            text = aha_html.plain_text(line.group("text"))
            rest = text
        priority = PRIORITY_RE.search(rest)
        if number in cases:
            duplicates.append(number)
            continue
        cases[number] = UseCase(number, text, f"P{priority.group(1)}" if priority else None)
    return cases, duplicates


def _definition_rows(rows: list[list[str]]) -> dict[str, str]:
    definition: dict[str, str] = {}
    last: str | None = None
    for cells in rows:
        name = aha_html.plain_text(cells[0]).lower() if cells else ""
        text = "<br>".join(cell for cell in cells[1:] if cell.strip("\\ "))
        if name:
            last = name
            definition[name] = text
        elif last is not None and text:
            definition[last] = f"{definition[last]}<br>{text}" if definition[last] else text
    return definition


def parse_definition(description: str) -> tuple[bool, dict[str, str]]:
    """Find the definition table: header 'Element', or under a '... Definition' heading."""
    lines = description.split("\n")
    heading = ""
    index = 0
    while index < len(lines):
        title = aha_html.HEADING_RE.match(lines[index])
        if title is not None:
            heading = aha_html.plain_text(title.group(2)).lower()
            index += 1
            continue
        if not aha_html.is_table_start(lines, index):
            index += 1
            continue
        header = [
            aha_html.plain_text(cell).lower() for cell in aha_html.split_table_row(lines[index])
        ]
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            rows.append(aha_html.split_table_row(lines[index]))
            index += 1
        named = "definition" in heading and "definition of done" not in heading
        if header[0] in DEFINITION_HEADERS or named:
            return True, _definition_rows(rows)
    return False, {}


def parse_user_story(description: str) -> dict[str, str] | None:
    for paragraph in re.split(r"\n\s*\n", description):
        match = USER_STORY_RE.search(aha_html.plain_text(paragraph))
        if match is not None:
            return {key: " ".join(value.split()) for key, value in match.groupdict().items()}
    return None


def parse_done(description: str) -> str | None:
    """Return the Definition of Done text under its heading or bold lead-in."""
    lines = description.split("\n")
    for index, line in enumerate(lines):
        heading = aha_html.HEADING_RE.match(line)
        label = aha_html.plain_text(heading.group(2) if heading else line).lower()
        if not any(name in label for name in DONE_LABELS):
            continue
        if heading is None and not line.strip().startswith(("**", "__")):
            continue
        level = len(heading.group(1)) if heading else 7
        body: list[str] = []
        for following in lines[index + 1 :]:
            next_heading = aha_html.HEADING_RE.match(following)
            if next_heading is not None and len(next_heading.group(1)) <= level:
                break
            body.append(following)
        return "\n".join(body).strip()
    return None


def split_items(text: str) -> list[str]:
    """Split a definition-table cell into items, by line break or sentence."""
    pieces = re.split(r"\s*<br\s*/?>\s*|(?<=[.;])\s+(?=[A-Z(])", text)
    items = [aha_html.plain_text(piece).strip(" ;") for piece in pieces]
    return [item for item in items if item.strip(" .")]


def bullet_items(markdown: str) -> list[str]:
    items: list[str] = []
    for line in markdown.split("\n"):
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if match is not None and match.group(1).strip():
            items.append(aha_html.plain_text(match.group(1)))
    return items


def parse_out_of_scope(description: str, definition: dict[str, str]) -> list[str]:
    for name, text in definition.items():
        if any(name.startswith(key) for key in OUT_OF_SCOPE_NAMES):
            return split_items(text)
    lines = description.split("\n")
    for index, line in enumerate(lines):
        heading = aha_html.HEADING_RE.match(line)
        if heading is None:
            continue
        title = aha_html.plain_text(heading.group(2)).lower()
        if any(key in title for key in OUT_OF_SCOPE_NAMES):
            section: list[str] = []
            for following in lines[index + 1 :]:
                if aha_html.HEADING_RE.match(following):
                    break
                section.append(following)
            return bullet_items("\n".join(section))
    return []


def defined_terms(bundle: Bundle) -> frozenset[str]:
    """Return terms the record defines (T1 Read-only) plus any listed in 'defined-terms'."""
    listed = bundle.meta.get("defined-terms", "").split(",")
    terms = {term.strip().lower() for term in listed if term.strip()}
    for section in bundle.sections:
        if section.kind in ("field", "requirement"):
            plain = aha_html.plain_text(section.body)
            terms.update(match.group(1).lower() for match in TIER_TERM_RE.finditer(plain))
    return frozenset(terms)


def analyze(bundle: Bundle, profile: str) -> Spec:
    """Parse a bundle into the parts the linter and exporters use."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; use one of {', '.join(PROFILES)}")
    description = bundle.field_text("Description")
    found, definition = parse_definition(description)
    use_cases, duplicate_use_cases = parse_use_cases(bundle.get_field("Use Case(s)"))
    criteria, duplicate_criteria = parse_criteria(bundle.get_field("Acceptance Criteria"))
    return Spec(
        bundle=bundle,
        profile=profile,
        requirements=[parse_requirement(section) for section in bundle.requirements()],
        use_cases=use_cases,
        duplicate_use_cases=duplicate_use_cases,
        criteria=criteria,
        duplicate_criteria=duplicate_criteria,
        definition=definition,
        definition_found=found,
        user_story=parse_user_story(description),
        done=parse_done(description),
        out_of_scope=parse_out_of_scope(description, definition),
        defined_terms=defined_terms(bundle),
    )


# --- Lint ---------------------------------------------------------------------------


@dataclass
class Finding:
    rule: str
    severity: str
    where: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "where": self.where,
            "line": self.line,
            "message": self.message,
        }


class _Findings:
    def __init__(self) -> None:
        self.items: list[Finding] = []

    def add(
        self, rule: str, severity: str | None, where: str, message: str, line: int | None = None
    ) -> None:
        if severity is not None:
            self.items.append(Finding(rule, severity, where, message, line))


def _at(gate: str, seed: str | None, elaborated: str | None, ready: str | None) -> str | None:
    return {"seed": seed, "elaborated": elaborated, "ready": ready}[gate]


def _ids(kind: str, numbers: Iterable[int]) -> str:
    return ", ".join(f"{kind}-{number}" for number in numbers)


def _has_row(definition: dict[str, str], row: str) -> bool:
    names = (row.lower(), *ROW_ALIASES.get(row.lower(), ()))
    return any(key.startswith(name) for key in definition for name in names)


def _keyword_position(text: str, keyword: str) -> int | None:
    match = re.search(rf"\b{keyword}\b", text)
    return match.start() if match else None


def ears_problems(text: str, exempt: frozenset[str] = frozenset()) -> list[tuple[str, str, str]]:
    """Return (rule, severity, message) for one EARS statement."""
    plain = aha_html.plain_text(text)
    problems: list[tuple[str, str, str]] = []
    if SHALL_RE.search(plain) is None:
        if re.search(r"\bshall\b", plain, re.IGNORECASE):
            problems.append(("EARS003", "warning", "write SHALL in capitals."))
        else:
            modal = WEAK_MODAL_RE.search(plain)
            hint = f" '{modal.group(0)}' leaves room to opt out." if modal else ""
            problems.append(
                ("EARS002", "error", f"no SHALL.{hint} Write '<system> SHALL <response>'.")
            )
    if len(SHALL_RE.findall(plain)) > 1:
        problems.append(("EARS007", "warning", "more than one SHALL; split it into statements."))
    lead = re.match(r"(When|While|If|Where)\b", plain)
    if lead is not None:
        word = lead.group(1)
        problems.append(("EARS003", "warning", f"write '{word}' as {word.upper()}."))
    if re.match(r"IF\b", plain) and not re.search(r"\bTHEN\b", plain):
        problems.append(
            ("EARS005", "warning", "IF needs THEN: 'IF <condition>, THEN the <system> SHALL ...'.")
        )
    when = _keyword_position(plain, "WHEN")
    while_ = _keyword_position(plain, "WHILE")
    where = _keyword_position(plain, "WHERE")
    if when is not None and while_ is not None and when < while_:
        problems.append(("EARS006", "warning", "put the WHILE clause before the WHEN clause."))
    if where is not None and where > 0 and plain[:where].strip():
        problems.append(("EARS006", "warning", "put the WHERE clause first."))
    for term in sorted({match.group(0).lower() for match in VAGUE_RE.finditer(plain)} - exempt):
        problems.append(
            (
                "EARS008",
                "warning",
                f"'{term}' is vague; use a number, a list, or an observable result.",
            )
        )
    return problems


def _check_description(spec: Spec, gate: str, findings: _Findings) -> None:
    description = spec.bundle.get_field("Description")
    where = "Field: Description"
    if description is None or not description.body.strip():
        findings.add(
            "STR001",
            "error",
            where,
            "Description is empty. Start with a user story and a definition table.",
        )
        return
    line = description.body_line or None
    if spec.user_story is None:
        findings.add(
            "STR001",
            "error",
            where,
            "No user story: 'As a <role>, I want <capability>, so that <value>.'",
            line,
        )
    if not spec.definition_found:
        findings.add(
            "STR002",
            "error",
            where,
            "No definition table. Add one with an 'Element | Definition' header.",
            line,
        )
    else:
        required = SEED_ROWS[spec.profile] if gate == "seed" else PROFILE_ROWS[spec.profile]
        missing = [row for row in required if not _has_row(spec.definition, row)]
        if missing:
            findings.add(
                "STR003",
                _at(gate, "error", "warning", "error"),
                where,
                f"The definition table has no {', '.join(missing)} row(s) for the {spec.profile} profile.",
                line,
            )
    count = len(spec.out_of_scope)
    if count < 3:
        findings.add(
            "STR004",
            _at(gate, "info", "warning", "error"),
            where,
            f"Out of scope lists {count} item(s); name at least 3 things this feature won't do.",
            line,
        )
    if spec.done is None:
        findings.add(
            "STR005",
            _at(gate, None, "warning", "error"),
            where,
            "No Definition of Done. Say which acceptance criteria and gates must pass.",
            line,
        )


def check_structure(spec: Spec, gate: str, findings: _Findings) -> None:
    _check_description(spec, gate, findings)
    bundle = spec.bundle
    if gate != "seed":
        for name, (elaborated, ready) in GATE_FIELDS.items():
            if not filled(bundle.field_text(name)):
                severity = elaborated if gate == "elaborated" else ready
                findings.add("STR006", severity, f"Field: {name}", f"{name} is empty.")
        if not spec.requirements:
            findings.add("STR007", "error", "Requirements", "The feature has no requirements.")
    value = bundle.field_text("Business Value")
    if TARGET_RE.search(value) and not BASELINE_RE.search(bundle.field_text("Business Problem")):
        findings.add(
            "STR008",
            "warning",
            "Field: Business Value",
            "Targets have no baseline. In Business Problem, give today's measure or say it isn't measured yet.",
        )
    summary = bundle.field_text("Summary")
    if len(aha_html.plain_text(summary)) > 1200:
        findings.add("STR009", "warning", "Field: Summary", "Summary is over 1,200 characters.")
    if gate == "seed" or not spec.requirements:
        return
    text = "\n".join(requirement.section.body for requirement in spec.requirements)
    coverage = _at(gate, None, "info", "warning")
    if not SECURITY_RE.search(text):
        findings.add("STR010", coverage, "Requirements", "No requirement covers security or audit.")
    if not MEASURE_RE.search(text):
        findings.add(
            "STR010",
            coverage,
            "Requirements",
            "No requirement states a measurable performance target.",
        )
    if spec.profile == "product" and not ACCESSIBILITY_RE.search(text):
        findings.add(
            "STR010", coverage, "Requirements", "No requirement covers accessibility (WCAG)."
        )


def check_requirements(spec: Spec, gate: str, findings: _Findings) -> None:
    seen: dict[str, str] = {}
    for requirement in spec.requirements:
        where = requirement.section.label
        if not requirement.statements:
            findings.add(
                "EARS001",
                _at(gate, "warning", "error", "error"),
                where,
                "No EARS statements. Write each behavior as "
                "'- **FR-n (P0):** WHEN <trigger>, the <system> SHALL <response>.'",
                requirement.section.body_line or None,
            )
        for statement in requirement.statements:
            if statement.sid in seen:
                findings.add(
                    "EARS010",
                    "error",
                    where,
                    f"{statement.sid} is also used in {seen[statement.sid]}.",
                    statement.line,
                )
            else:
                seen[statement.sid] = where
            for rule, severity, message in ears_problems(statement.text, spec.defined_terms):
                findings.add(rule, severity, where, f"{statement.sid}: {message}", statement.line)
            if statement.priority is None:
                findings.add(
                    "EARS009",
                    "warning",
                    where,
                    f"{statement.sid} has no priority; add (P0), (P1), or (P2).",
                    statement.line,
                )
            for token in statement.unknown:
                findings.add(
                    "EARS011",
                    "warning",
                    where,
                    f"{statement.sid}: unknown marker '{token}'.",
                    statement.line,
                )


def check_traceability(spec: Spec, gate: str, findings: _Findings) -> None:
    defined_uc = set(spec.use_cases)
    defined_ac = set(spec.criteria)
    defined_fr = {statement.sid for statement in spec.statements()}
    covered: set[int] = set()
    cited: set[int] = set()
    for requirement in spec.requirements:
        where = requirement.section.label
        line = requirement.section.body_line or None
        if not requirement.has_covers:
            findings.add(
                "TRC001",
                "error",
                where,
                "No 'Covers: UC-n.' line at the end of the requirement.",
                line,
            )
        if not requirement.has_verified:
            findings.add("TRC002", "error", where, "No 'Verified by AC-n.' line.", line)
        unknown_uc = sorted(requirement.covers_uc - defined_uc)
        if unknown_uc and defined_uc:
            findings.add(
                "TRC003",
                "error",
                where,
                f"Covers {_ids('UC', unknown_uc)}, which Use Case(s) doesn't define.",
                line,
            )
        unknown_ac = sorted(requirement.verified_ac - defined_ac)
        if unknown_ac and defined_ac:
            findings.add(
                "TRC004",
                "error",
                where,
                f"Verified by {_ids('AC', unknown_ac)}, which Acceptance Criteria doesn't define.",
                line,
            )
        if requirement.prd:
            findings.add(
                "TRC007",
                _at(gate, None, "info", "warning"),
                where,
                "Covers cites an external PRD. Move those behaviors into this requirement as EARS statements.",
                line,
            )
        elif defined_fr:
            missing = sorted(requirement.covers_fr - defined_fr)
            if missing:
                findings.add(
                    "TRC009",
                    "warning",
                    where,
                    f"Covers cites {', '.join(missing)}, which no statement defines.",
                    line,
                )
        covered |= defined_uc if requirement.covers_all else requirement.covers_uc
        cited |= requirement.verified_ac
    for number in sorted(defined_uc - covered):
        findings.add(
            "TRC005",
            _at(gate, None, "warning", "error"),
            "Field: Use Case(s)",
            f"UC-{number} isn't covered by any requirement.",
        )
    for number in sorted(defined_ac - cited):
        findings.add(
            "TRC006",
            "warning",
            "Field: Acceptance Criteria",
            f"AC-{number} isn't cited by any requirement's 'Verified by' line.",
        )
    if spec.done and defined_ac:
        span = DOD_RANGE_RE.search(spec.done)
        if span is not None:
            low, high = int(span.group(1)), int(span.group(2))
            if (low, high) != (min(defined_ac), max(defined_ac)):
                findings.add(
                    "TRC008",
                    "warning",
                    "Field: Description",
                    f"Definition of Done says AC-{low} to AC-{high}; Acceptance Criteria defines "
                    f"AC-{min(defined_ac)} to AC-{max(defined_ac)}.",
                )


def check_criteria(spec: Spec, gate: str, findings: _Findings) -> None:
    section = spec.bundle.get_field("Acceptance Criteria")
    if section is not None and section.body.strip():
        where = section.label
        if not spec.criteria:
            findings.add(
                "AC003",
                _at(gate, "info", "error", "error"),
                where,
                "No AC-n headings. Use '### AC-1. <title>' followed by Given, When, and Then lines.",
                section.body_line or None,
            )
        for number in spec.duplicate_criteria:
            findings.add("AC002", "error", where, f"AC-{number} appears more than once.")
        if spec.criteria:
            gaps = sorted(set(range(1, max(spec.criteria) + 1)) - set(spec.criteria))
            if gaps:
                findings.add("AC002", "info", where, f"AC numbering skips {_ids('AC', gaps)}.")
        for criterion in spec.criteria.values():
            missing = [
                key.title() for key in ("given", "when", "then") if not criterion.clauses.get(key)
            ]
            if missing:
                findings.add(
                    "AC001",
                    "error",
                    where,
                    f"AC-{criterion.number} has no {', '.join(missing)} clause.",
                    criterion.line,
                )
            text = " ".join(" ".join(parts) for parts in criterion.clauses.values())
            vague = {match.group(0).lower() for match in VAGUE_RE.finditer(text)}
            for term in sorted(vague - spec.defined_terms):
                findings.add(
                    "AC004",
                    "warning",
                    where,
                    f"AC-{criterion.number}: '{term}' is vague.",
                    criterion.line,
                )
    cases = spec.bundle.get_field("Use Case(s)")
    if cases is None or not cases.body.strip():
        return
    if not spec.use_cases:
        findings.add(
            "UC003",
            _at(gate, "info", "error", "error"),
            cases.label,
            "No UC-n IDs. Use a table: | ID | Use case | Priority |.",
            cases.body_line or None,
        )
    for number in spec.duplicate_use_cases:
        findings.add("UC001", "error", cases.label, f"UC-{number} appears more than once.")
    for case in spec.use_cases.values():
        if case.priority is None:
            findings.add(
                "UC002",
                "warning",
                cases.label,
                f"UC-{case.number} has no priority (P0, P1, or P2).",
            )


def check_writing(spec: Spec, gate: str, findings: _Findings) -> None:
    for section in spec.bundle.sections:
        if section.kind not in ("field", "requirement"):
            continue
        plain = aha_html.plain_text(section.body)
        overclaims = {match.group(0).lower() for match in OVERCLAIM_RE.finditer(plain)}
        claims = sorted(overclaims - spec.defined_terms)
        if claims:
            findings.add(
                "WRT001",
                "warning",
                section.label,
                f"Overclaims: {', '.join(claims)}. Say what it does and the measured result instead.",
            )
        timing = sorted(
            {
                match.group(0)
                for match in TIMING_RE.finditer(plain)
                if not DECISION_REF_RE.search(plain[max(0, match.start() - 40) : match.start()])
            }
        )
        if timing:
            findings.add(
                "WRT002",
                "warning",
                section.label,
                f"Release names or dates in text: {', '.join(timing[:5])}. "
                "Name records instead; the Release field carries timing.",
            )
        placeholders = PLACEHOLDER_RE.findall(section.body)
        if placeholders:
            findings.add(
                "WRT004",
                "error",
                section.label,
                f"{len(placeholders)} template placeholder(s) such as {placeholders[0]} left in the text.",
            )
        markers = OPEN_MARKER_RE.findall(plain)
        if markers:
            findings.add(
                "WRT003",
                _at(gate, "info", "info", "error"),
                section.label,
                f"{len(markers)} open marker(s) such as '{markers[0]}'. "
                "Resolve each one or track it as an open-question To-Do.",
            )


# Statuses in the elicitation record, in the skill's words and the matrix's.
RECORD_GAPS = frozenset({"missing", "partial", "open", "unanswered"})
RECORD_DONE = frozenset({"answered", "complete"})


def elicitation_statuses(bundle: Bundle) -> dict[int, str]:
    """Return the Status cell of each numbered dimension row in the elicitation record."""
    statuses: dict[int, str] = {}
    column = 2
    for line in bundle.elicitation().split("\n"):
        if "|" not in line or aha_html.TABLE_SEPARATOR_RE.match(line):
            continue
        cells = [aha_html.plain_text(cell) for cell in aha_html.split_table_row(line)]
        lowered = [cell.lower() for cell in cells]
        if "status" in lowered:
            column = lowered.index("status")
        elif cells and cells[0].isdigit() and column < len(cells):
            statuses[int(cells[0])] = cells[column]
    return statuses


def check_elicitation(bundle: Bundle, profile: str, gate: str, findings: _Findings) -> None:
    statuses = elicitation_statuses(bundle)
    if not statuses:
        return
    for dimension in assess_matrix(bundle, profile):
        recorded = statuses.get(dimension.number, "")
        word = re.split(r"[;,(\s]", recorded.strip().lower(), maxsplit=1)[0]
        stale = word in RECORD_GAPS and dimension.status == "complete"
        overclaimed = word in RECORD_DONE and dimension.status == "missing"
        if stale or overclaimed:
            findings.add(
                "ELC001",
                _at(gate, "info", "warning", "warning"),
                "Elicitation",
                f"The record says '{recorded}' for {dimension.number}. {dimension.name}, but the "
                f"matrix finds it {dimension.status}. Record every round's answers and their "
                "sources before the record goes into the change log.",
            )


def lint(bundle: Bundle, gate: str = "elaborated", profile: str | None = None) -> list[Finding]:
    """Check a bundle against the gate; return findings, most severe first."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}; use one of {', '.join(GATES)}")
    spec = analyze(bundle, profile or bundle.meta.get("profile") or "agent")
    findings = _Findings()
    check_structure(spec, gate, findings)
    check_requirements(spec, gate, findings)
    if gate != "seed":
        check_traceability(spec, gate, findings)
    check_criteria(spec, gate, findings)
    check_writing(spec, gate, findings)
    check_elicitation(bundle, spec.profile, gate, findings)
    ranked = sorted(
        enumerate(findings.items), key=lambda pair: (SEVERITY_RANK[pair[1].severity], pair[0])
    )
    return [finding for _, finding in ranked]


def summarize(findings: Sequence[Finding]) -> dict[str, int]:
    return {
        severity: sum(1 for f in findings if f.severity == severity) for severity in SEVERITY_RANK
    }


def format_findings(bundle: Bundle, findings: Sequence[Finding], gate: str, profile: str) -> str:
    counts = summarize(findings)
    title = f"{bundle.record} {bundle.name}".strip() or "bundle"
    lines = [
        (
            f"{title} (gate: {gate}, profile: {profile}): "
            f"{counts['error']} error(s), {counts['warning']} warning(s), {counts['info']} info"
        ),
    ]
    for finding in findings:
        where = f"{finding.where} (line {finding.line})" if finding.line else finding.where
        lines.append(f"{finding.severity:<8}{finding.rule:<9}{where}")
        lines.append(f"{'':17}{finding.message}")
    return "\n".join(lines)


# --- Elicitation matrix -------------------------------------------------------------

# The five dimensions to elicit before writing, with the Aha! fields that hold the answers.
DIMENSIONS = (
    ("Value & Persona", "Description (user story), Business Problem, Business Value"),
    ("Scope & Boundaries", "Description (definition table, workflow, out of scope), Requirements"),
    ("Tech & Data", "Dependencies, definition rows for context and data, NFR statements"),
    ("Edge Cases", "Acceptance Criteria, IF/THEN statements, stop conditions"),
    ("Success Metrics", "Definition of Done, Business Value targets, Goals and Key results"),
)
DATA_ROWS = ("context", "data", "read actions", "write actions", "integrations", "interfaces")


@dataclass
class Dimension:
    """How completely a bundle answers one elicitation dimension."""

    number: int
    name: str
    status: str
    found: list[str]
    gaps: list[str]
    fields: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "name": self.name,
            "status": self.status,
            "found": self.found,
            "gaps": self.gaps,
            "fields": self.fields,
        }


def _dimension(number: int, checks: Sequence[tuple[bool, str, str]]) -> Dimension:
    found = [evidence for passed, evidence, _ in checks if passed]
    gaps = [gap for passed, _, gap in checks if not passed]
    status = "complete" if not gaps else "missing" if not found else "partial"
    name, fields = DIMENSIONS[number - 1]
    return Dimension(number, name, status, found, gaps, fields)


def answered(text: str) -> bool:
    """Return whether text has content and no template placeholders left."""
    return filled(text) and PLACEHOLDER_RE.search(text) is None


def _row_text(definition: dict[str, str], row: str) -> str:
    names = (row.lower(), *ROW_ALIASES.get(row.lower(), ()))
    return next(
        (text for key, text in definition.items() if any(key.startswith(n) for n in names)), ""
    )


def _has_workflow(description: str) -> bool:
    """Return whether the Description has written workflow steps."""
    # Ignore placeholders and emphasis, so "1. **On demand:** ..." counts and "1. {{step}}" doesn't.
    text = re.sub(r"[*_`~]", "", PLACEHOLDER_RE.sub("", description))
    if re.search(r"(?m)^[ \t]*1[.)][ \t]+\w", text):
        return True
    heading = re.search(r"(?im)^\s{0,3}#{1,6}\s+.*\bworkflow\b.*$", text)
    if heading is None:
        return False
    following = re.split(r"(?m)^\s{0,3}#{1,6}\s", text[heading.end() :], maxsplit=1)[0]
    return re.search(r"(?m)^[ \t]*[-*+][ \t]+\w", following) is not None


def goal_alignment(bundle: Bundle) -> tuple[str, str]:
    """Say whether the feature links to an initiative, goal, or key result."""
    confirmed = bundle.meta.get("alignment", "")
    if answered(confirmed) and confirmed.lower().startswith("unlinked"):
        return "confirmed unlinked", confirmed
    keys = ("initiative", "goals", "key-results")
    if not any(key in bundle.meta for key in keys):
        return "unknown", "read the record's initiative, goals, and key results"
    linked = [f"{key} {bundle.meta[key]}" for key in keys if answered(bundle.meta.get(key, ""))]
    if linked:
        return "linked", "; ".join(linked)
    return "not linked", "ask for a goal or initiative, or confirm it stays unlinked"


def assess_matrix(bundle: Bundle, profile: str) -> list[Dimension]:
    """Score a bundle against the five elicitation dimensions; placeholders don't count."""
    spec = analyze(bundle, profile)
    description = bundle.field_text("Description")
    statements = spec.statements()
    written = [s for s in statements if answered(s.text)]
    story = spec.user_story
    complete_criteria = [
        criterion
        for criterion in spec.criteria.values()
        if all(
            answered(" ".join(criterion.clauses.get(key, []))) for key in ("given", "when", "then")
        )
    ]
    criteria_text = " ".join(
        " ".join(" ".join(parts) for parts in criterion.clauses.values())
        for criterion in complete_criteria
    )
    failure_modes = (
        any(
            re.match(r"IF\b", aha_html.plain_text(s.text)) or "SHALL NOT" in s.text for s in written
        )
        or FAILURE_RE.search(criteria_text) is not None
        or any(answered(_row_text(spec.definition, row)) for row in ("stops", "guardrails"))
    )
    out_of_scope = sum(1 for item in spec.out_of_scope if answered(item))
    definition = spec.definition_found and all(
        answered(text) for text in spec.definition.values() if text.strip()
    )
    dependencies = [
        bundle.field_text(name) for name in ("Dependencies (upstream)", "Dependencies (downstream)")
    ]
    value = bundle.field_text("Business Value")
    done = spec.done or ""
    return [
        _dimension(
            1,
            [
                (
                    story is not None
                    and all(answered(story[key]) for key in ("persona", "want", "so")),
                    f"user story for {story['persona']}" if story else "",
                    "no user story naming who benefits and why",
                ),
                (
                    answered(bundle.field_text("Business Problem")),
                    "Business Problem",
                    "no Business Problem",
                ),
                (answered(value), "Business Value", "no Business Value"),
            ],
        ),
        _dimension(
            2,
            [
                (definition, "definition table", "no definition table, or it has placeholders"),
                (_has_workflow(description), "workflow", "no workflow steps"),
                (
                    out_of_scope >= 3,
                    f"{out_of_scope} out-of-scope items",
                    f"{out_of_scope} out-of-scope item(s); name at least 3",
                ),
                (
                    bool(written) and len(written) == len(statements),
                    f"{len(written)} EARS statements",
                    "no EARS requirements, or some still have placeholders",
                ),
            ],
        ),
        _dimension(
            3,
            [
                (
                    any(answered(text) for text in dependencies),
                    "dependencies",
                    "no upstream or downstream dependencies",
                ),
                (
                    any(answered(_row_text(spec.definition, row)) for row in DATA_ROWS),
                    "context and data rows",
                    "no context, data, or integration rows",
                ),
                (
                    any(s.sid.startswith("NFR") for s in written),
                    "NFR statements",
                    "no NFR statements",
                ),
            ],
        ),
        _dimension(
            4,
            [
                (
                    bool(complete_criteria),
                    f"{len(complete_criteria)} acceptance criteria",
                    "no complete Given/When/Then criterion",
                ),
                (failure_modes, "failure modes", "no failure modes, validation errors, or limits"),
            ],
        ),
        _dimension(
            5,
            [
                (answered(done), "Definition of Done", "no Definition of Done"),
                (
                    TARGET_RE.search(PLACEHOLDER_RE.sub("", f"{value} {done}")) is not None,
                    "measurable target",
                    "no measurable target",
                ),
            ],
        ),
    ]


def format_matrix(bundle: Bundle, dimensions: Sequence[Dimension]) -> str:
    title = f"{bundle.record} {bundle.name}".strip() or "bundle"
    counts = {
        status: sum(1 for d in dimensions if d.status == status)
        for status in ("complete", "partial", "missing")
    }
    lines = [
        (
            f"{title}: elicitation matrix ({counts['complete']} complete, "
            f"{counts['partial']} partial, {counts['missing']} missing)"
        )
    ]
    for dimension in dimensions:
        found = "; ".join(dimension.found) or "-"
        lines.append(f"{dimension.number}. {dimension.name:<20}{dimension.status:<10}{found}")
        if dimension.gaps:
            lines.append(f"{'':33}gaps: {'; '.join(dimension.gaps)}")
            lines.append(f"{'':33}fill: {dimension.fields}")
    status, detail = goal_alignment(bundle)
    lines.append(f"Goal alignment: {status} ({detail})")
    pending = [f"{d.number}. {d.name}" for d in dimensions if d.status != "complete"]
    lines.append(
        "Elicit next: " + ", ".join(pending) if pending else "All five dimensions are answered."
    )
    return "\n".join(lines)


# --- Render, fingerprint, and verify ------------------------------------------------


def load_field_ids(source: str) -> dict[str, str]:
    """Map field names to field IDs from an Aha! fields_metadata JSON dump."""
    document = parse_json_text(read_text(source))
    node = document.get("result", document) if isinstance(document, dict) else document
    fields = node.get("fields") if isinstance(node, dict) else None
    mapping: dict[str, str] = {}
    for item in fields if isinstance(fields, list) else []:
        if isinstance(item, dict) and item.get("name") and item.get("field_id"):
            mapping[field_key(str(item["name"]))] = str(item["field_id"])
    return mapping


def render_bundle(
    bundle: Bundle,
    context: aha_html.LinkContext,
    field_ids: dict[str, str] | None = None,
    layouts: dict[tuple[str, str], aha_html.TableLayouts] | None = None,
) -> dict[str, Any]:
    """Convert every text section to Aha! Editor HTML, ready for manage_record.

    layouts (from record_layouts on the record re-read before writing) keep each live
    table's classes and column widths when its header row is unchanged.
    """

    def to_html(section: Section) -> str:
        pool = layouts.get(layout_key(section)) if layouts is not None else None
        return aha_html.markdown_to_html(section.body, context, pool)

    fields: list[dict[str, Any]] = []
    for section in bundle.fields():
        entry: dict[str, Any] = {"name": section.title, "html": to_html(section)}
        if field_ids is not None:
            entry["field_id"] = field_ids.get(field_key(section.title))
        fields.append(entry)
    return {
        "record": bundle.record,
        "text_field_format": "aha_editor_html",
        "fingerprint": fingerprint(bundle),
        "fields": fields,
        "requirements": [
            {"ref": section.ref, "name": section.title, "html": to_html(section)}
            for section in bundle.requirements()
        ],
        "elicitation": bundle.elicitation(),
        "to_dos": [{"name": section.title, "html": to_html(section)} for section in bundle.todos()],
    }


def visible_text(markdown: str) -> str:
    """Reduce Markdown to its visible words, so a draft and an Aha! re-read compare equal."""
    text = markdown.translate(QUOTE_TRANSLATION)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = aha_html.AUTOLINK_RE.sub(lambda match: match.group(1), text)
    text = aha_html.IMAGE_RE.sub(lambda match: match.group("alt"), text)
    text = aha_html.LINK_RE.sub(lambda match: match.group("text"), text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", " ", text)
    text = "\n".join(
        "" if "-" in line and aha_html.TABLE_SEPARATOR_RE.match(line) else line
        for line in text.split("\n")
    )
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|(?:>\s?)+)", " ", text)
    text = re.sub(r"\[![A-Za-z]+\]", " ", text)
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", " ", text)
    text = re.sub(r"\\(.)", r"\1", text)
    text = re.sub(r"[*_`|~\\]", " ", text)
    return " ".join(text.split())


def fingerprint_parts(bundle: Bundle) -> list[tuple[str, str]]:
    """Return the specification content that an approval covers, in a stable order."""
    parts: list[tuple[str, str]] = []
    for name in SPEC_FIELDS:
        body = bundle.field_text(name)
        if body.strip():
            parts.append((f"field:{name}", visible_text(body)))
    # Requirements are keyed by name, not reference, so creating one doesn't change the hash.
    requirements = sorted(
        bundle.requirements(), key=lambda s: (field_key(s.title), visible_text(s.body))
    )
    parts.extend(
        (f"requirement:{visible_text(section.title)}", visible_text(section.body))
        for section in requirements
    )
    return parts


def fingerprint(bundle: Bundle) -> str:
    digest = hashlib.sha256()
    for key, text in fingerprint_parts(bundle):
        digest.update(f"{key}\x00{text}\x00".encode())
    return "sha256:" + digest.hexdigest()[:16]


@dataclass
class Comparison:
    label: str
    status: str
    detail: str = ""


def describe_difference(expected: str, actual: str, limit: int = 3) -> str:
    want, got = expected.split(), actual.split()
    notes: list[str] = []
    matcher = difflib.SequenceMatcher(a=want, b=got, autojunk=False)
    for tag, start, end, other_start, other_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        context = " ".join(want[max(0, start - 4) : start])
        notes.append(
            f"after '{context}': expected '{' '.join(want[start:end])[:80]}', "
            f"found '{' '.join(got[other_start:other_end])[:80]}'"
        )
        if len(notes) == limit:
            break
    return "; ".join(notes)


def compare_bundles(expected: Bundle, actual: Bundle) -> list[Comparison]:
    """Compare what was written (expected) with what Aha! returns (actual)."""
    results: list[Comparison] = []
    for section in expected.sections:
        if section.kind in ("settings", "elicitation"):
            continue
        if section.kind == "field":
            other = actual.get_field(section.title)
        elif section.kind == "requirement":
            other = actual.find_requirement(section.ref, section.title)
        else:
            other = actual.find_todo(section.title)
        if other is None:
            results.append(Comparison(section.label, "missing", "not found in the re-read record"))
            continue
        if section.kind == "todo" and not other.body.strip():
            results.append(Comparison(section.label, "ok", "name matched; the re-read has no body"))
            continue
        want, got = visible_text(section.body), visible_text(other.body)
        if want == got:
            results.append(Comparison(section.label, "ok"))
        else:
            results.append(Comparison(section.label, "changed", describe_difference(want, got)))
    return results


# --- Export (on request only) -------------------------------------------------------

SPEC_KIT_PRIORITY = {"P0": "P1", "P1": "P2", "P2": "P3", "P3": "P3"}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "feature"


def git_root(path: Path) -> Path | None:
    """Return the work tree root that contains path, or None outside git."""
    try:
        result = subprocess.run(  # noqa: S603 -- fixed git argv; path is a single argument
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


@dataclass
class ExportSource:
    """A parsed specification plus the provenance every exported file carries."""

    spec: Spec
    fingerprint: str
    exported_on: str
    slug_override: str | None = None

    @property
    def bundle(self) -> Bundle:
        return self.spec.bundle

    @property
    def record(self) -> str:
        return self.bundle.record or "the Aha! record"

    @property
    def name(self) -> str:
        return self.bundle.name or self.bundle.record or "Feature"

    @property
    def url(self) -> str:
        url = self.bundle.meta.get("url", "")
        domain = self.bundle.meta.get("aha-domain", "")
        if not url and domain and self.bundle.record:
            url = f"https://{domain}/features/{self.bundle.record}"
        return url

    @property
    def slug(self) -> str:
        return self.slug_override or self.bundle.meta.get("slug") or slugify(self.name)


def _provenance(source: ExportSource) -> str:
    where = f" ({source.url})" if source.url else ""
    return (
        f"<!-- Exported from Aha! {source.record} {source.name}{where} on {source.exported_on}. "
        f"Source fingerprint: {source.fingerprint}. Aha! is the system of record: "
        "change the record there, then export again. -->"
    )


def _confirm(source: ExportSource) -> list[str]:
    return [
        "## Confirm before building",
        "",
        (
            "Before you write code, restate each FR and NFR statement in your own words and list any "
            "acceptance scenario you find ambiguous. Don't start until a person confirms the restatement."
        ),
        "",
        f"These requirements come from Aha! {source.record}. Propose changes there, not in this file.",
        "",
        (
            "When you finish, show evidence for each acceptance scenario: the command you ran and its "
            'output. "Should pass" is not evidence.'
        ),
        "",
    ]


def _traceability(source: ExportSource) -> list[str]:
    lines = [
        "## Traceability",
        "",
        "| Statement | Priority | Aha! requirement | Use cases | Verified by |",
        "|---|---|---|---|---|",
    ]
    for requirement in source.spec.requirements:
        section = requirement.section
        record = f"{section.ref} {section.title}" if section.ref else section.title
        cases = "all" if requirement.covers_all else _ids("UC", sorted(requirement.covers_uc))
        criteria = _ids("AC", sorted(requirement.verified_ac))
        for statement in requirement.statements:
            lines.append(
                f"| {statement.sid} | {statement.priority or ''} | {_table_cell(record)} "
                f"| {cases} | {criteria} |"
            )
    lines.append("")
    return lines


def _paragraphs(markdown: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]


def _first_sentence(text: str) -> str:
    plain = aha_html.plain_text(text)
    match = re.match(r"(.+?[.!?])(?:\s|$)", plain)
    return match.group(1) if match else plain


def _clause(parts: list[str]) -> str:
    return " and ".join(part.strip().rstrip(" .,;") for part in parts if part.strip())


def _gwt(criterion: Criterion) -> str:
    given = _clause(criterion.clauses.get("given", []))
    when = _clause(criterion.clauses.get("when", []))
    then = _clause(criterion.clauses.get("then", []))
    return f"**Given** {given}, **When** {when}, **Then** {then}."


def _short_title(text: str) -> str:
    head = text.split(":", 1)[0].strip().rstrip(".")
    words = head.split()
    return " ".join(words[:10]) + (" ..." if len(words) > 10 else "")


def _requirement_criteria(spec: Spec, requirement: RequirementInfo) -> list[Criterion]:
    return [spec.criteria[n] for n in sorted(requirement.verified_ac) if n in spec.criteria]


def _story_criteria(spec: Spec, number: int | None) -> list[Criterion]:
    numbers: set[int] = set()
    for requirement in spec.requirements:
        if number is None or requirement.covers_all or number in requirement.covers_uc:
            numbers |= requirement.verified_ac
    return [spec.criteria[n] for n in sorted(numbers) if n in spec.criteria]


def speckit_files(source: ExportSource, repo: Path, number: int | None) -> dict[Path, str]:
    """Spec Kit: specs/NNN-slug/spec.md, following the spec-template sections."""
    spec = source.spec
    if number is None:
        existing = [
            int(match.group(1))
            for child in (repo / "specs").glob("*")
            if child.is_dir() and (match := re.match(r"(\d{3})-", child.name))
        ]
        number = max(existing, default=0) + 1
    branch = f"{number:03d}-{source.slug}"
    where = f" ({source.url})" if source.url else ""
    lines = [
        _provenance(source),
        "",
        f"# Feature Specification: {source.name}",
        "",
        f"**Feature Branch**: `{branch}`",
        "",
        f"**Created**: {source.exported_on}",
        "",
        "**Status**: Draft",
        "",
        f"**Input**: Aha! feature {source.record}{where}",
        "",
        "## User Scenarios & Testing *(mandatory)*",
        "",
    ]
    stories: list[tuple[str, str, str | None, list[Criterion], str]] = [
        (
            _short_title(case.text),
            _story_sentence(spec, case.text, case.text),
            case.priority,
            _story_criteria(spec, case.number),
            f"UC-{case.number}",
        )
        for case in sorted(spec.use_cases.values(), key=lambda case: case.number)
    ]
    if not stories:
        text = _story_sentence(spec, None, source.name) if spec.user_story else source.name
        stories.append((source.name, text, None, _story_criteria(spec, None), "the feature"))
    for index, (title, text, priority, criteria, label) in enumerate(stories, start=1):
        lines.extend(
            [
                f"### User Story {index} - {title} (Priority: {SPEC_KIT_PRIORITY.get(priority or '', 'P3')})",
                "",
                text,
                "",
                f"**Why this priority**: {label} has priority {priority or 'unset'} in Aha! {source.record}.",
                "",
                f"**Independent Test**: The acceptance scenarios below pass ({_ids('AC', [c.number for c in criteria]) or 'none yet'}).",
                "",
                "**Acceptance Scenarios**:",
                "",
            ]
        )
        lines.extend(f"{n}. {_gwt(criterion)}" for n, criterion in enumerate(criteria, start=1))
        if not criteria:
            lines.append(
                "1. [NEEDS CLARIFICATION: no acceptance criterion in Aha! covers this story]"
            )
        lines.extend(["", "---", ""])
    stops = next((text for name, text in spec.definition.items() if name.startswith("stops")), "")
    if stops:
        lines.extend(["### Edge Cases", "", *(f"- {item}" for item in split_items(stops)), ""])
    statements = [
        (requirement, statement)
        for requirement in spec.requirements
        for statement in requirement.statements
    ]

    def requirement_line(requirement: RequirementInfo, statement: Statement) -> str:
        ref = requirement.section.ref or requirement.section.title
        return f"- **{statement.sid}**: {statement.text} *(priority {statement.priority or 'unset'}; Aha! {ref})*"

    functional = [requirement_line(r, s) for r, s in statements if s.sid.startswith("FR")]
    quality = [requirement_line(r, s) for r, s in statements if s.sid.startswith("NFR")]
    lines.extend(["## Requirements *(mandatory)*", "", "### Functional Requirements", ""])
    lines.extend(
        functional or ["- [NEEDS CLARIFICATION: Aha! has no EARS statements for this feature]"]
    )
    if quality:
        lines.extend(["", "### Non-Functional Requirements", "", *quality])
    outcomes = bullet_items(spec.done or "")
    lines.extend(["", "## Success Criteria *(mandatory)*", "", "### Measurable Outcomes", ""])
    lines.extend(f"- **SC-{n:03d}**: {item}" for n, item in enumerate(outcomes, start=1))
    if not outcomes:
        lines.append("- **SC-001**: [NEEDS CLARIFICATION: Aha! has no Definition of Done]")
    dependencies = bullet_items(source.bundle.field_text("Dependencies (upstream)"))
    if dependencies:
        lines.extend(["", "## Assumptions", "", *(f"- {item}" for item in dependencies)])
    if spec.out_of_scope:
        lines.extend(["", "## Out of Scope", "", *(f"- {item}" for item in spec.out_of_scope)])
    lines.extend(["", *_traceability(source), *_confirm(source)])
    return {repo / "specs" / branch / "spec.md": "\n".join(lines).rstrip() + "\n"}


def _scenarios(spec: Spec, requirement: RequirementInfo, statement: Statement) -> list[str]:
    lines: list[str] = []
    derived = EARS_CLAUSE_RE.match(aha_html.plain_text(statement.text))
    if derived is not None:
        lines.extend(
            [
                f"#### Scenario: {statement.sid} as specified",
                f"- **WHEN** {derived.group('condition').strip()}",
                f"- **THEN** {derived.group('response').strip()}",
                "",
            ]
        )
    for criterion in _requirement_criteria(spec, requirement):
        lines.append(f"#### Scenario: AC-{criterion.number} {criterion.title}".rstrip())
        if criterion.clauses.get("given"):
            lines.append(f"- **GIVEN** {_clause(criterion.clauses['given'])}")
        lines.append(
            f"- **WHEN** {_clause(criterion.clauses.get('when', [])) or 'the scenario runs'}"
        )
        lines.append(
            f"- **THEN** {_clause(criterion.clauses.get('then', [])) or 'the criterion holds'}"
        )
        lines.append("")
    return lines


def openspec_files(
    source: ExportSource,
    repo: Path,
    change_id: str | None,
    capability: str | None,
    existing: bool,
) -> tuple[dict[Path, str], list[str]]:
    """OpenSpec: a change folder with .openspec.yaml, proposal.md, and one spec delta."""
    spec = source.spec
    warnings: list[str] = []
    change_id = change_id or f"add-{source.slug}"
    capability = capability or source.slug
    base = repo / "openspec" / "changes" / change_id
    metadata = "\n".join(
        [
            "schema: spec-driven",
            f"created: {source.exported_on}",
            f"x-aha-record: {source.record}",
            f'x-aha-url: "{source.url}"',
            f'x-aha-fingerprint: "{source.fingerprint}"',
            "",
        ]
    )
    summary = _first_sentence(source.bundle.field_text("Summary")) or source.name
    purpose = _purpose(source)
    why = _paragraphs(source.bundle.field_text("Business Problem")) or [summary]
    proposal = [
        _provenance(source),
        "",
        f"# Proposal: {source.name}",
        "",
        "## Why",
        "",
        why[0],
        "",
        "## What Changes",
        "",
    ]
    for requirement in spec.requirements:
        ids = ", ".join(statement.sid for statement in requirement.statements) or "no statements"
        removed = any(statement.change == "REMOVED" for statement in requirement.statements)
        scope = f": {requirement.scope}" if requirement.scope else ""
        ref = f"{requirement.section.ref}; " if requirement.section.ref else ""
        proposal.append(
            f"- {'**BREAKING** ' if removed else ''}{requirement.section.title}{scope} ({ref}{ids})"
        )
    entry = f"- `{capability}`: {purpose}"
    proposal.extend(["", "## Capabilities", "", "### New Capabilities", ""])
    proposal.extend([] if existing else [entry])
    proposal.extend(["", "### Modified Capabilities", ""])
    proposal.extend([entry] if existing else [])
    proposal.extend(
        [
            "",
            "## Impact",
            "",
            f"- Aha! {source.record} ({source.url or 'no URL'}) is the system of record.",
        ]
    )
    proposal.extend(
        f"- Depends on: {item}"
        for item in bullet_items(source.bundle.field_text("Dependencies (upstream)"))
    )
    proposal.extend(["", *_traceability(source), *_confirm(source)])

    delta = [_provenance(source), "", "# Spec Delta", ""]
    if not existing:
        delta.extend(["## Purpose", "", purpose, ""])
    groups: dict[str, list[tuple[RequirementInfo, Statement]]] = {
        "ADDED": [],
        "MODIFIED": [],
        "REMOVED": [],
    }
    for requirement in spec.requirements:
        for statement in requirement.statements:
            groups[statement.change or "ADDED"].append((requirement, statement))
    if not existing and (groups["MODIFIED"] or groups["REMOVED"]):
        warnings.append(
            "MODIFIED or REMOVED statements change an existing capability: rerun with "
            "--existing-capability and match the existing requirement headers."
        )
    for change, items in groups.items():
        if not items:
            continue
        delta.extend([f"## {change} Requirements", ""])
        for requirement, statement in items:
            delta.append(f"### Requirement: {statement.sid} {requirement.section.title}")
            if change == "REMOVED":
                delta.extend(
                    [
                        f"**Reason**: {statement.text}",
                        f"**Migration**: [Describe the migration in Aha! {source.record}]",
                        "",
                    ]
                )
                continue
            delta.extend([statement.text, ""])
            if len(statement.text) > 500:
                warnings.append(
                    f"{statement.sid} is over 500 characters; openspec validate --strict rejects it."
                )
            scenarios = _scenarios(spec, requirement, statement)
            if not scenarios:
                warnings.append(
                    f"{statement.sid} has no scenario; add an acceptance criterion in Aha!."
                )
                scenarios = [
                    f"#### Scenario: {statement.sid} holds",
                    "- **WHEN** the capability is in use",
                    f"- **THEN** {statement.text}",
                    "",
                ]
            delta.extend(scenarios)
    if not spec.statements():
        warnings.append("No EARS statements to export; lint the bundle first.")
    files = {
        base / ".openspec.yaml": metadata,
        base / "proposal.md": "\n".join(proposal).rstrip() + "\n",
        base / "specs" / capability / "spec.md": "\n".join(delta).rstrip() + "\n",
    }
    return files, warnings


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _story_sentence(spec: Spec, use_case: str | None, fallback: str) -> str:
    """Write a user story from the feature's story, focused on one use case when given."""
    story = spec.user_story or {}
    persona = story.get("persona", "user")
    benefit = story.get("so", "the feature delivers its value")
    if use_case:
        text = use_case.rstrip(".")
        want = "to " + text[:1].lower() + text[1:]
    else:
        want = story.get("want", fallback)
    return f"As {_article(persona)} {persona}, I want {want}, so that {benefit}."


def _purpose(source: ExportSource) -> str:
    """Say what the capability is for, from the user story when there is one."""
    story = source.spec.user_story
    summary = _first_sentence(source.bundle.field_text("Summary"))
    if story is None:
        return summary or source.name
    want = story["want"]
    purpose = f"{want[:1].upper()}{want[1:]}, for {_article(story['persona'])} {story['persona']}."
    return purpose if len(purpose) >= 50 or not summary else f"{purpose} {summary}"


def _kiro_story(spec: Spec, requirement: RequirementInfo) -> str:
    cases = [spec.use_cases[n] for n in sorted(requirement.covers_uc) if n in spec.use_cases]
    return _story_sentence(spec, cases[0].text if cases else None, requirement.section.title)


def kiro_files(source: ExportSource, repo: Path) -> dict[Path, str]:
    """Kiro: .kiro/specs/slug/requirements.md with EARS acceptance criteria."""
    spec = source.spec
    summary = aha_html.plain_text(source.bundle.field_text("Summary")) or source.name
    where = f" ({source.url})" if source.url else ""
    lines = [
        _provenance(source),
        "",
        "# Requirements Document",
        "",
        "## Introduction",
        "",
        summary,
        "",
        f"Source: Aha! {source.record}{where}.",
        "",
    ]
    if spec.out_of_scope:
        lines.extend(["### Out of scope", "", *(f"- {item}" for item in spec.out_of_scope), ""])
    lines.extend(["## Requirements", ""])
    for index, requirement in enumerate(spec.requirements, start=1):
        lines.extend(
            [
                f"### Requirement {index}: {requirement.section.title}",
                "",
                f"**User Story:** {_kiro_story(spec, requirement)}",
                "",
                "#### Acceptance Criteria",
                "",
            ]
        )
        for number, statement in enumerate(requirement.statements, start=1):
            marker = (
                f"{statement.sid}, {statement.priority}" if statement.priority else statement.sid
            )
            lines.append(f"{number}. {statement.text} ({marker})")
        if not requirement.statements:
            lines.append("1. [Add EARS statements to this requirement in Aha!]")
        criteria = _requirement_criteria(spec, requirement)
        if criteria:
            lines.extend(["", "#### Acceptance Scenarios", ""])
            lines.extend(f"- AC-{c.number} {c.title}: {_gwt(c)}" for c in criteria)
        lines.append("")
    lines.extend(_traceability(source))
    lines.extend(_confirm(source))
    return {
        repo / ".kiro" / "specs" / source.slug / "requirements.md": "\n".join(lines).rstrip() + "\n"
    }


# --- Command line -------------------------------------------------------------------


def _write_output(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def command_bundle(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.source, args.record)
    _write_output(format_bundle(bundle), args.output)
    return 0


def command_lint(args: argparse.Namespace) -> int:
    if args.list_rules:
        for rule, description in RULES.items():
            print(f"{rule:<9}{description}")
        return 0
    if not args.source:
        print(
            "error: lint needs a source file (usage: aha_feature.py lint [--gate GATE] SOURCE; "
            "use - for stdin, --list-rules to list rules)",
            file=sys.stderr,
        )
        return 2
    bundle = load_bundle(args.source, args.record)
    profile = args.profile or bundle.meta.get("profile") or "agent"
    findings = lint(bundle, args.gate, profile)
    if args.format == "json":
        report = {
            "record": bundle.record,
            "name": bundle.name,
            "gate": args.gate,
            "profile": profile,
            "summary": summarize(findings),
            "findings": [finding.as_dict() for finding in findings],
        }
        print(json.dumps(report, indent=2))
    else:
        print(format_findings(bundle, findings, args.gate, profile))
    failing = {"error"} if args.fail_on == "error" else {"error", "warning"}
    return 1 if any(finding.severity in failing for finding in findings) else 0


def command_render(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.source, args.record)
    field_ids = load_field_ids(args.fields_metadata) if args.fields_metadata else None
    layouts = None
    if args.layout_from:
        live = select_record(
            iter_records(parse_json_text(read_text(args.layout_from))),
            args.record or bundle.record or None,
        )
        layouts = record_layouts(live)
    payload = render_bundle(
        bundle, bundle.link_context(args.aha_domain, args.link_prefix), field_ids, layouts
    )
    if field_ids is not None:
        for entry in payload["fields"]:
            if entry["field_id"] is None:
                print(
                    f"warning: no field_id for {entry['name']!r} in fields_metadata",
                    file=sys.stderr,
                )
    for (kind, name), pool in (layouts or {}).items():
        for layout in pool.unused():
            widths = ", ".join(layout.widths) or "none"
            print(
                f"warning: {kind} {name!r}: no table with header {' | '.join(layout.header)!r};"
                f" its column widths ({widths}) and classes will reset",
                file=sys.stderr,
            )
    _write_output(json.dumps(payload, indent=2) + "\n", args.output)
    return 0


def command_matrix(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.source, args.record)
    profile = args.profile or bundle.meta.get("profile") or "agent"
    dimensions = assess_matrix(bundle, profile)
    if args.format == "json":
        status, detail = goal_alignment(bundle)
        report = {
            "record": bundle.record,
            "name": bundle.name,
            "dimensions": [dimension.as_dict() for dimension in dimensions],
            "goal_alignment": {"status": status, "detail": detail},
        }
        print(json.dumps(report, indent=2))
    else:
        print(format_matrix(bundle, dimensions))
    return 0 if all(d.status == "complete" for d in dimensions) else 1


def command_fingerprint(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.source, args.record)
    if args.format == "json":
        parts = [
            {"part": key, "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]}
            for key, text in fingerprint_parts(bundle)
        ]
        print(
            json.dumps(
                {"record": bundle.record, "fingerprint": fingerprint(bundle), "parts": parts},
                indent=2,
            )
        )
    else:
        print(fingerprint(bundle))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    expected = load_bundle(args.expected)
    actual = load_bundle(args.actual, args.record or expected.record or None)
    results = compare_bundles(expected, actual)
    for result in results:
        detail = f": {result.detail}" if result.detail else ""
        print(f"{result.status.upper():<8}{result.label}{detail}")
    failures = sum(1 for result in results if result.status != "ok")
    expected_print, actual_print = fingerprint(expected), fingerprint(actual)
    print(f"fingerprint: expected {expected_print}, re-read {actual_print}")
    print(f"{len(results) - failures} of {len(results)} sections match.")
    return 1 if failures else 0


def command_export(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser()
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 2
    if git_root(repo) is None:
        print(
            f"error: {repo} is not inside a git work tree. SDD artifacts belong in a git "
            "repository: choose one, or run 'git init' there first.",
            file=sys.stderr,
        )
        return 2
    bundle = load_bundle(args.source, args.record)
    profile = args.profile or bundle.meta.get("profile") or "agent"
    spec = analyze(bundle, profile)
    source = ExportSource(
        spec, fingerprint(bundle), args.date or dt.date.today().isoformat(), args.slug
    )
    warnings: list[str] = []
    if args.format == "speckit":
        files = speckit_files(source, repo, args.number)
    elif args.format == "openspec":
        files, warnings = openspec_files(
            source, repo, args.change_id, args.capability, args.existing_capability
        )
    else:
        files = kiro_files(source, repo)
    errors = summarize(lint(bundle, "ready", profile))["error"]
    if errors:
        warnings.append(
            f"the source has {errors} error(s) at the ready gate; export it as a draft only."
        )
    conflicts = [path for path in files if path.exists()]
    if conflicts and not args.force:
        listed = ", ".join(str(path) for path in conflicts)
        print(f"error: already exists: {listed}. Use --force to overwrite.", file=sys.stderr)
        return 2
    for message in warnings:
        print(f"warning: {message}", file=sys.stderr)
    if args.dry_run:
        for path, content in files.items():
            print(f"==> {path} <==\n{content}")
        return 0
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path}")
    print("Review the files, then commit them in the repository. Nothing was committed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint, render, verify, and export Aha! feature specifications."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    source_help = "Bundle (.md), or an Aha! read_records JSON dump; - reads stdin"

    bundle = commands.add_parser("bundle", help="JSON dump to a bundle")
    bundle.add_argument("source", help="Aha! read_records JSON dump")
    bundle.add_argument("-o", "--output", help="Write here instead of stdout")
    bundle.add_argument("--record", help="Record to use when the dump holds several")
    bundle.set_defaults(handler=command_bundle)

    lint_parser = commands.add_parser("lint", help="Check a bundle against a gate")
    lint_parser.add_argument("source", nargs="?", help=source_help)
    lint_parser.add_argument("--gate", choices=GATES, default="elaborated")
    lint_parser.add_argument("--profile", choices=PROFILES, help="Overrides the bundle's profile")
    lint_parser.add_argument("--format", choices=("text", "json"), default="text")
    lint_parser.add_argument("--fail-on", choices=("error", "warning"), default="error")
    lint_parser.add_argument("--record", help="Record to use when the dump holds several")
    lint_parser.add_argument("--list-rules", action="store_true", help="Print the rule catalog")
    lint_parser.set_defaults(handler=command_lint)

    render = commands.add_parser("render", help="Bundle to Aha! Editor HTML payloads")
    render.add_argument("source", help=source_help)
    render.add_argument("-o", "--output", help="Write the JSON payload here instead of stdout")
    render.add_argument("--fields-metadata", help="fields_metadata JSON dump, to add field_id")
    render.add_argument(
        "--layout-from",
        help=(
            "The record re-read as HTML before writing (read_records JSON); tables keep"
            " their column widths and classes"
        ),
    )
    render.add_argument("--aha-domain", help="Aha! host for record mentions, e.g. example.aha.io")
    render.add_argument(
        "--link-prefix",
        action="append",
        default=[],
        help="Extra workspace prefix to link (repeatable)",
    )
    render.add_argument("--record", help="Record to use when the dump holds several")
    render.set_defaults(handler=command_render)

    matrix = commands.add_parser("matrix", help="Score the five elicitation dimensions")
    matrix.add_argument("source", help=source_help)
    matrix.add_argument("--profile", choices=PROFILES, help="Overrides the bundle's profile")
    matrix.add_argument("--format", choices=("text", "json"), default="text")
    matrix.add_argument("--record", help="Record to use when the dump holds several")
    matrix.set_defaults(handler=command_matrix)

    print_parser = commands.add_parser("fingerprint", help="Hash the specification content")
    print_parser.add_argument("source", help=source_help)
    print_parser.add_argument("--format", choices=("text", "json"), default="text")
    print_parser.add_argument("--record", help="Record to use when the dump holds several")
    print_parser.set_defaults(handler=command_fingerprint)

    verify = commands.add_parser("verify", help="Compare an applied bundle with a re-read")
    verify.add_argument("expected", help="The bundle that was applied")
    verify.add_argument("actual", help="read_records JSON dump taken after the write")
    verify.add_argument("--record", help="Record to use when the dump holds several")
    verify.set_defaults(handler=command_verify)

    export = commands.add_parser("export", help="On request: write SDD files into a git repo")
    export.add_argument("source", help=source_help)
    export.add_argument("--format", choices=("speckit", "openspec", "kiro"), required=True)
    export.add_argument("--repo", required=True, help="Directory inside a git work tree")
    export.add_argument("--slug", help="Folder name; defaults to the feature name")
    export.add_argument("--number", type=int, help="Spec Kit feature number; defaults to the next")
    export.add_argument("--change-id", help="OpenSpec change ID; defaults to add-<slug>")
    export.add_argument("--capability", help="OpenSpec capability path; defaults to the slug")
    export.add_argument(
        "--existing-capability",
        action="store_true",
        help="OpenSpec: the capability already exists, so omit Purpose",
    )
    export.add_argument("--profile", choices=PROFILES, help="Overrides the bundle's profile")
    export.add_argument("--date", help="Export date (YYYY-MM-DD); defaults to today")
    export.add_argument("--force", action="store_true", help="Overwrite existing files")
    export.add_argument("--dry-run", action="store_true", help="Print the files; write nothing")
    export.add_argument("--record", help="Record to use when the dump holds several")
    export.set_defaults(handler=command_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.handler(args)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
