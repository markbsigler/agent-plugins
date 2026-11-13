# CPU and MSU cost reduction on z/OS

Cost reduction is a common Refactor driver. Every lever below is a behavior-preserving change that needs the usual equivalence evidence plus before-and-after measurements. Change one lever at a time.

## How software cost follows CPU

- MSUs (millions of service units per hour) measure processor consumption.
- Under sub-capacity monthly license charges, IBM products (and some ISV products) are billed on each LPAR's or capacity group's peak rolling four-hour average (R4HA) of MSUs in the month, reported by the Sub-Capacity Reporting Tool from SMF type 70 and 89 records. CPU saved outside the peak window does not lower that bill; shrink or move peak work instead.
- Consumption-based pricing (for example Tailored Fit Pricing for IBM Z, Enterprise Consumption) charges the total MSUs consumed, so every CPU second counts.
- Some ISV contracts follow machine capacity rather than use; ask how each product is licensed.
- Never estimate money. Report CPU seconds, MSU-hours, and the change in the monthly peak R4HA, and let the capacity or finance team apply contract rates.

## Compiler and module levers

| Lever | Effect | Risk to control |
| --- | --- | --- |
| `ARCH(n)` set for the oldest machine in production and disaster recovery, `TUNE` at or above it | Uses newer instructions | A module built for a newer `ARCH` fails with operation exceptions (S0C1) on older machines |
| `OPT(2)`, plus `STGOPT` where safe | Best code; `STGOPT` drops unreferenced data items | Eye-catchers and unreferenced storage that programs rely on |
| `TRUNC(OPT)` instead of `TRUNC(STD)` or `TRUNC(BIN)` | No truncation code for binary items; `TRUNC(BIN)` is usually slowest | Different results when binary values exceed their PICTURE; use `COMP-5` where the full binary range is intended |
| `NUMPROC(PFD)` | Faster numeric comparisons and moves | Assumes preferred signs; data with other valid signs behaves differently |
| `SSRANGE`, `NUMCHECK`, `INITCHECK`, `PARMCHECK` in production | Run-time checks cost CPU | Removing them hides defects; decide per program from measured cost and defect history |
| IBM Automatic Binary Optimizer (ABO) | Optimizes existing COBOL modules for current hardware without recompiling | Treat it as its own change with equivalence evidence; profile first to choose hot modules |

Option semantics are in "Compiler options that change behavior" in [cobol-language.md](cobol-language.md).

## Db2 levers

- **Access paths:** capture `EXPLAIN` output before changes, run `RUNSTATS` so statistics are current, and `REBIND` with `EXPLAIN(YES)`, with `APCOMPARE(WARN)` or `APCOMPARE(ERROR)` to detect changed paths, and with `APREUSE(WARN)` or `APREUSE(ERROR)` to keep proven ones. `EXPLAIN(ONLY)` previews without replacing the package. Keep package copies so `SWITCH(PREVIOUS)` can fall back. Compare with [../assets/explain-compare.sql](../assets/explain-compare.sql).
- **Multi-row operations:** `FETCH ... ROWSET` and multi-row `INSERT` cut per-row overhead in high-volume batch.
- **Commit frequency:** read the commit interval from a control table. Commits that are too frequent cost CPU and log; too rare, they hold and escalate locks and lengthen rollbacks. Keep restart logic intact.
- **Indexes:** unused indexes cost CPU on every insert and delete; real-time statistics (`LASTUSED` in `SYSIBM.SYSINDEXSPACESTATS`) show when each index was last used.

## Batch I/O levers

- **Sort:** replace COBOL steps that only copy, select, reformat, sum, or join with DFSORT or ICETOOL; use `FASTSRT` for COBOL `SORT` with `USING` and `GIVING`; write several outputs in one pass with `OUTFIL`; remove sorts of data already in order. Keep collation and the order of equal keys (`EQUALS` where COBOL used `WITH DUPLICATES IN ORDER`).
- **VSAM buffering:** default nonshared-resource buffering is minimal. Raise `BUFND` for sequential and `BUFNI` for random keyed access (`AMP` parameter), let system-managed buffering choose (`ACCBIAS`, SMS extended-format clusters only), or use Batch LSR for heavy random access.
- **Block sizes:** code `BLKSIZE=0` or omit it for new DASD data sets so the system chooses half-track blocking; small blocks multiply EXCPs.
- **Tape to object storage:** moving archives and DFSMShsm migration and backup data from tape to object storage (for example with DFSMS transparent cloud tiering) removes tape mounts and hardware; check recall times against batch windows and retention rules.

## Online and specialty-engine levers

- **Threadsafe CICS:** quasi-reentrant programs that call Db2 or MQ switch between the QR TCB and an open TCB on every call. Defining them `CONCURRENCY(THREADSAFE)` or `REQUIRED`, after serializing shared storage, removes the switches; CICS monitoring data (SMF type 110) shows the change-mode counts.
- **zIIP:** Java (batch, Liberty, z/OS Connect, CICS Liberty), part of the Db2 work that arrives through DRDA, and XML parsing by z/OS XML System Services or Db2 are zIIP-eligible, and zIIP time costs less under most pricing. Eligible work runs on general processors when the zIIPs are busy; SMF types 30 and 72 show how much.

## Removing work

- Retire unused programs, transactions, jobs, and reports first. Usage evidence comes from SMF type 30, CICS statistics, and Db2 `LASTUSED` (see [discovery-checklist.md](discovery-checklist.md)); the `mainframe-program-docs` skill's `cobol_flow.py` reports unreachable paragraphs. Archive before deleting.
- Consolidate overlapping ISV products (two sort products, schedulers, monitors, or file managers) after mapping which jobs and teams use each.

## Measuring

| Source | Shows |
| --- | --- |
| SMF type 30 | CPU, zIIP, and EXCP counts per job step |
| SMF types 70-79 (RMF) | LPAR and processor use (70), workloads and service classes (72), devices and coupling facilities (74) |
| SMF type 101 | Db2 accounting per plan and package: class 1 and class 2 CPU, getpages, locks |
| SMF type 110 | CICS CPU and response time per transaction, TCB switches |
| IBM Application Performance Analyzer or BMC AMI Strobe | Samples of a job or region that attribute CPU to modules, offsets, and SQL statements |

## Evidence in the Refactor gates

- **Stage 1:** rank candidates by CPU in the peak window, from SMF data and profiler samples.
- **Stage 2:** baseline on the same LPAR class and time window, over several runs; record the noise band, compiler options, and `BIND` options.
- **Stage 3:** one lever per change, compiler options separate from source changes, and every rebind with `EXPLAIN` and `APCOMPARE`.
- **Stage 4:** attach the equivalence evidence and a table of metric, baseline, candidate, delta, noise band, and source (SMF type or profiler). Express savings as CPU seconds, MSU-hours, and the effect on the monthly peak R4HA; leave conversion to money to the capacity or finance team.
