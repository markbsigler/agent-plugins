# Data representation, encoding, collation, and dates

Most silent modernization defects come from treating mainframe bytes as text or numbers in the wrong representation. Drive every conversion and comparison from the copybook layout (`scripts/copybook_layout.py`).

## Code pages (CCSIDs)

| CCSID | Use |
| --- | --- |
| 37 / 1140 | US and Canada English (1140 adds the euro sign) |
| 500 / 1148 | International Latin-1 |
| 273 / 1141 | Germany and Austria |
| 277 / 1142, 278 / 1143 | Denmark and Norway; Finland and Sweden |
| 280 / 1144, 284 / 1145 | Italy; Spain and Latin America |
| 285 / 1146, 297 / 1147 | United Kingdom; France |
| 1047 | Latin-1 for z/OS UNIX and C programs |
| 870, 875, 1025 | Latin-2; Greek; Cyrillic |
| 930, 939, 1390, 1399 | Japanese, mixed single- and double-byte |
| 935, 1388 / 937 / 933, 1364 | Simplified Chinese / Traditional Chinese / Korean |
| 420, 424 | Arabic and Hebrew (bidirectional) |
| 1200 | UTF-16 (COBOL `NATIONAL` data) |
| 1208 | UTF-8 |

Rules:

- Identify the CCSID of every data set, Db2 table (`CCSID` clause), MQ message (`CodedCharSetId`), and file transfer. The compiler `CODEPAGE` option governs literals.
- Code pages disagree on characters such as `[`, `]`, `!`, `|`, `^`, `¬`, and the national characters `@`, `#`, and `$`. Those characters can appear in data set, member, program, and user names, so name mapping is a conversion too.
- Never translate a whole record or file with a character converter (for example `iconv` or an FTP text transfer) when it contains packed, binary, or floating-point fields. Convert character fields with the CCSID, convert numeric fields by type, and copy everything else byte for byte.
- Verify round trips (EBCDIC to Unicode to EBCDIC) for character fields and decide how unmappable characters are handled before migration, not after.

## Numeric representations

| COBOL | Bytes | Encoding | Example |
| --- | --- | --- | --- |
| `PIC S9(5)` (zoned decimal, `DISPLAY`) | 1 per digit | Zone nibble `F`; the last byte's zone holds the sign: `C` positive, `D` negative, `F` unsigned | +123 is `F1 F2 C3`; -123 is `F1 F2 D3` |
| `SIGN LEADING SEPARATE` | digits + 1 | Separate `+` or `-` character first | `-123` is `60 F1 F2 F3` |
| `PIC S9(7)V99 COMP-3` (packed decimal) | digits // 2 + 1 | Two digits per byte; last nibble is the sign | +12345.67 is `00 12 34 56 7C` (5 bytes) |
| `COMP`, `COMP-4`, `BINARY`, `COMP-5` | 2, 4, or 8 | Big-endian two's complement | `S9(4) COMP` value -2 is `FF FE` |
| `COMP-1`, `COMP-2` | 4, 8 | IBM hexadecimal floating point, not IEEE 754 | |
| `PIC N` (`NATIONAL`) | 2 per character | UTF-16 big-endian | |
| `PIC G` / `DISPLAY-1` | 2 per character | DBCS in the code page | |

Pitfalls:

- A zoned field displayed as text shows its signed last digit as a letter or brace: in EBCDIC, +0 is `{`, +1 to +9 are `A` to `I`, -0 is `}`, and -1 to -9 are `J` to `R`. Character conversion keeps the letter but loses the numeric meaning, because ASCII-based runtimes encode signs differently.
- ASCII-based COBOL runtimes encode zoned signs differently; configure the target compiler's host-compatible sign and numeric options or convert explicitly.
- Packed fields accept `A`, `C`, `E`, `F` as positive and `B`, `D` as negative sign nibbles; preferred signs are `C`, `D`, and `F`. Bad digits or signs cause S0C7 data exceptions.
- Binary fields are big-endian; x86 and most ARM targets are little-endian.
- `DECIMAL-POINT IS COMMA` (common in European shops) swaps the roles of period and comma in literals and edited pictures.
- Numeric-edited fields (`ZZ,ZZ9.99-`, `CR`, `DB`) are display formats. Parse them only with the exact picture.

## Special values and sentinels

| Constant | EBCDIC | ASCII or UTF-8 | Risk |
| --- | --- | --- | --- |
| `SPACE` | `40` | `20` | Space-filled numeric fields abend in arithmetic |
| `LOW-VALUES` | `00` | `00` | Used as "not set" or as the lowest key |
| `HIGH-VALUES` | `FF` | `FF` is invalid in UTF-8 | Used as end-of-file sentinel in match-merge logic and as the highest key |
| `ZERO` in alphanumeric fields | `F0` | `30` | Character zero, not numeric zero |

Map sentinels to explicit values in target designs instead of relying on byte values.

## Collating sequence

EBCDIC orders characters as: space, punctuation, lowercase letters, uppercase letters, digits. ASCII and Unicode order them as: space, punctuation, digits, uppercase letters, lowercase letters. The EBCDIC letter ranges also contain gaps (for example between `I` and `J`), so a range test such as `'A' THRU 'Z'` accepts some non-letter bytes.

Affected logic:

- `SORT` and `MERGE` output order, DFSORT `CH` fields, and every downstream consumer that expects that order.
- `SEARCH ALL` tables and VSAM KSDS key order.
- Db2 for z/OS `ORDER BY`, `BETWEEN`, and range predicates on EBCDIC `CHAR` columns.
- Control-break reports and balance-line (match-merge) programs that compare keys from two sorted files.
- Range checks in code (`IF CODE > 'Z'`, `IF KEY < LOW-LIMIT`).

Mitigations: keep keys numeric where possible; implement an explicit EBCDIC comparator or database collation where order is contractual; re-sort and re-verify after migration; add tests with mixed-case and alphanumeric keys.

## Dates and times

| Representation | Meaning |
| --- | --- |
| `YYMMDD`, `YYYYMMDD`, `MMDDYY` | Character or zoned dates; two-digit years rely on windowing |
| `YYDDD`, `YYYYDDD` | Julian (day of year) |
| `0CYYDDDF` packed | Date from the z/OS `TIME` macro; `C` is the century (0 = 19xx, 1 = 20xx) |
| Lilian day number | Language Environment day count; day 1 is 15 October 1582 (`CEEDAYS`, `CEEDATE`) |
| `FUNCTION INTEGER-OF-DATE` | COBOL day count; day 1 is 1 January 1601 |
| CICS `ABSTIME` | Milliseconds since 1 January 1900 (`ASKTIME`, `FORMATTIME`) |
| TOD clock (`STCK`) | 64-bit clock with a 1900 epoch; bit 51 is one microsecond |
| Db2 `TIMESTAMP` | `YYYY-MM-DD-HH.MM.SS.nnnnnn` in z/OS format, precision 6 by default |

Rules:

- Find the shop's shared date routines (often Assembler or high fan-in COBOL) and characterize them, including two-digit-year windows (fixed pivot or sliding) and holiday calendars.
- `ACCEPT ... FROM DATE` returns `YYMMDD`; `FROM DATE YYYYMMDD` returns four-digit years; `FUNCTION CURRENT-DATE` includes the offset from UTC.
- z/OS local time comes from the system's offset settings; batch scheduled near daylight-saving changes needs explicit tests.
- Use virtual-date tooling or injected clocks so tests can run month-end, year-end, and leap-day scenarios on demand.

## Record formats and transfers

- `RECFM=F` or `FB`: fixed-length records with no line terminators. `V` or `VB`: each record starts with a 4-byte record descriptor word (RDW) holding its length; blocks start with a block descriptor word (BDW). `LRECL` for `V` includes the RDW. `VBS` records can span blocks. `U` is used for load modules.
- `FBA` and `VBA` carry an ASA carriage-control character in the first byte (`1` new page, blank single space, `0` double space, `-` triple space, `+` overprint).
- Files often mix header, detail, and trailer records distinguished by a type code; trailers carry record counts and hash or control totals that downstream jobs verify. Preserve them.
- Binary transfers keep bytes exact. Variable-length records lose their lengths unless the transfer keeps the RDW (for example the FTP `RDW` site option), so agree the transfer mode with every partner.
- ESDS relative byte addresses (RBAs) stored in other files or tables do not survive a reorganization or migration.
