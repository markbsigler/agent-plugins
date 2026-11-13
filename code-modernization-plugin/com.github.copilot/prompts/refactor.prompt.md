---
name: refactor
description: Launch the 4-stage Gartner Refactor playbook (behavior-preserving code modernization).
argument-hint: "[module, directory, or service path]"
agent: agent
---

Execute the **playbook-refactor** skill strictly stage by stage for:
- **Target Scope:** `${input:targetScope:Enter the module, directory, or service path}`
- **Primary Driver:** `${input:driver:Framework upgrade, tech debt, security/CVE, or performance?}`
- **Target Version / Benchmark:** `${input:targetVersion:Enter target runtime/framework version or performance goal}`

Load every stack profile skill that matches the scope (for example **mainframe-analysis** for an Enterprise COBOL V4 to V6 upgrade) and complete its tasks at each stage.
