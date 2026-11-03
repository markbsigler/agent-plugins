# Quality Gates

What "ready" means at each stage, how the scripts score a record, and the judgment they can't make.

## Contents

- [Gates](#gates)
- [Matrix scoring](#matrix-scoring)
- [Lint rule catalog](#lint-rule-catalog)
- [Reporting findings](#reporting-findings)
- [Review rubric](#review-rubric)
- [Alignment review](#alignment-review)
- [Approval gates](#approval-gates)

## Gates

| Gate | Passes when | Typical workflow status |
| --- | --- | --- |
| Seed | `lint --gate seed` has no errors: a user story and a definition table with the profile's seed rows. Dimensions 1 and 2 answered, goal alignment linked or confirmed. | Under consideration |
| Elaborated | `lint --gate elaborated` has no errors, and `matrix` shows all five dimensions answered or deferred. | In design |
| Ready | `lint --gate ready` has no errors (no open markers, every use case covered), and the Approval To-Do for the current fingerprint is complete. | Ready to develop |

Status names differ by workspace; read them from `fields_metadata`. Change the status only when the user agrees.

## Matrix scoring

`aha_feature.py matrix` marks each dimension complete (every check passes), partial (some pass), or missing (none pass). Text that still holds a `{{placeholder}}` doesn't count.

| Dimension | Checks |
| --- | --- |
| 1. Value & Persona | A user story with persona, capability, and outcome; Business Problem; Business Value |
| 2. Scope & Boundaries | A definition table; workflow steps; at least 3 out-of-scope items; EARS statements, none with placeholders |
| 3. Tech & Data | Upstream or downstream dependencies; a context, data, read, write, or integration row; NFR statements |
| 4. Edge Cases | A complete Given/When/Then criterion; failure coverage: an IF or SHALL NOT statement, a criterion about failure, errors, limits, or escalation, or a stop-conditions or guardrails row |
| 5. Success Metrics | A Definition of Done; a measurable target in Business Value or the Definition of Done |

Goal alignment reports linked, not linked, confirmed unlinked (front matter `alignment: unlinked (confirmed by ...)`), or unknown (the source had no initiative, goals, or key results). The exit code is 1 while any dimension is incomplete.

The matrix measures presence, not quality. A dimension can be complete and still vague; judge that with the [review rubric](#review-rubric).

## Lint rule catalog

`aha_feature.py lint --list-rules` prints the same catalog. Severity by gate (seed / elaborated / ready); a dash means the rule doesn't run at that gate.

| Rule | Checks | Seed | Elaborated | Ready |
| --- | --- | --- | --- | --- |
| STR001 | Description has a user story | error | error | error |
| STR002 | Description has a definition table | error | error | error |
| STR003 | The table has the profile's rows (seed rows at the seed gate) | error | warning | error |
| STR004 | At least 3 out-of-scope items | info | warning | error |
| STR005 | A Definition of Done (or Exit criteria, Success criteria, Done when) | - | warning | error |
| STR006 | The gate's fields aren't empty | - | warning; error for Use Case(s) and Acceptance Criteria | error |
| STR007 | The feature has requirements | - | error | error |
| STR008 | Value targets have a baseline | warning | warning | warning |
| STR009 | Summary of 1,200 characters or fewer | warning | warning | warning |
| STR010 | Security, measurable performance, and (product) accessibility are covered | - | info | warning |
| EARS001 | Each requirement has EARS statements | warning | error | error |
| EARS002 | Each statement has SHALL | error | error | error |
| EARS003 | Keywords in capitals | warning | warning | warning |
| EARS005 | IF has THEN | warning | warning | warning |
| EARS006 | Clause order: WHERE, WHILE, WHEN or IF | warning | warning | warning |
| EARS007 | One SHALL per statement | warning | warning | warning |
| EARS008 | No vague terms | warning | warning | warning |
| EARS009 | Each statement has a priority | warning | warning | warning |
| EARS010 | Statement IDs are unique | error | error | error |
| EARS011 | Markers are a priority plus ADDED, MODIFIED, or REMOVED | warning | warning | warning |
| TRC001 | Each requirement has a Covers line | - | error | error |
| TRC002 | Each requirement has a Verified by line | - | error | error |
| TRC003 | Covers cites defined use cases | - | error | error |
| TRC004 | Verified by cites defined criteria | - | error | error |
| TRC005 | Every use case is covered | - | warning | error |
| TRC006 | Every criterion verifies a requirement | - | warning | warning |
| TRC007 | Covers doesn't cite an external PRD | - | info | warning |
| TRC008 | The Definition of Done range matches the criteria | - | warning | warning |
| TRC009 | Covers cites existing FR and NFR IDs | - | warning | warning |
| AC001 | Each criterion has Given, When, and Then | error | error | error |
| AC002 | Criterion IDs are unique (error) and sequential (info) | error | error | error |
| AC003 | Acceptance Criteria uses AC-n headings | info | error | error |
| AC004 | Criteria avoid vague terms | warning | warning | warning |
| UC001 | Use case IDs are unique | error | error | error |
| UC002 | Each use case has a priority | warning | warning | warning |
| UC003 | Use Case(s) uses UC-n IDs | info | error | error |
| WRT001 | No overclaims | warning | warning | warning |
| WRT002 | No release names or dates in text | warning | warning | warning |
| WRT003 | Open markers resolved or tracked | info | info | error |
| WRT004 | No template placeholders | error | error | error |
| ELC001 | The elicitation record agrees with the matrix: no dimension recorded missing, partial, or open that the matrix finds complete, and none recorded answered that it finds missing | info | warning | warning |

Use `--fail-on warning` to make warnings fail too, and `--format json` to process findings.

## Reporting findings

Report a review as a table, most important first, limited to what the user asked about:

| Priority | Finding | Recommendation | Where |
| --- | --- | --- | --- |
| High | Requirements are prose that cite an external PRD; no EARS statements | Convert each requirement to EARS statements with the PRD's FR numbers | Requirements |
| Medium | No failure modes in the acceptance criteria | Add criteria for invalid input and for an unavailable dependency | Acceptance Criteria |

High means a builder would guess wrong or the record contradicts another; Medium means a gap a builder would ask about; Low means wording or style.

## Review rubric

Judgment the scripts can't make:

- **Self-contained.** Could someone with no context build the right thing from this record alone?
- **Boundaries in three tiers.** What it always does (Guardrails), what needs a person first (Autonomy, stop conditions), and what it never does (Guardrails, Out of scope). An "ask first" rule says what happens when nobody answers.
- **Failure paths.** Deletion and cancellation, concurrent changes, unavailable dependencies, limits, permissions, time zones.
- **Separation of duties.** Who approves, and that the author of a change can't approve it.
- **Data handling.** What data reaches models, logs, or vendor tools, and who decides.
- **Handoffs both ways.** Every handoff this record declares is accepted by the record that receives it, and the reverse.
- **Consistency upward.** No conflict with the initiative, its shared decisions, or the epic.
- **Plausible numbers.** Targets and limits that a baseline or a stated method supports.
- **Overclaims in context.** Words the lists miss but that promise more than the feature does.

## Alignment review

When several features share an initiative or hand work to each other, compare them side by side:

1. Read the initiative, its shared decisions (`SD-n:` To-Dos), and each feature.
2. Build a consistency table: one row per dimension, one column per feature. Useful dimensions: owner; compatibility or deployment requirement; administrator policy with an acceptance criterion; autonomy or permission vocabulary; cancellation and restart criteria; audit criterion; secrets handling; a security requirement; entry points (tracker, sessions, APIs); outcome metrics; pilot or proof gates; latency targets marked "(to confirm)"; differentiator justification; dependencies on shared services; record references written as links; handoffs declared on both sides.
3. List the findings that sit *between* records: one-way handoffs, the same decision tracked under different IDs, conflicting rules, release order that contradicts dependencies.
4. Record each decision that affects more than one feature as an `SD-n:` To-Do on the initiative, with **Decision**, **Affects**, **Status**, **Owner**, and **Recommended**. Features cite `SD-n` instead of repeating it.
5. Apply the edits one record at a time, each through review, apply, and verify.

Keep the consistency table in a workspace note if the user wants it kept; otherwise it lives only in the conversation.

## Approval gates

- **Request.** Create an Approval To-Do on the record (`task_type: approval`), assigned to the approver the user names. Name: `Approve specification: APP-12 sha256:687d102450bc3522`. Description: the gate, the fields and requirements covered, the fingerprint, and "Any change to this content voids this approval."
- **Check.** The gate passes when the approval is complete and `aha_feature.py fingerprint` on a fresh read returns the same fingerprint.
- **Void.** When the content changes, add a comment to the old approval ("Void: the specification changed to sha256:...") and request a new one. Never edit the old approval's fingerprint.
- **Separation of duties.** The person who wrote or steered the change doesn't approve it when the workspace's policy says so; ask the user who approves.
- **Status.** After approval, propose the next status and change it only when the user agrees.
