# Online systems: CICS and IMS TM

## CICS execution model

- A transaction (4-character `TRANSID`) starts an initial program as a task. Most applications are **pseudo-conversational**: each screen interaction is a new task, and state travels in the COMMAREA (up to about 32 KB), in channels and containers (no fixed limit), or in temporary storage queues. `EIBCALEN = 0` marks the first entry.
- Program control: `LINK` calls and returns, `XCTL` transfers without return, `RETURN TRANSID(...) COMMAREA(...)` ends the task and names the next one, `START` begins an asynchronous task, optionally after an interval or on another terminal. A `LINK` can be a distributed program link to another region over MRO, ISC, or IPIC.
- Region topology matters: terminal-owning, application-owning, and file-owning regions (TOR, AOR, FOR) route work and ship file requests between regions. The code does not show this; the CSD and SIT do.
- Threadsafe programs run on open TCBs and avoid task switches for Db2 and MQ calls; quasi-reentrant programs run on the single QR TCB. Shared storage (CWA, `GETMAIN SHARED`, `EXTERNAL` data) must be serialized before declaring a program threadsafe.

## CICS data access and recovery

- File control (`READ`, `WRITE`, `REWRITE`, `DELETE`, `STARTBR`, `READNEXT`, `READPREV`, `ENDBR`) works on VSAM data sets, locally or function-shipped. `READ UPDATE` holds a lock until syncpoint.
- Temporary storage queues (main or auxiliary, recoverable or not) and transient data queues (intrapartition with trigger levels that start transactions, extrapartition to data sets) carry state and work between tasks.
- A unit of work ends at `SYNCPOINT` or task end and commits every recoverable resource together: recoverable VSAM files, TS and TD queues, Db2, MQ, and IMS through DBCTL. An abend backs all of them out. Replacing this with independent remote calls breaks atomicity; design a saga, outbox, or compensation before splitting it.

## CICS conditions and abends

- Modern code checks `RESP` and `RESP2` on each command. Legacy code uses `HANDLE CONDITION`, `HANDLE AID`, `HANDLE ABEND`, and `IGNORE CONDITION`, which act like `GO TO` from inside commands; map each active handler before restructuring.
- Common abend codes: `ASRA` (program check, often an S0C7 data exception), `AICA` (runaway task), `AKCS` (deadlock timeout), `AEI0` (program not found), `AEI9` (map failure), `AEY9` (Db2 connection unavailable).

## Presentation: BMS and 3270

- BMS mapsets (`DFHMSD`, `DFHMDI`, `DFHMDF`) generate physical maps and symbolic-map copybooks with length (`L`), flag (`F`), attribute (`A`), input (`I`), and output (`O`) fields.
- Behavior lives in attribute bytes (protected, numeric, intensity, modified data tag), cursor placement, and the attention identifier (`EIBAID` compared with `DFHAID` constants for Enter, PF, PA, and Clear keys). `RECEIVE MAP` raises `MAPFAIL` when no data was entered.
- Screens are often consumed by other systems: terminal-emulator macros, RPA bots, HATS, and screen scrapers. Inventory them before changing any field position.

## CICS interfaces

- CICS web services (SOAP pipelines), JSON and REST through z/OS Connect or CICS JSON support, CICS Transaction Gateway (ECI calls with COMMAREAs from Java or .NET clients), Liberty in CICS, EXCI from batch, and the MQ bridge.
- Security: transaction attach security, resource security, and user IDs propagated from the terminal or the client. Preserve the authorization model when exposing programs as APIs.

## CICS modernization patterns

- **Refactor in place:** replace `HANDLE` with `RESP` checks, move from COMMAREA to channels and containers when size limits bite, make programs threadsafe to reduce TCB switching, and separate presentation from business logic (a BMS program that `LINK`s to a business-logic program with a defined COMMAREA). Each is a behavior-preserving change with its own characterization tests.
- **Seam for rearchitecture:** the business-logic program with a defined COMMAREA or container copybook is the natural seam. Its copybook becomes the source of the API contract (the `copybook-data` skill's `copybook_layout.py --format json-schema`).
- **Strangler routing:** expose the business-logic program through an API layer (z/OS Connect or CICS Liberty), put a gateway in front, and route per operation; or add a router program that `LINK`s to either the legacy or the new implementation behind a toggle.
- **Latency budget:** a local `LINK` costs microseconds; a network call costs milliseconds. Count `LINK`s and file requests per business transaction before moving a slice off the platform, and keep chatty interactions co-located.

## IMS Transaction Manager

- Message processing regions (MPP), batch message processing (BMP), and Fast Path (IFP) regions run programs that loop: `GU` the I/O PCB for the next message, process it, `ISRT` the reply, and repeat until the queue is empty (status `QC`).
- Conversational transactions keep state in a scratch pad area (SPA). Alternate PCBs send to other terminals or transactions; program-to-program switches chain transactions.
- MFS formats (`DIF`, `DOF`, `MID`, `MOD`) define screens and message layouts.
- IMS Connect and OTMA give TCP/IP and Java clients access; the IMS-MQ bridge and z/OS Connect expose transactions as messages or APIs.
- Checkpoints (`CHKP`) and syncpoints commit work in BMPs; `XRST` supports restart.
- Modernization follows the CICS patterns: the message layout copybook is the contract, the SPA becomes explicit state, MFS screens become new user interfaces calling APIs, and transactions are routed one at a time.
