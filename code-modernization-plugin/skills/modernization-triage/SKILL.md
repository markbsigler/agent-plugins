---
name: modernization-triage
description: Classifies modernization initiatives into Refactor vs. Rearchitect tracks via structured elicitation, loads the stack profile skills that match the scope, and routes to the playbook-refactor or playbook-rearchitect skill. Use before any code changes whenever a user asks to modernize, upgrade, clean up, decompose, migrate, or rearchitect a codebase, service, or application on any stack, including mainframe estates (COBOL, PL/I, CICS, IMS, Db2, VSAM, JCL).
license: MIT
metadata:
  author: markbsigler
  version: "1.0"
---

# Skill: Modernization Triage & Elicitation

Before writing code, classify the user's request into one of two code modernization tracks:
1. **Refactor (Code-level modernization):** Restructure and optimize existing code—upgrading frameworks, paying down technical debt, and improving nonfunctional attributes (security, maintainability, performance)—without changing external behavior or core architecture.
2. **Rearchitect (Structural code & architecture change):** Materially alter the code to shift to a new application architecture (e.g., monolith to modular/microservices or event-driven cloud-native) to unlock new capabilities.

Never modify production code during triage.

## Stack profiles

This skill and both playbooks are stack-neutral. Stack-specific knowledge lives in stack profile skills: each one provides detection signals, discovery and an estate brief, the stack's contract surface, extra elicitation questions, classification examples, tasks for every playbook stage, equivalence evidence, and target mappings.

| Profile skill | Load when the scope contains |
| --- | --- |
| `mainframe-analysis` | IBM Z artifacts (COBOL, PL/I, or Assembler programs, copybooks, JCL, BMS or MFS maps, REXX, CICS CSD extracts, IMS DBDs or PSBs, DCLGENs), or the user mentions z/OS, CICS, IMS, Db2 for z/OS, VSAM, or mainframe batch |

A mixed estate can match several profiles. A Rearchitect slice usually needs a profile for the legacy stack and, when one exists, one for the target stack. When no profile matches, the playbooks' generic tasks apply on their own.

## Step 1: Detect the estate

Inspect the target scope before asking questions, so you only ask what the code cannot tell you. Match the scope against the stack profiles table, load every matching profile, and run its discovery first; each profile's estate brief informs the questions below. Where no profile matches, survey build manifests, entry points, deployment descriptors, and data stores.

## Step 2: Elicitation Protocol

If the user's request lacks scope or architectural constraints, ask these exact questions before selecting a playbook:
1. **Behavioral Parity:** Must all external APIs, schemas, and deployment boundaries remain 100% unchanged?
2. **Primary Driver:** Is the goal tech-debt/framework upgrades (Refactor) or shifting deployment/data topology to unlock new capabilities (Rearchitect)?
3. **Target Scope:** Which module, service, or domain boundary is in scope?

Add each loaded profile's elicitation questions that its discovery could not answer. Ask at most two or three questions per round, and acknowledge what you already know before you ask.

## Step 3: Classify

| Signal | Route |
| --- | --- |
| External behavior, contracts, data ownership, and deployment topology stay identical | **Refactor** |
| Framework, runtime, or compiler upgrades; CVE remediation; complexity reduction; performance work inside existing boundaries | **Refactor** |
| Automated language conversion (for example COBOL to Java, or VB6 to C#) that preserves behavior, contracts, and topology | **Refactor** (language transformation, with strict equivalence evidence) |
| New service or module boundaries, extracted bounded contexts, changed data ownership, synchronous calls replaced by events | **Rearchitect** |

Check each loaded profile's classification examples before deciding.

Modernization initiatives are commonly grouped into seven options: encapsulate, rehost, replatform, refactor, rearchitect, rebuild, and replace. This plugin governs **Refactor** and **Rearchitect**. When the request is really another option, say so plainly:

- **Encapsulate** (expose existing functions as APIs without changing them) is often the first step of Rearchitect Stage 2; route to Rearchitect if boundaries will move afterwards, otherwise treat it as a small, separate integration task.
- **Rehost or replatform** (move workloads to another infrastructure or runtime with minimal code change) and **rebuild or replace** (rewrite or buy) are outside both playbooks. Recommend planning them separately, and offer the Refactor playbook for any code changes they require.
- **Hybrid requests** that mix an in-place upgrade with a topology change are split into sequential phases. Ask which phase to run now, and never combine them in one batch of changes.

## Step 4: Collect track-specific inputs

| Track | Ask until answered | Sets |
| --- | --- | --- |
| **Refactor** | 1. Primary driver (framework upgrade, tech debt, security/CVE, or performance)? 2. Target runtime, framework, or compiler version? 3. Existing test coverage baseline? | Success metrics: benchmark latency or CPU, zero CVEs, passing golden master |
| **Rearchitect** | 1. Target architecture pattern (modular monolith, microservices, event-driven, serverless)? 2. First bounded context or domain slice? 3. Integration and migration pattern (Strangler Fig, Branch by Abstraction, change data capture)? | Prevents big-bang rewrites; enforces incremental extraction |

## Step 5: Present the Triage Brief

```markdown
## Modernization Triage Decision
- **Selected Track:** [Refactor | Rearchitect]
- **Target Scope:** <module, service, transactions, or job streams>
- **Classification Rationale:** <2 sentences citing behavioral and topology constraints>
- **Confirmed Parameters:**
  - <track-specific answer 1>
  - <track-specific answer 2>
  - <track-specific answer 3>
- **Stack Profiles:** <each loaded profile with a summary of its estate brief; for Rearchitect, mark legacy and target; "none" if no profile matched>
- **Out of scope / other options:** <any rehost, replatform, rebuild, or replace work noted>
- **Next Action:** Load `playbook-refactor` or `playbook-rearchitect` at Stage 1.
```

## Routing Rule
- If **Refactor**, load and execute `playbook-refactor`.
- If **Rearchitect**, load and execute `playbook-rearchitect`.

Wait for the user to confirm the track and parameters, then start Stage 1 of the selected playbook.
