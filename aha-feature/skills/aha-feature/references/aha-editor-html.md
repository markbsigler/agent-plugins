# Aha! Editor HTML

Aha! text fields take Aha! Editor HTML through `manage_record`. Draft in Markdown, then let `aha_feature.py render` (or `aha_html.py to-html`) produce the HTML. This page lists the Markdown the renderer understands and the HTML it emits, so drafts render the same way in Aha!.

## Contents

- [Markdown to HTML](#markdown-to-html)
- [Record mentions](#record-mentions)
- [Tables](#tables)
- [What the renderer doesn't do](#what-the-renderer-doesnt-do)
- [Reading HTML back](#reading-html-back)

## Markdown to HTML

| Markdown | Aha! Editor HTML |
| --- | --- |
| `## Title` | `<h2 id="title">Title</h2>`; duplicate IDs get `-2`, `-3` |
| A paragraph | `<p>...</p>`; a line ending in `\` or two spaces becomes `<br/>` |
| `**bold**`, `*italic*`, `~~struck~~`, `` `code` `` | `<strong>`, `<em>`, `<del>`, `<code>` |
| `[text](https://...)`, `<https://...>`, a bare URL | `<a href="...">` |
| `- item`, `1. item`, nested by indentation | `<ul>` or `<ol>` with `<li><p>...</p></li>` |
| `- [ ] open`, `- [x] done` | An Aha! checklist (`ul.checklist`, `checklist-item--checked` or `--unchecked`) |
| A pipe table | `table.Editor__table` with `Editor__thead`, `Editor__tbody`, `Editor__tr`, `Editor__th`, `Editor__td`, every cell wrapped in `<p>` |
| `> [!NOTE]`, `[!INFO]`, `[!TIP]`, `[!WARNING]` | A callout: `<div data-callout-box-type="noteBlock">` (also `infoBlock`, `tipBlock`, `warningBlock`); `[!IMPORTANT]` maps to info and `[!CAUTION]` to warning |
| `> quoted text` | `<blockquote>` |
| A fenced code block with a language | `<pre><code data-language="python">`, using the languages Aha! highlights |
| `---` | `<hr/>` |
| `\*`, `\|`, and other backslash escapes | The literal character |

Callouts hold paragraphs only: inside one, list items and headings become paragraphs.

## Record mentions

References to Aha! records render as mentions, the format Aha! uses for linked records:

```html
<a href="https://yourcompany.aha.io/records/APP-12?reference-class=Feature&amp;visible-fields=icon%2Cref"
   data-linked-element-type="Feature" data-visible-fields="icon,ref"><i class="fa-solid fa-grid-2 fa-fw aha-reference-icon"></i> APP-12</a>
```

- **Bare references** become mentions when their prefix is in the bundle's `link-prefixes` (plus the record's own prefix) and the bundle has an `aha-domain`. Add prefixes with `--link-prefix`. IDs such as UC-1, FR-8, or AC-3 never become mentions, because their prefixes aren't workspaces.
- **Links whose text is the reference**, such as `[APP-12](https://yourcompany.aha.io/features/APP-12)`, become mentions on any Aha! host.
- **Links with other text** stay ordinary links.
- **References in code spans** stay text.

The reference's shape sets its class and path. The icon is the one the Aha! editor writes for that class; classes without a known icon use the feature icon.

| Shape | Class | Path | Icon classes |
| --- | --- | --- | --- |
| `APP-12` | Feature | `records` | `fa-solid fa-grid-2 fa-fw` |
| `APP-12-3` | Requirement | `records` | `fa-solid fa-list` |
| `APP-E-2` | Epic | `epics` | `aha-icon aha-icon-epic-solid` |
| `APP-S-1` | Initiative | `initiatives` | `fa-solid fa-sitemap` |
| `APP-R-5` | Release | `releases` | feature icon |
| `APP-G-1` | Goal | `records` | feature icon |
| `APP-G-1-KR-2` | Key result | `records` | feature icon |
| `APP-N-3` | Page (note) | `pages` | feature icon |
| `APP-I-7` | Idea | `records` | feature icon |
| `APP-TODO-102` | To-Do | `tasks` | feature icon |

## Tables

- The first row is the header.
- Separate paragraphs inside a cell with `<br>`: `| Role | One job.<br>Second paragraph. |`.
- Escape a pipe inside a cell as `\|`, also inside code spans.
- `:---`, `:---:`, and `---:` align columns left, center, and right.
- A row with more cells than the header widens the table instead of dropping cells.
- Markdown can't express column widths, so a plain render resets them. Render with the record you re-read before writing to keep them: `aha_feature.py render bundle.md --layout-from before.json`.

### Keeping the live layout

With `--layout-from`, each rendered table takes the layout of the live table in the same field, requirement, or To-Do that has the same header row:

- **Classes**, such as `Editor__table--sticky-header`.
- **Column widths**, from the live table's `colgroup`, or from its first row's cells when it has none. The renderer writes them where the Aha! editor does: in a `colgroup` and on every cell (`style="width:11%"`). Widths apply only when the column count is unchanged.
- **Header alignment**, such as `text-align:left` on the header cells, unless the Markdown separator row sets one.

A table whose header row changed, and a new table, get the default layout. `render` prints a warning for each live table whose layout it couldn't place, so you can tell the user which widths to reset in Aha!.

## What the renderer doesn't do

- **Raw HTML** in Markdown is escaped and shows as text. Only `<br>` passes through.
- **Images** become links, because Aha! needs pixel sizes the Markdown doesn't carry. Attach images in Aha! instead.
- **Colors, fonts, label pills, and embeds** have no Markdown form. Add them in Aha! after the last API write, or keep them by editing other fields only.
- **HTML comments** are escaped. Keep working notes in the bundle's preamble or `# Elicitation` section, which are never written.
- **Spacing and default styles.** Empty spacer paragraphs and `text-align:start` (the default) aren't kept, and headings get `id` attributes. None of this changes the visible text or the fingerprint.

## Reading HTML back

`aha_html.py to-markdown` and `aha_feature.py bundle` turn Aha! Editor HTML back into the same Markdown:

- Mentions become bare references, and callouts become `> [!NOTE]` blocks.
- Multi-paragraph cells become `<br>`-joined cells; empty spacer paragraphs disappear.
- Checklists, nested lists, code blocks, and emphasis survive a round trip.

Because both directions share one Markdown form, a record read as HTML and the same record read as Markdown give the same `fingerprint`, and `verify` compares visible text rather than markup.
