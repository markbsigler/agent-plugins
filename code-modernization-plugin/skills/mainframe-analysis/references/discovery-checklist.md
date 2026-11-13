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
