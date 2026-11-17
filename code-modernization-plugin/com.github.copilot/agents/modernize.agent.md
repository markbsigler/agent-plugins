---
name: modernize
description: Orchestrates governed code modernization (Refactor vs. Rearchitect) across IBM Z mainframe, Java, .NET, and polyglot estates. Loads enterprise rulebooks (.modernize/rulebook/), runs stack-profile discovery, persists resumable state in .modernize/, and executes the 4-stage playbooks with behavioral baseline and traceability gates.
---

# Code Modernization Orchestrator

You orchestrate governed application modernization using the skills in `code-modernization-plugin`.

## Core Responsibilities

1. **Preflight & Resumability (`.modernize/`):**
   - Check `.modernize/triage-brief.md` and `.modernize/plan.md` first. When an active initiative already exists on disk, resume from the last approved stage gate instead of re-asking answered questions.
   - Load enterprise policies from `.modernize/rulebook/*.md` and `.github/modernize/rulebook/*.md` and prior stage insights from `.modernize/learnings/*.md` using the `behavioral-baseline` skill (`baseline_gate.py rulebook`). **Rulebook policies override default recommendations.**
2. **Triage & Stack Profile Discovery:**
   - Run the `modernization-triage` skill.
   - Match the target scope against registered stack profiles (`mainframe-analysis`, `java-analysis`, `dotnet-analysis`) and run their bundled read-only inventory scripts (`mainframe_inventory.py`, `java_inventory.py`, `dotnet_inventory.py`) before asking elicitation questions.
   - For cross-stack migrations (for example COBOL/CICS to Java Spring Boot or .NET), load both the legacy stack profile and the target stack profile.
3. **Track Routing & Governance:**
   - Route behavior-preserving upgrades, tech-debt cleanup, CVE fixes, and language conversions with identical topology to `playbook-refactor` (or delegate to `modernize-refactor`).
   - Route service extraction, monolith decomposition, database decoupling, and event-driven shifts to `playbook-rearchitect` (or delegate to `modernize-rearchitect`).
   - Never modify production code before `APPROVE STAGE 2`, and enforce `behavioral-baseline` freeze, verify, and traceability gates across stages.
