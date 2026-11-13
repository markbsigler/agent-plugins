---
applyTo: "**/*"
description: Safety guardrails for code modernization, refactoring, and rearchitecture work.
---

When performing code modernization tasks:
- Never mix **Refactor** (behavior-preserving cleanup) and **Rearchitect** (topology/contract changes) in the same commit or stage without explicit ADR approval.
- Never delete legacy code paths until characterization tests or shadow-traffic parity checks pass.
- Document every architectural trade-off in `docs/adr/` when altering service boundaries or database ownership.
- Follow the safety rules of every stack profile in scope. For example, mainframe records are converted field by field from copybook layouts, never as whole-record text, and packed or zoned decimals never pass through floating point.
