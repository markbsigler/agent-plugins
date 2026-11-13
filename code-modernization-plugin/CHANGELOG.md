# Changelog

All notable changes to `code-modernization-plugin` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the plugin uses
[Semantic Versioning](https://semver.org/) for the `version` in `plugin.json`.

## [1.0.0]

- Initial release of `code-modernization-plugin`:
  - Shared discovery and Gartner classification skill (`modernization-triage`), which loads the
    stack profiles that match the scope and flags Gartner's other options (encapsulate, rehost,
    replatform, rebuild, replace).
  - Track A 4-stage gated playbook (`playbook-refactor`) for behavior-preserving code transformations.
  - Track B 4-stage gated playbook (`playbook-rearchitect`) for structural and topology transformations using ADRs and Strangler Fig gates.
  - Stack-profile architecture: triage and both playbooks are stack-neutral. Every playbook stage
    runs its section from each loaded profile's `references/playbook-stages.md`, and every
    approval gate asks for the profiles' results.
  - First stack profile, `mainframe-analysis` (IBM Z), with z/OS tasks for every playbook stage
    and references for COBOL semantics, data and encoding, CICS and IMS TM, Db2, IMS DB, VSAM,
    and IDMS, batch and JCL, other mainframe languages, equivalence testing, target mappings,
    and tooling.
  - Read-only, stdlib-only scripts: `mainframe_inventory.py` (inventory, dependency graph, CICS
    transaction map, programs behind `IKJEFT01`/`DFSRRC00`/procedure symbols, risk scores,
    EBCDIC decoding) and `copybook_layout.py` (exact offsets, DFSORT formats, nested `COPY ...
    REPLACING`, JSON Schema drafts).
  - GitHub Copilot prompt slash commands (`/modernize`, `/refactor`, `/rearchitect`), guardrail
    instructions, and mainframe source-editing instructions under `com.github.copilot/`.
  - Cursor routing, safety guardrail, and auto-attached mainframe source rules under `com.cursor.client/`.
