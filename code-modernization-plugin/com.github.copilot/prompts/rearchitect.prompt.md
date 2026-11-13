---
name: rearchitect
description: Launch the 4-stage Gartner Rearchitect playbook (structural & architecture transformation).
argument-hint: "[bounded context, domain slice, or monolith module]"
agent: agent
---

Execute the **playbook-rearchitect** skill strictly stage by stage for:
- **Bounded Context / Scope:** `${input:boundedContext:Which domain slice or monolith module is being rearchitected?}`
- **Target Architecture:** `${input:targetArch:Modular monolith, microservices, event-driven, or serverless?}`
- **Data & Migration Strategy:** `${input:migrationPattern:e.g., Strangler Fig + Database-per-Service, Branch by Abstraction, CDC}`

Load the stack profile skills for the legacy stack and, when one exists, the target stack (for example **mainframe-analysis** for CICS, IMS, Db2 for z/OS, VSAM, or batch) and complete their tasks at each stage.
