---
name: dotnet-analysis
description: .NET stack profile for the modernization playbooks. Analyzes .NET estates (.sln, .slnx, .csproj, packages.config, Directory.Packages.props, Web.config, .NET Framework 4.x to modern .NET 8/9, ASP.NET to ASP.NET Core, WCF, EF6 to EF Core) and supplies the .NET tasks for every Refactor and Rearchitect stage, both when modernizing a .NET codebase in place and when targeting .NET as the destination of a mainframe or legacy migration. Bundled script only reads files.
license: MIT
compatibility: Python 3.11+, standard library only; run with uv or python3.
metadata:
  author: markbsigler
  version: "1.0"
---

# .NET Analysis (.NET Framework / Modern .NET / ASP.NET Core)

The .NET stack profile for `modernization-triage`, `playbook-refactor`, and `playbook-rearchitect`. Triage loads it when the scope contains .NET solutions, projects, or configuration files, or when modern .NET (ASP.NET Core, Worker Services) is the target stack of a cross-stack rearchitecture or language conversion.

## Stack profile

| Profile part | Where in this skill |
| --- | --- |
| Detection signals | [Detection signals](#detection-signals) |
| Discovery and estate brief | [Workflow](#workflow), Steps 1 to 3 |
| Contract surface | Operating rule 3 |
| Elicitation addendum | [Elicitation addendum](#elicitation-addendum) |
| Classification examples | [Classification examples](#classification-examples) |
| Playbook stage tasks | [references/playbook-stages.md](references/playbook-stages.md): `Refactor Stage 1` to `4` and `Rearchitect Stage 1` to `4` |
| Equivalence evidence and NFR baselines | [references/upgrade-and-migration.md](references/upgrade-and-migration.md) |
| Target platforms and transition patterns | [references/upgrade-and-migration.md](references/upgrade-and-migration.md) |

### Detection signals

- Solutions and projects: `*.sln`, `*.slnx`, `*.csproj`, `*.fsproj`, `*.vbproj`, `Directory.Build.props`, `Directory.Packages.props`, `packages.config`.
- Configuration and web descriptors: `Web.config`, `app.config`, `appsettings.json`, `Global.asax`.
- Mentions of .NET Framework 4.x, .NET Core, .NET 6/7/8/9, ASP.NET MVC/WebForms/Web API, ASP.NET Core, WCF, Entity Framework (EF6 / EF Core), or NuGet.

### Elicitation addendum

Ask only what `scripts/dotnet_inventory.py` and `.modernize/rulebook/` could not determine:
1. **Target .NET release and OS posture:** for example .NET 8/9 LTS on Linux containers, or staying on Windows where Windows-only APIs remain in scope.
2. **Transition strategy for large ASP.NET apps:** incremental YARP (System.Web Adapters) strangler proxy or direct project upgrade?
3. **Database and messaging test strategy:** Testcontainers for .NET (SQL Server, PostgreSQL, Azurite, Service Bus, RabbitMQ) or existing integration environments?

### Classification examples

| Request | Route |
| --- | --- |
| Converting legacy non-SDK `.csproj` and `packages.config` to SDK-style projects and `PackageReference` / `Directory.Packages.props` | Refactor |
| Upgrading .NET Core 3.1 / .NET 6 to .NET 8/9 LTS, or remediating NuGet CVEs without changing external APIs or topology | Refactor |
| Migrating an ASP.NET MVC / Web API or WCF service to ASP.NET Core / CoreWCF with identical HTTP/SOAP routes and payloads | Refactor |
| Decomposing a monolithic .NET solution into microservices or event-driven worker services, or extracting a bounded context behind YARP | Rearchitect |
| Extracting or converting a mainframe COBOL/CICS or batch workload into .NET 8/9 services | Rearchitect (load `mainframe-analysis` as legacy profile and `dotnet-analysis` as target profile) |

## Operating rules

1. **Evidence from project files and source.** Run `./scripts/dotnet_inventory.py` before proposing an upgrade order or seam split.
2. **SDK-style projects and `.NET Standard 2.0` first.** Migrate `packages.config` to `PackageReference` and shared class libraries to `netstandard2.0` (or multi-target `net48;net8.0`) before upgrading executable hosts.
3. **Contracts are wider than controller signatures.** JSON casing and date/enum serialization (`Newtonsoft.Json` vs. `System.Text.Json`), SOAP/WCF namespaces, model validation error envelopes, headers, EF migrations, and process exit codes are all part of the external contract surface.
4. **`decimal` for money and scaled quantities.** Never use `float` or `double` for currency, rates, or mainframe `COMP-3` / zoned-decimal fields; use C# `decimal` with explicit rounding (`MidpointRounding.ToZero` for COBOL truncation or `MidpointRounding.AwayFromZero` for `ROUNDED`).
5. **Read-only discovery.** The bundled inventory script only reads files.

## Workflow

### Step 1: Inventory the .NET estate

Run the inventory script on the repository root:

```bash
uv run --script ./scripts/dotnet_inventory.py <project-dir> --format markdown
uv run --script ./scripts/dotnet_inventory.py <project-dir> > .modernize/dotnet-inventory.json
```

It reports solutions, projects (`sdk_style`, target frameworks, legacy `net4x` vs. modern `.NET`), NuGet packages (from `PackageReference`, `Directory.Packages.props`, and `packages.config`), configuration files (`Web.config`, `appsettings.json`), entry points (ASP.NET / ASP.NET Core controllers, Minimal APIs, WCF `[ServiceContract]`, gRPC, `BackgroundService`), EF/SQL tables, and modernization/security risks (`legacy_target_framework`, `packages_config`, `system_web`, `wcf_service`, `ef6_context`, `windows_registry_or_com`, `binary_formatter`, `float_currency`, `sql_concatenation`, `hardcoded_secret`).

### Step 2: Load the rules for the findings

Read [references/playbook-stages.md](references/playbook-stages.md) for the active playbook stage and [references/upgrade-and-migration.md](references/upgrade-and-migration.md) for .NET Framework → .NET 8/9, `System.Web` / WCF / EF6 migration, `Newtonsoft.Json` vs. `System.Text.Json` parity, and mainframe-to-.NET data rules.

### Step 3: Report the .NET Estate Brief

```markdown
## .NET Estate Brief: <scope>
- **Solutions & projects:** <count, SDK-style vs. legacy, target frameworks>
- **Package management:** <PackageReference, Central Package Management, or legacy packages.config>
- **Entry points & contracts:** <Controllers, Minimal APIs, WCF/SOAP, gRPC, Worker Services>
- **Windows & .NET Framework coupling:** <System.Web, WCF, EF6, Registry/COM/WMI, Web.config>
- **Data & messaging:** <DbContext entities, SQL tables, Service Bus / Kafka / RabbitMQ>
- **Risk hotspots:** <risk counts and top affected files>
```
