---
applyTo: "**/*.cbl,**/*.cob,**/*.cpy,**/*.jcl,**/*.prc,**/*.proc,**/*.pli,**/*.pl1,**/*.inc,**/*.asm,**/*.mac,**/*.mlc,**/*.bms,**/*.mfs,**/*.ezt,**/*.rexx,**/*.rex,**/*.clist,**/*.psb,**/*.dbd,**/*.CBL,**/*.COB,**/*.CPY,**/*.JCL"
description: Editing rules for mainframe source (COBOL, copybooks, JCL, PL/I, Assembler, BMS and MFS maps, IMS PSBs and DBDs, REXX, CLIST, Easytrieve).
---

When reading or editing mainframe source:
- COBOL is fixed format: columns 1-6 sequence number, 7 indicator (`*` or `/` comment, `-` continuation), 8-72 code, 73-80 ignored. Never write past column 72, never insert tabs, and keep sequence numbers and change tags.
- Use only characters that exist in the target EBCDIC code page; no smart quotes, em dashes, or other non-ASCII characters.
- JCL statements use columns 1-71 and continue after a trailing comma on a `//` line with a blank name field. Keep JCL uppercase except inside quoted values.
- PL/I source lies inside the margins, columns 2-72 by default (`MARGINS(2,72)`). Leave column 1 and columns 73-80 untouched, never start a `/*` comment in column 1, and keep `%INCLUDE` members in the same record format and margins as the program.
- Assembler (HLASM), and BMS maps, IMS PSB and DBD source, and MFS formats written in the same style: the name field starts in column 1, followed by the operation and operands separated by blanks; `*` in column 1 marks a comment. Continue a statement with a nonblank character in column 72 and resume in column 16. Keep columns 73-80, and check for `ICTL`, which moves these columns.
- Treat copybooks as contracts: keep byte layouts identical unless a change is approved, list every program that copies the member, and verify offsets with the `copybook-data` skill's `copybook_layout.py` script.
- Preserve decimal arithmetic semantics (truncation, `ROUNDED`, high-order truncation), `RETURN-CODE` values, abend behavior, and `FILE STATUS` handling.
- A recompiled Db2 program needs its package rebound with the recorded options.
