---
name: mainframe-analysis
description: IBM Z (z/OS) stack profile for the modernization playbooks. Analyzes mainframe estates - COBOL, PL/I, Assembler, JCL, REXX, and Easytrieve with CICS, IMS, Db2, VSAM, IDMS, and MQ - and supplies the z/OS tasks for every Refactor and Rearchitect stage. Use when a modernization request touches mainframe code, data, or batch (copybooks, EBCDIC, packed decimal, 3270 screens, JCL jobs), or when you need a program inventory, a call, copybook, and data set dependency graph, or exact copybook record offsets. Bundled scripts only read files.
license: MIT
compatibility: Scripts need Python 3.11+ (standard library only; run with uv or python3). They analyze mainframe source exported to a local directory, for example from Endevor, ChangeMan ZMF, Code Pipeline (ISPW), or Git.
metadata:
  author: markbsigler
  version: "1.0"
---

# Mainframe Analysis (IBM Z / z/OS)

The IBM Z stack profile for `modernization-triage`, `playbook-refactor`, and `playbook-rearchitect`. Triage loads it when the scope contains mainframe code, data, or batch, and the playbooks then run its tasks at every stage. It produces evidence (inventory, dependency graph, record layouts, risk indicators) and holds the z/OS rules each stage applies. If you were invoked directly for a modernization request and no track has been chosen yet, run `modernization-triage` with this skill's estate brief.

## Stack profile

| Profile part | Where in this skill |
| --- | --- |
| Detection signals | [Detection signals](#detection-signals) |
| Discovery and estate brief | [Workflow](#workflow), Steps 1 to 5 |
| Contract surface | Operating rule 5 |
| Elicitation addendum | Last section of [references/discovery-checklist.md](references/discovery-checklist.md) |
| Classification examples | [Classification examples](#classification-examples) |
| Playbook stage tasks | [references/playbook-stages.md](references/playbook-stages.md): `Refactor Stage 1` to `4` and `Rearchitect Stage 1` to `4` |
| Equivalence evidence and NFR baselines | [references/equivalence-testing.md](references/equivalence-testing.md) |
| Target platforms and transition patterns | [references/target-mappings.md](references/target-mappings.md) |
| Editing rules | "Source format and safe editing" in [references/cobol-language.md](references/cobol-language.md) |

### Detection signals

- Members of these kinds: COBOL, PL/I, or Assembler programs; copybooks and includes; JCL jobs, procedures, and control cards; BMS or MFS maps; REXX or CLIST execs; Easytrieve; CICS CSD extracts; IMS DBDs and PSBs; DCLGENs and Db2 DDL. Members exported from PDS libraries often have no file extension; the inventory script classifies them by content.
- Common extensions: `.cbl`, `.cob`, `.cpy`, `.jcl`, `.prc`, `.proc`, `.pli`, `.asm`, `.mac`, `.bms`, `.mfs`, `.dbd`, `.psb`, `.dclgen`, `.rexx`, `.ezt`.
- Mentions of z/OS, CICS, IMS, Db2 for z/OS, VSAM, MQ on z/OS, JES, or mainframe batch scheduling.

### Classification examples

| Request | Route |
| --- | --- |
| Enterprise COBOL V4 to V6; replacing `HANDLE CONDITION` with `RESP` checks; threadsafe CICS; removing `GO TO` and `ALTER`; Db2 SQL tuning; standardizing JCL; separating BMS presentation from business logic in the same region | Refactor |
| COBOL to Java or C# conversion that keeps the batch and online topology | Refactor (language transformation) |
| Extracting a CICS and Db2 domain into services; moving data ownership off Db2 for z/OS or IMS; replacing batch file interfaces with event streams; re-implementing transactions behind an API gateway | Rearchitect |
| Exposing transactions as APIs (for example through z/OS Connect) with no further change | Encapsulate: a separate integration task, or Rearchitect Stage 2 when boundaries move later |
| Recompiling and running the workload on a mainframe-compatible runtime off z/OS | Rehost or replatform: outside both playbooks |

## Operating rules

1. **Evidence before opinion.** Every claim about the estate cites a member, a compiler listing, a CSD or scheduler extract, or runtime data (SMF, CICS statistics). Label inferences as inferences.
2. **The running system is the specification.** Source in the repository may not match production load modules. Reconcile source with the production library (SCM production stage, compile listings, binder data) before trusting it, and flag modules without source.
3. **Data is bytes defined by copybooks.** Never convert an EBCDIC file or record wholesale. Convert field by field from the layout, because packed-decimal and binary fields are corrupted by character translation.
4. **Decimal stays decimal.** Money and quantities defined as `COMP-3` or zoned decimal must never pass through binary floating point.
5. **Contracts are wider than APIs.** Data set layouts, COMMAREA and container layouts, MQ messages, 3270 screens consumed by scrapers or RPA, report layouts, return codes, abend codes, and file-transfer formats are all external contracts.
6. **The calendar is part of the program.** Behavior changes at month-end, quarter-end, year-end, leap day, daylight-saving changes, and holidays. Test evidence must cover the cycles that run in production.
7. **Read-only by default.** Analyze exported source and extracts. Never submit jobs, run utilities, or connect to an LPAR, CICS region, or Db2 subsystem unless the user explicitly authorizes the action and the target environment.

## Workflow

### Step 1: Establish the source of truth

Ask where the authoritative source lives (SCM product and stage), which libraries make up the compile concatenation, and whether compile listings, the CICS CSD, IMS definitions, Db2 DDL, and scheduler definitions are available. Use [references/discovery-checklist.md](references/discovery-checklist.md) to request the full artifact set in one round, and record any gaps.

### Step 2: Inventory the estate

Run the inventory script over the exported directories, from this skill's directory or with the full path:

```bash
uv run --script scripts/mainframe_inventory.py <export-dir> --format markdown   # human summary
uv run --script scripts/mainframe_inventory.py <export-dir> > inventory.json      # full graph
```

It classifies every member, extracts COPY, CALL, CICS LINK/XCTL, Db2 table, DL/I, MQ, file, JCL step, and data set references, resolves programs hidden behind `IKJEFT01`, `DFSRRC00`, and procedure overrides such as `MBR=`, maps CICS transactions to programs from CSD extracts, decodes EBCDIC members, and scores risk indicators (ALTER, GO TO DEPENDING ON, PERFORM THRU, dynamic CALL, HANDLE CONDITION, dynamic SQL, business logic in sort control cards, relative GDG references). Treat `unresolved` references as requests for missing libraries, and `duplicate_names` as copybook drift to resolve before any change.

The scan is static and heuristic. Confirm high-stakes findings with compiler cross-reference listings or the shop's analysis tooling.

### Step 3: Load the rules for what you found

Read only the references that the inventory shows are in scope:

| Inventory shows | Read |
| --- | --- |
| A playbook stage is running | [references/playbook-stages.md](references/playbook-stages.md) |
| COBOL programs or copybooks | [references/cobol-language.md](references/cobol-language.md) |
| Any data movement, conversion, comparison, or sorting | [references/data-and-encoding.md](references/data-and-encoding.md) |
| `cics` usage, BMS maps, CSD, IMS TM, or MFS | [references/online-cics-ims-tm.md](references/online-cics-ims-tm.md) |
| `db2`, `ims` (DL/I), VSAM or sequential files, IDMS | [references/data-stores.md](references/data-stores.md) |
| JCL, procedures, control cards, schedulers, reports | [references/batch-jcl.md](references/batch-jcl.md) |
| PL/I, Assembler, REXX, CLIST, Easytrieve, Natural, generated code | [references/other-languages.md](references/other-languages.md) |
| A playbook gate needs baseline or equivalence evidence | [references/equivalence-testing.md](references/equivalence-testing.md) |
| A target platform, language, or transition pattern is being chosen | [references/target-mappings.md](references/target-mappings.md) |
| The user asks which tools to use | [references/tooling.md](references/tooling.md) |

### Step 4: Compute exact record layouts

For every copybook that crosses a boundary (files, COMMAREAs, containers, MQ messages, Db2 host structures), compute the layout rather than estimating offsets by hand:

```bash
uv run --script scripts/copybook_layout.py CUSTREC.cpy --format markdown
uv run --script scripts/copybook_layout.py CUSTREC.cpy --copylib copy/ --replace :PFX: WS
uv run --script scripts/copybook_layout.py COMMAREA.cpy --format json-schema > commarea.schema.json
```

The JSON output gives each field's 0-based offset, 1-based position (as used by DFSORT and compiler MAP listings), byte length, category, digits, scale, sign handling, OCCURS strides, REDEFINES overlays, 88-level values, and a DFSORT format code. Use it to drive field-level conversion, copybook-aware file comparison, DFSORT control cards, and API contracts. `--format json-schema` drafts a contract that carries decimals as strings; review it before use. Check every warning: SYNCHRONIZED items, oversized REDEFINES, OCCURS DEPENDING ON tables, and unresolved COPY members all need confirmation against the compiler MAP listing.

### Step 5: Report the Mainframe Estate Brief

```markdown
## Mainframe Estate Brief: <scope>
- **Source of truth:** <SCM, stage, libraries; gaps such as modules without source>
- **Inventory:** <counts by kind and code lines; unused or duplicate members>
- **Subsystems in scope:** <CICS regions and transactions, IMS, Db2 subsystems and plans, VSAM, MQ, IDMS>
- **Batch:** <jobs, schedules, critical path, batch window, restart procedures>
- **External contracts:** <data sets, transfers, COMMAREAs, messages, screens, reports, return codes>
- **Data and encoding:** <CCSIDs, packed and binary fields, DBCS, collation-sensitive logic, dates>
- **Risk hotspots:** <top members by risk score, with the indicators>
- **Compile and runtime settings:** <compiler release and options, LE options, AMODE/RMODE>
- **Evidence gaps:** <what is missing and who can provide it>
```

Hand the brief to the calling playbook stage and keep it updated as gaps close.
