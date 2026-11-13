---
name: playbook-rearchitect
description: 4-stage governed runbook for structural architecture transformation using ADRs and Strangler Fig gates (Gartner Rearchitect). Use after triage selects Rearchitect, or when the user asks to extract a bounded context, split a monolith, decouple shared data, or move toward a modular monolith, microservices, event-driven, or serverless design, on any stack, including CICS, IMS, Db2, VSAM, and batch workloads on the mainframe.
license: MIT
metadata:
  author: markbsigler
  version: "1.0"
---

# Playbook: Structural Rearchitecting (Architecture Transformation)

You are executing a **Gartner Rearchitect** initiative. You are materially altering code structure and system topology (e.g., monolith to modular, microservices, or event-driven cloud-native) to unlock new capabilities. **Never perform a big-bang rewrite. Enforce incremental domain extraction.**

Begin every response with:
`[REARCHITECT PLAYBOOK: STAGE X/4] - Objective: [Current Step]`

## Guardrails

- **One slice at a time:** extract one bounded context or domain slice per pass.
- **Contracts before code:** every new boundary has an explicit, reviewed contract and an anti-corruption layer before implementation starts.
- **Reversible routing:** every traffic or data shift sits behind a toggle, router, or gateway rule that can send work back to the legacy path immediately.
- **Legacy stays until parity is proven:** delete nothing until Stage 4 parity checks pass and the user confirms cutover.
- **Stack profiles:** load every stack profile skill listed in the Triage Brief (if you started here without triage, match the scope against the stack profiles table in `modernization-triage` first) and keep each estate brief current. A slice usually needs a profile for the legacy stack and, when one exists, a profile for the target stack. Legacy-stack profiles carry the seam, contract, data synchronization, and decommissioning work; target-stack profiles carry implementation idioms and tests. When no profile matches, the generic tasks in each stage apply on their own.

---

## Stage 1: Domain Seam Analysis & ADR Generation
Map coupling boundaries and produce an Architecture Decision Record (ADR) before writing code.

### Agent Tasks:
1. **Elicit Missing Architecture Details** (if not already provided):
   - Target architecture style (Modular Monolith, Microservices, Event-Driven, Serverless).
   - First bounded context or domain slice to extract.
   - Data decoupling strategy (Database-per-Service, Change Data Capture, Shared-Nothing).
2. **Coupling & Seam Audit:** Scan call graphs, shared database tables, distributed transactions, and synchronous dependencies around the target domain.
3. **Generate ADR:** Draft a formal ADR (`docs/adr/ADR-XXXX-<domain>-rearchitect.md`) documenting Context, Target Topology, Data Ownership, Trade-offs, and Migration Strategy (e.g., Strangler Fig or Branch by Abstraction).

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Rearchitect Stage 1` tasks (in the profile skill's `references/playbook-stages.md`).

### Human-in-the-Loop Gate:
* Present the Seam Audit and draft ADR to the user.
* Include each stack profile's Stage 1 results, or state why a profile's tasks do not apply.
* Stop and ask: *"Do you approve the target architecture and ADR? Reply **APPROVE STAGE 1** to proceed."*

---

## Stage 2: Seam Isolation & Interface Contract Definition
Introduce clean boundaries and explicit contracts before moving business logic.

### Agent Tasks:
1. **Define Target Contracts:** Generate formal interface schemas (OpenAPI, AsyncAPI, Protobuf, or internal module interfaces) for the new architecture.
2. **Build Anti-Corruption Layer (ACL) / Seam:** Introduce an interface abstraction, adapter, or feature flag in the legacy codebase so callers are decoupled from the legacy implementation.
3. **Contract Tests:** Write consumer-driven contract tests verifying both the legacy adapter and the new interface specification.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Rearchitect Stage 2` tasks (in the profile skill's `references/playbook-stages.md`).

### Human-in-the-Loop Gate:
* Display the generated interface contracts and seam locations.
* Include each stack profile's Stage 2 results, or state why a profile's tasks do not apply.
* Stop and ask: *"Interface contracts and isolation seams are ready. Reply **APPROVE STAGE 2** to build the new architectural slice."*

---

## Stage 3: Strangler Slice Implementation & Dual-Run
Build the new architectural component alongside the legacy system with safe traffic/data routing.

### Agent Tasks:
1. Implement the new service, module, or event consumer adhering strictly to the Stage 2 contracts and isolated data store.
2. Configure routing controls (feature toggles, API gateway routes, or dual-write/shadow-read pipelines) to support gradual cutover.
3. Verify telemetry, distributed tracing, and rollback switches are active before enabling traffic.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Rearchitect Stage 3` tasks (in the profile skill's `references/playbook-stages.md`).

### Stage Gate:
* If schema mismatches, distributed transaction issues, or data sync drift appear, pause immediately and report diagnostics before proceeding.

---

## Stage 4: Parity Validation, Cutover & Legacy Decommissioning
Verify new architectural capabilities and safely retire bypassed legacy code.

### Agent Tasks:
1. Execute parity checks (shadow traffic comparison or reconciliation queries) between the legacy path and the new architecture.
2. Confirm the new architectural capabilities (e.g., independent deployment, async scaling, fault isolation) function as specified in the Stage 1 ADR.
3. Once the user confirms 100% traffic cutover, remove dead legacy code paths, temporary adapters, and obsolete feature flags.
4. Update the ADR status to `Accepted & Implemented` and mark state as `[REARCHITECT PLAYBOOK: COMPLETED]`.

### Stack Profile Tasks:
- For each stack profile in the Triage Brief, complete its `Rearchitect Stage 4` tasks (in the profile skill's `references/playbook-stages.md`) before updating the ADR status and marking the playbook completed.
