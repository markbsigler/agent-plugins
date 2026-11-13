# Playbook stage tasks (IBM Z / z/OS)

Stack profile tasks for the `playbook-refactor` and `playbook-rearchitect` skills. Each playbook
stage tells the agent to complete the matching section below for every loaded stack profile. Do
them alongside the stage's generic tasks and include the results in that stage's gate review.

## Refactor

### Refactor Stage 1: Tech Debt, Security & Dependency Audit

- Run the inventory (`scripts/mainframe_inventory.py`, Workflow Step 2 in this skill); list risk hotspots (`ALTER`, `GO TO DEPENDING ON`, `PERFORM THRU`, dynamic `CALL`, `HANDLE CONDITION`, dynamic SQL, words the target compiler reserves), unresolved references, duplicate and shadowed members, modules without source, `cross_checks` findings (file definitions that disagree with VSAM definitions, and DEFINE statements that disagree with the catalog), and data sets that CICS and batch both update.
- Record the compiler release and options, Language Environment runtime options, binder `AMODE` and `RMODE`, and Db2 `BIND` options for each program from listings and build definitions.
- Define the contract surface that must not change: data sets and layouts (computed with the `copybook-data` skill), COMMAREAs and containers, MQ messages, screens and their consumers (the `mainframe-program-docs` skill's `screen_map.py` records field positions), reports, return codes, and file transfers.
- Trace each job stream in scope with the `mainframe-batch-flow` skill: the expanded JCL, what each `COND` or `IF` test means, data set lineage, and data dependencies the scheduler does not enforce.
- Document programs the change touches with the `mainframe-program-docs` skill: paragraph flow, unreachable paragraphs, and business-rule candidates for subject-matter experts to confirm.
- Check where invalid data (S0C7 history), EBCDIC-sensitive logic (collation, `HIGH-VALUES`, hexadecimal literals), and date logic live.
- For compiler upgrades, plan IBM's migration path (diagnostic compile and regression first, optimized compile second) and the PDSE and `AMODE` prerequisites; see "Upgrading Enterprise COBOL" in [cobol-language.md](cobol-language.md).
- Use runtime evidence (SMF, CICS statistics, Db2 `LASTUSED`, scheduler history) to exclude unused programs and jobs from scope: pass it to the inventory with `--usage`, and confirm each `dead_code` candidate with its owner before removing it.
- For threadsafe CICS work, start from the inventory's `cics_threadsafe` assessment, and for cost goals record the levers and baselines in [performance-cost.md](performance-cost.md).

### Refactor Stage 2: Characterization & Nonfunctional Baseline

- Build a golden master as [equivalence-testing.md](equivalence-testing.md) describes: batch outputs compared field by field from copybook layouts, return codes, SYSOUT messages, Db2/IMS/VSAM end state, and online responses (COMMAREAs, containers, screens, messages).
- Include edge inputs: invalid numeric data that abends today, empty and maximum-volume files, every record type, and month-end, year-end, leap-day, and two-digit-year boundary dates under a controlled clock.
- Record z/OS baselines: CPU per job step and per transaction (SMF types 30, 110, 101), elapsed time against the batch window, I/O counts, Db2 getpages, and CICS response times, over repeated runs.
- Mask production-derived test data while keeping packed, zoned, and key values valid: the `copybook-data` skill's `record_mask.py` masks by field with a keyed permutation, so the same value masks the same way in every file and distinct keys stay distinct.

### Refactor Stage 3: Incremental Code Transformation

- Edit COBOL in fixed format: never past column 72, no tabs, sequence and identification areas preserved, only characters that exist in the target code page.
- Treat copybooks as contracts: change one only with an impact list from the inventory, keep its byte layout identical (the `copybook-data` skill's `copybook_layout.py --diff` must report no breaking change), and recompile every program that copies it.
- Keep build, link-edit, and Db2 bind consistent: a recompiled program needs its package rebound with the recorded options, promoted through the SCM stages together.
- Apply compiler option changes as their own step, separately from source changes, so any behavior difference can be attributed.
- Preserve `RETURN-CODE` values, abend behavior, `FILE STATUS` handling, and decimal arithmetic (truncation, `ROUNDED`, high-order truncation) exactly.
- For automated language conversion, follow the translation rules in [target-mappings.md](target-mappings.md) and plan a second pass to make generated code idiomatic.

### Refactor Stage 4: Equivalence & NFR Verification

- Compare every golden-master output with zero unexplained differences, including packed sign nibbles, record counts, trailer control totals, sort order, return codes, and the invalid-data cases. The `copybook-data` skill's `record_compare.py` compares field by field and reports differences in format only, such as a changed sign nibble, separately.
- Re-run the business-cycle scenarios (month-end, year-end, leap day) and confirm identical results.
- Report CPU, MSU, elapsed time, and I/O deltas against the Stage 2 noise band, and attach the evidence package from [equivalence-testing.md](equivalence-testing.md).

## Rearchitect

### Rearchitect Stage 1: Domain Seam Analysis & ADR Generation

- Build the dependency graph from the inventory: transactions to programs (CSD), programs to copybooks, called programs, Db2 tables, VSAM files, and IMS segments; jobs to steps, programs (including those behind `IKJEFT01`, `DFSRRC00`, and procedure symbols), and data sets; and scheduler dependencies (the `mainframe-batch-flow` skill).
- Produce a data ownership matrix with `scripts/seam_report.py` (Workflow Step 5): which programs and jobs create, read, update, and delete each table, data set, segment, and queue. Shared writers are the hardest seams; write clusters are the first candidate boundaries, and their outside readers become API or event consumers.
- Analyze units of work: the report's transaction footprints show which resources (Db2, VSAM, MQ, IMS, TS and TD queues) a transaction updates before its syncpoint. Confirm batch commit intervals in the code.
- Catalog interfaces and hidden consumers from the report and from the owners: file transfers, MQ channels, CTG and DRDA clients, existing APIs, screen scrapers, and report readers.
- Count local `LINK`s and resource accesses per transaction (in each footprint) to set a latency budget for any slice that moves off-platform.
- For IMS data, model the hierarchy, PSB sensitivity, and a draft relational schema with `scripts/ims_model.py`, and check program access against each PSB.
- The ADR must also decide: target platform (in place, hybrid, or off-platform), data synchronization (change data capture or outbox, never ad hoc dual writes), consistency strategy for split units of work, encoding and collation at the boundary, security mapping (RACF, ACF2, or Top Secret to the target identity model), batch window and schedule impact, rollback, retention and regulatory obligations, and decommissioning prerequisites.

### Rearchitect Stage 2: Seam Isolation & Interface Contract Definition

- Derive contracts from the boundary copybooks with the `copybook-data` skill (`copybook_layout.py --format json-schema`, or `avro` and `asyncapi` for events): decimals as strings or exact decimals, `OCCURS` as bounded arrays, `REDEFINES` as explicit variants chosen by a discriminator, `88` levels as documented value sets, and `FILLER` excluded. Review names and required fields with the domain owners.
- Encapsulate before re-implementing: expose the business-logic program through z/OS Connect, CICS web services or Liberty, IMS Connect, or MQ, and place an API gateway in front as the strangler facade.
- If presentation and business logic are mixed, separate them first (BMS program `LINK`s to a business-logic program) as a behavior-preserving refactor with its own tests.
- For branch by abstraction inside COBOL, insert a router program that reads a toggle from a Db2 control table, VSAM control record, or container and defaults to the legacy path.
- Put EBCDIC and Unicode conversion, decimal mapping, sentinel values (`HIGH-VALUES`, `LOW-VALUES`), and date formats inside the ACL, never in callers.
- For MQ seams, keep message order, units of work, and headers as [mq.md](mq.md) describes, and map identities as [security.md](security.md) describes.

### Rearchitect Stage 3: Strangler Slice Implementation & Dual-Run

- Keep data in step with log-based change data capture from Db2, IMS, or VSAM, or with a transactional outbox (Db2 table plus MQ) published from inside the unit of work. Do not add dual writes from COBOL to remote stores inside CICS units of work.
- Make consumers idempotent and order-aware, and convert encodings and numeric formats with layouts in the pipeline.
- For batch slices, cut at data set boundaries, run the new step in parallel with the legacy step, and reconcile outputs every cycle (the `copybook-data` skill's `record_compare.py` with `--key` and `--total`).
- Reach operational parity: monitoring, alerting, run books, restart procedures, security, and audit trails equivalent to the mainframe's.

### Rearchitect Stage 4: Parity Validation, Cutover & Legacy Decommissioning

- Run in parallel across full business cycles (month-end and, where relevant, quarter-end and year-end) with reconciliation of counts, control totals, and balances; only differences approved in the ADR may remain, and business owners sign off.
- Cut over per transaction, operation, or job stream, keeping the routing toggle until the rollback window closes.
- Decommission in dependency order and only after retention obligations allow it, confirming with a fresh inventory and usage evidence that nothing still calls or reads what you remove: CSD definitions, programs and load modules, Db2 packages, plans, and tables, VSAM and GDG data sets, JCL, procedures, and control cards, scheduler definitions, MQ objects, security profiles, and SCM elements. Archive what regulations require.
- Measure and report the CPU and MSU change alongside the new capabilities.
