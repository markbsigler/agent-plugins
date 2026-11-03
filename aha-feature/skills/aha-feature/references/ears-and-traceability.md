# EARS and Traceability

How to write requirements as EARS statements in Aha! requirement records, and how each one traces from a use case to the criterion that verifies it. `aha_feature.py lint` checks everything on this page.

## Contents

- [The EARS patterns](#the-ears-patterns)
- [Rules for every statement](#rules-for-every-statement)
- [Statement format in Aha!](#statement-format-in-aha)
- [Priorities and change markers](#priorities-and-change-markers)
- [IDs](#ids)
- [The trace chain](#the-trace-chain)
- [Examples tables](#examples-tables)
- [Converting prose requirements](#converting-prose-requirements)

## The EARS patterns

EARS (Easy Approach to Requirements Syntax, Alistair Mavin, Rolls-Royce, 2009) gives each requirement a fixed shape: optional conditions, the system, SHALL, and the response. This skill writes the keywords in capitals so they stand out.

| Pattern | Template | Example |
| --- | --- | --- |
| Ubiquitous (always true) | The \<system> SHALL \<response>. | The agent SHALL link each note to its change. |
| Event-driven | WHEN \<trigger>, the \<system> SHALL \<response>. | WHEN a release branch is cut, the agent SHALL draft one note per merged change. |
| State-driven | WHILE \<state>, the \<system> SHALL \<response>. | WHILE a release is frozen, the agent SHALL NOT change its draft. |
| Unwanted behavior | IF \<condition>, THEN the \<system> SHALL \<response>. | IF a draft has no approval, THEN the agent SHALL NOT publish it. |
| Optional feature | WHERE \<feature or setting>, the \<system> SHALL \<response>. | WHERE translations are enabled, the agent SHALL draft each note in every enabled language. |
| Complex | WHILE \<state>, WHEN \<trigger>, the \<system> SHALL \<response>. | WHILE a release is frozen, WHEN a change merges, the agent SHALL add it to the next release's draft. |

For changes to existing behavior, two more forms keep the boundary explicit:

- **Prohibition:** `the <system> SHALL NOT <action>`.
- **Preserved behavior:** `the <system> SHALL CONTINUE TO <existing behavior>`, for what a change must not break.

## Rules for every statement

1. **Clause order:** WHERE first, then WHILE, then WHEN or IF, then the response.
2. **Capitals for keywords:** WHEN, WHILE, IF, THEN, WHERE, SHALL. "When" or "shall" is a lint warning.
3. **One SHALL per statement.** "SHALL draft and SHALL notify" becomes two statements. SHALL NOT and SHALL CONTINUE TO count as one.
4. **SHALL, never should, may, will, must, or can.** A weaker verb gives the implementer an opt-out. Priority, not the verb, says when it's needed.
5. **IF needs THEN.**
6. **Name the system once and reuse it:** "the agent", "the export service". Define it in the requirement's scope sentence if it isn't obvious.
7. **Observable and measurable responses.** Numbers with units, exact messages, named states. No vague words: fast, easy, robust, appropriate, as needed, etc., and/or.
8. **One behavior per statement**, 500 characters or fewer. Put cases in an examples table, not in clauses.

## Statement format in Aha!

Each requirement record holds a scope sentence, the statements as a list, optional examples, and the trace line:

```markdown
Draft one note per merged change.

- **FR-1 (P0):** WHEN a release branch is cut, the agent SHALL draft one note for each merged change.
- **FR-2 (P0):** The agent SHALL link each note to its change.
- **NFR-1 (P1):** WHEN a release has up to 200 changes, the agent SHALL finish the draft within 2 minutes.

Covers: UC-1. Verified by AC-1.
```

- The marker in parentheses holds the priority and, optionally, a change marker: `(P1, MODIFIED)`.
- A long statement may continue on indented lines below its bullet.
- A table works too, when the first column is the ID and the last is the statement: `| FR-3 | P0 | IF ..., THEN ... |`.
- NFRs name their quality characteristic (ISO/IEC 25010) in the scope sentence or the statement when it helps: performance efficiency, security, reliability, usability, compatibility, maintainability, portability.

## Priorities and change markers

| Priority | Meaning | MoSCoW, for tools that need it |
| --- | --- | --- |
| P0 | Needed in the first release | Must |
| P1 | The next increment | Should |
| P2 | Later, or when a dependency arrives | Could |

Every priority still uses SHALL. P0, P1, and P2 say *when*, not *how firmly*.

Change markers matter when a feature changes what already exists; the OpenSpec export maps them to delta sections:

| Marker | Use for |
| --- | --- |
| ADDED (default) | A new behavior |
| MODIFIED | A behavior that exists and changes. State the full new behavior. |
| REMOVED | A behavior that goes away. State why and what replaces it. |

## IDs

| ID | Names | Where it's defined |
| --- | --- | --- |
| UC-n | A use case | The Use Case(s) field |
| FR-n | A functional statement | A requirement record |
| NFR-n | A non-functional statement | A requirement record |
| AC-n | An acceptance criterion | The Acceptance Criteria field |
| OQ-n | An open question | A To-Do on the record, tagged `(OQ-n)` |
| SD-n | A shared decision | An `SD-n:` To-Do on the initiative |

- **Stable.** Never renumber or reuse an ID, even after deleting the statement. Gaps are fine.
- **Feature-wide.** FR and NFR numbers run across all of a feature's requirement records.
- **Cited, not copied.** Other records cite an ID ("APP-12 FR-8") rather than repeating the text.

## The trace chain

```text
UC-n (Use Case(s))
  -> requirement record  "Covers: UC-n"
       -> FR-n and NFR-n statements
            -> AC-n (Acceptance Criteria)  "Verified by AC-n"
                 -> Definition of Done      "AC-1 to AC-n pass"
                      -> exported spec, code, and tests  (IDs kept unchanged)
```

The trace line ends every requirement record:

- `Covers: UC-2. Verified by AC-2, AC-3.`, on one line or two.
- Ranges: `UC-8 to UC-11`, `AC-1 to AC-13 and AC-15`.
- `Covers: all use cases.` for cross-cutting requirements such as security or compatibility.
- Statement IDs may appear in Covers (`Covers: UC-1; FR-1, FR-2.`); lint checks that they exist.

Lint fails when a requirement has no trace line, cites an undefined UC or AC, leaves a use case uncovered at the ready gate, or when the Definition of Done's AC range doesn't match.

## Examples tables

Rules with cases are clearer as a table of inputs and expected results than as prose:

| Input | Expected result |
| --- | --- |
| A change with a linked feature | One note that links to both |
| A change with no linked feature | No note; the change is listed in the escalation |
| 201 changes | The draft stops at 200 and escalates |

Use the same idea for state transitions (state, event, next state) and for routing (signal, route, alternative).

## Converting prose requirements

Older records often hold prose such as "Accept requests from the tracker, link each one to applications, and classify it (P0)", with a trace line that cites an external document: `Covers: UC-1; PRD FR-1 to FR-7.` Convert them in place:

1. Split the prose into one behavior per sentence.
2. Write each as an EARS statement. Keep the original FR number when the old document had one, so history still traces.
3. Carry each "(P0)" or "(P1)" marker into the statement's priority.
4. Turn conditions hidden in the prose ("when it's enabled", "if the budget is used up") into WHERE and IF clauses.
5. Drop the `PRD` prefix from the Covers line once the statements live in the record.
6. Keep the scope sentence and any tables.

Before:

> Send corrective requests to the assignee and make no change (P0). Return the triage result within 10 minutes of intake (target to confirm).

After:

```markdown
- **FR-4 (P0):** IF the request is corrective, THEN the agent SHALL route it to the assignee without changing any code.
- **NFR-10 (P0):** WHEN a request arrives, the agent SHALL return the triage result within 10 minutes (target to confirm).
```

If a prose sentence holds two behaviors that can fail independently, split it and give the second statement a new ID.
