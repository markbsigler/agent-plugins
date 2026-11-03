---
name: aha-feature
description: Use this skill whenever the user wants to create, draft, write a spec for, refine, elaborate, review, lint, align, approve, or export an Aha! feature, epic, or requirement - even if they just say "turn this idea into requirements" or paste an Aha! reference like APP-123. It elicits before writing (asks 2-3 targeted questions per round until value, scope, tech and data, edge cases, and success metrics are clear), then writes EARS requirements with acceptance criteria and traceability through the Aha! MCP server, and on request exports Spec Kit, OpenSpec, or Kiro specs to a git repository.
license: MIT
compatibility: Requires the Aha! MCP server. Scripts need Python 3.11+ (standard library only; run with uv or python3). Export needs git.
metadata:
  author: markbsigler
  version: "1.0"
---

# Aha! Feature Specifications

Turn an Aha! feature into a specification that someone with none of your context could build the right thing from: who it's for and why, what it does and won't do, EARS requirements with stable IDs, acceptance criteria that cover failures, and a definition of done with measured targets. Elicit before you write; Aha! holds the result.

## Operating rules

1. **Elicit before writing.** Score every request against the [elicitation matrix](#elicitation-matrix) first. If any dimension is missing or vague, stop drafting and ask.
2. **Never assume or invent.** Don't fill a gap with a plausible guess. Ask. If the user defers an answer, record it as an open-question To-Do or a "(to confirm)" marker, never as fact. Keep what a source says apart from what you infer.
3. **Prevent interview fatigue.** Ask at most 2 or 3 targeted, open-ended questions per round, grouping related dimensions. Acknowledge what you already know before you ask.
4. **Preserve intent.** Work within the user's request and workflow. Don't propose restructuring or refactoring outside what they asked for; note a blocking problem elsewhere in one line at most.
5. **Align to strategy.** If the feature has no initiative, goal, or key result, ask the user to name one or to confirm that it stays unlinked.
6. **Aha! is the system of record.** Every artifact lands in the record's fields, requirements, To-Dos, comments, record links, or a workspace note. Use the local file system only for temporary working files in one temporary directory, and delete it when you finish.
7. **SDD artifacts are on demand and live in git.** Create Spec Kit, OpenSpec, or Kiro files only when the user asks, only inside a git repository, and never commit for the user.
8. **Read before you write.** Discover fields with `fields_metadata` for each workspace and record type. Never guess a field ID or an option value; select fields take option IDs.
9. **Write nothing without approval** of the exact content: show the rendered preview and the write plan, then wait for a yes.
10. **One record, one call, at a time.** Aha! throttles parallel calls. Re-read and verify each record after you write it.
11. **EARS everywhere, IDs forever.** Every behavior is an EARS statement with an FR or NFR ID and a priority. IDs are never renumbered or reused.
12. **Approvals bind to a version.** An approval names the content fingerprint; any change to the specification voids it.

## Elicitation matrix

Evaluate every incoming request, and every existing record, against these five dimensions. A dimension is answered when the user has supplied it or explicitly deferred it.

| Dimension | Missing when | Aha! fields that hold the answer |
| --- | --- | --- |
| 1. Value & Persona | No one named who benefits, or no reason it matters strategically | Description (user story), Business Problem, Business Value, Summary |
| 2. Scope & Boundaries | Vague behavior, missing workflow steps, or nothing out of scope | Description (definition table, workflow, out of scope), Requirements |
| 3. Tech & Data | Unclear data, integrations, or downstream impact | Dependencies (upstream and downstream), definition rows for context and data, NFR statements, custom fields |
| 4. Edge Cases | No failure modes, validation errors, limits, or constraints | Acceptance Criteria, IF/THEN statements, stop conditions |
| 5. Success Metrics | No definition of done or measured outcome | Definition of Done, Business Value targets, Goals and Key results |

Also check **goal alignment**: the record's initiative, goals, and key results (rule 5).

For an existing record, score it with the script, which names each gap and the field to fill:

```bash
$AF matrix "$WORK/APP-12.json"     # exit 1 while any dimension is partial or missing
```

For a new request, score the user's words yourself. Treat adjectives without numbers, "etc.", and "handle errors" as vague.

## The elicit-before-writing loop

This loop runs before any drafting in the Seed, Elaborate, and Refine modes.

**Step 1: Analyze and match.** Score the request (and the record, if there is one) against the matrix. List which dimensions are answered, partial, or missing. A gap that is only format, such as prose requirements that already state the behavior, is drafting work: convert it instead of asking. Ask only about missing information, conflicts between parts of the record, and conflicts with the initiative or sibling records.

**Step 2: Elicit, if anything is incomplete.** Stop generating feature text. Then:

1. **Acknowledge:** in one or two sentences, restate what you already know.
2. **Interview:** ask 2 or 3 specific, open-ended questions that close the most important gaps. Group related dimensions (for example, scope with edge cases). Put the goal-alignment question in the first round when the record isn't linked.
3. **Wait:** stop and wait for the answers.

Use `ask_user` with free-text fields: the acknowledgment is the message, each question is a field. Don't prefill answers. Without `ask_user`, print the block and stop. Repeat until all five dimensions are answered or deferred. [interview-guide.md](references/interview-guide.md) has the question bank.

**Step 3: Elaborate and format, once all five are answered.** Write the bundle from [assets/feature-bundle-template.md](assets/feature-bundle-template.md), the standard output template, and record each answer and its source in the bundle's `# Elicitation` section.

## Modes

| Mode | Use when | Result in Aha! |
| --- | --- | --- |
| Seed | A record is new or its Description is empty | A draft role: user story, a draft definition table, numbered open questions |
| Elaborate | A seed or a legacy record needs a full specification | All text fields, EARS requirements, open-question To-Dos, an approval request |
| Refine | One part changes | The changed fields or requirements; the old approval voided, a new one requested |
| Review | The user wants an assessment only | Findings in chat; a comment or note only if asked |
| Align | Several features share an initiative or hand work to each other | A consistency table, shared-decision To-Dos on the initiative, proposed edits |
| Approve | A gate needs a decision | An Approval To-Do bound to the fingerprint; a status change once the user agrees |
| Export | The user asks for SDD files | Spec Kit, OpenSpec, or Kiro files in a git repository |

**Epics** follow the same loop on the epic's own fields (run `fields_metadata` for `epic`). **A single requirement** is elaborated inside its parent feature, so its use case and acceptance criteria exist to trace to.

## Setup

The scripts live in `scripts/` next to this file and use only the Python standard library.

```bash
SKILL_DIR=<directory that contains this SKILL.md>
WORK=$(mktemp -d "${TMPDIR:-/tmp}/aha-feature-APP-12.XXXX")   # one per record, deleted at the end
AF="uv run $SKILL_DIR/scripts/aha_feature.py"                  # or: python3 $SKILL_DIR/scripts/aha_feature.py
```

When an MCP result is too large for the conversation, the client saves it to a file; pass that path to the scripts. Otherwise save the JSON into `$WORK`.

## Elaborate: the workflow

Each phase ends at a gate. Don't start a phase until the previous gate passes.

1. **Discover.** One call at a time ([aha-mcp-playbook.md](references/aha-mcp-playbook.md)): `fields_metadata` for `feature`, `requirement`, and `to_do`; the feature with `fields: detailed`, `include: ["requirement", "to_do"]`, and `text_field_format: "aha_editor_html"` (HTML keeps callouts the Markdown export drops); its initiative, epic, and goals; its siblings with `fields: minimal`; and the records its links name. Shared decisions are To-Dos named `SD-n:` on the initiative. Then `$AF bundle "$WORK/feature.json" -o "$WORK/APP-12.md"`.
2. **Analyze and match.** Run `$AF matrix` and `$AF lint --gate seed`, then `--gate elaborated`. Report a findings table (Priority, Finding, Recommendation, Where) limited to the user's request ([quality-gates.md](references/quality-gates.md)).
3. **Elicit.** Run the loop above until all five dimensions are answered or deferred.
4. **Elaborate and format.** Edit the bundle per [feature-anatomy.md](references/feature-anatomy.md) (profile `agent`, `platform`, or `product`), [ears-and-traceability.md](references/ears-and-traceability.md) (statements such as `- **FR-8 (P0):** WHEN <trigger>, the <system> SHALL <response>.` and a last line `Covers: UC-n. Verified by AC-n.`), and [writing-policy.md](references/writing-policy.md).
5. **Gate.** `$AF lint "$WORK/APP-12.md" --gate elaborated` reports 0 errors, `$AF matrix` reports five answered dimensions, and `$AF fingerprint` gives the version. Explain any warning you keep.
6. **Review with the user.** Show the key sections as Markdown, the lint and matrix summaries, the fingerprint, and the write plan: each record, each field, create or update. Warn when the record has attachments. Wait for explicit approval; after any edit, return to step 5.
7. **Apply.** Re-read and save `$WORK/before.json` (the session's rollback copy; Aha! record history is the lasting trail); if its fingerprint differs from the one you reviewed, someone edited the record: stop and merge. Render with `$AF render "$WORK/APP-12.md" --fields-metadata "$WORK/fields.json" --layout-from "$WORK/before.json" -o "$WORK/payload.json"`, so tables keep their column widths; report any layout warning. Write with `manage_record`, one call each: the changed text fields; each requirement (`update`, or `create` with the feature, name, and status); each new To-Do; Goals and Key results if the user named them; record links. Then add one comment: what changed, the fingerprint, the To-Dos created, and the elicitation record (the payload's `elicitation` text, with every round's answers; lint rule ELC001 flags a stale record).
8. **Verify.** Re-read with `aha_editor_html` into `$WORK/after.json` and run `$AF verify "$WORK/APP-12.md" "$WORK/after.json"`: every section OK, fingerprints equal, and the attachment count unchanged. Fix any mismatch with another write.
9. **Request approval.** Create an Approval To-Do on the record, assigned to the approver the user names: `Approve specification: APP-12 sha256:…`. Propose the next workflow status; change it only when the user agrees ([quality-gates.md](references/quality-gates.md#approval-gates)).
10. **Clean up.** Delete `$WORK`. Nothing else stays on disk.

## Other modes

- **Seed:** discover, run the loop for dimensions 1 and 2 plus goal alignment, and write only the Description as a draft role. Run `lint --gate seed`. Leave the other dimensions as numbered open questions.
- **Refine:** read with `aha_editor_html`, bundle, run the loop for the dimensions the change touches, change only what was asked, lint at the record's gate, and show a before-and-after. When the fingerprint changes, void the old approval in a comment and request a new one.
- **Review:** phases 1 and 2 only. Write nothing unless asked; if asked, post the findings as a comment or a note.
- **Align:** read the initiative and every sibling, compare them across the dimensions in [quality-gates.md](references/quality-gates.md#alignment-review), and record each cross-feature decision as an `SD-n:` To-Do on the initiative. Apply edits one record at a time through phases 6 to 8.
- **Export:** follow [sdd-export.md](references/sdd-export.md). Lint at the ready gate first; export a draft only if the user accepts that. Preview with `--dry-run`; the script never commits.

## Where content lives in Aha!

| Content | Aha! home |
| --- | --- |
| One-paragraph summary | Summary |
| Problem today, evidence, unmeasured baselines | Business Problem |
| Measured value claims and targets | Business Value |
| User story, definition table, workflow, Definition of Done | Description |
| Use cases (UC-n) with priorities | Use Case(s) |
| Acceptance criteria (AC-n, Given/When/Then) | Acceptance Criteria |
| EARS statements (FR-n, NFR-n) with their trace line | Requirements: child records of the feature |
| What it needs and what needs it | Dependencies (upstream) and (downstream), plus Depends on links |
| Strategy alignment and OKRs | Initiative, Goals, and Key results fields |
| Risks and assumptions | Other important information, or the research note |
| Open questions (OQ-n) and deferred answers | To-Dos on the record |
| Decisions shared across features (SD-n) | To-Dos on the initiative |
| Approvals | Approval To-Dos |
| Elicitation record and change history | Comments, plus Aha! record history |
| Research, personas, journeys, interview notes | A workspace note, linked with `Has research in` |
| Timing | The Release field and links, never the text |

If a workspace lacks one of these fields, use a section of the Description or the research note. Never fall back to local files.

## Scripts

| Command | What it does |
| --- | --- |
| `aha_feature.py bundle JSON -o MD` | Turn a `read_records` dump (Markdown or HTML fields) into an editable bundle |
| `aha_feature.py matrix SRC` | Score the five elicitation dimensions and goal alignment; exit 1 while any is incomplete |
| `aha_feature.py lint SRC --gate seed\|elaborated\|ready` | Check EARS, traceability, structure, and writing rules; `--list-rules`; `--format json` |
| `aha_feature.py render MD --fields-metadata JSON --layout-from JSON` | Produce Aha! Editor HTML for every field, requirement, and To-Do, with field IDs; keep the live tables' widths and classes |
| `aha_feature.py fingerprint SRC` | Hash the specification content; the same for a draft and its Aha! re-read |
| `aha_feature.py verify MD JSON` | Compare what you wrote with what Aha! returns |
| `aha_feature.py export SRC --format speckit\|openspec\|kiro --repo DIR` | On request only: write SDD files into a git repository |
| `aha_html.py to-html\|to-markdown` | Convert one snippet between Markdown and Aha! Editor HTML |

`SRC` is a bundle or a JSON dump. Exit codes: 0 success, 1 findings or gaps, 2 usage errors.

## Gotchas

- **Throttling and restarts.** The Aha! MCP connection throttles long write sequences, and a throttle is often followed by "Unknown tool" while the connection restarts. A throttled or "Unknown tool" call didn't run, so retrying it is safe, even for a create. Wait 5 seconds and retry once; if it fails again, wait 60 seconds, search for the tool again, and retry. Pace writes about 10 seconds apart, and never send Aha! calls in parallel.
- **Read HTML before you edit.** The default Markdown export drops callout boxes and some formatting. Read with `text_field_format: "aha_editor_html"`, as Aha! advises before updating a text field.
- **Attachments and column widths.** Feature updates through the API have dropped attachments. Check the attachment count before and after, and tell the user what to re-attach. Column widths survive when you render with `--layout-from`; a table whose header row changed loses them, and `render` says which.
- **One format per field.** A text field takes HTML or Markdown, never both. The renderer always emits HTML.
- **Placeholders.** `{{...}}` in the template must be replaced; lint fails on any that remain.
- **Bulk reads.** `analyze_records` can fail on many records; read them one at a time instead.

## References

- [aha-mcp-playbook.md](references/aha-mcp-playbook.md): tools, call recipes, field types, To-Dos, approvals, comments, links, resilience.
- [feature-anatomy.md](references/feature-anatomy.md): what each field holds, definition-table profiles, the seed draft role, To-Do conventions.
- [ears-and-traceability.md](references/ears-and-traceability.md): EARS patterns, statement format, IDs, priorities, change markers, the trace chain.
- [writing-policy.md](references/writing-policy.md): plain language, text policy, measured claims, markers.
- [quality-gates.md](references/quality-gates.md): gates, the lint rule catalog, the matrix scoring, review and alignment rubrics, approval gates.
- [interview-guide.md](references/interview-guide.md): the elicitation round format and question bank by dimension.
- [aha-editor-html.md](references/aha-editor-html.md): the Markdown subset the renderer supports and the HTML it produces.
- [sdd-export.md](references/sdd-export.md): on-demand export to Spec Kit, OpenSpec, and Kiro.
- [assets/feature-bundle-template.md](assets/feature-bundle-template.md): the standard output template, with the elicitation record.
