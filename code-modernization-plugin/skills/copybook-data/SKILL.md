---
name: copybook-data
description: Works with mainframe record layouts and data. Computes exact field offsets from COBOL copybooks, PL/I structures, and HLASM DSECTs (including SYNCHRONIZED slack bytes, OCCURS DEPENDING ON, REDEFINES, and bit fields); checks whether a layout change is breaking; drafts JSON Schema, Avro, AsyncAPI, and DFSORT symbols; decodes EBCDIC data sets field by field (zoned and packed decimal, binary, hexadecimal float, national, DBCS) in 31 code pages; compares two data sets field by field as golden-master evidence; and masks personal data while keeping test data valid. Use when the user asks about a record layout or field offsets, a contract for an API or message, whether a copybook change breaks consumers, what a mainframe data file contains, whether two runs produced the same output, or how to build safe test data. The scripts only read files, except record_mask.py, which writes masked data to the output you name.
license: MIT
compatibility: Scripts need Python 3.11+ (standard library only; run with uv or python3). Data sets must be downloaded in binary, with their RDWs for variable-length records.
metadata:
  author: markbsigler
  version: "1.0"
---

# Copybook and Record Data

Exact record layouts and data-level evidence for mainframe modernization. It serves the `mainframe-analysis` stack profile and both playbooks: layouts define contracts (Refactor Stage 1, Rearchitect Stage 2), and decoded comparisons are the golden-master evidence for Refactor Stages 2 and 4 and for parallel runs in Rearchitect Stages 3 and 4. For encoding, collation, and date rules, read the `mainframe-analysis` skill's references/data-and-encoding.md.

## Operating rules

1. **Transfer data in binary.** Text-mode transfers corrupt packed, binary, and floating-point fields. Keep RDWs for variable-length data sets (for example `quote site rdw` with z/OS FTP).
2. **Decimal stays decimal.** Outputs carry zoned and packed values as exact decimal strings; never round-trip them through floating point.
3. **Confirm unusual layouts at the source.** When SYNCHRONIZED, ALIGNED, REDEFINES, or OCCURS DEPENDING ON appear, compare the offsets with the compiler MAP listing (COBOL), AGGREGATE listing (PL/I), or assembler listing.
4. **Mask before data leaves its controlled environment.** Pass the masking secret through an environment variable, never on the command line or in the repository.
5. **Everything is read-only** except `record_mask.py`, which writes only to the `--output` path you choose.

## Scripts

Run them from this skill's directory, or give the full path.

| Script | Purpose |
| --- | --- |
| `scripts/copybook_layout.py` | Layouts from COBOL, PL/I, or HLASM; JSON, Markdown, JSON Schema, Avro, AsyncAPI, DFSORT symbols; `--diff` for breaking changes |
| `scripts/record_decode.py` | Decode records to JSON lines or Markdown, with per-field issues |
| `scripts/record_compare.py` | Compare two data sets field by field, with counts, control totals, and the first differences |
| `scripts/record_mask.py` | Suggest and apply format-preserving masking rules |
| `scripts/pli_hlasm_layout.py` | PL/I and HLASM parsers used by the other scripts |
| `scripts/zos_encoding.py` | Code pages (`--list`), record formats, and hex dumps of raw records |

## Workflow

### 1. Compute the layout

```bash
uv run --script scripts/copybook_layout.py CUSTREC.cpy --format markdown
uv run --script scripts/copybook_layout.py ORDERS.cpy --copylib copy/ --replace :PFX: WS
uv run --script scripts/copybook_layout.py CUSTREC.pli --format markdown    # PL/I, detected
uv run --script scripts/copybook_layout.py CUSTDS.mac --language hlasm      # Assembler DSECT
```

The JSON gives each field's 0-based `offset`, 1-based `position`, `length` (one occurrence), `total_length`, `category`, `digits`, `scale`, `sign`, `dfsort` format, `occurs` and `occurs_in` (table strides), `redefines`, 88-level `conditions`, `slack_before` and `slack_after` for SYNCHRONIZED alignment, and `bit_offset` and `bits` for PL/I bit strings. Read every entry in `warnings`.

### 2. Draft contracts

```bash
uv run --script scripts/copybook_layout.py CUSTREC.cpy --format json-schema > cust.schema.json
uv run --script scripts/copybook_layout.py CUSTREC.cpy --format avro
uv run --script scripts/copybook_layout.py ORDERMSG.cpy --format asyncapi --channel ORDERS.EVENTS
uv run --script scripts/copybook_layout.py CUSTREC.cpy --format dfsort-symbols --rdw > CUST.SYMNAMES
```

Decimals stay exact: strings in JSON Schema, `decimal` logical types in Avro. REDEFINES overlays and pointer fields have no portable form and are reported as warnings. Every draft needs a human review before it becomes a contract.

### 3. Check a layout change

```bash
uv run --script scripts/copybook_layout.py OLD/CUSTREC.cpy --diff NEW/CUSTREC.cpy --format markdown
uv run --script scripts/copybook_layout.py CUSTREC.cpy --diff CUSTREC.pli --match position
```

Fields are matched by qualified name, or by offset with `--match position`, which compares definitions of the same record in different languages. Removed, moved, resized, or retyped fields, OCCURS or REDEFINES changes, and record-length changes are breaking. Added fields and changed 88-level values or VALUE clauses are reported but are not breaking. The exit status is 0 with no breaking changes, 1 with breaking changes, and 2 on errors, so the check can gate a pipeline.

### 4. Decode data

```bash
uv run --script scripts/record_decode.py CUSTREC.cpy CUST.DATA --format markdown --max-records 5
uv run --script scripts/record_decode.py CUSTREC.cpy CUST.VB --recfm V --codepage 273 --hex
uv run --script scripts/record_decode.py TRANREC.cpy TRAN.DATA --type-field 1:2 --type HD=TRAN-HEADER --type DT=TRAN-DETAIL
```

Fixed-length records default to the layout length. `--type-field POS:LEN` with `--type VALUE=RECORD` picks the layout for files with several record types. OCCURS DEPENDING ON tables use each record's count. Invalid numeric data (spaces, low-values, bad digits or signs) appears under `issues` rather than stopping the run. See [references/data-formats.md](references/data-formats.md) for how each format is read.

### 5. Compare outputs (golden master)

```bash
uv run --script scripts/record_compare.py CUSTREC.cpy GOLDEN.DATA NEW.DATA --format markdown
uv run --script scripts/record_compare.py CUSTREC.cpy GOLDEN.DATA NEW.DATA --key CUST-ID --ignore RUN-DATE --total CUST-BAL
```

Records pair by position, or by `--key` fields when order may differ. The report lists differences by field, format-only differences (same number, different bytes, such as a packed sign of C versus F), unmatched records, control totals, invalid numeric data per file, and the first differences with hex. Format-only differences count as differences unless `--numeric-equal` is given; decide explicitly whether consumers depend on those bytes. The exit status is 0 when the files match, 1 when they differ, and 2 on errors. Attach the Markdown report to the playbook gate.

### 6. Mask test data

```bash
uv run --script scripts/record_mask.py CUSTREC.cpy CUST.DATA --suggest
MASK_SECRET=... uv run --script scripts/record_mask.py CUSTREC.cpy CUST.DATA --secret-env MASK_SECRET --rule CUST-NAME=hash --rule CARD-NO=luhn --rule CUST-PIN=blank --output CUST.MASKED
```

| Rule | Effect |
| --- | --- |
| `hash` | Deterministic, one-to-one, format-preserving replacement (a keyed permutation): letters stay letters, digits stay digits, numbers keep their sign and digit count, and different values never mask to the same value, so masked keys stay unique and still join across files |
| `luhn` | Permutes every digit but the check digit, then recomputes a valid Luhn check digit (card numbers), one to one |
| `blank` | Spaces for text, zero for numbers |
| `zero` | Zero for numbers, `0` characters for text |
| `fixed:TEXT` | Fixed replacement text or number |
| `keep` | Leave the field unchanged (the default for unnamed fields) |

The same value masks to the same result with the same secret, in any field and any file, so keys still join. A key stored as text in one file and as a number in another can mask differently; check joins after masking. `--suggest` matches field names against common personal-data terms; review it, and treat dates of birth and amounts by policy. Invalid numeric values are left unchanged and counted. The summary prints to standard error as JSON.

## Limitations

- Layouts come from source text: compile-time `>>` directives are ignored, PL/I `LIKE` is not expanded, PL/I ALIGNED mapping and HLASM `ORG` expressions are approximated, and generated or dynamically built records need their listings.
- `record_compare.py` holds both files in memory. Use it on test-sized data and on samples of production volumes; use the platform's compare tools for full volumes.
- Double-byte text is shown as `<DBCS:hex>` markers; mixed-code-page conversion needs the platform's conversion services.
