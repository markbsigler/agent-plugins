# Mainframe discovery checklist

Request the whole artifact set in one round, record what is missing, and keep the list with the estate brief. Missing artifacts are risks, not reasons to guess.

## Source and build

| Artifact | Typical location | Why it matters |
| --- | --- | --- |
| Program source (COBOL, PL/I, Assembler, Easytrieve, REXX) | SCM production stage: Endevor, ChangeMan ZMF, Code Pipeline (ISPW), SCLM, Panvalet, Librarian, or Git | The code to analyze; export with member names intact and one folder per library |
| Copybooks and includes | Copy libraries in the compile `SYSLIB` concatenation | When the same member exists in several libraries, the concatenation order decides which one the compiler used |
| Compile, link-edit, and bind procedures and build definitions | PROCLIBs, SCM processors, DBB or zAppBuild scripts | Compiler options, binder options (AMODE, RMODE, RENT, static `INCLUDE` statements), and Db2 BIND options change runtime behavior |
| Compiler listings with `LIST`, `MAP`, and `XREF` | SCM listing libraries or build output | The authoritative record of options, offsets, and cross references for each program |
| Load libraries | `STEPLIB`, `JOBLIB`, CICS `DFHRPL`, IMS program libraries | Compare with source: compile dates, binder IDR data (for example from `AMBLIST`). Modules without source must be flagged |
| Generator models | CA Gen, Telon, APS, Natural Construct, CSP | Decide whether the model or the generated COBOL is the source of truth |

## Runtime definitions

| Artifact | Why it matters |
| --- | --- |
| CICS CSD extract (`DFHCSDUP` output): transactions, programs, files, TS models, URIMAPs, pipelines, web services, MQ connections | Maps transactions to programs and files to data sets; shows threadsafe and API settings |
| CICS region topology (TOR, AOR, FOR, MRO and ISC connections), SIT parameters | Distributed program links, function shipping, and routing that the code does not show |
| BMS mapsets and generated symbolic maps | Screen contracts and the copybooks programs use |
| IMS system definition (transactions to programs), DBDs, PSBs, ACBs, MFS formats, OTMA and IMS Connect setup | Message routing, database views, and the external interface |
| Db2 DDL (tables, views, indexes, triggers, stored procedures, UDFs, sequences), DCLGENs, packages, plans, collections, BIND options, RUNSTATS currency, GRANTs | Data contract, access paths, isolation, and authorization |
| VSAM and data set definitions (`IDCAMS DEFINE`, `LISTCAT`), GDG bases, SMS classes, retention | Keys, alternate indexes, sharing options, and record formats |
| MQ objects: queue managers, queues, channels, triggers, and message copybooks | Asynchronous contracts and trigger-started programs |
| IDMS schemas and subschemas, Datacom or ADABAS definitions | Navigational database structure |
| Security definitions (RACF, ACF2, or Top Secret) for data sets, transactions, Db2 objects, batch user IDs, surrogates | Who can run what; must be mapped, not dropped |

## Batch and operations

- Job scheduler definitions and run history: CA 7, Control-M, IBM Z Workload Scheduler (TWS/OPC), Zeke, or ESP. Capture dependencies, data set triggers, calendars, cyclic jobs, SLAs, and the critical path.
- JCL jobs, procedures, `INCLUDE` members, `JCLLIB` order, and every `SYSIN` or `SYSTSIN` control member (sort cards, IDCAMS, Db2 utilities, `DSN RUN` commands).
- Run books: restart and rerun procedures, abend handling, operator replies, manual steps.
- File transfers: Connect:Direct (NDM), FTP or SFTP jobs, and partner file formats.
- Report distribution and archive (SYSOUT classes, output management products) and the consumers of each report.

## Runtime evidence

- SMF type 30 (job and step CPU, EXCP counts), type 110 (CICS), type 101 (Db2 accounting), and data set activity records, or the shop's capacity reports.
- CICS statistics, Db2 package usage, and scheduler history to find unused programs, transactions, and jobs. Removing dead inventory before estimating often shrinks the scope substantially.
- Abend history (S0C7, S0C4, timeouts) by program; it shows where invalid data and fragile logic live.

## Exports the bundled scripts read

Request these in the same round as the rest of the checklist. People export them; the agent never connects to z/OS. Templates in this skill's `assets/` directory produce several of them, and the platform team reviews and submits every template.

| Evidence | How to produce | Read by |
| --- | --- | --- |
| Program source, copybooks, JCL and procedures, BMS and MFS maps | The production libraries or SCM stage named as the source of truth | `mainframe_inventory.py`; the `copybook-data` skill's `copybook_layout.py`; the `mainframe-batch-flow` skill's `batch_flow.py`; the `mainframe-program-docs` skill's `cobol_flow.py` and `screen_map.py` |
| Data set records (golden masters and test data) | Binary transfers of the data sets, keeping RDWs for variable-length records, with each data set's RECFM and LRECL | The `copybook-data` skill's `record_decode.py`, `record_compare.py`, and `record_mask.py` |
| Usage evidence | SMF type 30 step records summarized to a CSV per program; CICS program and transaction statistics; Db2 `LASTUSED` from `SYSIBM.SYSPACKAGE` (query 1 in [../assets/db2-catalog.sql](../assets/db2-catalog.sql)); scheduler run history. Each CSV needs a name column (`name`, `program`, `member`, `package`, `job`, or `transaction`) and may have a count column (`count`, `uses`, or `executions`); a row without a count counts as one use | `mainframe_inventory.py --usage` |
| CICS CSD extract | `DFHCSDUP EXTRACT` with the supplied program `DFH0CBDC`, which writes `DEFINE` commands: [../assets/csd-extract.jcl](../assets/csd-extract.jcl) | `mainframe_inventory.py` |
| Scheduler definitions | Control-M XML from `exportdeffolder` or `exportdefjob`; IBM Z Workload Scheduler batch-loader statements (`ADSTART`, `ADOP`, `ADDEP`), for example extracted with Workload Automation Programming Language; CA 7 `LJOB` listings of requirements and triggers, converted to a `predecessor,successor` CSV | The `mainframe-batch-flow` skill's `batch_flow.py` for dependencies; `mainframe_inventory.py` for jobs in no schedule |
| MQSC definitions | `CSQUTIL COMMAND` with `MAKEDEF`: [../assets/mqsc-export.jcl](../assets/mqsc-export.jcl) | `mainframe_inventory.py` |
| Catalog entries | `IDCAMS LISTCAT ... ALL`: [../assets/listcat.jcl](../assets/listcat.jcl) | `mainframe_inventory.py`, which prefers the catalog over IDCAMS `DEFINE` statements and reports where they disagree |
| Compiler and binder listings | The listings the build keeps (compile with `LIST` or `MAP` and the options in production; binder `LIST,MAP,XREF`) | `mainframe_inventory.py` (compiler release, options, AMODE, RMODE) |
| Db2 BIND statements | The bind control cards or the SCM's bind definitions | `mainframe_inventory.py` |
| IMS DBD and PSB source | DBDGEN and PSBGEN source from the IMS libraries or the SCM | `ims_model.py`, and `mainframe_inventory.py` for PSB names |
| Db2 catalog extracts | Packages, dependencies, plan package lists, tables, columns with CCSIDs, and index keys: [../assets/db2-catalog.sql](../assets/db2-catalog.sql), run by [../assets/db2-catalog-unload.jcl](../assets/db2-catalog-unload.jcl) | The agent, for the Db2 sections of the estate brief and the data ownership matrix |

Later stages use [../assets/explain-compare.sql](../assets/explain-compare.sql) (access paths before and after a rebind) and [../assets/compare-outputs.jcl](../assets/compare-outputs.jcl) (golden-master comparison with SuperC).

When exporting:

- Choose the transfer mode by content, as "Record formats and transfers" in [data-and-encoding.md](data-and-encoding.md) describes: binary for data sets, and for source whose code page is unknown; text only for source and reports that the transfer converts with the right code page.
- Put each kind in its own directory, and record the source data set, RECFM, LRECL, code page, and transfer mode of every file so the estate brief can cite them.
- Keep production data out of Git: export it into an ignored directory, and mask records with the `copybook-data` skill's `record_mask.py` before sharing them.

## Hidden interfaces to look for

- Programs started dynamically: `CALL identifier`, `EXEC CICS LINK PROGRAM(variable)`, `START TRANSID`, MQ triggers, and scheduler-driven `PARM` values.
- Programs hidden behind utilities: `IKJEFT01` with `RUN PROGRAM(...)`, `DFSRRC00` with `PARM='DLI,program,psb'`, and procedures run with `MBR=` or `PGM=` symbols.
- Business logic outside programs: DFSORT `INCLUDE`, `OUTREC`, `SUM`, and `JOINKEYS`; Easytrieve reports; REXX; ISPF file-tailoring skeletons that generate JCL; Db2 triggers and stored procedures.
- Consumers outside the estate: 3270 screen scrapers, RPA bots, HATS, CICS Transaction Gateway clients, DRDA clients, partner file feeds, and downstream report readers.

## Scoping heuristics

- High fan-in modules (date routines, error handlers, I/O modules, security checks) need the most characterization and the least change.
- Clones (near-identical programs) and generated code should be modernized once, at the source.
- Vendor packages are replaced or upgraded, not refactored.
- Assembler and unknown-language modules without source are rearchitecture or replacement candidates; record them as risks immediately.

## Elicitation addendum for mainframe scope

Ask at most two or three per round, starting with the gaps that block analysis:

1. Where is the production source of truth, and can you export the libraries used in the compile concatenation?
2. Which subsystems are in scope: CICS, IMS TM or DB, Db2, VSAM, MQ, IDMS, batch?
3. Is the target to stay on z/OS, run hybrid, or move off-platform, and by when?
4. Which constraints apply: batch window, CPU or MSU budget, regulatory obligations (for example SOX, PCI DSS, HIPAA), data residency, change freezes?
5. What test assets exist: regression suites, test LPARs and regions, masked production data, the ability to run parallel?
