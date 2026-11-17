# code-modernization-plugin

An [Agent Plugin](https://agent-plugins.org/) that draws a strict line between **Refactor** (behavior-preserving code transformation) and **Rearchitect** (structural and topology transformation), routes every request through interactive discovery, enterprise rulebooks (`.modernize/rulebook/`), and triage, and runs each track as a 4-stage playbook with human approval gates, frozen behavioral baselines (`behavioral-baseline`), and requirement traceability. The triage and playbook skills are stack-neutral; stack-specific knowledge comes from pluggable [stack profiles](#stack-profiles): `mainframe-analysis` (IBM Z), `java-analysis` (Java / Spring Boot / Jakarta EE), and `dotnet-analysis` (.NET Framework / modern .NET). Three mainframe tool skills (`copybook-data`, `mainframe-batch-flow`, and `mainframe-program-docs`) and the stack-neutral `behavioral-baseline` skill complete the toolkit.

```text
code-modernization-plugin/
├── plugin.json                                      # Portable manifest (Agent Plugins 1.0.0)
├── skills/                                          # Portable core logic & playbooks
│   ├── modernization-triage/                        # Shared discovery, rulebooks, track classification, profile registry
│   ├── playbook-refactor/                           # Track A: Behavior-preserving code transformation
│   ├── playbook-rearchitect/                        # Track B: Structural & topology transformation
│   ├── behavioral-baseline/                         # Tool skill: frozen TC-XXX baselines, rulebooks, traceability gates
│   ├── mainframe-analysis/                          # Stack profile: IBM Z (z/OS)
│   │   ├── SKILL.md
│   │   ├── scripts/                                 # Read-only, stdlib-only PEP 723 scripts
│   │   │   ├── mainframe_inventory.py               #   inventory, CRUD-tagged dependency graph, findings
│   │   │   ├── zos_definitions.py                   #   CSD, IDCAMS/LISTCAT, MQSC, binds, listings, schedules
│   │   │   ├── seam_report.py                       #   data ownership, write clusters, transaction footprints
│   │   │   ├── ims_model.py                         #   IMS hierarchy, PSB checks, draft relational DDL
│   │   │   └── zos_encoding.py                      #   EBCDIC code pages, record formats, hex dumps
│   │   ├── assets/                                  # Extraction job and query templates for the platform team
│   │   └── references/                              # Loaded on demand
│   │       ├── playbook-stages.md                   #   z/OS tasks for every playbook stage
│   │       └── ...                                  #   COBOL, data, CICS/IMS, Db2/IMS/VSAM, batch, MQ, security, cost, DevOps
│   ├── java-analysis/                               # Stack profile: Java / Spring Boot / Jakarta EE (java_inventory.py)
│   ├── dotnet-analysis/                             # Stack profile: .NET Framework / Modern .NET (dotnet_inventory.py)
│   ├── copybook-data/                               # Tool skill: layouts, diffs, decode, compare, mask
│   ├── mainframe-batch-flow/                        # Tool skill: JCL expansion, COND logic, data set lineage
│   └── mainframe-program-docs/                      # Tool skill: COBOL flow and rules, 3270 screen maps
├── com.github.copilot/                              # Client extension files (see below)
│   ├── agents/
│   │   ├── modernize.agent.md                       # Orchestrator agent
│   │   ├── modernize-refactor.agent.md              # Track A coordinator agent
│   │   └── modernize-rearchitect.agent.md           # Track B coordinator agent
│   ├── prompts/
│   │   ├── modernize.prompt.md                      # /modernize: triage, then launch the playbook
│   │   ├── refactor.prompt.md                       # /refactor: Track A directly
│   │   └── rearchitect.prompt.md                    # /rearchitect: Track B directly
│   └── instructions/
│       ├── modernization-guardrails.instructions.md # Passive safety rules
│       └── mainframe-sources.instructions.md        # Fixed-format COBOL and JCL editing rules
├── com.cursor.client/
│   └── rules/
│       ├── modernization-triage.mdc                 # Routes intent to Refactor vs. Rearchitect
│       ├── modernization-guardrails.mdc             # Passive safety rules
│       └── mainframe-sources.mdc                    # Auto-attached to mainframe source files
├── README.md
├── CHANGELOG.md
└── LICENSE
```

## Skills

| Skill | Role |
| --- | --- |
| [`modernization-triage`](./skills/modernization-triage/SKILL.md) | Detects the estate, loads `.modernize/rulebook/` policies and matching stack profiles, runs the elicitation protocol, classifies Refactor vs. Rearchitect (and flags the other modernization options: encapsulate, rehost, replatform, rebuild, replace), and persists `.modernize/triage-brief.md` |
| [`playbook-refactor`](./skills/playbook-refactor/SKILL.md) | Track A: audit, frozen characterization and NFR baseline, incremental transformation, equivalence verification |
| [`playbook-rearchitect`](./skills/playbook-rearchitect/SKILL.md) | Track B: seam analysis and ADR, contracts and anti-corruption layer, strangler slice and dual run, parity, cutover, and decommissioning |
| [`behavioral-baseline`](./skills/behavioral-baseline/SKILL.md) | Stack-neutral baseline & gate skill (`baseline_gate.py`): loads `.modernize/rulebook/` and `.modernize/learnings/`, freezes `.modernize/baseline/test-cases.md` and `testdata/` with SHA-256 digests, verifies 1:1 `TC-XXX` test coverage, and runs `spec-quality`, `spec-to-plan`, `plan-to-tasks`, and `completeness` traceability gates |
| [`mainframe-analysis`](./skills/mainframe-analysis/SKILL.md) | Stack profile for IBM Z: inventory, CRUD-tagged dependency graph, definitions from CSD, IDCAMS, LISTCAT, MQSC, binds, listings, and schedules, seam and data ownership evidence, IMS models, the Mainframe Estate Brief, and the z/OS tasks for every playbook stage |
| [`java-analysis`](./skills/java-analysis/SKILL.md) | Stack profile for Java / JVM (`java_inventory.py`): Maven and Gradle modules, Java 8→21 and Spring Boot 2→3 upgrades, `javax.*` → `jakarta.*` impact, WebSphere/EJB/JNDI/Struts coupling, JPA/SQL tables, `BigDecimal` financial safety, and target-side rules for mainframe-to-Java migrations |
| [`dotnet-analysis`](./skills/dotnet-analysis/SKILL.md) | Stack profile for .NET (`dotnet_inventory.py`): `.sln`/`.csproj` analysis, SDK-style vs. legacy `.NET Framework` target monikers, `packages.config` vs. `PackageReference`/CPM, `System.Web`/WCF/EF6 seams, `decimal` financial safety, and target-side rules for mainframe-to-.NET migrations |
| [`copybook-data`](./skills/copybook-data/SKILL.md) | Exact record layouts from COBOL copybooks, PL/I structures, and Assembler DSECTs (SYNCHRONIZED slack bytes included); layout diffs; JSON Schema, Avro, AsyncAPI, and DFSORT symbols; field-level decoding, golden-master comparison, and consistent masking of record files |
| [`mainframe-batch-flow`](./skills/mainframe-batch-flow/SKILL.md) | Expands JCL as the converter does, explains `COND` and `IF` logic, reads utility control statements, and traces data set lineage and job dependencies, checked against scheduler exports |
| [`mainframe-program-docs`](./skills/mainframe-program-docs/SKILL.md) | Documentation skeletons for COBOL programs (paragraph flow, unreachable paragraphs, interfaces, business-rule candidates) and BMS or MFS screens (field tables, mockups, screen contracts) |

## Two governance tracks

| Track | Definition | Core invariant |
| --- | --- | --- |
| **A: Refactor** | Code-level restructuring, framework, runtime, or compiler upgrades, CVE remediation, nonfunctional optimization | External behavior, contracts, data ownership, and deployment topology stay identical |
| **B: Rearchitect** | Material structural or topology change (modular monolith, microservices, event-driven, serverless) | One bounded context at a time, through seams, contracts, anti-corruption layers, and reversible cutover |

Both playbooks stop at `APPROVE STAGE 1` and `APPROVE STAGE 2` before any production code changes, prefix every response with `[REFACTOR PLAYBOOK: STAGE X/4]` or `[REARCHITECT PLAYBOOK: STAGE X/4]`, and end with a completion marker.

## Interactive elicitation

| Track | Questions |
| --- | --- |
| Shared triage | Must external APIs, schemas, and deployment boundaries remain 100% unchanged? Is the driver tech debt and upgrades, or new topology and capabilities? Which module, service, or domain is in scope? |
| Refactor | Primary driver (framework upgrade, tech debt, security/CVE, performance)? Target version or benchmark? Test coverage baseline? |
| Rearchitect | Target pattern (modular monolith, microservices, event-driven, serverless)? First bounded context? Migration pattern (Strangler Fig, Branch by Abstraction, CDC)? |
| Stack profile addendum (IBM Z example) | Source of truth and compile libraries? Subsystems in scope? Stay on z/OS, hybrid, or off-platform? Batch window, MSU budget, regulation, freezes? Test assets and parallel-run options? |

## Stack profiles

Triage and both playbooks contain only stack-neutral tasks. Everything stack-specific lives in stack profile skills:

1. Triage matches the scope against its stack profiles table and loads every profile that fits. A mixed estate can load several, and a Rearchitect slice usually loads one for the legacy stack and, when one exists, one for the target stack.
2. Each loaded profile adds its discovery, elicitation questions, and classification examples to triage, and the Triage Brief records which profiles apply.
3. Every playbook stage has a required step: complete that stage's section (for example `Refactor Stage 2`) in each loaded profile's `references/playbook-stages.md`. Each approval gate asks for the profiles' results.
4. When no profile matches, the generic tasks apply on their own.

Every profile provides the same parts, so the playbooks call each one the same way:

| Part | Purpose | In `mainframe-analysis` |
| --- | --- | --- |
| Detection signals | How triage recognizes the stack | "Detection signals" section of `SKILL.md` |
| Discovery and estate brief | Inventory, dependency graph, evidence gaps | Workflow steps, bundled scripts, and the tool skills |
| Contract surface | What counts as external behavior | Operating rule 5 |
| Elicitation addendum | Stack-specific triage questions | `references/discovery-checklist.md` |
| Classification examples | Stack-specific Refactor vs. Rearchitect examples | "Classification examples" section of `SKILL.md` |
| Playbook stage tasks | Sections `Refactor Stage 1` to `4` and `Rearchitect Stage 1` to `4` | `references/playbook-stages.md` |
| Equivalence evidence | Golden masters and NFR baselines | `references/equivalence-testing.md` |
| Target mappings | Target platforms, translation rules, and transition patterns | `references/target-mappings.md` |
| Editing rules (optional) | Copilot instructions and Cursor rules for the stack's source files | `mainframe-sources.*` in the client extension directories |

To add a stack (for example Java EE, .NET Framework, or IBM i):

1. Create `skills/<stack>-analysis/` with a `SKILL.md` whose description says when to load it, a "Stack profile" table mapping the parts above to its files, and `references/playbook-stages.md` with all eight stage sections.
2. Add a row for it to the stack profiles table in [`modernization-triage`](./skills/modernization-triage/SKILL.md).
3. Optionally add editing rules under `com.github.copilot/instructions/` and `com.cursor.client/rules/`, and list them in `plugin.json`.

Profiles for common target stacks such as Java and .NET pay off twice: as stacks in their own right, and as the target side of a conversion from another stack. In the [agent-plugins repository](https://github.com/markbsigler/agent-plugins), a test checks that every registered profile provides all eight stage sections, and `AGENTS.md` explains how to test bundled scripts.

## IBM Z stack profile: `mainframe-analysis`

Triage loads this profile when the scope contains mainframe artifacts, and both playbooks then run its z/OS tasks at every stage. It covers:

- **Discovery:** the full artifact checklist (SCM, compile listings, CSD, IMS definitions, Db2 DDL, catalog, and BIND options, VSAM and GDG definitions and LISTCAT reports, MQSC, schedules, run books, SMF evidence), templates for the extraction jobs, and hidden interfaces (programs behind `IKJEFT01`, `DFSRRC00`, and procedure symbols; business logic in DFSORT control cards; screen scrapers; file transfers).
- **Inventory findings:** create, read, update, and delete access on every resource; dynamic `CALL` and `LINK` targets resolved from literals; COBOL files checked against VSAM definitions and DEFINE statements against the catalog; data sets that CICS and batch both update; CICS threadsafe readiness; and dead code confirmed with usage evidence.
- **Language semantics:** fixed-format editing rules, `WORKING-STORAGE` persistence, decimal truncation and rounding, `TRUNC`/`NUMPROC`/`ARITH` effects, `REDEFINES`, `OCCURS DEPENDING ON`, `PERFORM THRU`, `ALTER`, `FILE STATUS`, and the Enterprise COBOL V4-to-V6 migration path.
- **Data:** CCSIDs, zoned, packed, and binary encodings, hexadecimal floating point, DBCS, sentinels, EBCDIC collation, mainframe date formats, record formats and transfers.
- **Subsystems:** CICS (pseudo-conversation, units of work, `HANDLE` vs. `RESP`, BMS, threadsafe), IMS TM and DB, Db2 for z/OS (binding, SQLCODEs, locking, migration), VSAM, GDGs, MQ (queue sharing, bridges, ordering, event streaming), IDMS, Datacom, ADABAS, PL/I, HLASM, REXX, Easytrieve, Natural, and generated code.
- **Operations:** security (RACF, ACF2, and Top Secret; identity propagation into APIs), performance and cost (MSU, zIIP, compiler and Db2 levers), and DevOps (Git, DBB, pipelines, and testing).
- **Evidence:** batch and online golden masters, copybook-aware comparison, masked test data, parallel runs and reconciliation, and z/OS NFR baselines from SMF.
- **Targets:** in-place, hybrid, and off-platform options, COBOL translation rules, subsystem mappings, and strangler patterns (z/OS Connect facades, COBOL router programs, change data capture, outbox).
- **Playbook stage tasks:** inventory, contract surface, batch flow, and compiler settings (Refactor Stage 1); golden masters, masked test data, and SMF baselines (Stage 2); fixed-format editing, copybook, and bind discipline (Stage 3); field-level equivalence evidence (Stage 4); dependency graph, data ownership matrix, transaction footprints, and IMS models (Rearchitect Stage 1); copybook-derived contracts and COBOL router seams (Stage 2); change data capture and batch parallel runs (Stage 3); and cycle-based parity and decommissioning (Stage 4).

Run the bundled scripts directly (Python 3.11+, standard library only):

```bash
uv run --script skills/mainframe-analysis/scripts/mainframe_inventory.py <export-dir> --format markdown
uv run --script skills/mainframe-analysis/scripts/mainframe_inventory.py <export-dir> --usage smf.csv > inventory.json
uv run --script skills/mainframe-analysis/scripts/seam_report.py inventory.json --format markdown
uv run --script skills/mainframe-analysis/scripts/ims_model.py dbd/ psb/ --format ddl
uv run --script skills/copybook-data/scripts/copybook_layout.py CUSTREC.cpy --format markdown
uv run --script skills/copybook-data/scripts/record_compare.py CUSTREC.cpy GOLDEN.DATA NEW.DATA --key CUST-ID
uv run --script skills/mainframe-batch-flow/scripts/batch_flow.py jcl/ --proclib proclib/ --format markdown
uv run --script skills/mainframe-program-docs/scripts/cobol_flow.py CUSTUPD.cbl --copylib copy/ > CUSTUPD.md
```

The scripts work on source and data exported to a local directory and decode members that are still EBCDIC (fixed, RDW-prefixed, or new-line delimited records, in 31 code pages including the national and euro variants). They only read files, except `record_mask.py`, which writes the masked copy to the `--output` file it is given.

The agent never connects to z/OS: people export the files. The job templates in `skills/mainframe-analysis/assets/` produce the CSD, LISTCAT, MQSC, and Db2 catalog extracts, and the platform team reviews and submits them. The `mainframe-analysis` skill's `references/discovery-checklist.md` lists every export the scripts read and how to transfer it.

## Install

Add the marketplace, then install just this plugin:

```text
/plugin marketplace add markbsigler/agent-plugins
/plugin install code-modernization-plugin@agent-plugins
```

Any Agent Plugins client that supports skills loads `plugin.json` and the ten skills. Clients such as VS Code also surface skills as slash commands.

### Client extension directories

`com.github.copilot/` and `com.cursor.client/` are client extension directories under [§8 of the Agent Plugins specification](https://agent-plugins.org/specification#8-client-extensions): each namespace belongs to the client that implements it, and clients that do not implement a namespace ignore it. The plugin works without them; they add custom agents, slash-command prompts, passive guardrails, and auto-attached editing rules. If your client does not load them from the plugin, copy them into the workspace:

| Files | Copy to |
| --- | --- |
| `com.github.copilot/agents/*.agent.md` | `.github/agents/` (Copilot custom agents) |
| `com.github.copilot/prompts/*.prompt.md` | `.github/prompts/` (VS Code prompt files) |
| `com.github.copilot/instructions/*.instructions.md` | `.github/instructions/` |
| `com.cursor.client/rules/*.mdc` | `.cursor/rules/` |

The mainframe editing rules match common extensions (`.cbl`, `.cob`, `.cpy`, `.jcl`, `.prc`, `.proc`, `.pli`, `.pl1`, `.inc`, `.asm`, `.mac`, `.mlc`, `.bms`, `.mfs`, `.ezt`, `.rexx`, `.rex`, `.clist`, `.psb`, `.dbd`, and uppercase `.CBL`, `.COB`, `.CPY`, `.JCL`). Members exported without extensions are not matched automatically; reference the rule manually or add extensions on export.

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification

## License

[MIT](./LICENSE)
