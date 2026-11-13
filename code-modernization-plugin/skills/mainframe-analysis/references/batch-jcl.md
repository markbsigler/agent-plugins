# Batch: JCL, utilities, schedules, restart, and reports

A batch application is the programs plus the JCL, the control cards, the schedule, and the run book. Analyze all four.

## JCL essentials

- `JOB` (class, message class, region, `RESTART=`), `EXEC` (`PGM=` or a procedure, `PARM`, `COND`, `REGION`, `TIME`), and `DD` statements (`DSN`, `DISP=(status,normal-end,abnormal-end)`, `SPACE`, `DCB` or `RECFM`/`LRECL`/`BLKSIZE`, `UNIT`, `VOL`, `SYSOUT`, `DUMMY`).
- In-stream data (`DD *` or `DD DATA`, ended by `/*` or a `DLM=` delimiter) often holds control cards with business parameters.
- Temporary data sets (`DSN=&&NAME`, `DISP=PASS`) and referbacks (`*.STEP.DD`) carry data between steps.
- Procedures with symbolic parameters (`&HLQ`), `SET` statements, `INCLUDE` members, `JCLLIB ORDER`, and overrides (`//STEP.DD`) change what actually runs. Resolve them to the expanded JCL before analysis.
- `COND=(4,LT)` skips the step if 4 is less than a previous return code; the logic is inverted compared with `IF (RC > 4) THEN`. Translate carefully and test both paths.
- Statements use columns 1-71; a statement continues when the operand field ends with a comma and the next line starts with `//` and a blank. JCL is uppercase except inside quoted values.

## Return codes and abends

- The program's `RETURN-CODE` becomes the step condition code; `COND`, `IF/THEN/ELSE`, and the scheduler's success criteria act on it. Preserve every code and its meaning.
- User abends (`Unnnn`, for example from `CEE3ABD` or `ILBOABN0`) deliberately stop a job for operator action. System abends to recognize: `S0C1` (operation), `S0C4` (protection), `S0C7` (data exception), `S0CB` (decimal divide), `S013` (open or DCB conflict), `S222` (cancelled), `S322` (CPU time exceeded), `S806` (module not found), `S80A` and `S878` (storage), `S913` (security), `SB37`, `SD37`, and `SE37` (space), `S722` (output limit), `U4038` (Language Environment severe condition).

## Restart, rerun, and recovery

- Step restart (`RESTART=step`) reruns from a step; programs with Db2 commits keep restart keys in a checkpoint table; IMS BMPs use `CHKP` and `XRST`.
- Reruns after partial output can duplicate records; `DISP=MOD` appends; relative GDG numbers change when a job is resubmitted. Run books define what operators do, and that procedure is a requirement.
- New designs must state their restart and idempotency rules explicitly and prove them in tests.

## Utilities that carry business logic

| Program | What to extract |
| --- | --- |
| DFSORT or Syncsort (`SORT`, `ICEMAN`, `SYNCSORT`) and `ICETOOL` | `INCLUDE`/`OMIT` filters, `INREC`/`OUTREC`/`OUTFIL` reformatting and splitting, `SUM` aggregation, `JOINKEYS` joins, symbols, and E15/E35 exit programs |
| `IDCAMS` | `DEFINE`, `DELETE`, `REPRO`, `LISTCAT`, and `IF LASTCC`/`MAXCC` logic |
| `IEBGENER`, `ICEGENER`, `IEBCOPY`, `IEFBR14` | Copies, PDS maintenance, allocation and deletion by `DISP` |
| `IKJEFT01`, `IKJEFT1A`, `IKJEFT1B` | TSO in batch; Db2 programs run as `DSN SYSTEM(...)` and `RUN PROGRAM(...) PLAN(...)` in `SYSTSIN`; REXX and CLIST execs |
| `DFSRRC00` | IMS batch and BMP regions; `PARM='DLI,program,psb'` names the program |
| `DSNUTILB`, `DSNTEP2`, `DSNTEP4`, `DSNTIAUL` | Db2 utilities, batch SQL, and unloads |
| `EZTPA00` | Easytrieve programs |
| `FTP`, Connect:Direct (`DMBATCH`) | File transfers to partners and other platforms |
| `ADRDSSU` | Dumps and restores (often backup steps that are part of recovery) |

The inventory script extracts programs hidden behind `IKJEFT01`, `DFSRRC00`, and procedure symbols such as `MBR=`, and flags sort control cards that filter, reformat, aggregate, or join.

## Scheduling

- The schedule is part of the program: job dependencies, data set triggers, resource conditions, calendars (business days, holidays, month-end), cyclic jobs, time windows, SLAs, and the critical path.
- Export definitions and run history from the scheduler (CA 7, Control-M, IBM Z Workload Scheduler, Zeke, ESP) and include them in the dependency graph.
- Scheduler variables often set JCL symbols and dates; treat them as configuration to migrate.

## Performance and capacity

- Measure elapsed time against the batch window, CPU time (and the MSU and rolling four-hour average that drive software cost), I/O counts, sort work, and contention with online processing.
- zIIP-eligible work (Java, some Db2 processing) is cheaper on z/OS; moving or restructuring work changes the cost profile, which is a nonfunctional requirement.

## Reports and output

- `SYSOUT` classes route output; carriage control (ASA or machine), forms control (FCB), and AFP resources (page and form definitions) shape printed and archived reports.
- Report layouts are contracts with auditors, regulators, and business users. When comparing reports, normalize volatile fields (run date and time, page numbers, job numbers) and compare everything else exactly.

## Mapping batch to modern platforms

| Mainframe | Typical target | Watch for |
| --- | --- | --- |
| Job and steps | Workflow in an orchestrator (Spring Batch, Apache Airflow, AWS Step Functions, Azure Data Factory, or a distributed scheduler) | Explicit return-code-to-status mapping and conditional steps |
| GDG | Versioned object storage paths or partitions | Retention, rollback, and rerun semantics |
| Temporary data sets | Workspace or scratch storage | Cleanup on failure |
| DFSORT and ICETOOL | SQL, sort utilities, or data-processing frameworks | EBCDIC collation, numeric formats (`ZD`, `PD`), stable ordering of equal keys |
| `IDCAMS REPRO` | Copy or load jobs | Record formats and key order |
| Checkpoint and restart | Framework checkpoints and idempotent steps | Exactly-once effects on outputs |
| Scheduler calendars | Orchestrator calendars | Holidays and month-end rules |
