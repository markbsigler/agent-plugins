---
name: modernize
description: Triage a modernization goal (Refactor vs. Rearchitect) and launch the governed playbook.
argument-hint: "[module, service, or mainframe application to modernize]"
agent: agent
---

Execute the **modernization-triage** skill using these user inputs:
- **Target Scope:** `${input:targetScope:Which module, service, or domain are you modernizing?}`
- **Modernization Goal:** `${input:goal:Describe the desired outcome (e.g., upgrade Spring Boot 2 to 3, or extract Orders into an event-driven service)}`
- **Architecture Change Required?:** `${input:archChange:Does this change deployment topology or database ownership? (yes/no)}`

Triage loads the stack profile skills that match the scope (for example **mainframe-analysis** for COBOL, PL/I, copybooks, JCL, CICS, IMS, Db2 for z/OS, and VSAM) and runs their discovery before classifying.

Classify the request, confirm any missing track-specific details, and immediately start Stage 1 of the matching playbook (`playbook-refactor` or `playbook-rearchitect`).
