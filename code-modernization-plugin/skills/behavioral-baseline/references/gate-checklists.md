# Modernization Quality Gates & Baseline Formats

Reference formats consumed by `scripts/baseline_gate.py`.

## 1. Frozen Baseline Layout (`.modernize/baseline/`)

```text
.modernize/
├── triage-brief.md
├── estate-brief.md
├── plan.md
├── traceability.json
├── rulebook/
│   └── enterprise-standards.md
├── learnings/
│   └── <slug>.md
└── baseline/
    ├── test-cases.md           # Frozen behavioral specification (TC-001, ...)
    ├── infra-decision-table.md # Dependency isolation choices
    ├── manifest.json           # SHA-256 digests written by `baseline_gate.py freeze`
    └── testdata/               # Input and expected-output fixtures
```

### `test-cases.md` format

Each test case has a unique `TC-XXX` identifier in a heading (`### TC-001: <title>`) or markdown table row, states the external entry point, references any fixtures under `testdata/...`, and states concrete expected outcomes:

```markdown
# Behavioral Test Baseline

### TC-001: Account inquiry returns current balance
- **Entry Point:** `POST /api/v1/accounts/inquiry` (or CICS transaction `CAIN`)
- **Input:** `testdata/inputs/acct-001.json`
- **Expected Output:** HTTP 200 matching `testdata/expectations/acct-001-out.json`
- **Resource Verification:** No writes to `ACCT.BALANCE`
```

Phrases such as `behaves as expected`, `works properly`, `returns a reasonable error`, or `[NEEDS CLARIFICATION]` fail the `freeze` check.

### `infra-decision-table.md` format

Every external dependency in scope is assigned an explicit test strategy (`mock`, `testcontainer`, `emulator`, or `golden-file`):

```markdown
| Dependency | Kind | Strategy | Notes |
| --- | --- | --- | --- |
| PostgreSQL (`acct_db`) | database | testcontainer | PostgreSQL 16 container |
| Fraud scoring API | http | mock | WireMock stub |
```

## 2. Traceability File (`.modernize/traceability.json`)

```json
{
  "track": "Refactor",
  "requirements": [
    {
      "id": "REQ-001",
      "title": "Preserve account balance interest rounding",
      "source": "ACCTBAT.cbl:142 (BR-001)"
    }
  ],
  "tasks": [
    {
      "id": "T-001",
      "title": "Migrate interest calculation to BigDecimal with HALF_EVEN rounding",
      "requirements": ["REQ-001"],
      "test_cases": ["TC-001"],
      "status": "done"
    }
  ]
}
```

## 3. Gate Checklists

| Gate Type | Stage | Checks Performed |
| --- | --- | --- |
| `spec-quality` | Stage 1 | Every requirement (`REQ-XXX` or `BR-XXX`) has a valid ID and non-empty title, contains no `[NEEDS CLARIFICATION]` or vague placeholders, and any `.modernize/learnings/*.md` file has a 3-line scannable header. |
| `spec-to-plan` | Stage 1 Gate | Passes `spec-quality`, and every requirement in `requirements` is referenced by at least one task in `tasks`. |
| `plan-to-tasks` | Stage 2 Gate | Passes `spec-to-plan`, every task references only known requirements, and every task lists at least one `TC-XXX` verification test case. |
| `completeness` | Stage 4 Gate | Passes `plan-to-tasks`, every task has `status` equal to `"done"` or `"verified"`, and if `.modernize/baseline/manifest.json` exists, all frozen files match their SHA-256 digests and cover every task's `TC-XXX` IDs. |

## 4. Persistent Learnings Format (`.modernize/learnings/<slug>.md`)

Every learning file starts with an `# H1` title, a blank line, and a one-sentence summary so agents can scan relevance by reading only the first three lines:

```markdown
# Copybook COMP-3 Sign Nibbles in Batch Extracts

Batch extract files use unsigned F nibbles where CICS online files use C nibbles for positive balances.

## What Was Found
...

## Takeaway
...
```
