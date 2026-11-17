"""Tests for code-modernization-plugin: behavioral-baseline skill and baseline_gate.py."""

from __future__ import annotations

import json
from pathlib import Path

import baseline_gate
import pytest


def _write_valid_baseline(baseline_dir: Path) -> None:
    (baseline_dir / "testdata" / "inputs").mkdir(parents=True)
    (baseline_dir / "testdata" / "expectations").mkdir(parents=True)
    (baseline_dir / "testdata" / "inputs" / "acct-001.json").write_text(
        '{"accountId": "0001"}\n', encoding="utf-8"
    )
    (baseline_dir / "testdata" / "expectations" / "acct-001-out.json").write_text(
        '{"balance": "125.50"}\n', encoding="utf-8"
    )
    (baseline_dir / "test-cases.md").write_text(
        "# Behavioral Test Baseline\n\n"
        "### TC-001: Account inquiry returns exact balance\n"
        "- **Entry Point:** `POST /api/v1/accounts/inquiry`\n"
        "- **Input:** `testdata/inputs/acct-001.json`\n"
        "- **Expected Output:** `testdata/expectations/acct-001-out.json`\n\n"
        "### TC-002: Missing account returns 404 problem detail\n"
        "- **Entry Point:** `POST /api/v1/accounts/inquiry`\n"
        "- **Expected Output:** HTTP 404 with code `ACCOUNT_NOT_FOUND`\n",
        encoding="utf-8",
    )
    (baseline_dir / "infra-decision-table.md").write_text(
        "| Dependency | Kind | Strategy | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| `acct_db` | database | testcontainer | PostgreSQL 16 |\n"
        "| `fraud_api` | http | mock | WireMock |\n",
        encoding="utf-8",
    )


def test_freeze_and_verify_baseline_happy_path_and_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_dir = tmp_path / ".modernize" / "baseline"
    _write_valid_baseline(baseline_dir)

    rc = baseline_gate.main(["freeze", str(baseline_dir), "--format", "markdown"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FREEZE — PASSED" in out
    assert (baseline_dir / "manifest.json").is_file()

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_accounts.py").write_text(
        "def test_tc_001_account_inquiry():\n    assert True\n\n"
        "def test_tc_002_missing_account():\n    assert True\n",
        encoding="utf-8",
    )

    rc = baseline_gate.main(
        ["verify", str(baseline_dir), str(tests_dir / "test_accounts.py"), "--format", "markdown"]
    )
    assert rc == 0
    verify_md = capsys.readouterr().out
    assert "VERIFY — PASSED" in verify_md


def test_freeze_detects_missing_files_vague_specs_duplicates_and_bad_infra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert baseline_gate.main(["freeze", str(empty_dir)]) == 1
    capsys.readouterr()

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "test-cases.md").write_text("No test cases here.\n", encoding="utf-8")
    assert baseline_gate.freeze_baseline(bad_dir)["status"] == "FAILED"

    (bad_dir / "test-cases.md").write_text(
        "### TC-001: First case\n"
        "System behaves as expected with `testdata/missing.json`.\n"
        "### TC-001:\n"
        "[NEEDS CLARIFICATION: status code]\n",
        encoding="utf-8",
    )
    (bad_dir / "infra-decision-table.md").write_text(
        "| Dependency | Kind | Strategy |\n| --- | --- | --- |\n| db | sql | magic |\n"
        "| short_row | only_two |\n",
        encoding="utf-8",
    )
    report = baseline_gate.freeze_baseline(bad_dir)
    assert report["status"] == "FAILED"
    joined = " | ".join(report["issues"])
    assert "duplicate test case ID TC-001" in joined
    assert "missing title" in joined
    assert "vague phrasing" in joined
    assert "testdata/missing.json" in joined
    assert "unknown strategy 'magic'" in joined


def test_verify_detects_tampering_deleted_files_untracked_files_and_tc_drift(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    _write_valid_baseline(baseline_dir)
    assert baseline_gate.verify_baseline(baseline_dir, [tmp_path])["status"] == "FAILED"

    assert baseline_gate.freeze_baseline(baseline_dir)["status"] == "PASSED"

    (baseline_dir / "testdata" / "inputs" / "extra.json").write_text("{}\n", encoding="utf-8")
    (baseline_dir / "testdata" / "expectations" / "acct-001-out.json").unlink()
    (baseline_dir / "test-cases.md").write_text(
        (baseline_dir / "test-cases.md").read_text(encoding="utf-8") + "\n<!-- tampered -->\n",
        encoding="utf-8",
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "TestAccounts.java").write_text(
        "// TC-001 and extra TC-999 with TODO marker\nvoid tc001() {}\nvoid tc999() {}\n",
        encoding="utf-8",
    )

    result = baseline_gate.verify_baseline(baseline_dir, [tests_dir])
    assert result["status"] == "FAILED"
    assert result["missing_test_cases"] == ["TC-002"]
    assert result["extra_test_cases"] == ["TC-999"]
    joined = " | ".join(result["issues"])
    assert "frozen file was modified after freeze: test-cases.md" in joined
    assert "frozen file was deleted: testdata/expectations/acct-001-out.json" in joined
    assert "untracked file added under frozen testdata/: testdata/inputs/extra.json" in joined
    assert "contains TODO/FIXME marker" in joined


def test_rulebook_and_quality_gates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod_dir = tmp_path / ".modernize"
    (mod_dir / "rulebook").mkdir(parents=True)
    (mod_dir / "learnings").mkdir(parents=True)

    assert baseline_gate.main(["rulebook", str(tmp_path), "--format", "markdown"]) == 0
    assert "No rulebook files found." in capsys.readouterr().out

    (mod_dir / "rulebook" / "standards.md").write_text(
        "# Enterprise Standards\n## Target Stack\n- Target Java 21 and Spring Boot 3.4\n"
        "- Use BigDecimal for all currency fields\n",
        encoding="utf-8",
    )
    (mod_dir / "learnings" / "comp3-signs.md").write_text(
        "# COMP-3 Sign Nibbles\n\nBatch extracts use unsigned F nibbles for positive values.\n\n"
        "## Takeaway\nAccept both C and F positive nibbles when decoding.\n",
        encoding="utf-8",
    )
    assert baseline_gate.main(["rulebook", str(tmp_path), "--format", "markdown"]) == 0
    rb_md = capsys.readouterr().out
    assert "Target Java 21" in rb_md
    assert "COMP-3 Sign Nibbles" in rb_md

    assert baseline_gate.run_gate(mod_dir, "spec-quality")["status"] == "FAILED"

    baseline_dir = mod_dir / "baseline"
    _write_valid_baseline(baseline_dir)
    baseline_gate.freeze_baseline(baseline_dir)

    trace = {
        "track": "Refactor",
        "requirements": [
            {"id": "REQ-001", "title": "Preserve account inquiry balance"},
            {"id": "BR-002", "title": "Return 404 when account is absent"},
        ],
        "tasks": [
            {
                "id": "T-001",
                "title": "Migrate inquiry controller",
                "requirements": ["REQ-001", "BR-002"],
                "test_cases": ["TC-001", "TC-002"],
                "status": "done",
            }
        ],
    }
    (mod_dir / "traceability.json").write_text(json.dumps(trace), encoding="utf-8")

    for gate in ("spec-quality", "spec-to-plan", "plan-to-tasks", "completeness"):
        assert baseline_gate.main(["gate", str(mod_dir), "--type", gate]) == 0
        capsys.readouterr()

    assert (
        baseline_gate.main(["gate", str(mod_dir), "--type", "completeness", "--format", "markdown"])
        == 0
    )
    assert "GATE (completeness) — PASSED" in capsys.readouterr().out

    # Exercise gate failure branches: bad learning header, duplicate/invalid IDs, unmapped items
    (mod_dir / "learnings" / "bad.md").write_text("Bad header without H1\n", encoding="utf-8")
    bad_trace = {
        "requirements": [
            {"id": "BAD-1", "title": ""},
            {"id": "REQ-001", "title": "Valid"},
            {"id": "REQ-001", "title": "Duplicate"},
            {"id": "REQ-002", "title": "Unmapped"},
        ],
        "tasks": [
            {"id": "BAD-T", "requirements": [], "test_cases": [], "status": "pending"},
            {
                "id": "T-001",
                "requirements": ["REQ-001", "REQ-999"],
                "test_cases": ["BAD-TC", "TC-999"],
                "status": "done",
            },
            {
                "id": "T-001",
                "requirements": ["REQ-001"],
                "test_cases": ["TC-001"],
                "status": "done",
            },
        ],
    }
    (mod_dir / "traceability.json").write_text(json.dumps(bad_trace), encoding="utf-8")
    failed = baseline_gate.run_gate(mod_dir, "completeness")
    assert failed["status"] == "FAILED"
    issues_text = " | ".join(failed["issues"])
    assert "learning must start with '# Title'" in issues_text
    assert "invalid requirement ID" in issues_text
    assert "duplicate requirement ID REQ-001" in issues_text
    assert "requirements not mapped to any task: BAD-1, REQ-002" in issues_text
    assert "invalid task ID" in issues_text
    assert "duplicate task ID T-001" in issues_text
    assert "maps to no requirements" in issues_text
    assert "references unknown requirements REQ-999" in issues_text
    assert "lists no TC-XXX verification test cases" in issues_text
    assert "invalid test case ID 'BAD-TC'" in issues_text
    assert "tasks not yet marked done or verified" in issues_text
    assert "tasks reference TC IDs missing from frozen baseline: BAD-TC, TC-999" in issues_text
    assert "Issues" in baseline_gate.to_markdown(failed)
    assert "Issues" in baseline_gate.to_markdown(
        baseline_gate.load_rulebooks_and_learnings(tmp_path)
    )

    (mod_dir / "traceability.json").write_text(
        json.dumps({"requirements": [], "tasks": []}), encoding="utf-8"
    )
    empty_gate = baseline_gate.run_gate(mod_dir, "spec-to-plan")
    assert "traceability.json contains no requirements" in empty_gate["issues"]
    assert "traceability.json contains no tasks" in empty_gate["issues"]
