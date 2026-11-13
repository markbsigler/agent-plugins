# Other mainframe languages and generated code

## PL/I

- Types: `FIXED DECIMAL(p,q)` is packed decimal; `FIXED BINARY(15)`, `(31)`, and `(63)` are halfword, fullword, and doubleword binary; `FLOAT DECIMAL` and `FLOAT BINARY` are hexadecimal floating point by default; `PICTURE` items are zoned or edited; `CHARACTER VARYING` carries a 2-byte length prefix; `BIT` strings pack flags.
- Storage: `BASED` variables and pointers, `AREA` and `OFFSET`, and `DEFINED` overlays act like `REDEFINES`. Structure alignment (`ALIGNED`, `UNALIGNED`) inserts padding that differs from COBOL layouts, so a copybook and a PL/I include describing the same record can disagree.
- Conditions: `ON` units (`ERROR`, `ENDFILE`, `CONVERSION`, `ZERODIVIDE`, `FIXEDOVERFLOW`, `SIZE`) handle errors, and condition prefixes enable or disable checks per statement. Control can resume after a handler, which has no direct equivalent in most languages.
- The preprocessor (`%INCLUDE`, `%IF`, `%DCL`) generates code; analyze the expanded source from the compiler listing.
- PL/I and COBOL call each other under Language Environment; check parameter conventions at every inter-language call.

## High Level Assembler (HLASM)

- Look for `CSECT` and `DSECT` definitions (a `DSECT` is a record layout, like a copybook), linkage conventions (register 13 save area, register 14 return address, register 15 entry point and return code, register 1 parameter list with the high-order bit marking the last parameter), and `AMODE` and `RMODE`.
- System macros reveal purpose: storage (`GETMAIN`, `FREEMAIN`, `STORAGE`), I/O (`OPEN`, `CLOSE`, `GET`, `PUT`, `READ`, `WRITE`), time (`TIME`, `STCK`), program management (`LINK`, `LOAD`, `XCTL`, `CALL`), serialization (`ENQ`, `DEQ`), recovery (`ESTAE`, `ESPIE`), messages (`WTO`, `WTOR`), and dynamic allocation (`SVC 99`).
- Assembler typically implements shared date routines, encryption, compression, high-volume I/O, and exits (JES, SMF, security, CICS task-related user exits, IMS exits, sort exits). Decimal instructions (`AP`, `SP`, `MP`, `DP`, `ZAP`, `PACK`, `UNPK`, `CVB`, `CVD`, `ED`, `EDMK`) define exact arithmetic and editing.
- Approach: classify each module by purpose; replace it with a platform service or reimplement it from characterized behavior. Do not machine-translate Assembler without equivalence proof. Watch for self-modifying code, `EX` instructions, and installation-specific macros.

## REXX and CLIST

- TSO and ISPF automation: `ADDRESS TSO`, `ADDRESS ISPEXEC`, `ADDRESS MVS`, `EXECIO` for I/O, `OUTTRAP` for command output, ISPF panels and tables.
- ISPF file tailoring can generate JCL from skeletons, so the JCL that runs exists in no library. Find the skeletons and the variables that fill them.
- These scripts often run operations, builds, and data fixes; include them in the inventory even when no business program calls them.

## Easytrieve

- Files are defined by start position, length, and type (`A` alphanumeric, `N` zoned, `P` packed, `B` binary, `U` unsigned packed). Reconcile those definitions with the copybooks for the same files.
- `JOB` activities process records, synchronized file processing performs match-merge logic, and `REPORT` sections produce control-break reports with totals. Replacements must reproduce totals, ordering, and page breaks.

## Natural and ADABAS

- Natural programs, subprograms, maps, and data definition modules (DDMs, which are views of ADABAS files); ADABAS periodic groups and multiple-value fields become child tables in relational targets. Natural Construct generates code from models.

## Generated code and 4GLs

- CA Gen, Telon, APS, CSP or VisualAge Generator (and its successor EGL), ADS/O for IDMS, Ideal for Datacom, FOCUS, Mark IV or VISION:Builder, and SAS on z/OS.
- Decide whether the model or the generated code is the source of truth. Do not hand-modify generated code while the generator is still in use; modernize the model, or retire the generator first and then treat the generated code as source.

## Java, C, and z/OS UNIX

- Java batch and Liberty on z/OS (zIIP-eligible), C and C++ under Language Environment, and shell scripts in z/OS UNIX System Services.
- z/OS UNIX files are usually EBCDIC (CCSID 1047) and may be tagged for automatic conversion; check tags before moving or comparing files.
