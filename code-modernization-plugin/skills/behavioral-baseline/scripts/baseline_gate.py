#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Freeze and verify behavioral test baselines, load rulebooks, and run quality gates.

Supports four subcommands for the Refactor and Rearchitect playbooks:

- ``rulebook``: scan ``.modernize/rulebook/*.md``, ``.github/modernize/rulebook/*.md``, and
  ``.modernize/learnings/*.md`` and emit a structured summary of active policies and learnings.
- ``freeze``: validate ``test-cases.md`` (and optional ``infra-decision-table.md`` and
  ``testdata/`` fixtures) and write a SHA-256 ``manifest.json`` locking the baseline before
  Stage 3 code changes begin.
- ``verify``: check that no frozen baseline file was modified or deleted and that the test
  suite has a 1:1 mapping for every ``TC-XXX`` test case without ``TODO``/``FIXME`` stubs.
- ``gate``: run ``spec-quality``, ``spec-to-plan``, ``plan-to-tasks``, or ``completeness``
  validation over ``traceability.json`` (and optional ``baseline/manifest.json``).

Examples:
    uv run --script scripts/baseline_gate.py rulebook . --format markdown
    uv run --script scripts/baseline_gate.py freeze .modernize/baseline
    uv run --script scripts/baseline_gate.py gate .modernize --type plan-to-tasks
    uv run --script scripts/baseline_gate.py verify .modernize/baseline tests/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

TC_HEADING = re.compile(
    r"^(?:#{2,4}\s+|[-*]\s+\*\*|\|\s*)(TC-\d{3,})\b[ \t:|*]*(.*)$", re.MULTILINE
)
TC_TOKEN = re.compile(r"(?<![A-Za-z0-9])TC[-_]?(\d{3,})(?![0-9])", re.IGNORECASE)
REQ_ID = re.compile(r"^(?:REQ|BR)-\d{3,}$")
TASK_ID = re.compile(r"^T-\d{3,}$")
TC_ID = re.compile(r"^TC-\d{3,}$")
TESTDATA_PATH = re.compile(r"\b(testdata/[A-Za-z0-9_./-]+)")
VAGUE_PHRASES = re.compile(
    r"\b(?:behaves?\s+as\s+expected|works?\s+properly|reasonable\s+error|"
    r"appropriate\s+response|as\s+usual)\b|\[NEEDS\s+CLARIFICATION",
    re.IGNORECASE,
)
VALID_STRATEGIES = frozenset({"mock", "testcontainer", "emulator", "golden-file", "real"})
TEST_SUFFIXES = frozenset({".py", ".java", ".cs", ".ts", ".tsx", ".js", ".go", ".cbl", ".jcl"})
GATE_TYPES = ("spec-quality", "spec-to-plan", "plan-to-tasks", "completeness")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_tc(raw: str) -> str:
    match = TC_TOKEN.search(raw)
    if not match:
        return raw.upper()
    return f"TC-{int(match.group(1)):03d}"


def parse_test_cases(text: str) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """Return (test_cases, referenced_fixtures, issues) from ``test-cases.md``."""
    matches = list(TC_HEADING.finditer(text))
    cases: list[dict[str, str]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for idx, match in enumerate(matches):
        tc_id = _normalize_tc(match.group(1))
        title = match.group(2).strip(" |*:-")
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[match.start() : end]
        if tc_id in seen:
            issues.append(f"duplicate test case ID {tc_id}")
        seen.add(tc_id)
        if not title:
            issues.append(f"{tc_id}: missing title")
        if VAGUE_PHRASES.search(body):
            issues.append(f"{tc_id}: contains vague phrasing or [NEEDS CLARIFICATION]")
        cases.append({"id": tc_id, "title": title})
    if not cases:
        issues.append("test-cases.md defines no TC-XXX test cases")
    fixtures = sorted(set(TESTDATA_PATH.findall(text)))
    return cases, fixtures, issues


def parse_infra_table(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """Parse ``infra-decision-table.md`` rows and validate dependency strategies."""
    decisions: list[dict[str, str]] = []
    issues: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() in {"dependency", "resource", "service"}:
            continue
        dep, kind, strategy = cells[0], cells[1], cells[2].lower()
        if strategy not in VALID_STRATEGIES:
            issues.append(
                f"infra-decision-table: {dep!r} has unknown strategy {strategy!r} "
                f"(expected one of {', '.join(sorted(VALID_STRATEGIES))})"
            )
        decisions.append({"dependency": dep, "kind": kind, "strategy": strategy})
    return decisions, issues


def freeze_baseline(baseline_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    """Validate a baseline directory and write its SHA-256 ``manifest.json``."""
    spec_path = baseline_dir / "test-cases.md"
    if not spec_path.is_file():
        return {
            "tool": "baseline_gate",
            "action": "freeze",
            "status": "FAILED",
            "issues": [f"missing required file: {spec_path}"],
        }
    spec_text = spec_path.read_text(encoding="utf-8")
    cases, fixtures, issues = parse_test_cases(spec_text)
    for rel in fixtures:
        if not (baseline_dir / rel).is_file():
            issues.append(f"referenced fixture does not exist: {rel}")

    infra_path = baseline_dir / "infra-decision-table.md"
    decisions: list[dict[str, str]] = []
    if infra_path.is_file():
        decisions, infra_issues = parse_infra_table(infra_path.read_text(encoding="utf-8"))
        issues.extend(infra_issues)

    files_to_hash: list[Path] = [spec_path]
    if infra_path.is_file():
        files_to_hash.append(infra_path)
    testdata_dir = baseline_dir / "testdata"
    if testdata_dir.is_dir():
        files_to_hash.extend(sorted(p for p in testdata_dir.rglob("*") if p.is_file()))

    digests = {path.relative_to(baseline_dir).as_posix(): _sha256(path) for path in files_to_hash}
    status = "PASSED" if not issues else "FAILED"
    manifest: dict[str, Any] = {
        "tool": "baseline_gate",
        "action": "freeze",
        "status": status,
        "test_cases": cases,
        "infra_decisions": decisions,
        "files": digests,
        "issues": issues,
    }
    if status == "PASSED":
        target = output_path or (baseline_dir / "manifest.json")
        target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _iter_test_files(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
        elif root.is_dir():
            found.extend(
                sorted(
                    p
                    for p in root.rglob("*")
                    if p.is_file()
                    and p.suffix.lower() in TEST_SUFFIXES
                    and not any(part.startswith(".") for part in p.relative_to(root).parts)
                )
            )
    return found


def verify_baseline(baseline_dir: Path, test_roots: Sequence[Path]) -> dict[str, Any]:
    """Verify frozen file digests and 1:1 ``TC-XXX`` coverage across ``test_roots``."""
    manifest_path = baseline_dir / "manifest.json"
    if not manifest_path.is_file():
        return {
            "tool": "baseline_gate",
            "action": "verify",
            "status": "FAILED",
            "issues": [f"missing frozen manifest: {manifest_path} (run freeze first)"],
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files: dict[str, str] = manifest.get("files", {})
    issues: list[str] = []

    for rel, expected_hash in sorted(expected_files.items()):
        file_path = baseline_dir / rel
        if not file_path.is_file():
            issues.append(f"frozen file was deleted: {rel}")
        elif _sha256(file_path) != expected_hash:
            issues.append(f"frozen file was modified after freeze: {rel}")

    testdata_dir = baseline_dir / "testdata"
    if testdata_dir.is_dir():
        for path in sorted(p for p in testdata_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(baseline_dir).as_posix()
            if rel not in expected_files:
                issues.append(f"untracked file added under frozen testdata/: {rel}")

    expected_tcs = {entry["id"] for entry in manifest.get("test_cases", [])}
    found_tcs: dict[str, list[str]] = {}
    for test_file in _iter_test_files(test_roots):
        text = test_file.read_text(encoding="utf-8", errors="replace")
        matches = {_normalize_tc(m.group(0)) for m in TC_TOKEN.finditer(text)}
        for tc_id in sorted(matches):
            found_tcs.setdefault(tc_id, []).append(str(test_file))
        if matches and re.search(r"\b(?:TODO|FIXME)\b", text):
            issues.append(f"{test_file}: contains TODO/FIXME marker in a TC-mapped test file")

    missing_tcs = sorted(expected_tcs - set(found_tcs))
    extra_tcs = sorted(set(found_tcs) - expected_tcs)
    if missing_tcs:
        issues.append(f"missing tests for frozen test cases: {', '.join(missing_tcs)}")
    if extra_tcs:
        issues.append(f"tests reference unknown TC IDs not in baseline: {', '.join(extra_tcs)}")

    return {
        "tool": "baseline_gate",
        "action": "verify",
        "status": "PASSED" if not issues else "FAILED",
        "expected_test_cases": sorted(expected_tcs),
        "covered_test_cases": dict(sorted(found_tcs.items())),
        "missing_test_cases": missing_tcs,
        "extra_test_cases": extra_tcs,
        "issues": issues,
    }


def load_rulebooks_and_learnings(workspace: Path) -> dict[str, Any]:
    """Scan rulebook and learnings directories and return structured rules and headers."""
    rulebook_dirs = [
        workspace / ".modernize" / "rulebook",
        workspace / ".github" / "modernize" / "rulebook",
    ]
    rulebooks: list[dict[str, Any]] = []
    for directory in rulebook_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            sections: dict[str, list[str]] = {}
            current = "General"
            for line in text.splitlines():
                heading = re.match(r"^#{1,3}\s+(.+)$", line.strip())
                if heading:
                    current = heading.group(1).strip()
                elif line.strip().startswith(("-", "*")):
                    sections.setdefault(current, []).append(line.strip().lstrip("-* ").strip())
            rulebooks.append({"path": str(path), "sections": sections})

    learnings_dir = workspace / ".modernize" / "learnings"
    learnings: list[dict[str, str]] = []
    learning_issues: list[str] = []
    if learnings_dir.is_dir():
        for path in sorted(learnings_dir.rglob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else ""
            summary = lines[2].strip() if len(lines) >= 3 and not lines[1].strip() else ""
            if not title or not summary or summary.startswith("#"):
                learning_issues.append(
                    f"{path}: learning must start with '# Title', a blank line, "
                    "and a one-sentence summary on line 3"
                )
            learnings.append({"path": str(path), "title": title, "summary": summary})

    return {
        "tool": "baseline_gate",
        "action": "rulebook",
        "rulebooks": rulebooks,
        "learnings": learnings,
        "issues": learning_issues,
    }


def run_gate(modernize_dir: Path, gate_type: str) -> dict[str, Any]:
    """Run one of the four stage quality gates on ``modernize_dir``."""
    trace_path = modernize_dir / "traceability.json"
    if not trace_path.is_file():
        return {
            "tool": "baseline_gate",
            "action": "gate",
            "gate": gate_type,
            "status": "FAILED",
            "issues": [f"missing traceability file: {trace_path}"],
        }
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    requirements = data.get("requirements", [])
    tasks = data.get("tasks", [])
    issues: list[str] = []

    workspace = modernize_dir.parent if modernize_dir.name == ".modernize" else modernize_dir
    issues.extend(load_rulebooks_and_learnings(workspace)["issues"])

    req_ids: set[str] = set()
    if not requirements:
        issues.append("traceability.json contains no requirements")
    for req in requirements:
        req_id = str(req.get("id", "")).strip()
        title = str(req.get("title", "")).strip()
        if not REQ_ID.match(req_id):
            issues.append(f"invalid requirement ID {req_id!r} (expected REQ-XXX or BR-XXX)")
        if req_id in req_ids:
            issues.append(f"duplicate requirement ID {req_id}")
        req_ids.add(req_id)
        if not title or VAGUE_PHRASES.search(title):
            issues.append(f"{req_id}: missing or vague requirement title")

    if gate_type in {"spec-to-plan", "plan-to-tasks", "completeness"}:
        covered_reqs: set[str] = set()
        if not tasks:
            issues.append("traceability.json contains no tasks")
        for task in tasks:
            covered_reqs.update(task.get("requirements", []))
        unmapped_reqs = sorted(req_ids - covered_reqs)
        if unmapped_reqs:
            issues.append(f"requirements not mapped to any task: {', '.join(unmapped_reqs)}")

    if gate_type in {"plan-to-tasks", "completeness"}:
        task_ids: set[str] = set()
        for task in tasks:
            task_id = str(task.get("id", "")).strip()
            if not TASK_ID.match(task_id):
                issues.append(f"invalid task ID {task_id!r} (expected T-XXX)")
            if task_id in task_ids:
                issues.append(f"duplicate task ID {task_id}")
            task_ids.add(task_id)
            task_reqs = set(task.get("requirements", []))
            if not task_reqs:
                issues.append(f"{task_id}: maps to no requirements")
            unknown_reqs = sorted(task_reqs - req_ids)
            if unknown_reqs:
                issues.append(
                    f"{task_id}: references unknown requirements {', '.join(unknown_reqs)}"
                )
            tcs = task.get("test_cases", [])
            if not tcs:
                issues.append(f"{task_id}: lists no TC-XXX verification test cases")
            issues.extend(
                f"{task_id}: invalid test case ID {tc_id!r} (expected TC-XXX)"
                for tc_id in tcs
                if not TC_ID.match(str(tc_id))
            )

    if gate_type == "completeness":
        incomplete = sorted(
            str(t.get("id", "?"))
            for t in tasks
            if str(t.get("status", "")).lower() not in {"done", "verified"}
        )
        if incomplete:
            issues.append(f"tasks not yet marked done or verified: {', '.join(incomplete)}")
        baseline_dir = modernize_dir / "baseline"
        if (baseline_dir / "manifest.json").is_file():
            check = verify_baseline(baseline_dir, [])
            integrity_issues = [
                i for i in check["issues"] if not i.startswith("missing tests for frozen")
            ]
            issues.extend(integrity_issues)
            manifest = json.loads((baseline_dir / "manifest.json").read_text(encoding="utf-8"))
            frozen_tcs = {c["id"] for c in manifest.get("test_cases", [])}
            referenced_tcs = {tc for t in tasks for tc in t.get("test_cases", [])}
            missing_in_baseline = sorted(referenced_tcs - frozen_tcs)
            if missing_in_baseline:
                issues.append(
                    "tasks reference TC IDs missing from frozen baseline: "
                    f"{', '.join(missing_in_baseline)}"
                )

    return {
        "tool": "baseline_gate",
        "action": "gate",
        "gate": gate_type,
        "status": "PASSED" if not issues else "FAILED",
        "requirements": len(requirements),
        "tasks": len(tasks),
        "issues": issues,
    }


def to_markdown(report: dict[str, Any]) -> str:
    """Format any ``baseline_gate`` report as Markdown."""
    action = report["action"]
    if action == "rulebook":
        lines = ["# Enterprise Rulebooks & Learnings", ""]
        if report["rulebooks"]:
            lines.append("## Active Rulebooks")
            for rb in report["rulebooks"]:
                lines.append(f"### `{rb['path']}`")
                for section, items in rb["sections"].items():
                    lines.append(f"- **{section}:** {'; '.join(items)}")
            lines.append("")
        else:
            lines += ["No rulebook files found.", ""]
        if report["learnings"]:
            lines.append("## Recorded Learnings")
            for item in report["learnings"]:
                lines.append(f"- **{item['title']}** (`{item['path']}`): {item['summary']}")
            lines.append("")
        if report["issues"]:
            lines.extend(["## Issues", *[f"- {i}" for i in report["issues"]], ""])
        return "\n".join(lines)

    heading = f"{action.upper()}" + (f" ({report['gate']})" if "gate" in report else "")
    lines = [f"# Baseline Gate: {heading} — {report['status']}", ""]
    if "test_cases" in report:
        lines.append(f"- **Frozen test cases:** {len(report['test_cases'])}")
        lines.append(f"- **Frozen files:** {len(report.get('files', {}))}")
    if "expected_test_cases" in report:
        lines.append(f"- **Expected test cases:** {len(report['expected_test_cases'])}")
        lines.append(f"- **Covered test cases:** {len(report['covered_test_cases'])}")
    if "requirements" in report:
        lines.append(f"- **Requirements:** {report['requirements']}")
        lines.append(f"- **Tasks:** {report['tasks']}")
    if report.get("issues"):
        lines.extend(["", "## Issues", *[f"- {issue}" for issue in report["issues"]]])
    return "\n".join(lines) + "\n"


def _emit(report: dict[str, Any], fmt: str) -> int:
    if fmt == "markdown":
        print(to_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2))
    if report.get("status") == "FAILED" or report.get("issues"):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rb = sub.add_parser("rulebook", help="Load enterprise rulebooks and learnings.")
    rb.add_argument("workspace", type=Path, help="Workspace root directory.")
    rb.add_argument("--format", choices=("json", "markdown"), default="json")

    fr = sub.add_parser("freeze", help="Validate and freeze a behavioral baseline directory.")
    fr.add_argument("baseline_dir", type=Path, help="Path to baseline directory.")
    fr.add_argument("--output", type=Path, help="Optional path for manifest.json.")
    fr.add_argument("--format", choices=("json", "markdown"), default="json")

    vr = sub.add_parser("verify", help="Verify frozen baseline integrity and 1:1 TC coverage.")
    vr.add_argument("baseline_dir", type=Path, help="Path to frozen baseline directory.")
    vr.add_argument("test_roots", nargs="+", type=Path, help="Test files or directories.")
    vr.add_argument("--format", choices=("json", "markdown"), default="json")

    gt = sub.add_parser("gate", help="Run a stage quality and traceability gate.")
    gt.add_argument("modernize_dir", type=Path, help="Path to .modernize directory.")
    gt.add_argument("--type", dest="gate_type", choices=GATE_TYPES, required=True)
    gt.add_argument("--format", choices=("json", "markdown"), default="json")

    args = parser.parse_args(argv)
    if args.command == "rulebook":
        return _emit(load_rulebooks_and_learnings(args.workspace), args.format)
    if args.command == "freeze":
        return _emit(freeze_baseline(args.baseline_dir, args.output), args.format)
    if args.command == "verify":
        return _emit(verify_baseline(args.baseline_dir, args.test_roots), args.format)
    return _emit(run_gate(args.modernize_dir, args.gate_type), args.format)


if __name__ == "__main__":
    raise SystemExit(main())
