# Aha! MCP Playbook

How to read, write, and verify Aha! records with the Aha! MCP server. Tool names appear here without the client's prefix (your client may show `aha-mcp_read_records` or similar). When a tool isn't loaded, search for it first.

## Contents

- [Tools](#tools)
- [Discover](#discover)
- [Read a record for editing](#read-a-record-for-editing)
- [Field values](#field-values)
- [Create and update](#create-and-update)
- [Apply sequence](#apply-sequence)
- [To-Do conventions](#to-do-conventions)
- [Comments as the change log](#comments-as-the-change-log)
- [Resilience](#resilience)
- [Side effects to check](#side-effects-to-check)
- [Never](#never)

## Tools

| Tool | Use it to |
| --- | --- |
| `find_project` | Turn a workspace name into its prefix |
| `fields_metadata` | List a record type's fields: `field_id`, type, required, options, and text-format guidance |
| `field_options_metadata` | List options too long for `fields_metadata` (users, products, custom tables) |
| `read_records` | Read records by reference, or list a workspace's records of one type |
| `search_records` | Find records by meaning or keywords |
| `analyze_records` | Ask a question across several records; fails on large sets, so prefer `read_records` |
| `manage_record` | Create or update any record type, optionally with record links |
| `create_record_link` | Link two existing records |
| `add_comment` | Add a Markdown comment to a record |
| `read_attachments` | Read files attached to a record |
| `send_record_to_integration` | Send a record to Jira or another integration; only when the user asks |

## Discover

Run these one at a time. Save large results in the session's temporary directory.

1. **Workspace.** `find_project` with the workspace name, or use the prefix of a record the user named.
2. **Fields.** `fields_metadata` with `project_id` and `record_type` for `feature`, `requirement`, and `to_do` (add `epic`, `note`, or `initiative` when you'll write them). Keep the output: `aha_feature.py render --fields-metadata` maps field names to IDs from it.
3. **The record.** `read_records` with `record_ids: ["APP-12"]`, `record_type: "feature"`, `fields: "detailed"`, `association_fields: "standard"`, `include: ["requirement", "to_do"]`, and `text_field_format: "aha_editor_html"`. Add `"approval"` to `include` when you check an approval gate, and `"goal"` and `"key_result"` when you check alignment.
4. **Context.** The initiative and epic the record names, with `fields: "detailed"`. The initiative's To-Dos (`include: ["to_do"]`) hold shared decisions named `SD-n:`.
5. **Siblings.** `read_records` with `project_id` and `record_type: "feature"`, `fields: "minimal"`; then the siblings that the record links to or that share its epic, one at a time.
6. **Linked records.** The records named in the record's links and text, when an answer depends on them.

Turn the record into a bundle with `aha_feature.py bundle`. Its Settings table lists the release, status, type, tags, custom values, To-Dos, and attachment count. Its front matter carries the initiative, goals, and key results for the goal-alignment check.

## Read a record for editing

- Read text fields as HTML (`text_field_format: "aha_editor_html"`) before you change them. The default Markdown export drops callout boxes and colors, so a Markdown round trip would lose them.
- Reading the same record in Markdown is fine for review: `aha_feature.py` gives both formats the same fingerprint.
- `fields: "minimal"` returns names and references only; use it for lists.

## Field values

`manage_record` takes `fields` as a list of `{"name": "<field_id>", "value": "<string>"}`. Use the `field_id` from `fields_metadata` (for example `ac` for Acceptance Criteria, not its display name), and send every value as a string. A To-Do's text comes back from `read_records` as `body` but is written as `description`.

| Field type in `fields_metadata` | Value to send |
| --- | --- |
| `text` (Description, note custom fields) | Aha! Editor HTML from `aha_feature.py render` |
| `string` (a select list) | The option's `value` from the metadata, not its display text |
| `array` (a multi-select) | A JSON array of option values, such as `["Reduce Cost", "Reduce Risk"]` |
| `record` (release, status, type, epic, initiative) | The option's `value`: a reference such as `APP-R-5`, or a numeric ID for statuses and types |
| `record_array` (tags, goals, key results) | Comma-separated references, such as `APP-G-1, APP-G-2` |
| `number` | Digits, such as `2` |
| `date` | `YYYY-MM-DD` |

The required fields differ by workspace; `fields_metadata` lists them in `required_fields`. A feature typically needs a name, release, status, and type.

## Create and update

| Record | `record_type` | Typical fields |
| --- | --- | --- |
| Feature | `feature` | Name, release, status, type, description, custom text fields, initiative, epic, goals, key results |
| Requirement | `requirement` | The parent feature (`feature_id`), name, status, description |
| To-Do or approval | `to_do` | Parent record (`taskable_from_reference`), `task_type` (`task`, `approval`, or `work_request`), name, description, due date, assignees |
| Research note | `note` | Name, status, parent note, description; link it to the feature with `Has research in` |

- **Update:** `operation: "update"`, `id: "APP-12"`, and only the fields you change.
- **Create:** `operation: "create"` with the required fields. Record the new reference from the response; requirements get `APP-12-n`.
- **Links:** `record_links` on `manage_record`, or `create_record_link` for existing records. Use `Depends on` for a hard dependency that must be delivered first, `Relates to` for siblings and records named in the text, and `Has research in` for the research note.

## Apply sequence

1. Re-read the record (HTML) into `before.json`, and note the attachment count. Compare its fingerprint with the one the user reviewed; if they differ, someone edited the record, so stop and merge.
2. `aha_feature.py render bundle.md --fields-metadata fields.json --layout-from before.json -o payload.json`. Tell the user about any layout warning: those tables' column widths reset.
3. Update the feature's changed text fields, in one `manage_record` call per record. Split very large updates across calls if the server rejects them.
4. Update each existing requirement; create each new one.
5. Create each To-Do; update or complete the ones the elaboration resolved.
6. Set Goals and Key results if the user named them. Add record links.
7. Add one comment with the change log (below).
8. Re-read into `after.json`; run `aha_feature.py verify bundle.md after.json`.

## To-Do conventions

| Kind | Where | Name | Description |
| --- | --- | --- | --- |
| Open question | The feature | The action that resolves it: "Confirm the entry limit" | The decision needed, options, recommendation, owner, and `(OQ-n)` |
| Shared decision | The initiative | `SD-n: <decision>` | **Decision**, **Affects** (records), **Status** (Open, or Decided: ...), **Owner**, **Recommended** |
| Request to another team | The initiative or feature | `Request: <what is needed>` | What, why, by when, and the records it unblocks |
| Approval | The record being approved | `Approve specification: APP-12 sha256:...` | What it covers (fields, requirements, fingerprint) and that any change voids it |

When an open question is answered, write the decision and its reason into the To-Do's description, mark it complete, and update the text that carried the "(to confirm)" marker.

## Comments as the change log

Post one comment per applied change. Its body is Markdown:

```markdown
**Specification updated** (aha-feature, elaborated gate, fingerprint sha256:687d102450bc3522)

- Fields: Description, Summary, Use Case(s), Acceptance Criteria
- Requirements: APP-12-1 updated; APP-12-3 created
- To-Dos: Confirm the entry limit (OQ-1) created
- Approval: requested from J. Doe

**Elicitation**

| # | Dimension | Status | Answers and sources |
|---|---|---|---|
| 1 | Value & Persona | answered | Release managers spend about a day per release; J. Doe |
```

## Resilience

- **Throttled.** "Throttled, try again in N seconds": the hint understates the wait in long write sequences. Wait 5 seconds and retry once.
- **Connection restarting.** "Unknown tool" or "client failed to connect", often right after a throttle: wait 60 seconds, search for the tool again, and retry.
- **Safe retries.** A throttled or "Unknown tool" call never reached Aha!, so retrying it can't create a duplicate. After any other failure of a create, read the parent record before retrying.
- **Pacing.** Space writes about 10 seconds apart in a long apply; it avoids most throttles.
- **Server error on bulk calls.** `analyze_records` with many records can return a 500: read the records one at a time instead.
- **Large results.** The client saves big results to a file. The scripts read the first JSON value in such a file and ignore anything after it.
- **Serialize.** Never send Aha! calls in parallel, even reads.

## Side effects to check

- **Attachments and column widths.** Updating a feature through the API has dropped its attachments. Compare the attachment count before and after, and tell the user which files to re-attach; the API can't. Column widths survive when you render with `--layout-from`; for any table `render` warns about, tell the user which widths to reset.
- **Auto-linking.** Aha! turns plain record references into links when it saves. The renderer writes them as mentions already.
- **Formats.** A text field takes HTML or Markdown, never a mix. Send the renderer's HTML.

## Never

- Write content the user hasn't approved in its final form.
- Delete records or overwrite a field you didn't read first.
- Send a record to an integration, change its release or status, or reassign it, unless the user asks.
- Store artifacts on the local file system beyond the session's temporary directory.
