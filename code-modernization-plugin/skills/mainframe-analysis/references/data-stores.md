# Data stores: Db2 for z/OS, IMS DB, VSAM, sequential data sets, IDMS

## Db2 for z/OS

### Programs and binding

- Embedded SQL is processed by the Db2 coprocessor or precompiler into a DBRM, bound into a package (in a collection) and reached through a plan. A program rebuilt without a matching bind fails with SQLCODE -805 (package not found) or -818 (consistency token mismatch). Build, bind, and promote together.
- `BIND` options change behavior: `ISOLATION` (`CS`, `RR`, `RS`, `UR`), `CURRENTDATA`, `RELEASE`, `VALIDATE`, `DEGREE`, `QUALIFIER`, `OWNER`, `DYNAMICRULES`, and `APPLCOMPAT`. Capture them per package.
- Static SQL access paths are fixed at bind time. Record `EXPLAIN` output before changes and use access-path stability controls (for example `APREUSE` and plan management) when rebinding.

### Host variables and types

- `DECIMAL(p,s)` maps to `COMP-3`; `INTEGER` and `SMALLINT` map to binary; `CHAR` and `VARCHAR` (a 49-level length and text pair) hold EBCDIC text; `DATE`, `TIME`, and `TIMESTAMP` usually arrive as character strings in Db2 format.
- Nullable columns need indicator variables (`-1` means null). Missing indicators cause SQLCODE -305 when a null arrives.
- `FOR BIT DATA` columns hold binary bytes in character columns; never convert them as text. `GRAPHIC` and `VARGRAPHIC` hold DBCS data.
- Column lengths are in bytes for EBCDIC data; expansion to UTF-8 can overflow targets sized in bytes.

### SQLCODEs that drive logic

| SQLCODE | Meaning |
| --- | --- |
| 0, +100 | Success; row not found or end of cursor |
| -803 | Duplicate key on insert or update |
| -811 | Singleton `SELECT` returned more than one row |
| -305 | Null value without an indicator variable |
| -302, -180, -181 | Value too large; invalid date or time string or value |
| -530, -532 | Foreign-key violations on insert or update; delete restricted |
| -911, -913 | Deadlock or timeout, with and without rollback |
| -904 | Resource unavailable |
| -805, -818 | Package not found; consistency token mismatch |
| -922 | Authorization failure |
| -501, -502 | Cursor not open; cursor already open |

Programs branch on these codes; preserve each branch or map it to an equivalent typed result.

### Concurrency and batch

- Lock size, lock escalation, and the difference between -911 (rolled back) and -913 (not rolled back) shape retry logic.
- Batch programs commit every N rows and save a restart key in a checkpoint table; cursors declared `WITH HOLD` survive commits. Restart logic depends on both.
- `ISOLATION(UR)` and `WITH UR` read uncommitted data, often deliberately in reporting.
- Db2 utilities in batch (`LOAD`, `UNLOAD`, `REORG`, `RUNSTATS`, `COPY`, `RECOVER`) are business process steps, not just housekeeping (for example a nightly `LOAD REPLACE`).

### Moving data or SQL off Db2 for z/OS

- EBCDIC collation changes `ORDER BY` and range predicates on `CHAR` columns.
- Fixed-length `CHAR` comparisons ignore trailing blanks; check the target's padding semantics.
- Timestamp formats and precision, `DECIMAL` precision up to 31 digits, special registers (`CURRENT DATE`, `CURRENT TIMESTAMP`, `CURRENT SQLID`), `WITH UR`, `FOR FETCH ONLY`, `OPTIMIZE FOR n ROWS`, `SELECT FROM FINAL TABLE`, `ROWID`, identity columns, sequences, temporal tables, LOBs, XML, triggers, stored procedures (COBOL external procedures and native SQL procedures), and UDFs all need explicit mapping.
- `UNLOAD` and `DSNTIAUL` produce EBCDIC files with packed fields and null indicator bytes; convert them with the layout, not as text.
- Prefer log-based change data capture over application dual writes during transition.

## IMS DB (hierarchical)

- A DBD defines segments, fields, key (sequence) fields, and the access method (HDAM, HIDAM, HISAM, SHISAM, DEDB, MSDB, GSAM, or HALDB partitions). A PSB's PCBs define each program's view (`SENSEG`, field sensitivity, `PROCOPT`).
- DL/I calls: `GU`, `GN`, `GNP`, `GHU`, `GHN`, `GHNP`, `ISRT`, `REPL`, `DLET`, with segment search arguments (SSAs) and command codes (for example `*D` path calls).
- Status codes drive logic: blank (success), `GE` (not found), `GB` (end of database), `GA` and `GK` (crossed a hierarchy level or segment type during `GN`), `II` (duplicate on insert), plus error statuses such as `AI`, `AK`, and `DJ`.
- Implicit state: database position after each call determines what `GN` returns next. Hierarchic sequence (parent before children, segment types left to right, twins ordered by sequence field or by insert rule) is part of the behavior.
- Watch for logical relationships, secondary indexes, segment edit and compression exits (data may be stored compressed or encrypted by an exit), and checkpoint and restart in BMPs.
- Relational mapping: one table per segment type with the concatenated key as the composite key, an ordering column for non-unique or unkeyed twins, `GN` loops rewritten as ordered keyset queries, and position-dependent logic made explicit.

## VSAM and sequential data sets

- **KSDS:** unique primary key in EBCDIC order; alternate indexes (`AIX`) with unique or non-unique keys reached through a `PATH`; generic-key browses; CI and CA splits; `SHAREOPTIONS` and record-level sharing (RLS) control concurrent access between CICS and batch.
- **ESDS:** append-only, addressed by relative byte address (RBA). **RRDS:** fixed slots by number. **LDS:** byte-stream data used by Db2 and data-in-virtual.
- Batch often closes files in CICS before updating them and reopens them afterwards (steps that issue `CEMT SET FILE CLOSED` or equivalent). That coordination is part of the design.
- **Sequential (QSAM):** fixed or variable records with no line terminators (see [data-and-encoding.md](data-and-encoding.md)). PDS and PDSE members can hold data as well as code.
- **GDGs:** relative references (`(+1)` new, `(0)` current, `(-1)` previous) resolve when the job starts; the base's `LIMIT`, `SCRATCH`, and `EMPTY` settings decide what is kept. Restarts and reruns interact with relative numbering.
- Tape data sets, DFSMShsm migration (recall delays), SMS classes, catalogs, and retention (`RETPD`, `EXPDT`) affect run time and decommissioning.
- Target mappings: KSDS to a keyed table or key-value store with ordered range queries (EBCDIC order where it is contractual); ESDS to an append-only table with a sequence column; RRDS to a table keyed by slot; GDG to versioned object storage or partitions with a retention policy.

## IDMS (network database)

- Records, sets (owner and members, ordered `FIRST`, `LAST`, `NEXT`, `PRIOR`, or `SORTED`; membership mandatory or optional, automatic or manual), areas, `CALC` (hashed) placement, and `VIA` placement near the owner.
- Navigational DML (`OBTAIN CALC`, `OBTAIN NEXT WITHIN set`, `FIND`, `CONNECT`, `DISCONNECT`, `STORE`, `MODIFY`, `ERASE`) depends on currencies (run unit, record type, set, area) that each call changes. `ERROR-STATUS` values such as `0000` (success), `0307` (end of set or area), and `0326` (record not found) drive logic.
- ADS/O dialogs and IDMS-DC or UCF provide online processing.
- Relational mapping: sets become foreign keys with ordering columns, currency becomes explicit cursor state, `ERASE ALL` becomes cascading deletes, and area sweeps become scans.

## Other databases

- **Datacom/DB:** tables and keys accessed through its own call interface or SQL.
- **ADABAS:** files, descriptors, periodic groups, and multiple-value fields (which map to child tables), usually accessed from Natural.
