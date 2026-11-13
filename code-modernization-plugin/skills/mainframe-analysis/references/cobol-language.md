# COBOL language semantics that modernization must preserve

IBM Enterprise COBOL for z/OS behavior. Confirm details for a specific program against its compiler listing and the IBM Language Reference and Programming Guide for the compiler release in use.

## Contents

- [Source format and safe editing](#source-format-and-safe-editing)
- [Program structure and calls](#program-structure-and-calls)
- [Data definitions](#data-definitions)
- [Arithmetic](#arithmetic)
- [Alphanumeric data and comparisons](#alphanumeric-data-and-comparisons)
- [Control flow](#control-flow)
- [File handling](#file-handling)
- [Compiler options that change behavior](#compiler-options-that-change-behavior)
- [Upgrading Enterprise COBOL](#upgrading-enterprise-cobol)
- [Where business rules hide](#where-business-rules-hide)

## Source format and safe editing

Fixed format (the norm on z/OS):

| Columns | Area | Notes |
| --- | --- | --- |
| 1-6 | Sequence number | Ignored by the compiler; keep existing values |
| 7 | Indicator | `*` or `/` comment, `-` continuation, `D` debugging line |
| 8-11 | Area A | Division, section, and paragraph names; `01`, `77`, `FD`, `SD` |
| 12-72 | Area B | Statements and subordinate entries |
| 73-80 | Identification | Ignored; often holds change tags |

Rules for any edit:

- Never write past column 72, never insert tab characters, and preserve sequence numbers and change tags.
- Use only characters that exist in the target EBCDIC code page. Smart quotes, em dashes, and other non-ASCII characters break compiles or change meaning.
- A continued literal runs to column 72 on the first line and resumes after the quote on the continuation line; a continued word resumes at the first nonblank character.
- Keep the shop's case and naming conventions. Do not convert to free format (`>>SOURCE FORMAT FREE`) as part of another change.

## Program structure and calls

- `WORKING-STORAGE` persists between calls to a subprogram for the life of the run unit unless the program is `IS INITIAL` or the caller issues `CANCEL`. Subprograms that count, cache, or remember state across calls rely on this; a stateless translation changes behavior. `LOCAL-STORAGE` is fresh on every call.
- `CALL 'literal'` is static or dynamic depending on the `DYNAM` option; `CALL identifier` is always dynamic and resolves at run time, so static analysis cannot see the target.
- Parameters pass `BY REFERENCE` by default: the callee can change the caller's storage. `BY CONTENT` passes a copy; `BY VALUE` passes the value.
- `GOBACK` returns to the caller; `STOP RUN` ends the whole run unit even from a subprogram; `EXIT PROGRAM` returns only from a called program.
- The `RETURN-CODE` special register becomes the step condition code that JCL `COND` and `IF` logic and the scheduler act on. Preserve every value a program can set.
- `ENTRY` statements create alternate entry points into the same program.
- `PARM` data from JCL arrives in the `LINKAGE SECTION` as a halfword length followed by the text.

## Data definitions

- A group item is alphanumeric, whatever its children are. A group `MOVE` or comparison is a byte copy or byte comparison, including any packed or binary fields inside it.
- `REDEFINES` overlays the same bytes with different types; multi-record files often use a record-type code to choose the view. Typed languages need an explicit byte buffer or a discriminated variant.
- `OCCURS DEPENDING ON` makes the group variable length; items after the table move when the count changes.
- `INDEXED BY` indexes hold byte displacements, not occurrence numbers. `SEARCH ALL` performs a binary search and is only correct when the table is ordered by its `KEY` in EBCDIC collating sequence.
- `88` levels name values; `SET condition TO TRUE` moves the first value listed.
- `66 RENAMES` regroups contiguous storage.
- `JUSTIFIED RIGHT`, `BLANK WHEN ZERO`, and `SIGN LEADING` or `TRAILING`, `SEPARATE` change the stored bytes.
- `SYNCHRONIZED` inserts slack bytes to align binary items, which shifts offsets. Compute layouts with the `copybook-data` skill's `copybook_layout.py`, which inserts the slack bytes, and confirm with the compiler `MAP` listing.
- `INITIALIZE` sets alphanumeric fields to spaces and numeric fields to zero, skips `FILLER` unless `WITH FILLER` is coded, skips pointers and indexes, and skips subordinate items that redefine storage (and their children), so only the first definition of an overlay is initialized. Items without `VALUE` clauses have no defined initial contents; programs sometimes depend on whatever the runtime leaves there.

## Arithmetic

COBOL arithmetic is fixed-point decimal. Every translation must reproduce it exactly.

- **Truncation is the default.** Results are truncated toward zero to the receiving field's scale unless `ROUNDED` is coded. Default `ROUNDED` rounds half away from zero, which matches Java `RoundingMode.HALF_UP` and .NET `MidpointRounding.AwayFromZero`; truncation matches `RoundingMode.DOWN`.
- **High-order digits are lost silently.** Moving or computing `1234` into `PIC 999` stores `234` unless `ON SIZE ERROR` is coded. Translated code that raises an overflow error or keeps the full value changes behavior.
- **Intermediate precision follows compiler rules** that depend on operand sizes and the `ARITH` option (maximum 18 digits with `ARITH(COMPAT)`, 31 with `ARITH(EXTEND)`). Division, exponentiation, and mixed scales are where translated code most often differs by a cent. Build golden-master tests for every `COMPUTE` and `DIVIDE` in scope.
- **Binary truncation depends on `TRUNC`.** `TRUNC(STD)` truncates binary results to the PICTURE digits, `TRUNC(BIN)` keeps the full binary value, and `TRUNC(OPT)` lets the compiler assume values fit, so results for out-of-range data are unpredictable. `COMP-5` always uses the full binary range.
- **Signs.** Moving a negative value to an unsigned field stores its absolute value. Packed decimal can hold negative zero. `NUMPROC(PFD)` assumes preferred sign nibbles (`C`, `D`, `F`), so data with other valid signs can compare differently than under `NUMPROC(NOPFD)`.
- **Invalid data abends.** Arithmetic on a packed or zoned field holding spaces or bad digits raises a data exception (S0C7, or ASRA in CICS). Some jobs depend on that abend to stop processing bad input; translated code must reproduce the stop or an explicitly approved replacement.
- **Floating point is hexadecimal.** `COMP-1` and `COMP-2` are IBM hexadecimal floating point on z/OS, not IEEE 754. Convert explicitly and expect precision differences.

## Alphanumeric data and comparisons

- Alphanumeric `MOVE` pads with spaces or truncates on the right (on the left for `JUSTIFIED RIGHT`).
- Comparisons pad the shorter operand with spaces, so `'ABC'` equals `'ABC   '`. Most target languages do not.
- Comparisons and ordering use EBCDIC unless a `PROGRAM COLLATING SEQUENCE` is declared. See the collation section of [data-and-encoding.md](data-and-encoding.md).
- Reference modification (`field(start:length)`) counts bytes, which breaks on DBCS and UTF-8 data.
- `INSPECT ... CONVERTING`, `HIGH-VALUES`, `LOW-VALUES`, and hexadecimal literals usually encode EBCDIC-specific assumptions.
- Class tests (`IS NUMERIC`, `IS ALPHABETIC`) are byte tests; `IS NUMERIC` on a packed field checks digit and sign nibbles.

## Control flow

- Paragraphs fall through into the next paragraph unless control leaves explicitly.
- `PERFORM A THRU B` executes the range in source order; a `GO TO` out of an active range, or overlapping ranges, leaves return points that can cause surprising fall-through later.
- `GO TO ... DEPENDING ON` is a computed jump; `ALTER` rewrites a `GO TO` target at run time. Both need explicit state machines in structured code.
- `NEXT SENTENCE` jumps past the next period, not the end of the scope (`CONTINUE` does nothing). Mixing it with scope terminators is a classic defect source; preserve the actual behavior, not the apparent intent, unless a fix is approved.
- `DECLARATIVES` with `USE AFTER ERROR` run on file errors.
- Restructuring rule: build the control-flow graph first, change structure only under characterization tests, and keep one structural change per commit.

## File handling

- `SELECT ... ASSIGN TO ddname` binds a file to a JCL DD name at run time; the data set is chosen in JCL, not in the program. Programs can also allocate data sets dynamically (for example through `BPXWDYN` or Assembler `SVC 99`), which hides data set names.
- Check `FILE STATUS` behavior, not just success paths. Common values: `00` success, `02` duplicate alternate key, `04` length mismatch, `10` end of file, `22` duplicate key, `23` record not found, `35` file not found at `OPEN`, `39` attribute conflict, `9x` implementation-specific (VSAM return and feedback codes).
- Multiple `01` records under one `FD` share the same buffer (an implicit `REDEFINES`).
- `READ INTO` and `WRITE FROM` copy between buffers; a record area after `WRITE` is not guaranteed to keep its contents.
- `START` positions a browse at a key that is equal, greater, or not less than the value given; generic keys compare a leading portion.
- `REWRITE` after a sequential `READ` replaces that record; record length rules differ for variable-length files.

## Compiler options that change behavior

The same source compiled with different options behaves differently. Record the options for each program from its listing, not from shop standards.

| Option | Effect to preserve |
| --- | --- |
| `ARITH(COMPAT\|EXTEND)` | Maximum digits and intermediate precision |
| `TRUNC(STD\|OPT\|BIN)` | Binary truncation semantics |
| `NUMPROC(NOPFD\|PFD)` | Sign handling and comparisons for zoned and packed data |
| `DYNAM\|NODYNAM` | Whether `CALL 'literal'` is dynamic |
| `RMODE`, `DATA(24\|31)`, binder `AMODE` and `RMODE` | Addressing mode and storage location |
| `CODEPAGE(ccsid)` | Code page for literals and national conversions |
| `NSYMBOL(NATIONAL\|DBCS)` | Meaning of `PIC N` |
| `INTDATE(ANSI\|LILIAN)` | Base of date intrinsic functions |
| `SSRANGE`, `NUMCHECK`, `INITCHECK`, `PARMCHECK` | Run-time checks that turn silent defects into abends |
| `INVDATA` (or the older `ZONEDATA`) | Tolerance of invalid zoned and packed data |
| `QUOTE\|APOST` | Literal delimiter |
| `SQL` coprocessor or separate precompiler, `CICS` integrated or separate translator | How embedded statements are processed |
| `OPT`, `ARCH` | Performance; also affects code paths for invalid data |

## Upgrading Enterprise COBOL

Moving from Enterprise COBOL V4 (or earlier) to V6 is a classic refactor with specific risks:

- V5 and later produce program objects that must be stored in PDSE libraries, and some AMODE 24 configurations are not supported. Check binder steps, library allocation, and the AMODE and RMODE of every module.
- Behavior differences show up mainly with invalid data (for example spaces in zoned fields or bad sign nibbles) and in rare `COMPUTE ... ROUNDED` cases.
- IBM's migration recommendation is to compile with `SSRANGE`, `NUMCHECK`, `PARMCHECK`, `INITCHECK`, and `OPT(0)` and run regression tests; fix the programs or data that fail, or use `INVDATA` to tolerate bad zoned data; then recompile without the checks at `OPT(2)` with the target `ARCH` and test again. Follow the Enterprise COBOL Migration Guide for the exact release.
- Modules compiled with very old compilers (OS/VS COBOL, VS COBOL II) have additional interoperability restrictions; inventory them separately.
- When source is missing or a quick CPU reduction is the goal, IBM Automatic Binary Optimizer (ABO) optimizes existing modules without recompiling; treat it as its own change with its own equivalence evidence.
- Change compiler options in a separate batch from code changes, so differences can be attributed.

## Where business rules hide

- Copybooks containing `PROCEDURE DIVISION` code.
- Shared date, holiday, rate, and validation routines (often high fan-in, sometimes Assembler).
- Tables in VSAM or Db2 that drive logic (rates, codes, routing).
- Control cards, `PARM` values, and JCL symbolic parameters set by the scheduler.
- `88`-level value lists and `EVALUATE` tables.
- Message and error tables; operator procedures documented only in run books.
