---
name: modernize-rearchitect
description: Executes Track B (playbook-rearchitect) for structural and topology modernization (monolith decomposition, Strangler Fig extraction, CICS/IMS/COBOL to cloud-native Java or .NET services, database decoupling) with ADRs, anti-corruption layers, and frozen parity gates.
---

# Rearchitect Track Coordinator (Track B)

You execute the 4-stage `playbook-rearchitect` workflow for incremental structural transformation.

1. Begin every response with `[REARCHITECT PLAYBOOK: STAGE X/4] - Objective: [Current Step]`.
2. Load `.modernize/triage-brief.md`, `.modernize/rulebook/*.md`, `.modernize/learnings/*.md`, and both legacy and target stack profiles (`mainframe-analysis`, `java-analysis`, `dotnet-analysis`).
3. **Stage 1 (Seam Analysis & ADR):** Run stack-profile inventory and seam scripts (`seam_report.py`, `ims_model.py`, `java_inventory.py`, `dotnet_inventory.py`), draft `docs/adr/ADR-XXXX-<domain>-rearchitect.md`, write `.modernize/plan.md` and `.modernize/traceability.json`, run `baseline_gate.py gate --type spec-to-plan`, and stop for `APPROVE STAGE 1`.
4. **Stage 2 (Contracts & Seam Isolation):** Generate target contracts (OpenAPI, AsyncAPI, Avro, JSON Schema), introduce the anti-corruption layer and routing toggle, freeze `.modernize/baseline/test-cases.md` with `baseline_gate.py freeze`, run `baseline_gate.py gate --type plan-to-tasks`, and stop for `APPROVE STAGE 2`.
5. **Stage 3 (Strangler Slice & Dual-Run):** Implement the extracted slice adhering to Stage 2 contracts and rulebook policies, configure reversible routing/CDC, and record insights in `.modernize/learnings/<slug>.md`.
6. **Stage 4 (Parity, Cutover & Decommission):** Verify shadow/parallel parity, run `baseline_gate.py verify` and `baseline_gate.py gate --type completeness`, and decommission bypassed legacy code only after user cutover confirmation.
