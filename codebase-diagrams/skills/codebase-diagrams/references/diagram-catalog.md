# Diagram Catalog

Detailed specifications for each diagram type. Consult during Step 3 (Generate).

## Table of Contents

1. [Core Architecture](#1-core-architecture)
2. [Architecture Layers](#2-architecture-layers)
3. [Dependencies Overview](#3-dependencies-overview)
4. [Dependencies Key](#4-dependencies-key)
5. [Dependencies Full](#5-dependencies-full)
6. [Dependencies by Category](#6-dependencies-by-category)
7. [Data Flow](#7-data-flow)
8. [Backend Services](#8-backend-services)
9. [Build & Deployment](#9-build--deployment)
10. [Batch Processing](#10-batch-processing)
11. [Frontend Architecture](#11-frontend-architecture)
12. [Auth & Security](#12-auth--security)
13. [Dependency Tree](#13-dependency-tree)
14. [Component Interactions](#14-component-interactions)

---

## 1. Core Architecture

**File**: `{project}_core_architecture.mmd`
**Type**: `flowchart TD`
**Always include**: Yes

Show the complete system at a glance:

- Entry points (user interfaces, CLI, API endpoints, job schedulers)
- All major programs/services as nodes, color-coded by role
- External systems (databases, message queues, third-party APIs)
- Build/deployment infrastructure
- Use subgraphs to group by function (e.g., "Online Services", "Batch Programs", "Data Stores")
- Connect with `-->` for runtime calls, `-.->` for compile-time/config dependencies
- Include `init` config block to set theme and font size

## 2. Architecture Layers

**File**: `{project}_architecture_layers.mmd`
**Type**: `flowchart TD`
**Always include**: Yes

Show the architectural stack layer by layer:

- Typical layers: Presentation → Dispatch/Routing → Business Logic → Shared Types → Cross-Cutting → Data Access → Infrastructure → Persistence
- Adapt layer names to what actually exists in the codebase
- Each layer is a subgraph containing relevant components
- Arrows flow top-down (or reference direction appropriate to the codebase)
- Label layer boundaries with the interface/protocol used

## 3. Dependencies Overview

**File**: `{project}_dependencies_overview.mmd`
**Type**: `flowchart TD`
**Include for**: Medium+ codebases

High-level statistics and summary:

- Project stats: file count, LOC, languages, tech stack
- Component breakdown by category (e.g., frontend vs backend, services vs jobs)
- Import/dependency categories with counts
- Dependency fan-out summary (which modules are most depended upon)
- Use a clean layout with labeled boxes — no complex connections needed

## 4. Dependencies Key

**File**: `{project}_dependencies_key.mmd`
**Type**: `flowchart TD`
**Always include**: Yes

Critical dependencies only — the "executive summary" of dependencies:

- Show only the top 5–8 most important dependency paths
- Runtime dispatch/routing connections
- Primary data store connections (database, file system)
- Cross-process communication (shared memory, message passing)
- Use `==>` for critical runtime paths, `-.->` for type/config dependencies
- Maximum ~15 nodes — trim aggressively

## 5. Dependencies Full

**File**: `{project}_dependencies_full.mmd`
**Type**: `flowchart LR`
**Include for**: Medium+ codebases

Complete import/include matrix:

- Left side: all programs/modules grouped by category in subgraphs
- Right side: all shared libraries/modules/packages grouped by type
- Every dependency edge shown with `-->`
- Color-code both sides consistently
- Use `flowchart LR` for readability with many-to-many relationships

## 6. Dependencies by Category

**File**: `{project}_dependencies_by_category.mmd`
**Type**: `flowchart TB`
**Include for**: Medium+ codebases

Group dependencies by functional area:

- One subgraph per dependency category (e.g., "Data Structures", "System/Middleware", "Cross-Cutting", "Foundation")
- Within each subgraph: programs on left, shared modules on right
- Shows which programs use which category of shared code
- Helps answer: "if I change module X in category Y, what breaks?"

## 7. Data Flow

**File**: `{project}_data_flow.mmd`
**Type**: `flowchart TB`
**Include when**: System has significant data processing, storage, or I/O

End-to-end data movement:

- Input sources (UI, files, APIs, job parameters)
- Processing nodes (each program/service that transforms data)
- Persistence targets (databases, file systems, caches, reports)
- Shared memory / inter-process communication
- Label edges with operation type (SQL CRUD, file READ/WRITE, message publish, etc.)
- Use subgraphs: "Input", "Online Flow", "Batch Flow", "Persistence", "Shared Data"

## 8. Backend Services

**File**: `{project}_backend_services.mmd`
**Type**: `flowchart TB`
**Include when**: System has service layer, APIs, or dispatcher patterns

Backend service architecture:

- Service registry / dispatcher / router
- Individual service implementations
- Middleware and cross-cutting services (auth, logging, caching)
- Communication protocols between services
- Data store connections per service
- Task management / concurrency patterns

## 9. Build & Deployment

**File**: `{project}_build_deployment.mmd`
**Type**: `flowchart TB`
**Include when**: Build pipeline has multiple stages or deployment targets

Build pipeline visualization:

- Source libraries / input
- Build phases (preprocess → compile → link → package → deploy)
- Parallel tracks for different output types
- Deployment targets (container registries, CDNs, servers, artifact repositories)
- Color-code: source (green), compile steps (yellow), link steps (red), package (blue), output (gray)

## 10. Batch Processing

**File**: `{project}_batch_processing.mmd`
**Type**: `flowchart TB`
**Include when**: System has batch jobs, scheduled tasks, or pipeline processing

Job execution flow:

- Job steps in execution order
- Input parameters per step
- I/O operations per step (what each step reads/writes)
- Conditional execution (step dependencies, error handling)
- External data store connections
- Final verification / cleanup steps

## 11. Frontend Architecture

**File**: `{project}_frontend_architecture.mmd`
**Type**: `flowchart TD`
**Include when**: System has UI components, SPAs, or presentation layer

Frontend component structure:

- Page/route hierarchy
- Component tree (layout → pages → widgets)
- State management flow
- API client connections
- Shared UI libraries / design system
- Asset pipeline (bundler, CDN)

## 12. Auth & Security

**File**: `{project}_auth_security.mmd`
**Type**: `flowchart TD`
**Include when**: System has authentication, authorization, or security infrastructure

Security architecture:

- Auth flow (login → token → validation → refresh)
- Identity providers and SSO integrations
- Authorization model (roles, permissions, policies)
- Encryption points (at-rest, in-transit)
- Audit logging and compliance hooks

## 13. Dependency Tree

**File**: `{project}_dependency_tree.mmd`
**Type**: `flowchart TD`
**Include for**: Medium+ codebases

Hierarchical tree view:

- Root node = project name with stats
- Level 1: Major categories (e.g., Foundation, Applications, Build)
- Level 2: Subcategories (e.g., Services, Jobs, Shared Types, Config)
- Level 3: Individual programs/modules with metadata (include count, runtime deps)
- Level 4 (leaves): Runtime requirements per program
- Use 4 classDefs: root, level1, level2, level3/leaf

## 14. Component Interactions

**File**: `{project}_component_interactions.mmd`
**Type**: `sequenceDiagram`
**Include when**: Inter-component communication is architecturally significant

Runtime sequence diagram:

- Participants = major components/services
- Show primary user flow (request → dispatch → process → respond)
- Show alternative flows with `alt`/`else` blocks
- Highlight async operations with `rect` shading
- Include data formats on arrows (JSON, protobuf, SQL, message payloads, etc.)
- Use `autonumber` for step tracking
- Use `Note over` for contextual annotations
