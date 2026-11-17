# Changelog

All notable changes to `code-modernization-plugin` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the plugin uses
[Semantic Versioning](https://semver.org/) for the `version` in `plugin.json`.

## [1.0.0]

- Initial release of `code-modernization-plugin`:
  - Shared discovery and classification skill (`modernization-triage`), which loads the stack
    profiles that match the scope and flags the other modernization options (encapsulate,
    rehost, replatform, rebuild, replace).
  - Track A 4-stage gated playbook (`playbook-refactor`) for behavior-preserving code transformations.
  - Track B 4-stage gated playbook (`playbook-rearchitect`) for structural and topology transformations using ADRs and Strangler Fig gates.
  - Stack-profile architecture: triage and both playbooks are stack-neutral. Every playbook stage
    runs its section from each loaded profile's `references/playbook-stages.md`, and every
    approval gate asks for the profiles' results.
  - First stack profile, `mainframe-analysis` (IBM Z), with z/OS tasks for every playbook stage
    and references for COBOL semantics, data and encoding, CICS and IMS TM, Db2, IMS DB, VSAM,
    and IDMS, MQ, batch and JCL, other mainframe languages, security, performance and cost,
    DevOps, equivalence testing, target mappings, and tooling, plus JCL and SQL templates the
    platform team submits to extract the CSD, LISTCAT reports, MQSC definitions, and Db2
    catalog data. The agent works only from exported files and never connects to z/OS.
  - Read-only, stdlib-only scripts in `mainframe-analysis`:
    - `mainframe_inventory.py`: inventory and dependency graph for COBOL, PL/I, Assembler, JCL,
      REXX, CLIST, ISPF skeletons, Easytrieve, and Natural; create, read, update, and delete
      access on every table, data set, DD name, CICS file and queue, IMS segment, MQ queue, and
      Adabas file; dynamic `CALL` and CICS `PROGRAM` targets resolved from literals; programs
      behind `IKJEFT01`, `DFSRRC00`, and procedure symbols; FTP and Connect:Direct transfers;
      cross-checks of COBOL files against VSAM definitions and of DEFINE statements against the
      catalog; data sets that CICS and batch both update; CICS threadsafe readiness; dead code
      confirmed with usage evidence; search order with shadowed members; JSON Lines output and
      incremental rescans.
    - `zos_definitions.py`: CICS CSD extracts, IDCAMS DEFINE statements and LISTCAT reports,
      MQSC, Db2 BIND statements, compiler and binder listings, and Control-M, IBM Z Workload
      Scheduler, and CSV schedule exports.
    - `seam_report.py`: data ownership matrix, resources with several writers, write clusters,
      CICS transaction footprints, and interfaces, as JSON, Markdown, or Mermaid.
    - `ims_model.py`: IMS DBD and PSB hierarchy, keys, logical relationships, secondary indexes,
      PCB sensitivity checked against program access, and draft relational DDL.
    - `zos_encoding.py`: 31 EBCDIC code pages (national, euro, and mixed double-byte), fixed,
      RDW-prefixed, and new-line delimited records, and hex dumps; shared by the mainframe
      skills.
  - `copybook-data` skill: exact layouts for COBOL copybooks (including SYNCHRONIZED slack
    bytes), PL/I structures, and Assembler DSECTs; layout diffs that flag breaking changes;
    JSON Schema, Avro, AsyncAPI, and DFSORT symbol output; and field-level decoding,
    golden-master comparison, and keyed masking of record files.
  - `mainframe-batch-flow` skill: JCL expansion (symbols, procedures, overrides, INCLUDE
    members), `COND` and `IF` explanations, utility control statements, data set lineage, and
    data dependencies checked against scheduler exports.
  - `mainframe-program-docs` skill: COBOL documentation skeletons (paragraph flow, unreachable
    paragraphs, interfaces, business-rule candidates) and BMS and MFS screen maps with mockups,
    screen contracts, and symbolic-map checks.
  - `behavioral-baseline` skill (`baseline_gate.py`): loads `.modernize/rulebook/` enterprise
    policies and `.modernize/learnings/` stage insights, freezes `.modernize/baseline/test-cases.md`,
    `infra-decision-table.md`, and `testdata/` with SHA-256 digests (`manifest.json`), verifies
    1:1 `TC-XXX` test coverage in the test suite, and runs `spec-quality`, `spec-to-plan`,
    `plan-to-tasks`, and `completeness` traceability gates over `.modernize/traceability.json`.
  - `java-analysis` stack profile (`java_inventory.py`) and `dotnet-analysis` stack profile
    (`dotnet_inventory.py`) for Java/Spring Boot/Jakarta EE/WebSphere/Struts and .NET Framework
    to modern .NET modernization, as well as target-stack guidance for mainframe-to-Java and
    mainframe-to-.NET migrations.
  - GitHub Copilot custom agents (`modernize`, `modernize-refactor`, `modernize-rearchitect`),
    prompt slash commands (`/modernize`, `/refactor`, `/rearchitect`), guardrail instructions,
    and mainframe source-editing instructions under `com.github.copilot/`.
  - Cursor routing, safety guardrail, and auto-attached mainframe source rules under `com.cursor.client/`.
