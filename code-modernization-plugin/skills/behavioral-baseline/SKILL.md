---
name: behavioral-baseline
description: Freezes and verifies externally observable behavior baselines (TC-XXX test cases, infrastructure decision tables, and SHA-256 fixture manifests), enforces 1:1 test-case-to-test-method parity, loads enterprise rulebooks and stage learnings, and runs deterministic stage quality gates (spec-quality, spec-to-plan, plan-to-tasks, completeness) over REQ-XXX / BR-XXX -> T-XXX -> TC-XXX traceability. Use during Stage 1, 2, and 4 of playbook-refactor or playbook-rearchitect, or whenever asked to freeze a test baseline, check requirement traceability, validate a modernization quality gate, or audit post-migration test parity.
license: MIT
compatibility: Python 3.11+, standard library only; run with uv or python3. Read-only except when writing the baseline SHA-256 manifest during freeze.
metadata:
  author: markbsigler
  version: "1.0"
---

# Behavioral Baseline & Quality Gates

Locks in externally observable behavior before modernization code changes begin, enforces 1:1 traceability from requirements (`REQ-XXX` / `BR-XXX`) to implementation tasks (`T-XXX`) and verification test cases (`TC-XXX`), and loads enterprise rulebooks and persistent learnings across stages.

Related skills:

- `modernization-triage`, `playbook-refactor`, and `playbook-rearchitect` call this skill at Stage 1, Stage 2, and Stage 4 gates.
- `copybook-data` (`record_compare.py` and `record_mask.py`) compares and masks binary mainframe data files referenced by `testdata/` fixtures.

## Operating rules

1. **External boundaries only.** Baseline test cases (`TC-001`, `TC-002`, ...) describe observable inputs and outputs at public entry points (HTTP/RPC endpoints, CLI commands, batch jobs, CICS transactions, message consumers). Never lock internal private helpers.
2. **Freeze before Stage 3.** Once Stage 2 is approved, `test-cases.md`, `infra-decision-table.md`, and `testdata/` are frozen (`manifest.json` records their SHA-256 digests). Never weaken or edit a frozen test case during Stage 3 to make a failing test pass.
3. **Strict 1:1 `TC-ID` mapping.** Every `TC-XXX` in `test-cases.md` must map to a test method or case in the test suite whose name or body carries the `TC-XXX` identifier (for example `tc_001_...`, `tc001_...`, or `TC-001`), with no missing or unmapped IDs.
4. **Traceability gates are deterministic.** Every requirement (`REQ-XXX` or `BR-XXX`) must trace to at least one task (`T-XXX`), and every task must trace to at least one verification test (`TC-XXX`).

## Workflow

### Step 1: Load rulebooks and prior learnings

Before planning or writing baseline specs, inspect `.modernize/rulebook/` (or `.github/modernize/rulebook/`) and `.modernize/learnings/`:

```bash
uv run --script ./scripts/baseline_gate.py rulebook . --format markdown
```

### Step 2: Author and freeze the behavioral baseline (Stage 2)

Create `.modernize/baseline/test-cases.md` (listing each `TC-XXX` with entry point, input fixture or parameters, expected output, and side effects), optional `.modernize/baseline/infra-decision-table.md` (`mock`, `testcontainer`, `emulator`, or `golden-file` per dependency), and `.modernize/baseline/testdata/` fixtures. Then freeze the baseline:

```bash
uv run --script ./scripts/baseline_gate.py freeze .modernize/baseline
```

The command validates that every `TC-XXX` is well-formed, rejects vague assertions (`behaves as expected`, `reasonable error`, `[NEEDS CLARIFICATION]`), checks that every referenced `testdata/...` file exists, and writes `.modernize/baseline/manifest.json` with SHA-256 digests.

### Step 3: Run stage quality gates (Stages 1, 2, and 4)

Validate `.modernize/traceability.json` (see [references/gate-checklists.md](references/gate-checklists.md) for the schema and checklists) at each stage boundary:

```bash
uv run --script ./scripts/baseline_gate.py gate .modernize --type spec-quality --format markdown
uv run --script ./scripts/baseline_gate.py gate .modernize --type spec-to-plan --format markdown
uv run --script ./scripts/baseline_gate.py gate .modernize --type plan-to-tasks --format markdown
uv run --script ./scripts/baseline_gate.py gate .modernize --type completeness --format markdown
```

### Step 4: Verify baseline integrity and 1:1 test parity (Stage 4)

After transformation or slice implementation, verify that the frozen baseline files were not modified and that every `TC-XXX` is covered by the test suite:

```bash
uv run --script ./scripts/baseline_gate.py verify .modernize/baseline tests/ --format markdown
```

The command exits with status `0` only when all frozen SHA-256 digests match, every `TC-XXX` has a matching test, no unknown `TC-XXX` IDs appear, and no matched test contains `TODO`/`FIXME` placeholders.
