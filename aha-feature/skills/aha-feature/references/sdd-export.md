# SDD Export

Export an Aha! specification to Spec Kit, OpenSpec, or Kiro, so a coding agent can build from it. Two rules govern every export:

1. **On demand only.** Export when the user asks, never as a side effect of elaborating or approving.
2. **Into a git repository.** The script refuses a directory outside a git work tree, never overwrites without `--force`, and never commits. The user reviews and commits.

Aha! stays the system of record. Each exported file starts with a provenance comment naming the Aha! record, the export date, and the content fingerprint; to change a requirement, change it in Aha! and export again.

## Contents

- [Before you export](#before-you-export)
- [Commands](#commands)
- [What each tool receives](#what-each-tool-receives)
- [After you export](#after-you-export)

## Before you export

1. Ask which tool and which repository; confirm the folder name (slug) and, for OpenSpec, the change ID and capability path.
2. Read the record and build the bundle (`aha_feature.py bundle`), or use the bundle you just applied and verified.
3. Run `lint --gate ready`. If it reports errors, tell the user; export only if they accept a draft. The script warns when the source has ready-gate errors.
4. Check the approval: the Approval To-Do for the current fingerprint should be complete. Say so if it isn't.
5. Preview with `--dry-run` and show the user the files.

## Commands

```bash
$AF export "$WORK/APP-12.md" --format speckit  --repo ~/src/app            # specs/NNN-<slug>/spec.md
$AF export "$WORK/APP-12.md" --format openspec --repo ~/src/app            # openspec/changes/add-<slug>/...
$AF export "$WORK/APP-12.md" --format kiro     --repo ~/src/app            # .kiro/specs/<slug>/requirements.md
```

| Option | Meaning |
| --- | --- |
| `--dry-run` | Print the files; write nothing |
| `--force` | Overwrite files that exist |
| `--slug` | Folder name; defaults to the feature name in kebab case |
| `--number` | Spec Kit feature number; defaults to the next free one under `specs/` |
| `--change-id`, `--capability` | OpenSpec change folder and capability path; default `add-<slug>` and `<slug>` |
| `--existing-capability` | OpenSpec: the capability exists in `openspec/specs/`, so the delta omits Purpose |
| `--date` | Export date for the provenance line; defaults to today |

The source can also be a `read_records` JSON dump.

## What each tool receives

The export carries requirements (the WHAT). Design and task files (the HOW and HOW MUCH) are left to the tool's own workflow in the repository, where engineers own them.

### Spec Kit: `specs/NNN-<slug>/spec.md`

| Spec Kit section | From Aha! |
| --- | --- |
| Header: branch, created, status, input | `NNN-<slug>`, the export date, Draft, the record and its URL |
| User Scenarios & Testing: one user story per use case | UC-n text as a user story; priority P0, P1, P2 maps to Spec Kit's P1, P2, P3; acceptance scenarios from the criteria that verify the requirements covering that use case |
| Edge Cases | The definition table's stop-conditions row |
| Functional and Non-Functional Requirements | Every FR and NFR statement, IDs unchanged, with priority and Aha! requirement |
| Success Criteria: Measurable Outcomes | Definition of Done bullets as SC-001, SC-002, ... |
| Assumptions, Out of Scope | Dependencies (upstream); the Out of scope row |
| Traceability; Confirm before building | Statement to requirement, use case, and criterion; the restate-first instruction |

Gaps appear as `[NEEDS CLARIFICATION: ...]`, Spec Kit's own marker.

### OpenSpec: `openspec/changes/<change-id>/`

| File | From Aha! |
| --- | --- |
| `.openspec.yaml` | `schema: spec-driven`, the date, and `x-aha-record`, `x-aha-url`, `x-aha-fingerprint` |
| `proposal.md` | Why: Business Problem. What Changes: one bullet per requirement record, with its statement IDs; **BREAKING** if it removes behavior. Capabilities: the capability and its purpose. Impact: the Aha! record and dependencies. Then traceability and the restate-first instruction. |
| `specs/<capability>/spec.md` | `## Purpose` for a new capability (from the user story). One `### Requirement: <ID> <record name>` per statement, grouped under ADDED, MODIFIED, or REMOVED by its change marker. Each requirement gets a `#### Scenario:` derived from its EARS clauses and one per acceptance criterion that verifies it. REMOVED requirements carry **Reason** and **Migration**. |

OpenSpec's validator wants one behavior per requirement, descriptions of 500 characters or fewer, and at least one scenario each; the export warns about anything that breaks these. MODIFIED requirements must match the existing headers in `openspec/specs/`: use `--existing-capability` and adjust the headers if needed. Continue in OpenSpec to generate the design and tasks.

### Kiro: `.kiro/specs/<slug>/requirements.md`

| Kiro section | From Aha! |
| --- | --- |
| Introduction | Summary, the source record, and the Out of scope items |
| `### Requirement n: <record name>` | One per Aha! requirement record |
| User Story | The feature's persona and outcome, focused on the use case the record covers |
| Acceptance Criteria | The record's EARS statements, numbered, with ID and priority |
| Acceptance Scenarios | The Given/When/Then criteria that verify the record |
| Traceability; Confirm before building | As above |

Kiro generates `design.md` and `tasks.md` from this file in its own workflow.

## After you export

- Show the user the paths and suggest the commit; don't commit.
- If the user wants Aha! to record the export, add a comment to the record with the repository, the paths, the fingerprint, and the commit once it exists.
- When requirements change, update Aha! first, void the approval, re-approve, and export again with `--force`. Don't edit the exported requirements in the repository; the next export would overwrite them.
- Keep repository-wide rules (commands, conventions, permanent boundaries) in the repository's AGENTS.md, not in the feature specification.
