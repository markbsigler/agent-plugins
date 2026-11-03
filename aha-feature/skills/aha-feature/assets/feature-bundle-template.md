---
record: {{APP-12, or new}}
name: {{Name: a role or capability, such as Release Notes Agent}}
workspace: {{Workspace prefix, such as APP}}
aha-domain: {{yourcompany.aha.io}}
profile: agent
link-prefixes: {{Prefixes to turn into record mentions, such as APP, PLAT}}
initiative: {{APP-S-1 Initiative name, or leave empty}}
goals: {{APP-G-1 Goal name, or leave empty}}
key-results: {{APP-G-1-KR-1 Key result, or leave empty}}
---

This is the standard output template for the aha-feature skill. Lines before the first
"# Field:" heading are notes and aren't written to Aha!.

- Fill every {{placeholder}}. `aha_feature.py lint` fails while any remain, and
  `aha_feature.py matrix` counts a dimension as answered only when its text has none.
- Keep the profile that fits: agent (this table), platform (Role, Consumers, Capabilities,
  Guardrails, Out of scope), or product (Users, Entry points, Behavior, Permissions,
  Out of scope). See references/feature-anatomy.md.
- Write the Elicitation section first, from the user's answers. Draft fields only after all
  five dimensions are answered or deferred.
- Delete any field the workspace doesn't have, and move its content to the Description or
  the research note.

# Elicitation

Working record of the elicit-before-writing loop. Not written to a field: after applying,
post it as a comment on the record.

| # | Dimension | Status | Answers and sources | Aha! fields |
|---|---|---|---|---|
| 1 | Value & Persona | {{answered, deferred, or missing}} | {{Who benefits and why it matters; who said so}} | Description, Business Problem, Business Value, Summary |
| 2 | Scope & Boundaries | {{status}} | {{Workflow, boundaries, and what is out of scope}} | Description, Requirements |
| 3 | Tech & Data | {{status}} | {{Data, integrations, and downstream impact}} | Dependencies, Requirements |
| 4 | Edge Cases | {{status}} | {{Failure modes, validation errors, and limits}} | Acceptance Criteria, Requirements |
| 5 | Success Metrics | {{status}} | {{Definition of done and measured outcomes}} | Description, Business Value, Goals |
| - | Goal alignment | {{linked, or confirmed unlinked}} | {{Initiative, goals, and key results}} | Initiative, Goals, Key results |

Deferred answers (each becomes an open-question To-Do below):

- {{OQ-1: the question, who will answer it, and when it's needed}}

# Field: Summary

{{One paragraph, 1,200 characters or fewer: how the work happens today and what goes wrong, what this feature does, how it does it differently, and what stays with people.}}

# Field: Description

> [!NOTE]
> **Scope:** {{One sentence: what this record covers, and which records own the neighboring work.}}

**As a** {{persona}}, **I want** {{capability}}, **so that** {{outcome}}.

### Agent Definition

| Element | Definition |
|---|---|
| Role | {{The one bounded job, and what it can never do, such as approve its own work.}} |
| Triggers | {{What starts the work, each with a priority, such as a tracker rule (P0).}} |
| Context | {{What it reads to decide, with record links.}} |
| Read actions | {{Systems and data it reads.}} |
| Write actions | {{Everything it can change, and where.}} |
| Autonomy | {{What runs without approval, what needs a person, and what never happens.}} |
| Guardrails | {{Rules it always follows and limits with numbers, such as at most 500 changed lines.}} |
| Stops and escalates when | {{Each condition that stops the work.}}<br>{{Who receives the escalation, and what it contains.}} |
| Outputs | {{Artifacts and evidence it produces.}} |
| Handoffs | {{What goes to which sibling record or person.}} |
| Out of scope | {{At least three things it won't do, each with the record that owns it.}} |

### Workflow

1. {{First step.}}
2. {{Next step, with the gate marked, such as: A person approves the plan.}}
3. {{Last step.}}

### Definition of Done

- AC-1 to AC-{{n}} pass.
- {{A measured gate, such as: 10 pilot releases with at least 90% of notes accepted without edits.}}

# Field: Business Problem

{{How the work is done today, what goes wrong, and the evidence, with links to customer records.}}

Not yet measured: {{the baselines to capture before targets are final}}.

# Field: Business Value

**{{Benefit}}:** {{What changes for the customer, with a target against a baseline, such as at least 20% less effort per change.}}

# Field: Use Case(s)

| ID | Use case | Priority |
|---|---|---|
| UC-1 | {{The main job, as a verb phrase}} | P0 |
| UC-2 | {{Another job}} | {{P1}} |

# Field: Acceptance Criteria

### AC-1. {{Main path}}

- **Given** {{the starting state}},
- **When** {{the action}},
- **Then** {{the observable result, with exact values or messages}}.

### AC-2. {{Failure or validation}}

- **Given** {{an invalid input or a failure}},
- **When** {{the action}},
- **Then** {{the exact rejection, message, or escalation, and that nothing changes}}.

### AC-3. {{Audit and limits}}

- **Given** {{any run}},
- **When** {{it is audited, or reaches a limit}},
- **Then** {{what is recorded, or how it stops}}.

# Field: Dependencies (upstream)

- {{Record or product it needs}}: {{what it needs from it, and whether that is confirmed}}.

# Field: Dependencies (downstream)

- {{Record or team that relies on this}}: {{what it receives}}.

# Field: Other important information

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| {{Risk}} | {{Low, Medium, or High}} | {{Low, Medium, or High}} | {{Mitigation}} |

# Requirement: new {{Capability name}}

{{One sentence of scope for this group of behaviors.}}

- **FR-1 (P0):** WHEN {{trigger}}, the {{system}} SHALL {{response}}.
- **FR-2 (P0):** The {{system}} SHALL {{always-true behavior}}.
- **FR-3 (P0):** IF {{unwanted condition}}, THEN the {{system}} SHALL {{mitigation}}.
- **NFR-1 (P1):** WHEN {{load condition}}, the {{system}} SHALL {{respond within a measured limit}}.

| Input | Expected result |
|---|---|
| {{Example input}} | {{Exact result or message}} |

Covers: UC-1. Verified by AC-1, AC-2.

# Requirement: new Security, audit, and limits

- **NFR-2 (P0):** The {{system}} SHALL {{act under a named identity with least privilege}}.
- **NFR-3 (P0):** The {{system}} SHALL {{record every read, decision, and change with identity and time}}.
- **NFR-4 (P1):** IF {{a configured limit is reached}}, THEN the {{system}} SHALL {{stop and report the reason}}.

Covers: UC-2. Verified by AC-3.

# To-Do: {{An action that resolves the open question, such as Confirm the size limit}}

{{The decision needed, the options, the recommendation, and the owner.}} (OQ-1)
