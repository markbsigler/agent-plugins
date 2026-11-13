---
name: playbook-refactor
description: 4-stage governed runbook for behavior-preserving code-level modernization (the Refactor track), with approval gates, characterization tests, and equivalence evidence. Use after triage selects Refactor, or when the user asks for a framework, runtime, or compiler upgrade, tech-debt reduction, CVE remediation, or performance work that must not change external behavior or topology, on any stack, including Enterprise COBOL upgrades and other mainframe refactors.
license: MIT
metadata:
  author: markbsigler
  version: "1.0"
---

# Playbook: Code-Level Refactoring (Behavior-Preserving)

You are executing a **Refactor** initiative. You must improve code structure, framework versions, security, or performance **without altering external behavior or core architecture**.

Begin every response with:
`[REFACTOR PLAYBOOK: STAGE X/4] - Objective: [Current Step]`

## Before Stage 1

Confirm the three Refactor inputs (ask for any that are missing):
1. **Primary driver:** framework upgrade, tech debt, security/CVE, or performance?
2. **Target version or benchmark:** runtime, framework, or compiler release, or the performance goal.
3. **Test coverage baseline:** what tests exist, and how they are run.

Load every stack profile skill listed in the Triage Brief. If you started here without triage, match the scope against the stack profiles table in `modernization-triage` first. Keep each profile's estate brief current throughout. When no profile matches, the generic tasks in each stage apply on their own.

## Guardrails

- **Zero external drift:** public APIs, file and record layouts, messages, screens, reports, database schemas, exit or return codes, and error behavior stay identical, together with everything a loaded stack profile adds to the contract surface.
- **No topology creep:** do not split deployment units, move data ownership, or add brokers. If a structural change becomes necessary, stop and return to `modernization-triage`.
- **One concern per change:** keep dependency or compiler upgrades, option changes, mechanical API migrations, and structural cleanup in separate, reviewable commits.
- **Gates are hard stops:** never modify production code before `APPROVE STAGE 2`.

---

## Stage 1: Tech Debt, Security & Dependency Audit
Analyze the target codebase without modifying files.

### Agent Tasks:
1. Identify outdated dependencies, deprecated APIs, high cyclomatic complexity hotspots, and security vulnerabilities.
2. Confirm that proposed changes keep all public APIs, database schemas, and integration contracts identical.
3. Present a prioritized refactoring backlog.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Refactor Stage 1` tasks (in the profile skill's `references/playbook-stages.md`).

### Human-in-the-Loop Gate:
* Include each stack profile's Stage 1 results, or state why a profile's tasks do not apply.
* Stop and ask: *"Do you approve the Refactor scope and target versions? Reply **APPROVE STAGE 1** to proceed."*

---

## Stage 2: Characterization & Nonfunctional Baseline
Lock in current behavior and nonfunctional metrics before changing code.

### Agent Tasks:
1. Verify or write characterization tests covering all public entry points and edge cases.
2. Execute the test suite and record baseline nonfunctional metrics (test execution time, build time, bundle/binary size, or benchmark latency).

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Refactor Stage 2` tasks (in the profile skill's `references/playbook-stages.md`).

### Human-in-the-Loop Gate:
* Display the passing baseline test summary and nonfunctional metrics.
* Include each stack profile's Stage 2 evidence, or state why a profile's tasks do not apply.
* Stop and ask: *"Baseline behavior and NFR metrics are locked. Reply **APPROVE STAGE 2** to begin refactoring."*

---

## Stage 3: Incremental Code Transformation
Apply refactoring changes in small, atomic, verifiable steps.

### Agent Tasks:
1. Upgrade frameworks/libraries or restructure internal modules while keeping external interfaces untouched.
2. Run the test suite after each logical change to ensure continuous green builds.
3. Pause immediately if any public signature or external payload changes unexpectedly.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Refactor Stage 3` tasks (in the profile skill's `references/playbook-stages.md`).

---

## Stage 4: Equivalence & NFR Verification
Prove behavioral equivalence and nonfunctional improvement.

### Agent Tasks:
1. Run the full Stage 2 characterization test suite and confirm 100% pass rate with zero contract drift.
2. Re-measure the nonfunctional metrics from Stage 2 and output a Before/After comparison table.
3. Mark state as `[REFACTOR PLAYBOOK: COMPLETED]`.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Refactor Stage 4` tasks (in the profile skill's `references/playbook-stages.md`) before marking the playbook completed.
