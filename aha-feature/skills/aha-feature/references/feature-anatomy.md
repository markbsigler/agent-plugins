# Feature Anatomy

What each part of an Aha! feature holds in this skill's house style, and how the parts fit. Field names follow a common Aha! configuration; when a workspace names a field differently, map it with `fields_metadata` and keep the content rules.

## Contents

- [Record settings](#record-settings)
- [Description](#description)
- [Definition-table profiles](#definition-table-profiles)
- [The seed draft role](#the-seed-draft-role)
- [Summary, problem, and value](#summary-problem-and-value)
- [Use cases and acceptance criteria](#use-cases-and-acceptance-criteria)
- [Dependencies, differentiation, and risks](#dependencies-differentiation-and-risks)
- [Requirements](#requirements)
- [To-Dos, notes, and links](#to-dos-notes-and-links)

## Record settings

| Setting | Rule |
| --- | --- |
| Name | A noun phrase for the capability or role: "Release Notes Agent", "Invoice Export". No verbs, dates, or releases. |
| Type | The workspace's types, such as New, Improved, or Enabling Capability. Enabling capabilities usually use the platform profile. |
| Release | Carries timing. Text never repeats it. |
| Status | Changes only with the user's agreement; see the gates in [quality-gates.md](quality-gates.md#gates). |
| Initiative, epic, goals, key results | Set from the user's answers. If none applies, the user confirms it stays unlinked. |
| Tags | Categories the workspace already uses, such as capability tags. Don't invent new tag schemes. |
| Assignee | The owner. If none, raise "Assign an owner" as an open question. |
| Priority | Relative importance only. Text never states a commitment level. |

## Description

The Description reads top to bottom as the feature's contract. Use these parts, in this order:

1. **Callouts (optional).** A note callout for scope ("**Scope:** ...") or a dependency on another record ("**Verification:** delivers specifications only until APP-3 exists"). Keep each to one or two sentences.
2. **User story.** `**As a** <persona>, **I want** <capability>, **so that** <outcome>.` One persona, one capability, one outcome. Name a second persona with "and as" only if both truly share the story.
3. **Definition table.** A heading such as "### Agent Definition" and a two-column table with the header `| Element | Definition |`. The profile sets the rows. Add domain rows when the feature makes a choice of its own, such as "Specification method" or "Test types". In a multi-paragraph cell, separate paragraphs with `<br>`.
4. **Workflow.** A numbered list from trigger to result. Mark each point where a person decides: "A person approves the plan." Add a short "Two ways to work" paragraph when the feature runs both from a tracker and from a person's session.
5. **Definition of Done.** Bullets: "AC-1 to AC-n pass." first, then measured gates such as pilot results, compatibility, or a review. The range must match the Acceptance Criteria field. A draft role may use "Exit criteria" instead; lint and the matrix also accept "Success criteria" and "Done when" as the heading.

## Definition-table profiles

Pick the profile in the bundle's front matter. `lint` checks the rows; `matrix` uses them to judge scope and data.

### Agent

For a feature that acts on its own within limits.

| Row | Say |
| --- | --- |
| Role | The one bounded job, and what it can never do (approve its own work, write to production) |
| Triggers | What starts work, each with a priority: a tracker rule (P0), a person's session (P1), another agent's work item (P2) |
| Context | What it reads to decide, with record links |
| Read actions | Systems and data it reads |
| Write actions | Everything it can change, and where |
| Autonomy | What runs without approval, what needs a person, what never happens |
| Guardrails | Rules it always follows, with numeric limits |
| Stops and escalates when | Each stop condition, and what the escalation contains |
| Outputs | Artifacts and evidence it produces |
| Handoffs | What goes to which sibling record or person |
| Out of scope | At least three things it won't do, each with the record that owns it |

### Platform

For an enabling capability that other features build on.

| Row | Say |
| --- | --- |
| Role | What it provides, and to whom |
| Consumers | The features and teams that use it, with record links |
| Capabilities | Each capability, phased if needed (Core, Next) |
| Guardrails | Rules every consumer gets, such as approval binding or audit |
| Out of scope | What consumers must build themselves |

Useful extra rows: what the team owns versus reuses, and the decisions it applies (`SD-n`).

### Product

For a user-facing feature.

| Row | Say |
| --- | --- |
| Users | Personas and their goals |
| Entry points | Where users start: pages, commands, APIs, events |
| Behavior | What the feature does, step by step |
| Permissions | Who may see, change, approve, or override |
| Out of scope | At least three things it won't do |

Useful extra rows: Data (what is stored, for how long), Integrations, Constraints.

## The seed draft role

A new feature starts with only a Description:

- The user story.
- The definition table under a heading ending in "(Draft)", with at least Role and Out of scope (Users and Out of scope for a product), and any rows the user already answered.
- A final row or paragraph, **Status**: "Draft role to begin elaboration", followed by numbered open questions.

Other fields, requirements, and links wait for elaboration.

## Summary, problem, and value

| Field | Holds | Rules |
| --- | --- | --- |
| Summary | One paragraph of 1,200 characters or fewer | The problem today, what the feature does, how it differs, and what stays with people. Bold the feature's name once. |
| Business Problem | How the work happens today, what goes wrong, and the evidence | Link customer records and requests. End with "Not yet measured:" and the baselines that targets need. |
| Business Value | Each benefit as a bold lead-in, then what changes and its target | Every target names its baseline or method, such as a pilot against matched control work. Mark unconfirmed targets "(to confirm)". |

## Use cases and acceptance criteria

**Use Case(s)** is a table: `| ID | Use case | Priority |`. Each use case is a verb phrase for a job the user does (UC-1, UC-2, ...) with a priority: P0 for the first release, P1 for the next increment, P2 for later. Add the dependency in the priority cell when a priority depends on another record.

**Acceptance Criteria** holds one heading per criterion and three clauses:

```markdown
### AC-2. Approval before publishing

- **Given** a draft,
- **When** a person approves it,
- **Then** the notes move to the publishing pipeline, and an unapproved draft never does.
```

Cover more than the main path. A complete set usually includes:

- each main job (one per P0 use case),
- validation and failure (what is rejected, the exact message, and that nothing changes),
- limits and escalation (what stops the work and who is told),
- administration (only an administrator changes policy; every change is audited),
- data protection (what may reach a model or vendor tool),
- audit (every read, decision, and change traceable to identity and time),
- deployment or compatibility when the feature runs in several environments.

Mark unconfirmed numbers "(target to confirm)".

## Dependencies, differentiation, and risks

| Field | Holds |
| --- | --- |
| Dependencies (upstream) | One bullet per provider: the record or product, what this feature needs from it, and whether that is confirmed. Add a `Depends on` link for each hard dependency. |
| Dependencies (downstream) | One bullet per consumer and what it receives. |
| Differentiator and justification | Why it is better than alternatives, with named comparisons and no superlatives. Set only from the user's answers. |
| Other important information | Risks as a table (Risk, Likelihood, Impact, Mitigation) and assumptions. |
| Marketing fields | Customer value, market characteristic, and similar: only from the user's answers. |

## Requirements

Requirements are child records of the feature, each a cluster of related behaviors (see [ears-and-traceability.md](ears-and-traceability.md)):

- Name each for its capability: "Intake and triage", "Approval and audit".
- Put cross-cutting concerns in their own records: deployment and compatibility first, then the capability clusters, and "Security, audit, and limits" last.
- Each record holds a scope sentence, EARS statements with IDs and priorities, examples tables where rules have cases, and the trace line `Covers: UC-n. Verified by AC-n.`
- Statement IDs run across the feature (FR-1 to FR-n), not per record.

## To-Dos, notes, and links

- **Open questions** are To-Dos on the feature; **shared decisions** are `SD-n:` To-Dos on the initiative; **approvals** are Approval To-Dos. See the [conventions](aha-mcp-playbook.md#to-do-conventions).
- **Research** that doesn't fit a field (personas, journeys, interview notes, market scans) goes in a workspace note linked to the feature with `Has research in`. If the workspace keeps research notes under a parent such as "Research", name the note `<REF> - <Name>`.
- **Links:** `Depends on` for hard dependencies delivered first, `Relates to` for siblings and every record the text names.
