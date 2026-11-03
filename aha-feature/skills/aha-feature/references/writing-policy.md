# Writing Policy

How text in an Aha! specification reads. The test, adapted from spec-driven development practice: someone with none of your context reads the record and builds the right thing without asking a question. Lint enforces the mechanical parts (rule IDs in parentheses).

## Contents

- [Plain language](#plain-language)
- [Text policy](#text-policy)
- [Claims and evidence](#claims-and-evidence)
- [Markers](#markers)
- [Word lists](#word-lists)
- [Before and after](#before-and-after)

## Plain language

- Short sentences, active voice, present tense. One idea per sentence.
- One name per concept, used everywhere. Define an acronym on first use in each field.
- Say what happens, not what is "supported" or "enabled": "The agent drafts one note per change," not "The agent supports note drafting."
- Write numbers with units: "within 2 minutes", "at most 500 changed lines".
- Contractions are fine: can't, doesn't, isn't.
- Each field stands alone. Don't write "as above"; cite the field, ID, or record instead.

## Text policy

| Rule | Meaning |
| --- | --- |
| Name records, not releases, dates, or status (WRT002) | The Release field and links carry timing and status. Write "APP-3", not "APP-3, shipping in the spring release". Release names in text also go stale when plans move. |
| Use relational timing | "Needed before this feature's release", not a date. Exceptions: due dates on decision To-Dos and goal dates on goals. Lint allows a date right after a decision reference, such as "SD-18 (due 6 Nov 2026)". |
| Keep rationale, drop release history | Delete paragraphs that only record when plans moved. Keep the reasons for decisions. |
| Priority is relative | Don't state commitment levels ("committed for wave 1"). Autonomy or permission tiers that are defined terms are fine. |
| Keep confidence the links don't carry | "Not yet confirmed as funded" stays, because the linked record doesn't say it. |
| No placeholders (WRT004) | Every `{{...}}` from the template is replaced before writing. |

## Claims and evidence

- **Measured, gated claims only (WRT001).** State what the feature does and the result to measure, not adjectives. "At least 20% less effort per accepted change, against matched control work" instead of "drastically cuts effort".
- **Baselines first (STR008).** A target needs today's measure. When none exists, Business Problem says "Not yet measured:" and lists what to capture.
- **Facts versus inference.** A fact cites its source: a record, a customer request, a document. An inference is labeled as one: "likely", "inferred from", or an open question.
- **Standards cite their edition**, such as ISO/IEC/IEEE 29148:2018. Treat inactive standards as guidance, not as the governing standard.
- **People keep authority.** Say which approvals stay with people; don't describe automation as unsupervised.

## Markers

| Marker | Use | Gate |
| --- | --- | --- |
| (to confirm) | A value or fact the user hasn't confirmed | Info at seed and elaborated; error at ready (WRT003) |
| (target to confirm) | A numeric target awaiting a baseline | Same |
| `(OQ-n)` | Ties text to its open-question To-Do | Stays; the To-Do tracks it |
| `SD-n` | Cites a shared decision on the initiative | Stays |
| TBD, TBC, ?? | Avoid; use "(to confirm)" plus an open question | Same as "(to confirm)" |

Every "(to confirm)" needs an open-question To-Do or a shared decision that will resolve it.

## Word lists

Lint matches these as whole words. Terms the record defines as tier or level names, written `T<n> <Name>` (such as "T3 Autonomous"), are exempt everywhere in that record; list other defined terms in the bundle's `defined-terms` front matter.

**Overclaims (WRT001), in any field:** autonomous, autonomously, seamless, seamlessly, eliminate, eliminates, instant, instantly, instantaneous, drastically, dramatically, revolutionary, revolutionize, game-changing, effortless, effortlessly, zero-touch, fully automated, guarantee, guarantees, guaranteed, best-in-class, world-class, cutting-edge, unparalleled, unmatched, magically.

**Vague terms (EARS008 in statements, AC004 in criteria):** fast, quick, quickly, slow, user-friendly, easy, easily, intuitive, simple, simply, robust, efficient, efficiently, appropriate, appropriately, adequate, adequately, reasonable, reasonably, gracefully, flexible, sufficient, sufficiently, optimal, optimally, as needed, as appropriate, if possible, where possible, as soon as possible, etc, and so on, and/or, various, normally, usually, typically, scalable.

**Weak verbs in statements (EARS002):** should, may, might, could, will, must, can. Use SHALL.

## Before and after

| Before | After |
| --- | --- |
| The system should be fast. | WHEN a list holds up to 1,000 items, the service SHALL return it within 500 ms at p95. |
| Handle errors gracefully. | IF the provider times out, THEN the agent SHALL retry 3 times with exponential backoff and then queue the item for review. |
| Seamlessly eliminates manual triage. | Triage arrives with evidence attached. Pilot target: at least 30% less time to first response (to confirm). |
| Shipping in Q3 with APP-3. | Depends on APP-3. |
| Validate the title appropriately. | An examples table: empty, 1 character, 501 characters, whitespace only, each with its exact message. |
