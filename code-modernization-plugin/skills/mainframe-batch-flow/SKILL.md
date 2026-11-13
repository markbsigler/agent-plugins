---
name: mainframe-batch-flow
description: Traces z/OS batch flow from exported JCL. Expands each job the way the JCL converter does (SET, PROC defaults, EXEC and DD overrides, nested and in-stream procedures, INCLUDE members, system symbols), explains COND and IF/THEN/ELSE logic, reads IDCAMS, DFSORT, ICETOOL, IEBGENER, IEBCOPY, IKJEFT01, DFSRRC00, FTP, and Connect:Direct control statements, and builds data set lineage across jobs - producers, consumers, external inputs, final outputs, GDG generations, and job dependencies implied by data. Compares those dependencies with Control-M, IBM Z Workload Scheduler, or CSV schedule exports and reports missing scheduler dependencies. Use when asked "what does this job do", "which jobs create or read this data set", "what feeds this file", "draw the job flow", or "check scheduler dependencies". The bundled script only reads files.
license: MIT
compatibility: Python 3.11+, standard library only; run with uv or python3. Works on JCL, procedures, and control cards exported from Endevor, ChangeMan ZMF, Code Pipeline (ISPW), or Git.
metadata:
  author: markbsigler
  version: "1.0"
---

# Mainframe Batch Flow

Answers batch questions from the JCL itself: what each step really runs, which data sets it reads, writes, and deletes, how jobs depend on each other through data, and whether the scheduler enforces those dependencies. Two sibling skills complete the picture: the `mainframe-analysis` stack profile, whose `references/batch-jcl.md` holds the z/OS batch rules (return codes, restart, utilities, scheduling) to apply to these findings, and `copybook-data`, which computes the record layouts of the data sets this skill traces.

## Operating rules

1. **The expanded JCL is the evidence.** Report what the converter would run after symbols, procedures, overrides, and INCLUDE members are applied, not what the job member appears to say.
2. **Static is not runtime.** Confirm critical findings against JES job logs, SMF type 14, 15, and 30 records, or the scheduler's run history before you rely on them.
3. **Gaps are findings.** Treat `unresolved` procedures, INCLUDE members, and symbols, and control statements that were not found, as requests for the missing libraries or values.
4. **Read-only.** Never submit jobs or connect to an LPAR or scheduler; analyze exported members only.

## Workflow

### Step 1: Gather the inputs

Ask for these in one round and export them to local directories:

- **Jobs:** the JCL library the scheduler submits from.
- **Procedures:** every library in the PROCLIB concatenation, in order, and any library named on `JCLLIB ORDER`.
- **INCLUDE members and control cards:** the libraries that hold INCLUDE groups and SYSIN members such as sort cards and IDCAMS commands.
- **Schedules:** Control-M XML exports, IBM Z Workload Scheduler batch-loader statements, or a CSV with `predecessor` and `successor` columns (and optionally `condition`) for CA 7 or other schedulers.
- **Symbol values:** system symbols such as `&SYSUID` and `&SYSPLEX`, and the scheduler variables that jobs use.

Members are recognized by content, so PDS names without extensions work: a JOB statement makes a job, PROC as the first statement makes a cataloged procedure, other JCL is an INCLUDE member, and text without JCL statements is a control-card member. Directories are searched for files ending in `.jcl`, `.job`, `.prc`, `.proc`, `.cntl`, or `.txt`, or with no extension; a file named on the command line is always read. Members still in EBCDIC (80-byte records, RDW-prefixed, or new-line delimited) are decoded with `--codepage`.

### Step 2: Run the script

Run from this skill's directory or with the full path:

```bash
uv run --script scripts/batch_flow.py jcl/ cntl/ --proclib proclib/ --format markdown
uv run --script scripts/batch_flow.py jcl/ cntl/ --proclib site.proclib/ --proclib sys1.proclib/ \
    --schedule ctm-export.xml --set SYSUID=BATCHID > flow.json
uv run --script scripts/batch_flow.py jcl/ --proclib proclib/ --format mermaid --job PAYD010
```

| Option | Meaning |
| --- | --- |
| `ROOT ...` | Directories (walked recursively, hidden ones skipped) or files with jobs, INCLUDE members, procedures, and control cards |
| `--proclib DIR` | A procedure library; repeat in concatenation order. Searched before the roots |
| `--schedule FILE` | A Control-M XML, batch-loader, or CSV export; the format is detected from the content |
| `--set NAME=VALUE` | A system symbol value; it takes precedence over SET, PROC, and EXEC values |
| `--job NAME` | Limit the output to these jobs and their data sets |
| `--format` | `json` (default), `markdown`, or `mermaid` |
| `--codepage` | EBCDIC code page of members not yet converted (default 037) |
| `--max-bytes N` | Skip larger members with a warning |

The script exits with status 1 and an `error:` message for a missing path, a bad `--set` value, an unknown `--job`, an unsupported code page, or a schedule export it cannot read.

### Step 3: Read the output

The JSON output starts with `tool`, `roots`, and `proclibs`, followed by these keys:

| Key | Contents |
| --- | --- |
| `jobs` | Per job: `member`, `path`, `encoding`, `class`, `msgclass`, `parameters` (JOB keywords except PASSWORD), `cond`, `jcllib`, `symbols` (each symbol used and the values it resolved to), `unresolved_symbols`, `procs`, `includes`, job-level `dds` such as JOBLIB, `steps`, and `temporary_datasets` (`&&` names with the steps that write, read, and delete them) |
| `jobs.*.steps` | Per step: `name` (`JOBSTEP.PROCSTEP` for expanded procedures), `procstep`, `proc`, `program`, `runs` (programs behind IKJEFT01, DFSRRC00, or BPXBATCH), `utility`, `parm`, `cond` (`raw` and `explanation`), `if_context`, `flags`, `control` (what the utility's control statements do), and `dds` |
| `jobs.*.steps.*.dds` | `ddname` and `concat` (concatenation index), plus what is coded or derived: `override` (`overridden` or `added`), `dsn`, `dataset`, `generation`, `member`, `temporary`, `backref`, `disp` (`raw`, `status`, `normal`, `abnormal`), `dcb`, `space`, `unit`, `like`, `refdd`, the SMS classes, `sysout`, `dest`, `output`, `dummy`, `path`, `pathopts`, `instream_lines`, `instream`, `control_member` (the scanned member that supplied control statements), and `library` for STEPLIB and similar DDs |
| `datasets` | Per data set or z/OS UNIX file (GDGs under their base name, PDS members under the library): `producers`, `consumers`, `deleted_by`, `generations`, `members`, and every access with job, step, DD, action, and DISP. Temporary `&&` data sets stay in their job, and program libraries such as STEPLIB and JOBLIB are left out |
| `transfers` | FTP and Connect:Direct transfers: direction, host or node, local and remote names, and the local data set |
| `reports` | SYSOUT DDs with class, writer, destination, and `kind` (`report`, or `messages` for SYSPRINT, dumps, and similar) |
| `schedule` | `null` without `--schedule`; otherwise `sources`, `jobs`, IWS `operations` and `run_cycles`, `edges`, `unmatched_conditions`, `jobs_without_jcl`, and `unscheduled_jobs` |
| `edges` | Graph edges: `writes` (job to data set), `reads` (data set to job), `deletes`, and `schedule` (job to job) |
| `external_inputs` | Data sets that are read but never written by the scanned jobs: interfaces to confirm with their owners |
| `final_outputs` | Data sets written but never read (work data sets deleted by the same step are excluded): deliverables, archives, or dead output |
| `job_dependencies` | `data` entries (a job writes a data set that another job reads, with `scheduled` true, false, or null when a job is not in the schedule) and `schedule` entries |
| `unresolved` | `procs`, `includes`, and `symbols` that could not be resolved |
| `warnings` | Parse problems, unresolved references, unused overrides, and missing scheduler dependencies |

How to apply it:

- Read `cond.explanation` before translating a step's logic: `COND=(4,LT)` bypasses the step when 4 is less than an earlier return code, which inverts the reading of `IF (RC > 4)`.
- Flags such as `business logic in sort control cards` mark steps whose control statements filter, reformat, aggregate, or join records; specify them as requirements, not plumbing.
- A `missing scheduler dependency` warning means the data says job A must finish before job B starts but the schedule does not enforce it; the jobs may run in the wrong order or rely on timing.
- Feed `external_inputs`, `final_outputs`, and `transfers` into the estate brief as external contracts, and give each data set's copybook to `copybook-data` for its layout.

### Step 4: Confirm with the platform team

Review unresolved items, warnings, and the dependency findings with the people who run the batch. Confirm the PROCLIB concatenation, symbol values, restart procedures, and which external inputs and final outputs cross system boundaries.

## Limitations

- The analysis is static. Programs' own I/O is inferred from DISP and from utility control statements; `DISP=OLD` is recorded as a read that may update, and dynamic allocation inside programs is not seen.
- System symbols (`&SYSUID`, `&SYSPLEX`) and scheduler variables (Control-M `%%ODATE`, IWS `&O`-variables) are unknown unless passed with `--set`; unresolved symbols stay as written.
- The PROCLIB concatenation order comes from the `--proclib` order. `JCLLIB ORDER` is recorded but not mapped to directories.
- Data-implied dependencies ignore run order: when two jobs each write a data set that the other reads (for example, generations of the same GDG), both directions are reported.
- Control statements in members that are not among the scanned files are reported as not found. In-stream data of FTP and Connect:Direct steps is not echoed because it often holds credentials.
