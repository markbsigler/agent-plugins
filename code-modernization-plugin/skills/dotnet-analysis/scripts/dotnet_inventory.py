#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Inventory a .NET repository for modernization triage, refactoring, and rearchitecture.

Scans solution files (``.sln``, ``.slnx``), project files (``.csproj``, ``.fsproj``,
``.vbproj``), NuGet manifests (``packages.config``, ``Directory.Packages.props``),
configuration files (``Web.config``, ``app.config``, ``appsettings.json``), and ``.cs`` source
files. Reports SDK-style vs. legacy projects, target frameworks, NuGet dependencies, entry
points, EF/SQL data access, and modernization or security risks.

The script is read-only and uses only the Python standard library.

Examples:
    uv run --script scripts/dotnet_inventory.py . --format markdown
    uv run --script scripts/dotnet_inventory.py path/to/repo > dotnet-inventory.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

SKIP_DIRS = frozenset({".git", "bin", "obj", ".vs", "packages", "node_modules", ".modernize"})
PROJECT_SUFFIXES = frozenset({".csproj", ".fsproj", ".vbproj"})
LEGACY_TFM = re.compile(r"^(?:net[1-4]\d*|v[1-4]\.\d+(?:\.\d+)?)$", re.IGNORECASE)
NAMESPACE_DECL = re.compile(r"^\s*namespace\s+([A-Za-z0-9_.]+)", re.MULTILINE)
ENDPOINT_PATTERNS = re.compile(
    r"(\[(?:ApiController|Route|HttpGet|HttpPost|HttpPut|HttpDelete|ServiceContract|"
    r"OperationContract|WebMethod)\b|\b(?:MapGet|MapPost|MapPut|MapDelete|MapGrpcService)\s*\("
    r"|\b:\s*(?:ControllerBase|Controller|ApiController|BackgroundService|IHostedService)\b)"
)
TABLE_ATTR = re.compile(r'\[Table\s*\(\s*"([^"]+)"')
DBSET_PROP = re.compile(r"\bDbSet\s*<\s*([A-Za-z0-9_]+)\s*>\s+([A-Za-z0-9_]+)")
SQL_TABLE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\b", re.IGNORECASE
)
RISK_PATTERNS = {
    "system_web": re.compile(r"\busing\s+System\.Web\b|\bHttpContext\.Current\b"),
    "wcf_service": re.compile(r"\busing\s+System\.ServiceModel\b|\[ServiceContract\b"),
    "ef6_context": re.compile(r"\busing\s+System\.Data\.Entity\b|\bObjectContext\b"),
    "windows_registry_or_com": re.compile(
        r"\bMicrosoft\.Win32\.Registry\b|\[DllImport\b|\[ComImport\b|\bSystem\.Management\b"
    ),
    "binary_formatter": re.compile(r"\bBinaryFormatter\b|\bNetDataContractSerializer\b"),
    "float_currency": re.compile(
        r"\b(?:float|double|Single|Double)\s+\w*(?:amount|balance|price|rate|total|fee|tax|amt)\w*\b",
        re.IGNORECASE,
    ),
    "sql_concatenation": re.compile(
        r"\b(?:SqlCommand|FromSqlRaw|ExecuteSqlRaw)\s*\(\s*(?:\$\"|\"[^\"]*\"\s*\+)"
    ),
    "hardcoded_secret": re.compile(
        r'\b(?:Password|Secret|ApiKey|ClientSecret)\s*=\s*"?[^";$\s]{6,}"?', re.IGNORECASE
    ),
}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_project(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    project: dict[str, Any] = {
        "path": rel,
        "sdk_style": False,
        "target_frameworks": [],
        "legacy_framework": False,
        "packages": [],
    }
    try:
        tree = ET.parse(path)  # noqa: S314
    except ET.ParseError:
        return project
    elem = tree.getroot()
    if "Sdk" in elem.attrib or any(_strip_ns(c.tag) == "Sdk" for c in elem):
        project["sdk_style"] = True

    tfms: list[str] = []
    pkgs: list[str] = []
    for node in elem.iter():
        tag = _strip_ns(node.tag)
        text = (node.text or "").strip()
        if tag in {"TargetFramework", "TargetFrameworks", "TargetFrameworkVersion"} and text:
            tfms.extend(part.strip() for part in text.split(";") if part.strip())
        elif tag == "PackageReference":
            include = node.attrib.get("Include") or node.attrib.get("Update") or ""
            version = node.attrib.get("Version") or ""
            if not version:
                ver_child = next((c for c in node if _strip_ns(c.tag) == "Version"), None)
                version = (ver_child.text or "").strip() if ver_child is not None else ""
            if include:
                pkgs.append(f"{include}:{version}" if version else include)

    project["target_frameworks"] = sorted(set(tfms))
    project["legacy_framework"] = any(
        LEGACY_TFM.match(t) for t in project["target_frameworks"]
    ) or (not project["sdk_style"])
    project["packages"] = sorted(set(pkgs))
    return project


def _parse_packages_config(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    packages: list[str] = []
    try:
        tree = ET.parse(path)  # noqa: S314
        for node in tree.getroot().iter():
            if _strip_ns(node.tag) == "package":
                pkg_id = node.attrib.get("id", "")
                ver = node.attrib.get("version", "")
                if pkg_id:
                    packages.append(f"{pkg_id}:{ver}" if ver else pkg_id)
    except ET.ParseError:
        pass
    return {"path": rel, "packages": sorted(set(packages))}


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts):
            continue
        yield path


def build_inventory(root: Path) -> dict[str, Any]:
    """Scan ``root`` and return a structured .NET modernization inventory."""
    base = root if root.is_dir() else root.parent
    solutions: list[str] = []
    projects: list[dict[str, Any]] = []
    packages_configs: list[dict[str, Any]] = []
    config_files: list[str] = []
    central_package_management = False
    entry_points: list[dict[str, str]] = []
    db_tables: set[str] = set()
    risk_totals: Counter[str] = Counter()
    files_with_risks: list[dict[str, Any]] = []
    cs_files = 0
    total_loc = 0

    for path in _iter_files(root):
        name = path.name
        lower = name.lower()
        rel = path.relative_to(base).as_posix()
        if path.suffix.lower() in {".sln", ".slnx"}:
            solutions.append(rel)
            continue
        if path.suffix.lower() in PROJECT_SUFFIXES:
            proj = _parse_project(path, base)
            projects.append(proj)
            if proj["legacy_framework"]:
                risk_totals["legacy_target_framework"] += 1
            continue
        if lower == "packages.config":
            packages_configs.append(_parse_packages_config(path, base))
            risk_totals["packages_config"] += 1
            continue
        if lower == "directory.packages.props":
            central_package_management = True
            continue
        if lower in {"web.config", "app.config"} or (
            lower.startswith("appsettings") and lower.endswith(".json")
        ):
            config_files.append(rel)
            continue
        if path.suffix.lower() != ".cs":
            continue

        cs_files += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        total_loc += sum(1 for line in text.splitlines() if line.strip())
        ns_match = NAMESPACE_DECL.search(text)
        namespace = ns_match.group(1) if ns_match else "(global)"

        matches = sorted({m.strip("[:( ") for m in ENDPOINT_PATTERNS.findall(text)})
        entry_points.extend({"path": rel, "namespace": namespace, "kind": kind} for kind in matches)

        db_tables.update(t.upper() for t in TABLE_ATTR.findall(text))
        db_tables.update(prop.upper() for _, prop in DBSET_PROP.findall(text))
        for sql_match in SQL_TABLE.findall(text):
            if len(sql_match) > 2 and sql_match.upper() not in {"SELECT", "WHERE", "SET"}:
                db_tables.add(sql_match.upper())

        file_risks: Counter[str] = Counter()
        for risk_name, pattern in RISK_PATTERNS.items():
            count = len(pattern.findall(text))
            if count:
                file_risks[risk_name] += count

        if file_risks:
            risk_totals.update(file_risks)
            files_with_risks.append(
                {
                    "path": rel,
                    "namespace": namespace,
                    "risks": dict(sorted(file_risks.items())),
                    "score": sum(file_risks.values()),
                }
            )

    files_with_risks.sort(key=lambda item: (-item["score"], item["path"]))
    return {
        "tool": "dotnet_inventory",
        "root": str(root),
        "summary": {
            "solutions": len(solutions),
            "projects": len(projects),
            "legacy_projects": sum(1 for p in projects if p["legacy_framework"]),
            "cs_files": cs_files,
            "code_lines": total_loc,
            "central_package_management": central_package_management,
            "packages_configs": len(packages_configs),
            "entry_points": len(entry_points),
            "db_tables": len(db_tables),
            "risk_totals": dict(sorted(risk_totals.items())),
        },
        "solutions": solutions,
        "projects": projects,
        "packages_configs": packages_configs,
        "config_files": config_files,
        "entry_points": entry_points,
        "db_tables": sorted(db_tables),
        "risk_files": files_with_risks,
    }


def to_markdown(inventory: dict[str, Any]) -> str:
    """Render the .NET inventory as a Markdown summary."""
    summary = inventory["summary"]
    cpm = "yes" if summary["central_package_management"] else "no"
    lines = [
        f"# .NET Inventory: `{inventory['root']}`",
        "",
        f"- **Solutions:** {summary['solutions']}",
        f"- **Projects:** {summary['projects']} ({summary['legacy_projects']} legacy)",
        f"- **C# files:** {summary['cs_files']} ({summary['code_lines']} code lines)",
        f"- **Central Package Management:** {cpm}",
        f"- **Entry points:** {summary['entry_points']}",
        f"- **Database tables / DbSets:** {summary['db_tables']}",
        "",
    ]
    if inventory["projects"]:
        lines.extend(
            [
                "## Projects",
                "",
                "| Path | SDK-Style | Target Frameworks | Legacy | Packages |",
                "| --- | --- | --- | --- | --- |",
                *[
                    f"| `{proj['path']}` | {'yes' if proj['sdk_style'] else 'no'} | "
                    f"{', '.join(proj['target_frameworks']) or '?'} | "
                    f"{'yes' if proj['legacy_framework'] else 'no'} | {len(proj['packages'])} |"
                    for proj in inventory["projects"]
                ],
                "",
            ]
        )
    if summary["risk_totals"]:
        lines.extend(
            [
                "## Modernization & Security Risk Totals",
                "",
                *[f"- `{risk}`: {count}" for risk, count in summary["risk_totals"].items()],
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help=".NET solution/project root directory or file.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    if not args.root.exists():
        print(f"error: path not found: {args.root}", file=sys.stderr)
        return 1
    inventory = build_inventory(args.root)
    if args.format == "markdown":
        print(to_markdown(inventory), end="")
    else:
        print(json.dumps(inventory, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
