# Playbook stage tasks (.NET Framework / Modern .NET)

Stack profile tasks for the `playbook-refactor` and `playbook-rearchitect` skills. Complete the matching section below alongside the playbook's generic tasks and include the results in that stage's gate review.

## Refactor

### Refactor Stage 1: Tech Debt, Security & Dependency Audit

- Run `scripts/dotnet_inventory.py` across the solution and record every `.csproj`, whether it uses the SDK-style format, its `TargetFramework` / `TargetFrameworks`, and its NuGet dependencies.
- Identify `.NET Framework`-only coupling: `System.Web` (`HttpContext.Current`), WCF server hosting (`System.ServiceModel`), ASMX web services, `.NET Remoting`, Windows Registry / COM / P/Invoke (`windows_registry_or_com`), and Entity Framework 6 (`System.Data.Entity`).
- Flag security and precision hazards reported by `dotnet_inventory.py`: `BinaryFormatter` deserialization (`binary_formatter`), SQL string interpolation/concatenation (`sql_concatenation`), hardcoded connection strings or secrets (`hardcoded_secret`), and `float`/`double` currency fields (`float_currency`).
- Check `.modernize/rulebook/` for mandatory target `.NET` version, container OS, and NuGet/cloud policies.

### Refactor Stage 2: Characterization & Nonfunctional Baseline

- Use the `behavioral-baseline` skill to freeze `.modernize/baseline/test-cases.md` and `.modernize/baseline/infra-decision-table.md` covering every controller, Minimal API endpoint, WCF operation, and worker/job in scope.
- Capture wire-level JSON/XML snapshots (`Newtonsoft.Json` property casing, null/default handling, date formats, enum strings/integers) so moving to ASP.NET Core or `System.Text.Json` does not break callers.
- Prefer `WebApplicationFactory<TProgram>` and Testcontainers for .NET over in-memory database providers when SQL dialect or transaction semantics matter.
- Record baseline build time, test duration, startup time, and memory allocation.

### Refactor Stage 3: Incremental Code Transformation

- Sequence changes in small, buildable commits:
  1. Convert legacy `.csproj` files to SDK-style projects and migrate `packages.config` to `PackageReference` (or `Directory.Packages.props` central package management).
  2. Target `netstandard2.0` (or multi-target `net48;net8.0`) in class libraries from the bottom of the project dependency graph upward.
  3. Upgrade executable/web projects to the target `.NET` LTS release, migrating `Web.config` settings to `appsettings.json` and the `IOptions<T>` pattern, and replacing `HttpContext.Current` with injected `IHttpContextAccessor` or controller context.
  4. Replace `BinaryFormatter` and insecure serializers, parameterize raw SQL queries, and replace `float`/`double` currency fields with `decimal`.
- Run `dotnet test` after each step.

### Refactor Stage 4: Equivalence & NFR Verification

- Run `dotnet test` and `baseline_gate.py verify` to confirm 100% pass rate and 1:1 `TC-XXX` coverage.
- Verify that JSON/XML payloads, status codes, validation error envelopes, and `decimal` rounding match the Stage 2 baseline with zero drift.
- Compare startup time, throughput/latency, and memory usage against the Stage 2 baseline.

## Rearchitect

### Rearchitect Stage 1: Domain Seam Analysis & ADR Generation

- Run `scripts/dotnet_inventory.py` to map projects, namespaces, entry points, `DbContext` types, and SQL tables (`db_tables`).
- Identify shared `DbContext` or database tables accessed across multiple modules, synchronous RPC chains, `TransactionScope` distributed transactions, and shared in-memory/session state.
- In the ADR, specify the target service/module boundaries, whether ASP.NET strangulation uses YARP (`Microsoft.ReverseProxy` + `System.Web` Adapters for shared auth/session during transition), how data ownership is decoupled, and any cloud/platform rules from `.modernize/rulebook/`.

### Rearchitect Stage 2: Seam Isolation & Interface Contract Definition

- Define OpenAPI, AsyncAPI, or gRPC `.proto` contracts for the extracted slice. When the legacy side is a mainframe copybook (`mainframe-analysis` + `copybook-data`), generate the schema from the copybook and map all `COMP-3` / zoned-decimal fields to C# `decimal`.
- Introduce an interface seam and anti-corruption layer (ACL) in the legacy host (wired via `IServiceCollection` and feature flags or YARP route rules) so traffic can shift without code redeployments.
- Lock contract tests and freeze `.modernize/baseline/test-cases.md` via `behavioral-baseline`.

### Rearchitect Stage 3: Strangler Slice Implementation & Dual-Run

- Implement the new ASP.NET Core API or `BackgroundService` worker adhering to the Stage 2 contracts, `IOptions<T>` configuration, `ILogger<T>` / OpenTelemetry instrumentation, and isolated data store.
- When migrating from mainframe COBOL/CICS/IMS to .NET:
  - Preserve fixed-point scale and rounding (`Math.Round(value, scale, MidpointRounding.ToZero)` for COBOL truncation or `MidpointRounding.AwayFromZero` for `ROUNDED`).
  - Isolate EBCDIC (`Encoding.GetEncoding(...)`) and copybook byte marshaling inside the ACL adapter.
- Route a controlled slice of traffic through YARP, the API gateway, or feature toggles and verify with Testcontainers.

### Rearchitect Stage 4: Parity Validation, Cutover & Legacy Decommissioning

- Run shadow/parallel comparisons and `baseline_gate.py verify` + `baseline_gate.py gate --type completeness` to prove behavioral parity across all `TC-XXX` test cases and `REQ-XXX` / `BR-XXX` requirements.
- Shift 100% traffic to the new slice, remove retired projects, legacy `Web.config` routes, and temporary adapters, and update the ADR status to `Accepted & Implemented`.
