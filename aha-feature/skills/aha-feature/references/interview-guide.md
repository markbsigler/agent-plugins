# Interview Guide: Elicit Before Writing

Use this guide in step 2 of the elicit-before-writing loop. The goal is to close the gaps the [elicitation matrix](../SKILL.md#elicitation-matrix) found without tiring the user and without guessing.

## Contents

- [The round](#the-round)
- [Choosing the questions](#choosing-the-questions)
- [Recording answers and deferrals](#recording-answers-and-deferrals)
- [Example round](#example-round)
- [Question bank by dimension](#question-bank-by-dimension)
- [Where answers go in Aha!](#where-answers-go-in-aha)

## The round

1. **Score first.** For an existing record, run `aha_feature.py matrix`. For a new request, score the user's words against the five dimensions yourself.
2. **Acknowledge.** In one or two sentences, restate what you already know, in the user's words.
3. **Interview.** Ask 2 or 3 specific, open-ended questions. Never more than 3 in a round.
4. **Wait.** Stop. Don't draft feature text while questions are open.
5. **Record and re-score.** Write each answer and its source into the bundle's `# Elicitation` section, then score again. Start another round only for what is still missing.

Stop when every dimension is answered or deferred, and goal alignment is linked or confirmed unlinked.

### With the `ask_user` tool

- The **message** is the acknowledgment: what you have, and which gaps this round closes.
- Each **question is a free-text field**. Its title is the question. Its description says why it matters and which Aha! field the answer fills.
- **Don't prefill answers** or offer a default for a gap: that is an assumption in disguise. Offer choices only to confirm a proposal the user already made.
- A form has 2 or 3 fields, never more.

Without `ask_user`, print the same block and stop:

```markdown
**What I have:** A Release Notes Agent that drafts notes from merged changes for release managers.

**To close the gaps:**
1. What must the agent never do with a draft, and what should happen when a change has no linked feature?
2. What do you measure today, and what result would make the pilot a success?
3. Which initiative or goal should this support, or should it stay unlinked?
```

## Choosing the questions

- **Blocking gaps first.** Value & Persona, then Scope & Boundaries, shape every other answer. Ask about them before Tech & Data or Success Metrics.
- **Group related dimensions.** One question can close two gaps: "What should happen when the publishing service is down, and who needs to know?" covers Edge Cases and Scope.
- **Open-ended, specific, about one thing.** "What happens when two release managers edit the same draft?" beats "Any concurrency concerns?" and "Is it fast?"
- **Ask about the hard parts.** People and agents both describe the happy path. Ask about failures, limits, deletion and cancellation, concurrent changes, permissions, time zones, and what must never change.
- **Don't ask what the record already says.** Quote it instead and ask only about what conflicts or is missing. When the record states a behavior in prose, convert it to EARS; that's drafting, not a question.
- **Conflicts are the best questions.** A callout that contradicts a criterion, a handoff the receiving record doesn't accept, or a tier the initiative defers: quote both sides and ask which holds.
- **Ask goal alignment in the first round** when the record has no initiative, goal, or key result.
- **Stay in scope.** Ask only about the record the user asked about. Don't open questions about neighboring features unless an answer depends on them.

## Recording answers and deferrals

Every answer goes into the bundle's `# Elicitation` table with its source: the user's name or "the user", the date, or the record it came from. Then it goes into the fields the [table below](#where-answers-go-in-aha) names.

A **deferral** is an answer too: the user says it isn't known yet, or someone else must decide. Record it:

- As an open-question To-Do on the record. Name it with the action that resolves it ("Confirm the entry limit"); its description gives the decision needed, the options, a recommendation if the user gave one, the owner, and the tag `(OQ-n)`.
- As a "(to confirm)" marker where the text depends on it. The ready gate fails while markers remain.

Never turn a deferral into a guess. A missing answer is a recorded question, not a default.

After the record is written, post the Elicitation section as a comment on the record, so the reasons for each decision stay in Aha!.

## Example round

The user asks: "Create a feature for an agent that drafts our release notes."

The matrix finds Value & Persona partial (a persona is implied but not named), and Scope, Tech & Data, Edge Cases, and Success Metrics missing. The workspace has no initiative linked.

Round 1 (Value & Persona, Scope, goal alignment):

- Message: "I have: an agent that drafts release notes. I don't yet have who it's for, where its job ends, or which goal it supports."
- Who prepares release notes today, how long does it take, and what goes wrong?
- Walk me through a release: what should start the agent, what should it produce, and where should a person decide?
- Which initiative or goal should this support, or should it stay unlinked?

Round 2 (Edge Cases, Tech & Data):

- What should happen when a merged change has no linked feature, or a release has hundreds of changes?
- Which systems does the agent read and write, and what data must never leave them?

Round 3 (Success Metrics), if still open:

- What do you measure today about release notes, and what result in a pilot would make this worth it?

## Question bank by dimension

### 1. Value & Persona

- Who does this work today, how often, and what does it cost them?
- Who else is affected: approvers, administrators, auditors, customers?
- Why now: which customer requests, deals, or strategy decisions drive it? Which Aha! records show the evidence?
- What do people do instead today, and why isn't that enough?

### 2. Scope & Boundaries

- Walk me through the work from what starts it to the result. Where does a person decide or approve?
- What must it never do? What must always stay with a person?
- Which neighboring features or teams own the adjacent work?
- What can wait for a later release (P1 or P2)?

### 3. Tech & Data

- Which systems does it read and write, and through which interfaces?
- Which data is sensitive, and where may it go: logs, models, vendor tools?
- What must another record or team deliver first? What depends on this one?
- How many items, how often, and how large?

### 4. Edge Cases

- What happens when input is missing, invalid, duplicated, or too large? What exact message or behavior?
- What happens when a dependency is down, slow, or returns an error? How many retries, and who is told?
- What happens when two people or agents act on the same item at once?
- What happens on cancellation, deletion, or restart midway? What state remains?
- Who may see, start, approve, or override it?

### 5. Success Metrics

- What does "done" mean for this release: which acceptance criteria and gates?
- What is measured today? If nothing, what will you capture first?
- What target makes this worth it, against which baseline, measured how?
- Which goal or key result does it move?

### Goal alignment

- Which initiative, goal, or key result should this support? If none, should it stay unlinked, and why?

## Where answers go in Aha!

| Answer | Field or record |
| --- | --- |
| Who benefits, and their goal | Description: the user story |
| Today's process, its cost, the evidence | Business Problem |
| Unmeasured baselines | Business Problem: "Not yet measured: ..." |
| The benefit and its target | Business Value |
| Steps and approval points | Description: workflow |
| What it reads, writes, and decides | Description: definition table |
| What it won't do, and who does | Description: Out of scope row |
| Behaviors and rules | Requirements: EARS statements |
| Failure modes, validation, limits | Acceptance Criteria, IF/THEN statements, the stop-conditions row |
| Systems and records it needs, or that need it | Dependencies (upstream) and (downstream), Depends on links |
| Volumes, latency, security, privacy | Requirements: NFR statements |
| Done, gates, measured outcomes | Description: Definition of Done; Business Value |
| Initiative, goals, key results | The record's Initiative, Goals, and Key results fields |
| Unknowns and decisions for later | Open-question To-Dos; "(to confirm)" markers |
