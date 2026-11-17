#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Inventory a Java / JVM repository for modernization triage, refactoring, and rearchitecture.

Scans Maven (``pom.xml``) and Gradle (``build.gradle``, ``build.gradle.kts``) build manifests,
Java EE / WebSphere / Struts deployment descriptors (``web.xml``, ``ejb-jar.xml``,
``struts.xml``, ``struts-config.xml``, ``ibm-web-bnd.xml``, ``ibm-ejb-jar-bnd.xml``), and
``.java`` / ``.jsp`` source files. Reports modules, Java and Spring Boot versions, direct
dependencies, ``javax.*`` vs. ``jakarta.*`` usage, entry points, JPA/SQL data access, and
modernization or security risks.

The script is read-only and uses only the Python standard library.

Examples:
    uv run --script scripts/java_inventory.py . --format markdown
    uv run --script scripts/java_inventory.py path/to/repo > java-inventory.json
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

SKIP_DIRS = frozenset({".git", "target", "build", ".gradle", ".idea", "node_modules", ".modernize"})
JAKARTA_ELIGIBLE = frozenset(
    {
        "javax.servlet",
        "javax.persistence",
        "javax.validation",
        "javax.annotation",
        "javax.transaction",
        "javax.ejb",
        "javax.jms",
        "javax.ws.rs",
        "javax.xml.bind",
        "javax.xml.ws",
        "javax.mail",
    }
)
DESCRIPTOR_NAMES = frozenset(
    {
        "web.xml",
        "ejb-jar.xml",
        "application.xml",
        "struts.xml",
        "struts-config.xml",
        "ibm-web-bnd.xml",
        "ibm-ejb-jar-bnd.xml",
        "weblogic.xml",
        "jboss-web.xml",
    }
)
PACKAGE_DECL = re.compile(r"^\s*package\s+([A-Za-z0-9_.]+)\s*;", re.MULTILINE)
IMPORT_DECL = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+)\s*;", re.MULTILINE)
ENDPOINT_ANNOTATIONS = re.compile(
    r"@(RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|"
    r"DeleteMapping|PatchMapping|Path|WebServlet|JmsListener|KafkaListener|RabbitListener|"
    r"Scheduled)\b"
)
ENTITY_TABLE = re.compile(r'@Table\s*\([^)]*?\bname\s*=\s*"([^"]+)"')
SQL_TABLE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?)\b", re.IGNORECASE
)
RISK_PATTERNS = {
    "ejb_component": re.compile(r"@(?:Stateless|Stateful|MessageDriven|EJB)\b|\bSessionBean\b"),
    "jndi_lookup": re.compile(r"\bInitialContext\b|\.lookup\s*\("),
    "struts_action": re.compile(
        r"\bextends\s+(?:Action|DispatchAction|ActionSupport|ActionForm)\b"
    ),
    "websphere_binding": re.compile(r"\bcom\.ibm\.(?:websphere|mq|ejs)\b"),
    "float_currency": re.compile(
        r"\b(?:float|double|Float|Double)\s+\w*(?:amount|balance|price|rate|total|fee|tax|amt)\w*\b",
        re.IGNORECASE,
    ),
    "sql_concatenation": re.compile(
        r'(?:executeQuery|executeUpdate|createQuery|createNativeQuery)\s*\(\s*"[^"]*"\s*\+'
    ),
    "java_serialization": re.compile(r"\bObjectInputStream\b|\.readObject\s*\("),
    "hardcoded_secret": re.compile(
        r'\b(?:password|secret|apiKey|clientSecret)\s*=\s*"[^"${]{6,}"', re.IGNORECASE
    ),
    "synchronized_io": re.compile(r"\bsynchronized\s*\("),
}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_pom(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    module: dict[str, Any] = {
        "path": rel,
        "build_tool": "maven",
        "packaging": "jar",
        "java_version": None,
        "spring_boot_version": None,
        "dependencies": [],
    }
    try:
        tree = ET.parse(path)  # noqa: S314
    except ET.ParseError:
        return module
    elem = tree.getroot()
    props: dict[str, str] = {}
    for child in elem:
        tag = _strip_ns(child.tag)
        if tag == "packaging" and child.text:
            module["packaging"] = child.text.strip()
        elif tag == "parent":
            parent_group = ""
            parent_artifact = ""
            parent_version = ""
            for pchild in child:
                ptag = _strip_ns(pchild.tag)
                if ptag == "groupId" and pchild.text:
                    parent_group = pchild.text.strip()
                elif ptag == "artifactId" and pchild.text:
                    parent_artifact = pchild.text.strip()
                elif ptag == "version" and pchild.text:
                    parent_version = pchild.text.strip()
            if "spring-boot" in parent_group or "spring-boot" in parent_artifact:
                module["spring_boot_version"] = parent_version
        elif tag == "properties":
            for prop in child:
                if prop.text:
                    props[_strip_ns(prop.tag)] = prop.text.strip()
        elif tag == "dependencies":
            for dep in child:
                if _strip_ns(dep.tag) != "dependency":
                    continue
                vals = {_strip_ns(c.tag): (c.text or "").strip() for c in dep}
                coord = f"{vals.get('groupId', '?')}:{vals.get('artifactId', '?')}"
                if vals.get("version"):
                    coord = f"{coord}:{vals['version']}"
                module["dependencies"].append(coord)

    for key in ("maven.compiler.release", "maven.compiler.source", "java.version"):
        if props.get(key):
            module["java_version"] = props[key]
            break
    if not module["spring_boot_version"] and props.get("spring-boot.version"):
        module["spring_boot_version"] = props["spring-boot.version"]
    return module


def _parse_gradle(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = path.relative_to(root).as_posix()
    java_ver = None
    for pat in (
        r"sourceCompatibility\s*=\s*['\"]?([0-9.]+)",
        r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)",
        r"jvmToolchain\(\s*(\d+)\s*\)",
    ):
        match = re.search(pat, text)
        if match:
            java_ver = match.group(1)
            break
    sb_match = re.search(
        r"org\.springframework\.boot['\"]?\s*\)\s*version\s*['\"]([^'\"]+)['\"]", text
    )
    deps = re.findall(
        r"\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(?['\"]([^'\"]+:[^'\"]+)['\"]",
        text,
    )
    return {
        "path": rel,
        "build_tool": "gradle",
        "packaging": "war" if re.search(r"id\s*\(?['\"]war['\"]", text) else "jar",
        "java_version": java_ver,
        "spring_boot_version": sb_match.group(1) if sb_match else None,
        "dependencies": sorted(set(deps)),
    }


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
    """Scan ``root`` and return a structured Java modernization inventory."""
    base = root if root.is_dir() else root.parent
    modules: list[dict[str, Any]] = []
    descriptors: list[dict[str, str]] = []
    javax_packages: Counter[str] = Counter()
    jakarta_packages: Counter[str] = Counter()
    entry_points: list[dict[str, str]] = []
    db_tables: set[str] = set()
    risk_totals: Counter[str] = Counter()
    files_with_risks: list[dict[str, Any]] = []
    java_files = 0
    jsp_files = 0
    total_loc = 0

    for path in _iter_files(root):
        name = path.name
        rel = path.relative_to(base).as_posix()
        if name == "pom.xml":
            modules.append(_parse_pom(path, base))
            continue
        if name in {"build.gradle", "build.gradle.kts"}:
            modules.append(_parse_gradle(path, base))
            continue
        if name.lower() in DESCRIPTOR_NAMES:
            descriptors.append({"path": rel, "kind": name.lower()})
            if name.lower().startswith("ibm-"):
                risk_totals["websphere_binding"] += 1
            elif name.lower().startswith("struts"):
                risk_totals["struts_action"] += 1
            elif name.lower() == "ejb-jar.xml":
                risk_totals["ejb_component"] += 1
            continue
        if path.suffix.lower() == ".jsp":
            jsp_files += 1
            continue
        if path.suffix.lower() != ".java":
            continue

        java_files += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        total_loc += sum(1 for line in text.splitlines() if line.strip())
        pkg_match = PACKAGE_DECL.search(text)
        pkg = pkg_match.group(1) if pkg_match else "(default)"

        file_risks: Counter[str] = Counter()
        for imp in IMPORT_DECL.findall(text):
            parts = imp.split(".")
            prefix = ".".join(parts[:2])
            prefix3 = ".".join(parts[:3])
            if prefix in JAKARTA_ELIGIBLE or prefix3 in JAKARTA_ELIGIBLE:
                key = prefix3 if prefix3 in JAKARTA_ELIGIBLE else prefix
                javax_packages[key] += 1
                file_risks["javax_namespace"] += 1
            elif parts[0] == "jakarta" and len(parts) > 1:
                jakarta_packages[prefix] += 1

        entry_points.extend(
            {"path": rel, "package": pkg, "kind": f"@{ann}"}
            for ann in sorted(set(ENDPOINT_ANNOTATIONS.findall(text)))
        )

        db_tables.update(t.upper() for t in ENTITY_TABLE.findall(text))
        for sql_match in SQL_TABLE.findall(text):
            if len(sql_match) > 2 and sql_match.upper() not in {"SELECT", "DUAL", "WHERE"}:
                db_tables.add(sql_match.upper())

        for risk_name, pattern in RISK_PATTERNS.items():
            count = len(pattern.findall(text))
            if count:
                file_risks[risk_name] += count

        if file_risks:
            risk_totals.update(file_risks)
            files_with_risks.append(
                {
                    "path": rel,
                    "package": pkg,
                    "risks": dict(sorted(file_risks.items())),
                    "score": sum(file_risks.values()),
                }
            )

    files_with_risks.sort(key=lambda item: (-item["score"], item["path"]))
    return {
        "tool": "java_inventory",
        "root": str(root),
        "summary": {
            "modules": len(modules),
            "java_files": java_files,
            "jsp_files": jsp_files,
            "code_lines": total_loc,
            "descriptors": len(descriptors),
            "entry_points": len(entry_points),
            "db_tables": len(db_tables),
            "risk_totals": dict(sorted(risk_totals.items())),
        },
        "modules": modules,
        "descriptors": descriptors,
        "javax_imports": dict(sorted(javax_packages.items())),
        "jakarta_imports": dict(sorted(jakarta_packages.items())),
        "entry_points": entry_points,
        "db_tables": sorted(db_tables),
        "risk_files": files_with_risks,
    }


def to_markdown(inventory: dict[str, Any]) -> str:
    """Render the Java inventory as a Markdown summary."""
    summary = inventory["summary"]
    lines = [
        f"# Java Inventory: `{inventory['root']}`",
        "",
        f"- **Modules:** {summary['modules']}",
        f"- **Java files:** {summary['java_files']} ({summary['code_lines']} code lines)",
        f"- **JSP files:** {summary['jsp_files']}",
        f"- **Entry points:** {summary['entry_points']}",
        f"- **Database tables:** {summary['db_tables']}",
        "",
    ]
    if inventory["modules"]:
        lines.extend(
            [
                "## Build Modules",
                "",
                "| Path | Tool | Packaging | Java | Spring Boot | Direct Deps |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| `{mod['path']}` | {mod['build_tool']} | {mod['packaging']} | "
            f"{mod['java_version'] or '?'} | {mod['spring_boot_version'] or '-'} | "
            f"{len(mod['dependencies'])} |"
            for mod in inventory["modules"]
        )
        lines.append("")
    if inventory["javax_imports"]:
        lines.extend(["## `javax.*` Packages Requiring Jakarta Migration", ""])
        for pkg, count in inventory["javax_imports"].items():
            lines.append(f"- `{pkg}` ({count} imports)")
        lines.append("")
    if summary["risk_totals"]:
        lines.extend(["## Modernization & Security Risk Totals", ""])
        for risk, count in summary["risk_totals"].items():
            lines.append(f"- `{risk}`: {count}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Java project root directory or file.")
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
