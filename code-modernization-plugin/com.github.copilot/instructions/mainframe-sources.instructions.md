---
applyTo: "**/*.cbl,**/*.cob,**/*.cpy,**/*.jcl,**/*.prc,**/*.proc,**/*.pli,**/*.asm,**/*.bms,**/*.CBL,**/*.COB,**/*.CPY,**/*.JCL"
description: Editing rules for mainframe source (COBOL, copybooks, JCL, PL/I, Assembler, BMS).
---

When reading or editing mainframe source:
- COBOL is fixed format: columns 1-6 sequence number, 7 indicator (`*` or `/` comment, `-` continuation), 8-72 code, 73-80 ignored. Never write past column 72, never insert tabs, and keep sequence numbers and change tags.
- Use only characters that exist in the target EBCDIC code page; no smart quotes, em dashes, or other non-ASCII characters.
- JCL statements use columns 1-71 and continue after a trailing comma on a `//` line with a blank name field. Keep JCL uppercase except inside quoted values.
- Treat copybooks as contracts: keep byte layouts identical unless a change is approved, list every program that copies the member, and verify offsets with the `mainframe-analysis` skill's `copybook_layout.py` script.
- Preserve decimal arithmetic semantics (truncation, `ROUNDED`, high-order truncation), `RETURN-CODE` values, abend behavior, and `FILE STATUS` handling.
- A recompiled Db2 program needs its package rebound with the recorded options.
