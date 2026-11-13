# Target platforms, translation rules, and transition patterns

## Choose the target platform first

| Option | What changes | Track |
| --- | --- | --- |
| Modernize in place on z/OS | Compiler and runtime upgrades, restructuring, threadsafe CICS, SQL tuning, APIs through z/OS Connect, Java or Liberty services next to COBOL | Refactor for code-level work; Rearchitect for new boundaries and data ownership |
| Hybrid | Mainframe remains system of record; new capabilities run off-platform and integrate through APIs, MQ or event streaming, and change data capture | Rearchitect, one slice at a time |
| Rehost or replatform | Recompile and run COBOL, CICS-compatible, and batch workloads on a mainframe-compatible runtime with minimal code change | Outside both tracks; plan separately and use the Refactor playbook for the code changes it needs |
| Automated language conversion (COBOL to Java or C#) | Same behavior and topology in a new language | Refactor when behavior, contracts, and topology are preserved; Rearchitect when the conversion also redraws boundaries |
| Rebuild or replace | New system or package | Outside both tracks; the analysis and equivalence evidence still define what must be preserved |

## Translation rules (COBOL to Java, C#, or similar)

- **Decimal arithmetic:** use `BigDecimal` or `decimal` with an explicit scale for every field; truncate with `RoundingMode.DOWN` unless `ROUNDED` is coded, and round half away from zero (`HALF_UP`, `MidpointRounding.AwayFromZero`) when it is. Reproduce high-order truncation on stores, or prove with tests that it cannot occur. Never use `double` or `float` for packed or zoned data.
- **Binary fields:** respect PICTURE digits under `TRUNC(STD)` and full binary range for `COMP-5` or `TRUNC(BIN)`; convert byte order at boundaries.
- **Fixed-length text:** right-pad and truncate on assignment, compare with space padding, and document where trailing spaces are trimmed at boundaries.
- **Group items and `REDEFINES`:** back records with byte buffers and typed views, or with explicit variant types chosen by a discriminator. Line-by-line translation that keeps COBOL shapes in another language (sometimes called "JOBOL") is acceptable only as an intermediate step with a planned second refactoring pass.
- **Control flow:** convert `GO TO`, `PERFORM THRU`, `ALTER`, and `GO TO DEPENDING ON` through control-flow analysis, not by hand-editing jumps.
- **Subprogram state:** reproduce `WORKING-STORAGE` persistence across calls explicitly, or prove that callers do not depend on it.
- **Files:** sequential files become streams of fixed or variable records; KSDS becomes a keyed table or store with ordered access; `FILE STATUS` values map to typed results that callers check.
- **Return codes and abends:** map to process exit codes and exceptions that the orchestrator interprets exactly as the scheduler did.
- **Encoding and collation:** convert at the boundary using layouts, and keep EBCDIC ordering wherever order is contractual.
- **Dates:** reimplement shared date routines with explicit calendars and windowing rules, verified against the characterized originals.

## Subsystem mappings

| Mainframe | Typical target | Keep in mind |
| --- | --- | --- |
| CICS transaction | API operation or service endpoint | One transaction can span several pseudo-conversational steps |
| COMMAREA or container | Request and response schema | Derive from the copybook; decimals as strings or exact decimals |
| TS queue / TD queue | Cache or session store / queue or log | Recoverability and trigger semantics |
| `START` | Asynchronous message or job | Ordering and retries |
| `SYNCPOINT` unit of work | Transaction boundary, saga step, or outbox | Atomicity across resources |
| BMS or MFS screens | Web or mobile UI calling APIs | Screen-scraping consumers |
| `HANDLE ABEND` | Exception handling | Backout behavior |
| IMS TM transaction | Message-driven service | SPA state becomes explicit |
| Db2 for z/OS | Target relational database | Collation, timestamps, decimals, isolation, static SQL access paths |
| IMS DB, IDMS | Relational or document store, chosen by access pattern | Hierarchic or set ordering, position and currency |
| VSAM, QSAM, GDG | Tables, key-value stores, object storage | Key order, record formats, retention |
| JCL and schedule | Workflow orchestrator and calendars | Return-code logic, restart |
| DFSORT and Easytrieve | SQL, sort utilities, reporting tools | Collation, numeric formats, totals |
| MQ | MQ, Kafka, or cloud queues | Syncpoint participation, message layout, CCSID |
| RACF, ACF2, Top Secret | Enterprise identity and access management | Least privilege, service identities for batch |
| Printed reports | Report services, PDF, HTML | Regulatory layouts |

## Transition patterns for strangling mainframe workloads

- **Encapsulate first.** Expose existing programs through z/OS Connect (REST to CICS, IMS, and Db2), CICS web services, IMS Connect, or MQ. An API gateway in front becomes the strangler facade. Generate the contract from the copybook (`scripts/copybook_layout.py --format json-schema`) and review it.
- **Branch by abstraction in COBOL.** Insert a router program between callers and the implementation. It reads a toggle (a Db2 control table, a VSAM control record, or a container value) and routes to the legacy program or to the new implementation by key range, percentage, or operation. Default to the legacy path.
- **Data during transition.** Use log-based change data capture from Db2, IMS, or VSAM to keep the new store current; use a transactional outbox (a Db2 table plus MQ) to publish events from inside the CICS unit of work. Avoid dual writes from COBOL to remote databases. Plan reverse replication if the new side becomes the writer before cutover, and reconcile continuously.
- **Batch.** Carve job streams at data set boundaries, because input and output files are natural seams. Run the new step in parallel, reconcile outputs, then switch the schedule.
- **Screens.** Build new user interfaces on the APIs, retire 3270 screens transaction by transaction, and coordinate with screen-scraping consumers.
- **Shadow traffic.** Duplicate requests or messages to the new implementation, compare responses offline, and only then route real traffic.
- **Performance budget.** Count remote calls per business transaction and keep chatty interactions co-located.

## Anti-patterns

- Big-bang rewrites of whole estates or of several bounded contexts at once.
- Line-by-line translation without characterization and equivalence tests.
- Character-converting files that contain packed or binary data.
- Splitting a CICS unit of work into independent remote calls without a consistency design.
- Ignoring the schedule, calendars, run books, and restart procedures.
- Migrating dead code and unused data.
- Deleting data sets or tables before retention obligations expire.
- Dropping trailer records, control totals, or report layouts that auditors rely on.
