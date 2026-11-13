#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Turn a mainframe inventory into seam evidence for rearchitecture.

Reads the JSON or JSON Lines inventory from mainframe_inventory.py (or scans export
directories with ``--scan``) and reports:

- a data ownership matrix: every table, data set, CICS file, IMS segment, and MQ queue with the
  programs and jobs that create, read, update, or delete it. Program DD names and CICS files
  are resolved to the data sets behind them through JCL steps and the CSD, and resources with
  more than one writer are flagged;
- write clusters: groups of programs and resources joined by writes, which are candidate
  bounded contexts (shared readers are listed, because they become API or event consumers);
- transaction footprints: for each CICS transaction, the programs reached through LINK, XCTL,
  and CALL, the resources they touch, the units of work (SYNCPOINT), the next transactions in
  a pseudo-conversation, and LINK and data-request counts that set a latency budget;
- interfaces: data sets read but never written in the estate (inbound feeds), written but
  never read (outbound feeds), file transfers, MQ queues, web endpoints, remote Db2
  locations, printed reports, and 3270 screens.

The analysis is static: confirm writers with the code and runtime evidence before you draw a
boundary. The script only reads files.

Examples:
    uv run --script seam_report.py inventory.json --format markdown
    uv run --script seam_report.py --scan exports/ --transaction CINQ --format mermaid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mainframe_inventory

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

RESOURCE_TYPES = frozenset(
    {"db2-table", "dataset", "cics-file", "cics-queue", "ims-segment", "mq-queue", "adabas-file"}
)
PROGRAM_EDGES = frozenset({"call", "cics-link", "cics-xctl", "cics-load", "load-link"})
WRITES = frozenset("CUD")
CRUD = "CRUD"
MAX_DEPTH = 25


def load_inventory(path: Path) -> dict[str, Any]:
    """Read an inventory written as JSON or as JSON Lines."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        inventory: dict[str, Any] = {"members": [], "edges": []}
        for line in text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            kind = record.pop("record", None)
            if kind == "summary":
                inventory["tool"] = record.pop("tool")
                inventory["roots"] = record.pop("roots")
                inventory["summary"] = record
            elif kind == "section":
                inventory[record["name"]] = record["data"]
            elif kind in {"member", "edge"}:
                inventory[f"{kind}s"].append(record)
        return inventory


def _crud(operations: Iterable[str]) -> str:
    present = set(operations)
    return "".join(letter for letter in CRUD if letter in present)


def _dataset_name(dsn: str) -> str:
    """Drop a GDG relative generation or a PDS member from a data set name."""
    return re.sub(r"\((?:[+-]?\d+|[A-Z0-9@#$]{1,8})\)$", "", dsn)


def _step_programs(step: dict[str, Any]) -> list[str]:
    names = [step.get("program"), step.get("proc_program"), step.get("ims_program")]
    return [name for name in [*names, *step.get("db2_programs", [])] if name]


def ownership(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return resources keyed ``type:name`` with the actors that use them and how.

    A batch data set is credited to the program that opens its DD when the program's access
    is known, and otherwise to ``JOB.STEP`` (utilities, unscanned programs). CICS files are
    credited both as files and, through the CSD DSNAME, as the data sets behind them.
    """
    resources: dict[str, dict[str, Any]] = {}

    def record(kind: str, name: str, actor: str, operations: str, via: str = "") -> None:
        entry = resources.setdefault(f"{kind}:{name}", {"type": kind, "name": name, "actors": {}})
        use = entry["actors"].setdefault(actor, {"ops": "", "via": []})
        use["ops"] = _crud(set(use["ops"]) | set(operations))
        if via and via not in use["via"]:
            use["via"].append(via)

    program_dds = {
        (edge["from"], edge["to"]): edge["access"]
        for edge in inventory["edges"]
        if edge["type"] == "ddname" and edge.get("access")
    }
    jcl_members = set()
    for member in inventory["members"]:
        if member["kind"] not in {"jcl-job", "jcl-proc"}:
            continue
        details = member.get("details", {})
        job = details.get("name") or member["name"]
        jcl_members.add(job)
        for step in details.get("steps", []):
            programs = _step_programs(step)
            for entry in details.get("datasets", []):
                if entry["step"] != step["step"] or "access" not in entry:
                    continue
                dataset, where = _dataset_name(entry["dsn"]), f"{job}.{step['step']}"
                opened = [p for p in programs if (p, entry["dd"]) in program_dds]
                for program in opened:
                    ops = program_dds[(program, entry["dd"])]
                    record("dataset", dataset, program, ops, via=f"{where} DD {entry['dd']}")
                if not opened:
                    runs = step.get("program") or f"PROC {step.get('proc', '?')}"
                    record("dataset", dataset, where, entry["access"], via=runs)
    cics_files = {
        name: attrs["dsname"]
        for name, attrs in inventory.get("cics", {}).get("files", {}).items()
        if attrs.get("dsname")
    }
    for edge in inventory["edges"]:
        operations, kind, name, actor = edge.get("access"), edge["type"], edge["to"], edge["from"]
        if not operations or kind == "ddname" or (kind == "dataset" and actor in jcl_members):
            continue
        if kind == "cics-file" and name in cics_files:
            record("dataset", cics_files[name], actor, operations, via=f"CICS file {name}")
        if kind in RESOURCE_TYPES:
            record(kind, name, actor, operations)
    for entry in resources.values():
        writers = sorted(a for a, use in entry["actors"].items() if set(use["ops"]) & WRITES)
        entry["writers"] = writers
        entry["readers"] = sorted(a for a in entry["actors"] if a not in writers)
        entry["multiple_writers"] = len(writers) > 1
    return dict(sorted(resources.items()))


def write_clusters(resources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Group programs and resources that are joined by writes (union-find)."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for key, entry in resources.items():
        for writer in entry["writers"]:
            parent[find(f"actor:{writer}")] = find(f"resource:{key}")
    groups: dict[str, dict[str, set[str]]] = {}
    for key, entry in resources.items():
        if not entry["writers"]:
            continue
        root = find(f"resource:{key}")
        group = groups.setdefault(root, {"writers": set(), "resources": set(), "readers": set()})
        group["resources"].add(key)
        group["writers"].update(entry["writers"])
        group["readers"].update(entry["readers"])
    clusters = []
    for group in groups.values():
        outside = sorted(group["readers"] - group["writers"])
        clusters.append(
            {
                "writers": sorted(group["writers"]),
                "resources": sorted(group["resources"]),
                "outside_readers": outside,
            }
        )
    return sorted(clusters, key=lambda c: (-len(c["resources"]), c["resources"]))


def footprints(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return, for each CICS transaction, the programs it reaches and what each one touches.

    Counts are static: every LINK and every resource access inside the footprint becomes a
    network call if the code behind it moves to another service, so together they give the
    latency budget of a split.
    """
    calls: dict[str, set[tuple[str, str]]] = {}
    access: dict[str, set[tuple[str, str, str]]] = {}
    next_transactions: dict[str, set[str]] = {}
    for edge in inventory["edges"]:
        if edge["type"] in PROGRAM_EDGES:
            calls.setdefault(edge["from"], set()).add((edge["type"], edge["to"]))
        if edge.get("access") and edge["type"] in RESOURCE_TYPES:
            access.setdefault(edge["from"], set()).add((edge["type"], edge["to"], edge["access"]))
        if edge["type"] in {"cics-return-transid", "cics-start-transid"}:
            next_transactions.setdefault(edge["from"], set()).add(edge["to"])
    syncpoints = {
        member.get("program_id") or member["name"]: member.get("details", {}).get("syncpoints", 0)
        for member in inventory["members"]
    }
    result: dict[str, dict[str, Any]] = {}
    for transaction, program in sorted(inventory.get("cics_transactions", {}).items()):
        depth = {program: 0}
        queue = deque([program])
        call_edges: list[dict[str, str]] = []
        while queue:
            current = queue.popleft()
            for kind, target in sorted(calls.get(current, set())):
                call_edges.append({"from": current, "type": kind, "to": target})
                if target not in depth and depth[current] < MAX_DEPTH:
                    depth[target] = depth[current] + 1
                    queue.append(target)
        reached = sorted(depth)
        touched = sorted((p, *use) for p in reached for use in access.get(p, set()))
        result[transaction] = {
            "program": program,
            "programs": reached,
            "calls": call_edges,
            "resources": [{"program": p, "type": k, "name": n, "ops": o} for p, k, n, o in touched],
            "updates_in_unit_of_work": sorted(
                {f"{k}:{n}" for _, k, n, o in touched if set(o) & WRITES}
            ),
            "syncpoints": sum(syncpoints.get(p, 0) for p in reached),
            "links": sum(1 for edge in call_edges if edge["type"] == "cics-link"),
            "resource_accesses": len(touched),
            "next_transactions": sorted(
                set().union(*(next_transactions.get(p, set()) for p in reached))
            ),
        }
    return result


def interfaces(inventory: dict[str, Any], resources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return the estate's external interfaces and likely hidden consumers."""
    datasets = [entry for entry in resources.values() if entry["type"] == "dataset"]
    queues = [entry for entry in resources.values() if entry["type"] == "mq-queue"]
    reports = []
    screens = set()
    for member in inventory["members"]:
        details = member.get("details", {})
        job = details.get("name") or member["name"]
        reports.extend({"job": job, **report} for report in details.get("reports", []))
        screens.update(member.get("references", {}).get("bms-mapset", []))
    return {
        "inbound_datasets": sorted(e["name"] for e in datasets if not e["writers"]),
        "outbound_datasets": sorted(
            e["name"]
            for e in datasets
            if e["writers"] and not any("R" in use["ops"] for use in e["actors"].values())
        ),
        "transfers": inventory.get("transfers", []),
        "mq_put_only": sorted(
            e["name"]
            for e in queues
            if all(set(u["ops"]) <= set("CUD") for u in e["actors"].values())
        ),
        "mq_get_only": sorted(e["name"] for e in queues if not e["writers"]),
        "web_endpoints": inventory.get("cics", {}).get("web", {}).get("urimaps", {}),
        "remote_db2_locations": inventory.get("db2", {}).get("remote_locations", []),
        "reports": reports,
        "screens": sorted(screens),
    }


def build_report(inventory: dict[str, Any], transaction: str | None = None) -> dict[str, Any]:
    """Assemble ownership, clusters, footprints, and interfaces."""
    resources = ownership(inventory)
    transactions = footprints(inventory)
    if transaction is not None:
        transactions = {k: v for k, v in transactions.items() if k == transaction.upper()}
    return {
        "tool": "seam_report",
        "resources": resources,
        "multiple_writers": [key for key, entry in resources.items() if entry["multiple_writers"]],
        "write_clusters": write_clusters(resources),
        "transactions": transactions,
        "interfaces": interfaces(inventory, resources),
    }


def _cell(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(map(str, value))
    return str(value).replace("|", "\\|")


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def to_markdown(report: dict[str, Any]) -> str:
    """Render the seam report as Markdown."""
    lines = ["# Seam report", ""]
    rows = []
    for entry in report["resources"].values():
        uses = ", ".join(f"{a} {u['ops']}" for a, u in sorted(entry["actors"].items()))
        rows.append(
            (entry["type"], entry["name"], uses, "yes" if entry["multiple_writers"] else "")
        )
    lines += ["## Data ownership (C create, R read, U update, D delete)", ""]
    lines += _table(["Type", "Resource", "Programs and jobs", "Several writers"], rows)
    if report["write_clusters"]:
        lines += ["## Write clusters (candidate boundaries)", ""]
        lines += _table(
            ["Writers", "Resources", "Readers outside the cluster"],
            (
                (c["writers"], c["resources"], c["outside_readers"])
                for c in report["write_clusters"]
            ),
        )
    if report["transactions"]:
        lines += ["## Transaction footprints", ""]
        lines += _table(
            [
                "Transaction",
                "Programs",
                "Updates in one unit of work",
                "LINKs",
                "Resource accesses",
                "SYNCPOINTs",
                "Next transactions",
            ],
            (
                (
                    name,
                    t["programs"],
                    t["updates_in_unit_of_work"],
                    t["links"],
                    t["resource_accesses"],
                    t["syncpoints"],
                    t["next_transactions"],
                )
                for name, t in report["transactions"].items()
            ),
        )
    found = report["interfaces"]
    labels = {
        "inbound_datasets": "Data sets read but never written here (inbound feeds)",
        "outbound_datasets": "Data sets written but never read here (outbound feeds)",
        "mq_put_only": "Queues only written here",
        "mq_get_only": "Queues only read here",
        "remote_db2_locations": "Remote Db2 locations",
        "screens": "3270 mapsets (check for screen scrapers and RPA)",
    }
    items = [(label, found[key]) for key, label in labels.items() if found[key]]
    if items or found["transfers"] or found["web_endpoints"] or found["reports"]:
        lines += ["## Interfaces and hidden consumers", ""]
        lines += [f"- **{label}:** {', '.join(values)}" for label, values in items]
        lines += [
            f"- **Transfer:** {t['job']}.{t['step']} {t['direction']} {t['local']} "
            f"{'to' if t['direction'] == 'send' else 'from'} {t['host'] or '?'} {t['remote']}"
            for t in found["transfers"]
        ]
        lines += [
            f"- **Web endpoint:** {name} {u.get('path', '')} -> "
            f"{u.get('program') or u.get('pipeline', '')}"
            for name, u in found["web_endpoints"].items()
        ]
        lines += [
            f"- **Report:** {r['job']}.{r['step']} {r['dd']} class {r['class']}"
            + (f" to {r['dest']}" if r.get("dest") else "")
            for r in found["reports"]
        ]
        lines.append("")
    return "\n".join(lines)


def _node(prefix: str, name: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9]", "_", name)


def to_mermaid(report: dict[str, Any]) -> str:
    """Draw transaction footprints (or, without transactions, write clusters) in Mermaid."""
    lines = ["flowchart LR"]
    if report["transactions"]:
        for name, footprint in report["transactions"].items():
            lines.append(
                f'    {_node("t_", name)}(["{name}"]) --> {_node("p_", footprint["program"])}'
            )
            lines.extend(f'    {_node("p_", p)}["{p}"]' for p in footprint["programs"])
            lines.extend(
                f"    {_node('p_', c['from'])} -->|{c['type']}| {_node('p_', c['to'])}"
                for c in footprint["calls"]
            )
            for use in footprint["resources"]:
                node = _node("r_", f"{use['type']}_{use['name']}")
                lines.append(f'    {node}[("{use["name"]}")]')
                lines.append(f"    {_node('p_', use['program'])} -->|{use['ops']}| {node}")
        return "\n".join(dict.fromkeys(lines)) + "\n"
    for index, cluster in enumerate(report["write_clusters"], start=1):
        lines.append(f'    subgraph cluster{index}["Write cluster {index}"]')
        lines.extend(f'        {_node("p_", w)}["{w}"]' for w in cluster["writers"])
        lines.extend(
            f'        {_node("r_", r)}[("{report["resources"][r]["name"]}")]'
            for r in cluster["resources"]
        )
        lines.append("    end")
        for resource in cluster["resources"]:
            entry = report["resources"][resource]
            target = _node("r_", resource)
            lines.extend(
                f"    {_node('p_', w)} -->|{entry['actors'][w]['ops']}| {target}"
                for w in entry["writers"]
            )
            lines.extend(f"    {target} -.->|R| {_node('p_', r)}" for r in entry["readers"])
    return "\n".join(dict.fromkeys(lines)) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Read or build an inventory and print the seam report."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("inventory", nargs="?", type=Path, help="Inventory JSON or JSONL.")
    parser.add_argument("--scan", nargs="+", type=Path, help="Scan these roots instead.")
    parser.add_argument("--transaction", help="Only report this CICS transaction's footprint.")
    parser.add_argument("--format", choices=["json", "markdown", "mermaid"], default="json")
    args = parser.parse_args(argv)
    if (args.inventory is None) == (args.scan is None):
        parser.error("give an inventory file or --scan, not both")
    missing = [str(root) for root in args.scan or [] if not root.exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    try:
        if args.scan:
            inventory = mainframe_inventory.build_inventory(args.scan)
        else:
            inventory = load_inventory(args.inventory)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = build_report(inventory, args.transaction)
    if args.format == "markdown":
        print(to_markdown(report))
    elif args.format == "mermaid":
        print(to_mermaid(report), end="")
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
