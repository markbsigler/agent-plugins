# .NET Upgrade, Rearchitecture & Target Migration Rules

Reference guidance for `dotnet-analysis`.

## 1. .NET Framework 4.x → Modern .NET (8 / 9 LTS)

- **Upgrade bottom-up:** Leaf class libraries with no `System.Web` or Windows-specific dependencies should move to SDK-style `.csproj` targeting `netstandard2.0` (or multi-targeting `net48;net8.0`) first so both legacy `.NET Framework` hosts and new `.NET` services can reference them during transition.
- **ASP.NET (`System.Web`) to ASP.NET Core:**
  - `Global.asax`, `HttpModules`, and `HttpHandlers` map to ASP.NET Core middleware (`Program.cs`).
  - For large ASP.NET MVC / WebForms applications that cannot migrate in one pass, place a YARP (`Yarp.ReverseProxy`) ASP.NET Core host in front of the legacy app and use `Microsoft.AspNetCore.SystemWebAdapters` to share authentication and session state while controllers are extracted slice by slice.
- **WCF (`System.ServiceModel`):**
  - Client-side WCF calls are supported on modern .NET via `System.ServiceModel.Primitives` / `System.ServiceModel.Http`.
  - Server-side WCF contracts (`[ServiceContract]`, `[OperationContract]`) can be hosted on ASP.NET Core using **CoreWCF** when SOAP callers must remain unchanged, or rearchitecting to gRPC / OpenAPI behind an ACL when boundaries are modernized.
- **Entity Framework 6 → EF Core:**
  - EF Core does not support `.edmx` designer files; use code-first `DbContext` + fluent configuration.
  - Audit lazy-loading assumptions, client-side LINQ evaluation (EF Core throws on un-translatable expressions that EF6 silently evaluated in memory), and `DateTime` / `decimal(p, s)` column precision.

## 2. `Newtonsoft.Json` vs. `System.Text.Json` Contract Parity

Moving from `Newtonsoft.Json` to `System.Text.Json` is a frequent source of subtle contract drift during Refactor:
- Property casing (`CamelCasePropertyNamesContractResolver` vs. `JsonNamingPolicy.CamelCase`)
- String-to-number coercion (`JsonNumberHandling.AllowReadingFromString`)
- Reference loop handling (`ReferenceLoopHandling.Ignore` vs. `ReferenceHandler.IgnoreCycles`)
- Date/time and timezone formatting.

If strict wire parity is required in a Refactor track, either keep `Microsoft.AspNetCore.Mvc.NewtonsoftJson` until callers are covered by golden snapshot tests or configure `JsonSerializerOptions` to match the frozen Stage 2 snapshots byte-for-byte.

## 3. .NET as the Target of a Mainframe Migration

When `dotnet-analysis` is loaded alongside `mainframe-analysis` for a COBOL/PL/I/CICS/IMS → .NET modernization:

- **Arithmetic & `decimal`:**
  - Map every `PIC 9(n)V9(m)` / `COMP-3` / zoned-decimal field to C# `decimal`.
  - C# `Math.Round(d, scale)` defaults to banker's rounding (`MidpointRounding.ToEven`), whereas COBOL truncates toward zero (`MidpointRounding.ToZero`) unless `ROUNDED` is coded (`MidpointRounding.AwayFromZero` for standard COBOL absolute rounding). Wrap COBOL arithmetic rules in explicit helper methods tested against mainframe golden records.
- **EBCDIC & Code Pages:**
  - Register code-page encodings with `Encoding.RegisterProvider(CodePagesEncodingProvider.Instance)` before resolving `IBM037`, `IBM1140`, or national EBCDIC code pages, and never decode binary/packed records with text `Encoding` (use field-level byte slicing from the copybook layout).
