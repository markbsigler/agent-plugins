# Mermaid Standards & Pitfalls

Syntax rules and known issues to avoid when generating `.mmd` files.

## Directive Format

Always include an init block at the top for consistent rendering:

```text
%%{ init: { 'theme': 'base', 'themeVariables': { 'fontSize': '13px' } } }%%
```

## Diagram Type

- Use `flowchart TD` or `flowchart LR` rather than the legacy `graph TD` / `graph LR` alias, so every diagram uses the same keyword and current syntax
- Use `sequenceDiagram` for interaction/timing diagrams
- `flowchart` supports `classDef` and `class` assignments

## Reserved Words

These Mermaid keywords **cannot** be used as node IDs. They cause silent parse failures or misrendered diagrams:

| Reserved | Use Instead |
| --- | --- |
| `call` | `call_module`, `callout`, `invoke` |
| `end` | `end_node`, `finish`, `terminate` |
| `default` | `default_val`, `fallback` |
| `click` | `click_handler`, `on_click` |
| `style` | `styling`, `node_style` |
| `class` | `cls`, `klass`, `category` |
| `subgraph` | (cannot be a node ID) |
| `direction` | `dir`, `flow_dir` |

## Node ID Rules

- IDs must start with a letter or underscore
- Use `UPPER_SNAKE` or `camelCase` — avoid spaces or special characters in IDs
- Put display text in brackets: `MY_NODE["Display Label"]`
- IDs must be unique across the entire diagram (including across subgraphs)
- **Duplicate IDs in different subgraphs cause rendering errors** — prefix with subgraph abbreviation if needed (e.g., `SYS_MAIN`, `CC_MAIN`)

## Node Labels

- Use `<b>text</b>` for bold (primary names)
- Use `<i>text</i>` for italic (descriptions)
- Use `<br/>` for line breaks
- Wrap multi-line labels in `["..."]` (quotes inside brackets)
- Do **not** use Markdown syntax (`**bold**`, `*italic*`) inside node labels
- Always wrap labels in `["..."]` when they contain parentheses, braces, colons, semicolons, `#`, or quotes. An unquoted `A[Foo (bar)]` fails to parse; `A["Foo (bar)"]` works
- File paths and generics (`List<String>`) in labels: quote the label, and write `&lt;` / `&gt;` in place of angle brackets that aren't `<b>`, `<i>`, or `<br/>`

## Edge Syntax

| Syntax | Meaning | Use For |
| --- | --- | --- |
| `A --> B` | Solid arrow | Strong/required dependency |
| `A -.-> B` | Dotted arrow | Weak/optional dependency |
| `A ==> B` | Thick arrow | Critical runtime path |
| `A <--> B` | Bidirectional | Two-way communication |
| `A -->\|"label"\| B` | Labeled edge | Describe the relationship |

Put a space before an edge's target when its ID starts with `o` or `x`: `A --- oB` is fine, but `A---oB` parses as a circle-ended edge to `B`, not an edge to a node named `oB`.

## Subgraph Rules

- Subgraphs can be nested (max 3 levels recommended)
- Subgraph labels support `<b>` tags: `subgraph ID ["<b>Label</b>"]`
- Use `direction TB` or `direction LR` inside subgraphs to control inner layout
- Nodes defined inside a subgraph can still be connected to nodes outside
- Closing with `end` is required — ensure it's not confused with a node ID

## classDef & class

Define styles once, apply to many nodes:

```mermaid
classDef myStyle fill:#FF6B6B,stroke:#C0392B,color:#fff,stroke-width:2px
class NODE1,NODE2,NODE3 myStyle
```

- Place all `classDef` declarations right after the `flowchart` line
- Place all `class` assignments at the bottom of the diagram
- Can assign multiple nodes to one class in a single `class` statement
- Stroke color should be a darker shade of the fill color

## Sequence Diagram Specifics

- Use `participant` to declare actors with custom labels: `participant A as "Service Name"`
- `autonumber` adds step numbers automatically
- `->>+` activates the target; `-->>-` deactivates it (for activation bars)
- `alt` / `else` / `end` for conditional flows
- `rect rgb(R, G, B)` to shade background sections
- `Note over A,B: text` for annotations spanning participants
- Participants cannot use `classDef` — style with `participant` order and naming

## Common Rendering Issues

1. **Diagram renders blank**: Usually a reserved word used as node ID, or unclosed subgraph
2. **Edges not visible**: Check for typos in node IDs (case-sensitive)
3. **Labels not rendering HTML**: Ensure node label uses `["..."]` not `[...]`
4. **Too many crossing lines**: Switch from `TD` to `LR`, or split into multiple diagrams
5. **mmdc timeout on large diagrams**: Reduce node count or split; keep under ~80 nodes per diagram

## Comments

Use `%%` for single-line comments in Mermaid:

```text
%% This is a comment
%% ═══════════════════
```
