# Security: RACF, ACF2, and Top Secret

Programs on z/OS rarely check authority themselves. CICS, Db2, MQ, JES, and the access methods ask the security manager through SAF, so the authorization model lives in security definitions. Inventory it before adding callers, moving workloads, or exposing APIs, map it explicitly, and never replace it with one all-powerful service ID.

RACF terms are used below. ACF2 (logonids, access rules, resource rules) and Top Secret (accessor IDs, profiles, facilities, owned and permitted resources) make the same SAF decisions; ask for the equivalent reports.

## RACF building blocks

- **User IDs and groups:** each task or job runs under one user ID; the groups it is connected to grant access and can become Db2 secondary authorization IDs.
- **Data set profiles:** discrete or generic profiles (for example `PROD.PAYROLL.**`) with a universal access and an access list (`READ`, `UPDATE`, `CONTROL`, `ALTER`). Conditional access (`WHEN(PROGRAM(...))`) grants access only through a named program.
- **General resource classes:**

| Class | Controls |
| --- | --- |
| `TCICSTRN` (group class `GCICSTRN`) | CICS transaction attach (`XTRAN=YES`) |
| `FCICSFCT`, `MCICSPPT`, `ACICSPCT`, `RCICSRES` | CICS files, programs, started transactions, and other resources (`XFCT`, `XPPT`, `XPCT`, `XRES`) |
| `FACILITY` | System functions, for example `STGADMIN.*` storage administration and `BPX.*` z/OS UNIX privileges |
| `SURROGAT` | Submitting work as another user (`userid.SUBMIT`) |
| `PROGRAM` | Program control, including program access to data sets |
| `DSNR` | Connecting to a Db2 subsystem from each environment (batch, CICS, IMS, DDF) |
| `MQCONN`, `MQQUEUE`, `MQADMIN`, `MQCMDS` | MQ connections, queues, security switches, and commands |
| `PTKTDATA` | PassTicket keys per application |
| `IDIDMAP` | Distributed identity filters created with `RACMAP` |

## CICS and Db2

- CICS: `SEC=YES` activates external security; the `X...` system initialization parameters (`XTRAN`, `XFCT`, `XPPT`, `XRES`, `XCMD`) choose which checks run, and `RESSEC(YES)` on a transaction enables resource checks for it. The user ID comes from sign-on, the client (CICS TG, IPIC, web), or the region default; trigger-started and `START`ed tasks can run under other IDs.
- Db2 static SQL runs with the package `OWNER`'s privileges, so users need only `EXECUTE` on the package or plan; `QUALIFIER` resolves unqualified table names. Moving SQL to dynamic SQL or to a new client changes whose privileges apply (see `DYNAMICRULES`).
- Secondary authorization IDs (RACF groups passed by the connection and sign-on exits) widen what each user can do, so grants to groups matter.
- Roles and trusted contexts tie privileges to connections that match attributes such as address, job name, or system authorization ID; DRDA service IDs should use them.
- Some shops route Db2 authorization to RACF through the access control exit; then `GRANT`s are not the whole picture.
- Package owners and qualifiers come from [../assets/db2-catalog.sql](../assets/db2-catalog.sql); ask the DBAs for `SYSTABAUTH`, `SYSPACKAUTH`, and `SYSPLANAUTH` extracts.

## Batch and service identities

- A job runs under `USER=` on the `JOB` statement, the submitter's ID propagated by JES, or the ID the scheduler assigns. Submitting as another user without a password needs `SURROGAT` authority.
- Schedulers (CA 7, Control-M, IBM Z Workload Scheduler) submit under their own ID or a per-job owner; take that mapping from the scheduler definitions.
- Treat batch IDs as service identities: list what each reads and updates, and give every target workload its own identity with the same least-privilege scope.
- PassTickets replace passwords for server-to-server sign-on. They are one-time, specific to an application, and valid only briefly: 10 minutes for legacy PassTickets, a configurable period for enhanced PassTickets, whose HMAC keys live in ICSF. Inventory every `PTKTDATA` profile and who generates tickets for it.

## Encryption

- **Data sets:** z/OS data set encryption (part of pervasive encryption) encrypts extended-format data sets with a key label from the RACF `DFP` segment (`DATAKEY`), the SMS data class, or JCL `DSKEYLBL`. Access needs both the data set permission and the key label (`CSFKEYS`). Programs do not change, but data read through the access method is cleartext to the reader, so copies and transfers need their own protection.
- **Keys:** ICSF manages keys in its key data sets (for example the `CKDS`) under hardware master keys; the `CSFKEYS` and `CSFSERV` classes control who can use keys and services.
- **Network:** AT-TLS adds TLS to TCP connections from Policy Agent rules without code changes; MQ channels and Db2 DRDA can also use their own TLS settings. Certificates sit in RACF key rings.
- Record which data sets, columns, and links are encrypted and why; any off-platform target needs an equivalent key-management decision.

## Exposing programs as APIs

- Propagate the end user's identity. z/OS Connect, CICS IPIC, and CICS TG can assert a distributed identity that RACF maps to a user ID through `RACMAP` filters (`IDIDMAP` class), so transaction, resource, and Db2 checks still apply to the real user.
- Map API scopes to existing transaction and resource profiles instead of granting a gateway ID access to everything, and document every surrogate or PassTicket the integration uses.

## Audit

- RACF writes SMF type 80 records for violations and audited access; ACF2 and Top Secret keep their own logs and record formats. Collect the audit settings (`SETROPTS` options, profile `AUDIT` levels) and the reports auditors already receive.
- Regulated workloads must keep an equivalent audit trail on every new platform.

## What to inventory and who to ask

| Evidence | Ask |
| --- | --- |
| Profiles and access lists for the application's data sets, transactions, programs, queues, and Db2 subsystems (`LISTDSD`, `RLIST`, `SEARCH`, or ACF2 and Top Secret reports) | Security administrators |
| Batch, started task, CICS default, and DRDA user IDs with their groups; scheduler job owners | Security and scheduling teams |
| Surrogate, PassTicket, and `RACMAP` definitions | Security administrators |
| Db2 grants, package owners and qualifiers, roles, trusted contexts | DBAs |
| Encryption policy, key labels, ICSF setup, AT-TLS rules | Security, cryptography, and network teams |
| SMF type 80 retention and audit reports | Security and audit teams |
