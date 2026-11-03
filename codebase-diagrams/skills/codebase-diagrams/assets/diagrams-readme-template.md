# {Project} Architecture Diagrams

Generated {date}. Source: {repo or path}, commit {short sha}.

## Diagrams

| File | Type | What it shows |
| --- | --- | --- |
| [{project}_core_architecture.png]({project}_core_architecture.png) | flowchart | {one line} |

Each diagram has a `.mmd` source next to its `.png`. Edit the `.mmd` and re-render.

## Where to start

- **New to the codebase:** {core_architecture, architecture_layers, dependencies_key}
- **Changing code:** {the dependency and data-flow diagrams for the area}
- **Operating it:** {build_deployment, backend_services}

## Color legend

| Color | Meaning |
| --- | --- |
| {role} | {what the color marks} |

## Key findings

- {Pattern, hotspot, or risk, with the file or module it comes from}

## Not covered

- {Areas skipped or only partly covered, and why (size, generated code, vendored code)}

## Rendering

Use the Mermaid CLI (`mmdc -i file.mmd -o file.png`), the VS Code Mermaid extension, or GitHub, which renders `.mmd` and fenced `mermaid` blocks natively.
