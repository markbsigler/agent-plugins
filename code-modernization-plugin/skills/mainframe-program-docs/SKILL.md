---
name: mainframe-program-docs
description: Documents IBM Z COBOL programs and 3270 screens from source. Use when asked to explain or document a COBOL program, draw its section and paragraph flow, find dead or unreachable paragraphs, list business-rule candidates for subject-matter experts, list a program's CALL, CICS, SQL, DL/I, MQ, and file interfaces, document or mock up a CICS BMS map or IMS MFS format, or check a BMS symbolic-map copybook against its map. Produces a Markdown documentation skeleton with a Mermaid flowchart, or JSON. Bundled scripts only read files.
license: MIT
compatibility: Scripts need Python 3.11+ (standard library only; run with uv or python3). They read COBOL programs, copybooks, and BMS or MFS members exported to a local directory, as text or EBCDIC.
metadata:
  author: markbsigler
  version: "1.0"
---

# Mainframe Program Documentation

Turns one COBOL program, or one BMS mapset or MFS member, into a documentation skeleton backed by static analysis: structure, flow, unreachable code, interfaces, business-rule candidates, and screen layouts. The scripts find and cross-reference; whoever writes the final document reads the code, writes the descriptions, and gets the rules confirmed.

Related skills:

- `mainframe-analysis` inventories the estate (programs, copybooks, JCL, call and data set graphs). Use it to choose which programs to document, and apply the COBOL semantics in its `references/cobol-language.md` while you read code.
- `copybook-data` computes exact record layouts, offsets, and JSON Schemas for the copybooks that this skill lists under Data and Interfaces.

## Operating rules

1. **The scripts produce evidence, not documentation.** Every description, purpose, and rule in the final document comes from reading the code, and cites the line it came from.
2. **Unreachable means unproven.** A paragraph that no PERFORM, GO TO, fall-through, SORT procedure, CICS HANDLE label, or entry point reaches is a candidate. Confirm it with runtime coverage (code coverage from a test run, or production monitoring) before calling it dead.
3. **Rules need owners.** Business-rule candidates are patterns: conditions, calculations, condition names, and literal thresholds or codes. A subject-matter expert confirms each one before it becomes a rule.
4. **Screens are contracts.** Field positions can be read by screen scrapers, RPA bots, and terminal-emulator macros. Record them before anything moves.
5. **Read-only.** The scripts only read files and print to standard output.

## Workflow

### Step 1: Generate the program skeleton

Run from this skill's directory, or give the full script path. Pass every copy library in compile-concatenation order; the program's own directory is searched last.

```bash
uv run --script scripts/cobol_flow.py CUSTUPD.cbl --copylib copybooks > CUSTUPD.md
uv run --script scripts/cobol_flow.py CUSTUPD.cbl --copylib copybooks --format json > CUSTUPD.json
uv run --script scripts/cobol_flow.py CUSTUPD.cbl --copylib copybooks --format mermaid --max-nodes 80
uv run --script scripts/cobol_flow.py PAYROLL --codepage 1140
```

The Markdown skeleton has these sections:

| Section | Contents |
| --- | --- |
| Overview | PROGRAM-ID, AUTHOR, INSTALLATION, DATE-WRITTEN, DATE-COMPILED, REMARKS, header comments, nested programs, PROCEDURE DIVISION USING, ENTRY points |
| Files | SELECT, DD name, organization, access, record key, file status, and the I/O verbs used on each file |
| Data | 01 and 77 records per section with the copybook they come from, copybooks not expanded, and 88-level condition names |
| Interfaces | Static and dynamic CALLs (dynamic targets resolved from `VALUE` and `MOVE` literals), CICS commands and resources, SQL statements and tables, DL/I calls, MQ calls and queue names |
| Procedure structure | Each section and paragraph with its line, the comment block above it as a draft description, and what it performs and goes to |
| Flow | A Mermaid `flowchart TD`: `-->` PERFORM, `-->\|thru X\|` PERFORM THRU, `-.->` GO TO and fall-through (`next`), `==>` ALTER; unreachable nodes are highlighted |
| Unreachable candidates | Procedures that no entry point reaches |
| Structure risks | GO TO out of a PERFORM range, recursive PERFORM cycles, ALTER, GO TO DEPENDING ON, CICS HANDLE labels, and procedure names that are not defined |
| Business-rule candidates | `BR-001` onward, with paragraph, line, kind, normalized text, data names, and signals (`condition-name`, `literal-comparison`, `literal-constant`, `technical`) |
| To complete | The work left for the person or agent writing the final document |

JSON holds the full model: procedures, edges with their kinds and lines, rules, interfaces, copybooks, and warnings. Line numbers always refer to the program; lines that came from a copybook carry the line of the COPY statement and the copybook name.

### Step 2: Read the code and write the descriptions

Work from the roots in the procedure table (the first procedure, DECLARATIVES sections, and ENTRY points) down the PERFORM tree. For each procedure, replace _To complete_ with what it does and why, check descriptions taken from comments against the code (comments drift), and write the Purpose in the Overview. Keep the semantics in `mainframe-analysis` in mind: truncation in arithmetic, fall-through, `NEXT SENTENCE`, and `HANDLE CONDITION` change what code that looks simple does.

Rerun with every copy library you can get when the skeleton lists copybooks not expanded or procedure names not defined; both usually mean a missing library rather than a defect.

### Step 3: Confirm business rules

Take the candidates to a subject-matter expert. For each one, record the rule in business terms with its `BR` id, paragraph, and line; record what each literal means (a threshold, a status code, a product type); and drop candidates that are only technical checks (file status, `SQLCODE`, `EIBRESP`). Keep the line references, so that a later change can be traced back to the rule it affects.

### Step 4: Document the screens

```bash
uv run --script scripts/screen_map.py CUSTMAP.bms > CUSTMAP.md
uv run --script scripts/screen_map.py CUSTMAP.bms --symbolic CUSTMAP.cpy
uv run --script scripts/screen_map.py CUSTFMT.mfs --format json > CUSTFMT.json
```

For each BMS map or MFS device format the output gives:

- **Field table:** name, attribute-byte row and column, first data row and column, length, attributes, initial value, PICIN and PICOUT, and role (constant, input, output, plus numeric, hidden, and initial-cursor flags). OCCURS fields are expanded; GRPNAME subfields share one attribute byte.
- **Mockup:** the screen as text under a column ruler. Constants show their text, `_` marks input (`9` for numeric input), `X` marks output, and attribute bytes and hidden fields are blank.
- **Screen contract:** named fields with 1-based row, column, and length, for screen scrapers and RPA.
- **Warnings:** overlapping fields, fields past the screen width, and input fields without a length.

For MFS, each message field (MFLD) is linked to the device field (DFLD) of the same name. `--symbolic` checks a BMS symbolic-map copybook for each named field's length (`L`), flag (`F`) and attribute (`A`), extended attribute subfields requested by DSATTS (`C`, `H`, `P`, `V`, `U`, `M`, `T`), input (`I`), and output (`O`) entries, field lengths, the output structure redefining the input, and the 12-byte prefix that `TIOAPFX=YES` adds.

## Limitations

- **Static analysis.** Reachability ignores data values and run-time state. A PERFORM covers its whole range and returns at its end, and a GO TO that stays in the active range keeps that return point; overlapping ranges and GO TO out of a range are flagged, not modeled.
- **Dynamic flow is approximate.** ALTER, GO TO DEPENDING ON, CICS HANDLE labels, and dynamic CALLs are resolved only as far as literals in the source show. Fall-through is modeled within a section only.
- **Source, not load modules.** Analyze the source that matches production. Document generated programs (from code generators or 4GLs) at the generator level, and analyze the original source rather than precompiler or translator output.
- **Copybooks are needed.** Without them, data names, condition names, and paragraphs held in copybooks are missing. `REPLACE` statements and conditional compilation (`>>IF`) are not processed.
- **One program per run.** Nested and following programs are listed, not analyzed.
- **Screens are approximate.** Mockups ignore color, highlighting, and DBCS; XINIT and GINIT values are not shown; the symbolic-map check assumes the layout BMS generates for COBOL.
