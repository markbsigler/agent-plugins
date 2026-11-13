# code-modernization-plugin

An [Agent Plugin](https://agent-plugins.org/) that draws a strict line between **Refactor** (behavior-preserving code transformation) and **Rearchitect** (structural and topology transformation), routes every request through interactive discovery and Gartner-aligned triage, and runs each track as a 4-stage playbook with human approval gates. The triage and playbook skills are stack-neutral; stack-specific knowledge comes from pluggable [stack profiles](#stack-profiles). The first profile, `mainframe-analysis`, adds deep IBM Z support: COBOL, PL/I, Assembler, JCL, REXX, and Easytrieve with CICS, IMS, Db2 for z/OS, VSAM, IDMS, and MQ.

```text
code-modernization-plugin/
├── plugin.json                                      # Portable manifest (Agent Plugins 1.0.0)
├── skills/                                          # Portable core logic & playbooks
│   ├── modernization-triage/                        # Shared discovery, Gartner classification, stack profile registry
│   ├── playbook-refactor/                           # Track A: Behavior-preserving code transformation
│   ├── playbook-rearchitect/                        # Track B: Structural & topology transformation
│   └── mainframe-analysis/                          # Stack profile: IBM Z (z/OS)
│       ├── SKILL.md
│       ├── scripts/                                 # Read-only, stdlib-only PEP 723 scripts
│       │   ├── mainframe_inventory.py               #   inventory + dependency graph + risk scores
│       │   └── copybook_layout.py                   #   exact copybook offsets + JSON Schema draft
│       └── references/                              # Loaded on demand
│           ├── playbook-stages.md                   #   z/OS tasks for every playbook stage
│           └── ...                                  #   COBOL, data, CICS/IMS, Db2/IMS/VSAM, batch, testing, targets, tools
├── com.github.copilot/                              # Client extension files (see below)
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
| [`modernization-triage`](./skills/modernization-triage/SKILL.md) | Detects the estate, loads matching stack profiles, runs the elicitation protocol, classifies Refactor vs. Rearchitect (and flags Gartner's other options: encapsulate, rehost, replatform, rebuild, replace), and hands off with a Triage Brief |
| [`playbook-refactor`](./skills/playbook-refactor/SKILL.md) | Track A: audit, characterization and NFR baseline, incremental transformation, equivalence verification |
| [`playbook-rearchitect`](./skills/playbook-rearchitect/SKILL.md) | Track B: seam analysis and ADR, contracts and anti-corruption layer, strangler slice and dual run, parity, cutover, and decommissioning |
| [`mainframe-analysis`](./skills/mainframe-analysis/SKILL.md) | Stack profile for IBM Z: inventory, dependency graph, copybook layouts, Mainframe Estate Brief, and the z/OS tasks for every playbook stage |

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
| Discovery and estate brief | Inventory, dependency graph, evidence gaps | Workflow steps and bundled scripts |
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

- **Discovery:** the full artifact checklist (SCM, compile listings, CSD, IMS definitions, Db2 DDL and BIND options, VSAM and GDG definitions, schedules, run books, SMF evidence) and hidden interfaces (programs behind `IKJEFT01`, `DFSRRC00`, and procedure symbols; business logic in DFSORT control cards; screen scrapers; file transfers).
- **Language semantics:** fixed-format editing rules, `WORKING-STORAGE` persistence, decimal truncation and rounding, `TRUNC`/`NUMPROC`/`ARITH` effects, `REDEFINES`, `OCCURS DEPENDING ON`, `PERFORM THRU`, `ALTER`, `FILE STATUS`, and the Enterprise COBOL V4-to-V6 migration path.
- **Data:** CCSIDs, zoned, packed, and binary encodings, hexadecimal floating point, DBCS, sentinels, EBCDIC collation, mainframe date formats, record formats and transfers.
- **Subsystems:** CICS (pseudo-conversation, units of work, `HANDLE` vs. `RESP`, BMS, threadsafe), IMS TM and DB, Db2 for z/OS (binding, SQLCODEs, locking, migration), VSAM, GDGs, IDMS, Datacom, ADABAS, PL/I, HLASM, REXX, Easytrieve, Natural, and generated code.
- **Evidence:** batch and online golden masters, copybook-aware comparison, masked test data, parallel runs and reconciliation, and z/OS NFR baselines from SMF.
- **Targets:** in-place, hybrid, and off-platform options, COBOL translation rules, subsystem mappings, and strangler patterns (z/OS Connect facades, COBOL router programs, change data capture, outbox).
- **Playbook stage tasks:** inventory, contract surface, and compiler settings (Refactor Stage 1); golden masters and SMF baselines (Stage 2); fixed-format editing, copybook, and bind discipline (Stage 3); equivalence evidence (Stage 4); dependency graph, data ownership, and units of work (Rearchitect Stage 1); copybook-derived contracts and COBOL router seams (Stage 2); change data capture and batch parallel runs (Stage 3); and cycle-based parity and decommissioning (Stage 4).

Run the bundled scripts directly (Python 3.11+, standard library only):

```bash
uv run --script skills/mainframe-analysis/scripts/mainframe_inventory.py <export-dir> --format markdown
uv run --script skills/mainframe-analysis/scripts/copybook_layout.py CUSTREC.cpy --format markdown
uv run --script skills/mainframe-analysis/scripts/copybook_layout.py COMMAREA.cpy --format json-schema
```

Both scripts only read files. They work on source exported to a local directory and decode members that are still EBCDIC (80-byte records in code page 037).

## Install

Add the marketplace, then install just this plugin:

```text
/plugin marketplace add markbsigler/agent-plugins
/plugin install code-modernization-plugin@agent-plugins
```

Any Agent Plugins client that supports skills loads `plugin.json` and the four skills. Clients such as VS Code also surface skills as slash commands.

### Client extension directories

`com.github.copilot/` and `com.cursor.client/` are client extension directories under [§8 of the Agent Plugins specification](https://agent-plugins.org/specification#8-client-extensions): each namespace belongs to the client that implements it, and clients that do not implement a namespace ignore it. The plugin works without them; they add slash-command prompts, passive guardrails, and auto-attached editing rules. If your client does not load them from the plugin, copy them into the workspace:

| Files | Copy to |
| --- | --- |
| `com.github.copilot/prompts/*.prompt.md` | `.github/prompts/` (VS Code prompt files) |
| `com.github.copilot/instructions/*.instructions.md` | `.github/instructions/` |
| `com.cursor.client/rules/*.mdc` | `.cursor/rules/` |

The mainframe editing rules match common extensions (`.cbl`, `.cob`, `.cpy`, `.jcl`, `.prc`, `.pli`, `.asm`, `.bms`). Members exported without extensions are not matched automatically; reference the rule manually or add extensions on export.

## Canonical references

- Plugin package format — https://agent-plugins.org/specification
- Skill format — https://agentskills.io/specification

## License

[MIT](./LICENSE)
