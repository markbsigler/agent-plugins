---
applyTo: "**/*"
description: Safety guardrails for code modernization, refactoring, and rearchitecture work.
---

When performing code modernization tasks:
- Honor enterprise modernization policies in `.modernize/rulebook/*.md` and `.github/modernize/rulebook/*.md`; rulebook constraints override default recommendations.
- Never mix **Refactor** (behavior-preserving cleanup) and **Rearchitect** (topology/contract changes) in the same commit or stage without explicit ADR approval.
- Freeze behavioral baselines (`.modernize/baseline/test-cases.md` and `manifest.json`) before Stage 3 code changes, and never weaken or delete frozen test cases to make a failing build pass.
- Never delete legacy code paths until characterization tests or shadow-traffic parity checks pass.
- Document every architectural trade-off in `docs/adr/` when altering service boundaries or database ownership.
- Follow the safety rules of every stack profile in scope (`mainframe-analysis`, `java-analysis`, `dotnet-analysis`). For example, mainframe records are converted field by field from copybook layouts, never as whole-record text, and packed or zoned decimals never pass through floating point (`BigDecimal` in Java, `decimal` in .NET).
