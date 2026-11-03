---
name: codebase-diagrams
description: Use this skill when the user wants to visualize, map, or document a codebase's architecture - system overviews, layered views, dependency graphs, data flow, build pipelines, or component interactions - even if they don't mention Mermaid. It analyzes the project, writes color-coded Mermaid .mmd diagrams plus a README, and renders PNG files.
license: MIT
compatibility: Rendering needs Node.js 18+ and npm, plus Python 3.11+ to run the bundled script (uv or python3). Diagram generation itself needs no tools.
metadata:
  author: markbsigler
  version: "1.0"
---

# Codebase Diagrams

Analyze any codebase and generate a suite of Mermaid architecture diagrams at multiple levels of detail, with consistent styling, PNG renders, and documentation.

## Workflow

### Step 1: Analyze

Build a mental model from the highest-signal files first, not by reading everything:

- **Manifests and config**: `package.json`, `pom.xml`, `pyproject.toml`, `go.mod`, `Dockerfile`, CI and deploy files
- **Entry points and top-level directories**: what runs, and how the code is divided
- **Components**: follow imports, calls, queries, and config references outward from the entry points
- **Stack and external systems**: languages, frameworks, databases, queues, third-party APIs
- **Patterns**: layered, microservice, monolith, event-driven, pipeline, and so on

For a large codebase, work one subsystem at a time and sample rather than read every file. Keep notes in the conversation; don't write a separate analysis document unless asked. If `docs/diagrams/` or other diagram files already exist, update them instead of creating duplicates.

**Draw only what you verified.** Every node must be a real module, service, or store you saw in the code, and every edge a real import, call, query, or config reference (confirm with a search). Leave out anything you can't confirm, or say it is inferred in the README.

### Step 2: Plan

Pick the diagrams from [references/diagram-catalog.md](references/diagram-catalog.md) by codebase size, then add any system-specific ones the analysis supports (data flow, backend services, build and deployment, frontend, auth):

| Size | Files | Diagrams |
| --- | --- | --- |
| Small | <20 | 3–5: `core_architecture`, `architecture_layers`, `dependencies_key`, plus data flow or build if relevant |
| Medium | 20–100 | 7–10: add `dependencies_overview`, `dependencies_full`, `dependencies_by_category`, and the matching system diagrams |
| Large | >100 | 12+: the full catalog, split by subsystem |

Defaults, unless the user says otherwise: output to `docs/diagrams/`, files named `{project}_<diagram>.mmd` with the project name taken from the repo or directory, and the default color theme. Ask the user only when the scope is genuinely ambiguous, such as which subsystem of a large repo to cover.

### Step 3: Generate

Write the `.mmd` files, starting from [assets/example_core_architecture.mmd](assets/example_core_architecture.mmd) as a structural model:

- Use `flowchart TD`, `flowchart LR`, or `sequenceDiagram` (not the legacy `graph` keyword)
- Define `classDef` styles from [references/color-themes.md](references/color-themes.md) and assign a class to every node
- Group related components in subgraphs
- Use `-->` for strong dependencies, `-.->` for weak or optional ones, and `==>` for critical runtime paths
- Use `<b>` for primary names and `<i>` for secondary detail in labels
- Keep each diagram focused; split rather than overload

### Step 4: Validate and render

Check that every diagram parses before rendering PNG files. Run these from the skill directory, or with the full path to the script:

```bash
uv run --script scripts/render_diagrams.py --check docs/diagrams   # parse check, writes nothing
uv run --script scripts/render_diagrams.py docs/diagrams           # render images next to the .mmd files
```

If `uv` is not available, use `python3 scripts/render_diagrams.py` with the same arguments. Run `--help` for options and exit codes. If a diagram fails, the script prints the Mermaid parse error. Fix that diagram (see [references/mermaid-standards.md](references/mermaid-standards.md)) and rerun until `--check` exits 0, then render. The script uses `mmdc` if installed, otherwise a pinned Mermaid CLI through `npx`, with no global install.

### Step 5: Document

Write `README.md` in the diagrams directory from [assets/diagrams-readme-template.md](assets/diagrams-readme-template.md): inventory table, where to start by audience, color legend, key findings, what is not covered, and rendering instructions.

## Diagram Catalog Quick Reference

| Category | Diagrams | When to Include |
| --- | --- | --- |
| Architecture | `core_architecture`, `architecture_layers` | Always |
| Dependencies | `dependencies_key` | Always |
| Dependencies | `dependencies_overview`, `dependencies_full`, `dependencies_by_category` | Medium+ |
| System | `data_flow`, `backend_services`, `build_deployment`, `batch_processing`, `frontend_architecture`, `auth_security` | Those matching systems you found |
| Hierarchy | `dependency_tree` | Medium+ |
| Runtime | `component_interactions` (sequence diagram) | When inter-component communication is significant |

Full specifications for each diagram type: [references/diagram-catalog.md](references/diagram-catalog.md)

## Gotchas

- **Plausible but invented structure** is the most common failure. A diagram that looks right but shows a dependency that doesn't exist is worse than a smaller correct one. Verify edges against the code.
- **Too dense to read.** Keep `dependencies_key` to about 15 nodes and every other diagram under about 80. Beyond that, split by subsystem.
- **Reserved words as node IDs** (`end`, `call`, `class`, `style`, `default`) break parsing, sometimes silently. Use `end_node`, `call_module`, and so on.
- **A parse error and a browser error look different.** A parse error names a line in the `.mmd` file. A Chromium or sandbox error on every diagram, including the known-good example, is an environment problem; set `RENDER_PUPPETEER_CONFIG` (see `--help`).
- **Don't overwrite existing diagrams** without saying so. If files with the same names exist, update them in place and note what changed.

## Resources

- [references/diagram-catalog.md](references/diagram-catalog.md): detailed spec for every diagram type. Read it when choosing and writing diagrams in Steps 2 and 3.
- [references/mermaid-standards.md](references/mermaid-standards.md): syntax rules, reserved words, rendering problems. Read it when a diagram fails to parse or render.
- [references/color-themes.md](references/color-themes.md): default palette and alternative themes, with copy-paste `classDef` blocks.
- [assets/example_core_architecture.mmd](assets/example_core_architecture.mmd): a valid worked example to copy the structure from.
- [assets/diagrams-readme-template.md](assets/diagrams-readme-template.md): template for the diagrams `README.md`.
- [scripts/render_diagrams.py](scripts/render_diagrams.py): checks and renders `.mmd` to `.png`.
