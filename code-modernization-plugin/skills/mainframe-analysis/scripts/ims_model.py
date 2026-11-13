#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Model IMS databases and PSBs: hierarchy, keys, sensitivity, and draft relational DDL.

Reads DBD and PSB generation source (text or EBCDIC exports) and reports:

- each database's access method, data set DD names, and segment hierarchy: parent, length,
  sequence field (unique, non-unique, or none), logical parents, and secondary indexes;
- each PSB's PCBs in order: type, DBD, PROCOPT, KEYLEN, PROCSEQ, and the sensitive segments
  with their processing options as create/read/update/delete letters;
- with ``--inventory``, which programs touch which segments (from mainframe_inventory.py),
  checked against the PSB each program runs with (from DFSRRC00 steps, PSB scheduling calls,
  or a PSB of the same name): segments the PSB is not sensitive to,
  operations its PROCOPT does not allow, and KEYLEN values shorter than the longest
  concatenated key;
- draft DDL: one table per physical segment, keyed by the parent's key columns plus the
  segment's own sequence field, with an ordering column where twins are non-unique or unkeyed,
  and an index per secondary index. FIELD statements usually describe only search fields, so
  the DDL marks the bytes left to map from the segment's copybook.

The model is static and approximate: confirm it against the DBD and PSB listings, the IMS
catalog, and the copybooks before using the DDL. The script only reads files.

Examples:
    uv run --script ims_model.py dbd/ psb/ --format markdown
    uv run --script ims_model.py dbd/ psb/ --inventory inventory.json --format json
    uv run --script ims_model.py dbd/CUSTDB.dbd --format ddl
    uv run --script ims_model.py dbd/ --format mermaid
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

NAME = re.compile(r"[A-Z0-9@#$/]{1,8}")
CRUD = "CRUD"
PROCOPT_CRUD = {"G": "R", "I": "C", "R": "RU", "D": "RD", "A": "CRUD", "L": "C"}
DATATYPE_SQL = {
    "INT": "INTEGER",
    "UINT": "INTEGER",
    "SHORT": "SMALLINT",
    "USHORT": "SMALLINT",
    "LONG": "BIGINT",
    "ULONG": "BIGINT",
    "FLOAT": "REAL",
    "DOUBLE": "DOUBLE",
    "DATE": "DATE",
    "TIME": "TIME",
    "TIMESTAMP": "TIMESTAMP",
    "XML": "XML",
}
NO_TABLE_ACCESS = frozenset({"INDEX", "PSINDEX", "LOGICAL", "GSAM"})
SUFFIXES = frozenset({"", ".asm", ".dbd", ".psb", ".mac", ".txt", ".src"})


@dataclass
class Field:
    """One FIELD statement."""

    name: str
    start: int
    length: int
    type: str = "C"
    datatype: str | None = None
    sequence: str | None = None


@dataclass
class Index:
    """An LCHILD statement, with the XDFLD that follows it for a secondary index."""

    segment: str
    dbd: str | None
    pointer: str | None
    xdfld: str | None = None
    search: list[str] = field(default_factory=list)
    source_segment: str | None = None


@dataclass
class Segment:
    """One SEGM statement and the FIELD, LCHILD, and XDFLD statements under it."""

    name: str
    parent: str | None
    bytes: int | None = None
    min_bytes: int | None = None
    fields: list[Field] = field(default_factory=list)
    logical_parent: dict[str, str] | None = None
    source: list[str] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)

    def key(self) -> Field | None:
        """Return the sequence field, if the segment has one."""
        return next((f for f in self.fields if f.sequence), None)


@dataclass
class Database:
    """One DBD."""

    name: str
    access: list[str]
    path: str
    datasets: list[str] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    def segment(self, name: str) -> Segment | None:
        """Return a segment by name."""
        return next((s for s in self.segments if s.name == name), None)


@dataclass
class Pcb:
    """One PCB statement and its SENSEG statements."""

    type: str
    name: str | None = None
    dbd: str | None = None
    procopt: str = "A"
    keylen: int | None = None
    procseq: str | None = None
    destination: str | None = None
    sensitive: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Psb:
    """One PSB."""

    name: str
    path: str
    language: str | None = None
    pcbs: list[Pcb] = field(default_factory=list)


@dataclass
class Model:
    """Everything read from the inputs."""

    databases: dict[str, Database] = field(default_factory=dict)
    psbs: dict[str, Psb] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _split(text: str) -> list[str]:
    """Split on commas that are outside parentheses and quotes."""
    parts, depth, quoted, start = [], 0, False, 0
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and depth == 0 and char == ",":
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts]


def _items(value: str) -> list[str]:
    """Return the items of an operand value, removing one level of enclosing parentheses."""
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        inner, depth = value[1:-1], 0
        for char in inner:
            depth += {"(": 1, ")": -1}.get(char, 0)
            if depth < 0:
                return [value]
        return _split(inner)
    return [value]


def _operand_field(text: str) -> str:
    """Return the operands, dropping remarks after the first blank outside quotes."""
    quoted = False
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return text[:index]
    return text


def statements(text: str) -> Iterator[tuple[str, str, dict[str, str]]]:
    """Yield (label, operation, keyword operands) for each macro statement.

    Joins continuations marked in column 72, and continuation lines whose marker was lost
    in export (a line that starts with a keyword after an operand list ending in a comma).
    """
    current: list[str] | None = None
    continued = False
    for raw in text.upper().splitlines():
        if raw.startswith(("*", ".*")) and not continued:
            continue
        body = raw[:71].rstrip()
        marker = len(raw) > 71 and raw[71] != " "
        first = body.split()[0] if body.split() else ""
        lost = (
            current is not None
            and current[2].endswith(",")
            and body[:1] == " "
            and ("=" in first or first.startswith("("))
        )
        if current is not None and (continued or lost):
            current[2] += _operand_field(body.strip())
        elif body.strip():
            label = "" if body[:1] == " " else first
            rest = body[len(label) :].strip().split(None, 1)
            if not rest:
                continue
            if current is not None:
                yield _statement(current)
            current = [label, rest[0], _operand_field(rest[1]) if len(rest) > 1 else ""]
        continued = marker
    if current is not None:
        yield _statement(current)


def _statement(parts: list[str]) -> tuple[str, str, dict[str, str]]:
    keywords = {}
    for operand in _split(parts[2]):
        key, sep, value = operand.partition("=")
        if sep:
            keywords[key.strip()] = value.strip()
    return parts[0], parts[1], keywords


def _int(value: str | None) -> int | None:
    return int(value) if value and value.strip().isdigit() else None


def parse_dbd(text: str, path: str = "") -> Database | None:
    """Parse DBD generation statements; return None when the text has no DBD statement."""
    database: Database | None = None
    segment: Segment | None = None
    index: Index | None = None
    for _, operation, keywords in statements(text):
        if operation == "DBD":
            database = Database(keywords.get("NAME", "?"), _items(keywords.get("ACCESS", "")), path)
        elif database is None:
            continue
        elif operation in {"DATASET", "AREA"}:
            for key in ("DD1", "DD2", "OVFLW"):
                if keywords.get(key) and keywords[key] not in database.datasets:
                    database.datasets.append(keywords[key])
        elif operation == "SEGM":
            parent_items = _items(keywords.get("PARENT", "0"))
            physical = _items(parent_items[0])[0] if parent_items else "0"
            sizes = _items(keywords.get("BYTES", ""))
            segment = Segment(
                keywords.get("NAME", "?"),
                None if physical in {"0", ""} else physical,
                _int(sizes[0]),
                _int(sizes[1]) if len(sizes) > 1 else None,
            )
            if len(parent_items) > 1:
                logical = _items(parent_items[1])
                segment.logical_parent = {
                    "segment": logical[0],
                    "storage": logical[1] if len(logical) > 1 else "",
                    "dbd": logical[2] if len(logical) > 2 else database.name,
                }
            if keywords.get("SOURCE"):
                segment.source = [_items(item)[0] for item in _items(keywords["SOURCE"])]
            database.segments.append(segment)
            index = None
        elif operation == "FIELD" and segment is not None:
            names = _items(keywords.get("NAME", keywords.get("EXTERNALNAME", "?")))
            sequence = None
            if len(names) > 1 and names[1] == "SEQ":
                sequence = names[2] if len(names) > 2 else "U"
            segment.fields.append(
                Field(
                    names[0],
                    _int(keywords.get("START")) or 1,
                    _int(keywords.get("BYTES")) or 0,
                    keywords.get("TYPE", "C"),
                    keywords.get("DATATYPE"),
                    sequence,
                )
            )
        elif operation == "LCHILD" and segment is not None:
            names = _items(keywords.get("NAME", "?"))
            index = Index(names[0], names[1] if len(names) > 1 else None, keywords.get("POINTER"))
            segment.indexes.append(index)
        elif operation == "XDFLD" and index is not None:
            index.xdfld = keywords.get("NAME")
            index.search = _items(keywords.get("SRCH", ""))
            index.source_segment = keywords.get("SEGMENT")
    return database


def parse_psb(text: str, path: str = "") -> Psb | None:
    """Parse PSB generation statements; return None when the text has no PSBGEN statement."""
    pcbs: list[Pcb] = []
    for label, operation, keywords in statements(text):
        if operation == "PCB":
            pcb_type = keywords.get("TYPE", "DB")
            pcbs.append(
                Pcb(
                    pcb_type,
                    keywords.get("PCBNAME") or label or None,
                    keywords.get("DBDNAME") or (keywords.get("NAME") if pcb_type == "DB" else None),
                    keywords.get("PROCOPT", "A" if pcb_type != "TP" else ""),
                    _int(keywords.get("KEYLEN")),
                    keywords.get("PROCSEQ"),
                )
            )
            if pcb_type == "TP":
                pcbs[-1].destination = keywords.get("LTERM") or keywords.get("NAME")
        elif operation == "SENSEG" and pcbs:
            procopt = keywords.get("PROCOPT", pcbs[-1].procopt)
            pcbs[-1].sensitive.append(
                {
                    "segment": keywords.get("NAME", "?"),
                    "parent": keywords.get("PARENT", "0"),
                    "procopt": procopt,
                    "ops": procopt_crud(procopt),
                }
            )
        elif operation == "PSBGEN":
            return Psb(
                keywords.get("PSBNAME", Path(path).stem.upper()), path, keywords.get("LANG"), pcbs
            )
    return None


def procopt_crud(procopt: str) -> str:
    """Return the create/read/update/delete letters a PROCOPT allows."""
    letters = {letter for code in procopt for letter in PROCOPT_CRUD.get(code, "")}
    return "".join(letter for letter in CRUD if letter in letters)


def load(paths: Sequence[Path], codepage: str = "cp037") -> Model:
    """Read DBD and PSB sources from files and directories."""
    model = Model()
    for path in _walk(paths):
        decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
        if decoded is None:
            continue
        text = decoded.text
        if re.search(r"\bDBDGEN\b|^\S*\s+DBD\s", text.upper(), re.MULTILINE):
            database = parse_dbd(text, str(path))
            if database is not None:
                _add(model.databases, database.name, database, model.warnings)
        if re.search(r"\bPSBGEN\b", text.upper()):
            psb = parse_psb(text, str(path))
            if psb is not None:
                _add(model.psbs, psb.name, psb, model.warnings)
    for database in model.databases.values():
        names = {segment.name for segment in database.segments}
        for segment in database.segments:
            if segment.parent and segment.parent not in names:
                model.warnings.append(f"{database.name}: {segment.name} has unknown parent")
    return model


def _add(found: dict[str, Any], name: str, item: Any, warnings: list[str]) -> None:
    if name in found:
        warnings.append(f"{name} is defined in {found[name].path} and {item.path}; using the first")
    else:
        found[name] = item


def _walk(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (
                child
                for child in sorted(path.rglob("*"))
                if child.is_file() and child.suffix.lower() in SUFFIXES
            )


def concatenated_key(database: Database, segment: Segment) -> int:
    """Return the concatenated key length of a segment: the sequence fields on its path."""
    length = 0
    current: Segment | None = segment
    while current is not None:
        key = current.key()
        length += key.length if key else 0
        current = database.segment(current.parent) if current.parent else None
    return length


def _checks(model: Model, inventory: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict]]:
    """Return the program-to-segment access matrix and the sensitivity findings."""
    findings: list[dict[str, Any]] = []
    for psb in model.psbs.values():
        for position, pcb in enumerate(psb.pcbs, start=1):
            database = model.databases.get(pcb.dbd or "")
            if pcb.type != "DB" or database is None:
                continue
            longest = 0
            for sensitive in pcb.sensitive:
                segment = database.segment(sensitive["segment"])
                if segment is None:
                    findings.append(
                        {
                            "check": "unknown-segment",
                            "psb": psb.name,
                            "detail": f"PCB {position} names {sensitive['segment']}, "
                            f"which {database.name} does not define",
                        }
                    )
                    continue
                longest = max(longest, concatenated_key(database, segment))
            if pcb.keylen is not None and pcb.keylen < longest:
                findings.append(
                    {
                        "check": "keylen",
                        "psb": psb.name,
                        "detail": f"PCB {position} KEYLEN={pcb.keylen} is shorter than the "
                        f"longest concatenated key ({longest}) of its sensitive segments",
                    }
                )
    if inventory is None:
        return {}, findings
    psb_of: dict[str, set[str]] = {}
    for member in inventory.get("members", []):
        for step in member.get("details", {}).get("steps", []):
            if step.get("ims_program") and step.get("psb"):
                psb_of.setdefault(step["ims_program"], set()).add(step["psb"])
    access: dict[str, dict[str, str]] = {}
    for edge in inventory.get("edges", []):
        if edge["type"] == "ims-segment" and edge.get("access"):
            access.setdefault(edge["to"], {})[edge["from"]] = edge["access"]
        elif edge["type"] == "ims-psb":
            psb_of.setdefault(edge["from"], set()).add(edge["to"])
    for segment, programs in sorted(access.items()):
        for program, ops in sorted(programs.items()):
            names = psb_of.get(program) or ({program} if program in model.psbs else set())
            for name in sorted(names & set(model.psbs)):
                allowed = {
                    letter
                    for pcb in model.psbs[name].pcbs
                    for sensitive in pcb.sensitive
                    if sensitive["segment"] == segment
                    for letter in sensitive["ops"]
                }
                where = f"{program} with PSB {name}"
                if not allowed:
                    findings.append(
                        {
                            "check": "not-sensitive",
                            "psb": name,
                            "detail": f"{where} uses {segment}, which no PCB is sensitive to",
                        }
                    )
                elif set(ops) - allowed:
                    findings.append(
                        {
                            "check": "procopt",
                            "psb": name,
                            "detail": f"{where} does {ops} on {segment}; PROCOPT allows "
                            f"{''.join(c for c in CRUD if c in allowed)}",
                        }
                    )
    return access, findings


def build_report(model: Model, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the model, access matrix, and findings as a JSON-serializable dictionary."""
    access, findings = _checks(model, inventory)
    databases = {}
    for name, database in sorted(model.databases.items()):
        entry = asdict(database)
        for segment, data in zip(database.segments, entry["segments"], strict=True):
            key = segment.key()
            data["twins"] = "unique" if key and key.sequence == "U" else "non-unique"
            if key is None:
                data["twins"] = "unkeyed"
            data["concatenated_key"] = concatenated_key(database, segment)
            data["children"] = [s.name for s in database.segments if s.parent == segment.name]
        databases[name] = entry
    return {
        "tool": "ims_model",
        "databases": databases,
        "psbs": {name: asdict(psb) for name, psb in sorted(model.psbs.items())},
        "segment_access": access,
        "findings": findings,
        "warnings": model.warnings,
    }


def _ident(name: str) -> str:
    cleaned = name.replace("-", "_")
    return cleaned if re.fullmatch(r"[A-Z][A-Z0-9_]*", cleaned) else f'"{name}"'


def _sql_type(item: Field) -> tuple[str, str]:
    """Return the SQL type for a field and a note when the mapping is a guess."""
    datatype = (item.datatype or "").upper()
    decimal = re.fullmatch(r"DECIMAL\((\d+)(?:,(\d+))?\)", datatype)
    if decimal:
        return f"DECIMAL({decimal.group(1)},{decimal.group(2) or 0})", ""
    base = datatype.split("(")[0]
    if base in DATATYPE_SQL:
        return DATATYPE_SQL[base], ""
    if base in {"BINARY", "BIT", "BYTE", "UBYTE"} and item.type != "P":
        return f"BINARY({item.length})", ""
    if item.type == "P":
        return f"DECIMAL({2 * item.length - 1},0)", "packed: take the scale from the copybook"
    if item.type == "X":
        return f"BINARY({item.length})", "hexadecimal: check the copybook for a binary number"
    if item.type == "F":
        return "INTEGER", ""
    if item.type == "H":
        return "SMALLINT", ""
    return f"CHAR({item.length})", ""


def _key_columns(database: Database, cache: dict[str, list[tuple[str, str]]], name: str) -> list:
    """Return a segment's primary-key columns as (column, SQL type), ancestors first.

    The segment's own key is its sequence field, plus SEQ_NO when twins are non-unique or
    unkeyed. A child inherits its parent's key columns, prefixing the parent's own ones.
    """
    if name in cache:
        return cache[name]
    segment = database.segment(name)
    if segment is None:
        return []
    inherited = []
    if segment.parent:
        parent = database.segment(segment.parent)
        parent_own = {"SEQ_NO", *(key.name for key in [parent.key() if parent else None] if key)}
        inherited = [
            (f"{segment.parent}_{column}" if column in parent_own else column, sql_type)
            for column, sql_type in _key_columns(database, cache, segment.parent)
        ]
    key = segment.key()
    own = [(key.name, _sql_type(key)[0])] if key else []
    if key is None or key.sequence == "M":
        own.append(("SEQ_NO", "INTEGER"))
    cache[name] = [*inherited, *own]
    return cache[name]


def _render(items: Sequence[tuple[str, str]]) -> list[str]:
    """Render (SQL, comment) table elements with commas between the SQL ones only."""
    last = max((i for i, (sql, _) in enumerate(items) if sql), default=-1)
    lines = []
    for index, (sql, comment) in enumerate(items):
        text = sql + ("," if sql and index < last else "")
        if comment:
            text = f"{text}  -- {comment}" if text else f"-- {comment}"
        lines.append(f"    {text}")
    return lines


def _segment_ddl(database: Database, segment: Segment, cache: dict[str, list]) -> list[str]:
    keys = _key_columns(database, cache, segment.name)
    key_names = {column for column, _ in keys}
    items: list[tuple[str, str]] = [(f"{_ident(c)} {t} NOT NULL", "") for c, t in keys]
    key = segment.key()
    covered = [(key.start, key.start + key.length)] if key else []
    for item in segment.fields:
        if item.name.startswith(("/CK", "/SX")) or item is key:
            continue
        end = item.start + item.length
        if any(item.start < stop and start < end for start, stop in covered):
            items.append(("", f"{item.name} overlaps another field; map it from the copybook"))
            continue
        covered.append((item.start, end))
        sql_type, note = _sql_type(item)
        column = item.name if item.name not in key_names else f"{segment.name}_{item.name}"
        items.append((f"{_ident(column)} {sql_type}", note))
    if segment.bytes:
        prefix = 2 if segment.min_bytes else 0
        remaining = segment.bytes - prefix - sum(stop - start for start, stop in covered)
        if remaining > 0:
            items.append(
                (
                    "",
                    (
                        f"{remaining} of {segment.bytes} bytes are not described by FIELD "
                        "statements: add columns from the segment copybook"
                    ),
                )
            )
    items.append((f"PRIMARY KEY ({', '.join(_ident(c) for c, _ in keys)})", ""))
    if segment.parent:
        parent_keys = _key_columns(database, cache, segment.parent)
        mine = ", ".join(_ident(column) for column, _ in keys[: len(parent_keys)])
        theirs = ", ".join(_ident(column) for column, _ in parent_keys)
        items.append((f"FOREIGN KEY ({mine}) REFERENCES {_ident(segment.parent)} ({theirs})", ""))
    if segment.logical_parent:
        logical = segment.logical_parent
        items.append(
            (
                "",
                (
                    f"logical parent {logical['dbd']}.{logical['segment']}: the segment starts "
                    "with its concatenated key; add a foreign key to its table"
                ),
            )
        )
    lines = [f"CREATE TABLE {_ident(segment.name)} (", *_render(items), ");"]
    for index in segment.indexes:
        if index.xdfld and index.search:
            table = index.source_segment or segment.name
            columns = ", ".join(_ident(name) for name in index.search)
            source = f": search fields from {table}" if table != segment.name else ""
            lines.append(f"-- secondary index {index.xdfld} on {segment.name}{source}")
            name = _ident(f"{segment.name}_{index.xdfld}")
            lines.append(f"CREATE INDEX {name} ON {_ident(table)} ({columns});")
    return lines


def to_ddl(model: Model, only: str | None = None) -> str:
    """Return draft DDL for every physical database (or only one)."""
    lines = [
        "-- Draft relational DDL generated by ims_model.py from DBD source.",
        "-- Review names, types, and keys; FIELD statements rarely describe whole segments.",
        "",
    ]
    for name, database in sorted(model.databases.items()):
        if only and name != only.upper():
            continue
        access = (database.access or ["?"])[0]
        if access in NO_TABLE_ACCESS:
            lines += [f"-- {name} ({access}): no tables for index, logical, or GSAM databases.", ""]
            continue
        lines += [f"-- Database {name} ({', '.join(database.access)})", ""]
        cache: dict[str, list] = {}
        for segment in database.segments:
            if segment.source:
                lines += [
                    f"-- {segment.name} is a virtual segment over {', '.join(segment.source)}",
                    "",
                ]
                continue
            lines += [*_segment_ddl(database, segment, cache), ""]
    return "\n".join(lines)


def _node(*parts: str) -> str:
    return "_".join(re.sub(r"[^A-Za-z0-9]", "_", part) for part in parts)


def to_mermaid(model: Model) -> str:
    """Draw each database's segment hierarchy and logical relationships."""
    lines = ["flowchart TD"]
    for name, database in sorted(model.databases.items()):
        lines.append(f'    subgraph {_node("db", name)}["{name} ({", ".join(database.access)})"]')
        for segment in database.segments:
            key = segment.key()
            label = segment.name + (f"<br/>key {key.name} ({key.sequence})" if key else "")
            lines.append(f'        {_node(name, segment.name)}["{label}"]')
        lines.append("    end")
        for segment in database.segments:
            if segment.parent:
                lines.append(f"    {_node(name, segment.parent)} --> {_node(name, segment.name)}")
            if segment.logical_parent:
                logical = segment.logical_parent
                target = _node(logical["dbd"], logical["segment"])
                lines.append(f"    {_node(name, segment.name)} -.->|logical parent| {target}")
    return "\n".join(lines) + "\n"


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += [
        "| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows
    ]
    return [*lines, ""]


def to_markdown(report: dict[str, Any]) -> str:
    """Render the report as Markdown."""
    lines = ["# IMS model", ""]
    for name, database in report["databases"].items():
        lines += [f"## Database {name} ({', '.join(database['access'])})", ""]
        if database["datasets"]:
            lines += [f"DD names: {', '.join(database['datasets'])}", ""]
        rows = []
        for segment in database["segments"]:
            key = next((f for f in segment["fields"] if f["sequence"]), None)
            logical = segment["logical_parent"]
            indexes = [
                i["xdfld"] or f"{i['segment']} ({i['pointer'] or 'logical'})"
                for i in segment["indexes"]
            ]
            rows.append(
                (
                    segment["name"],
                    segment["parent"] or "(root)",
                    (
                        f"{segment['min_bytes']}-{segment['bytes']}"
                        if segment["min_bytes"]
                        else segment["bytes"] or ""
                    ),
                    key["name"] if key else "",
                    segment["twins"],
                    f"{logical['dbd']}.{logical['segment']}" if logical else "",
                    ", ".join(indexes),
                )
            )
        lines += _table(
            [
                "Segment",
                "Parent",
                "Bytes",
                "Key",
                "Twins",
                "Logical parent",
                "Indexes and logical children",
            ],
            rows,
        )
    if report["psbs"]:
        lines += ["## PSBs", ""]
        rows = []
        for name, psb in report["psbs"].items():
            for position, pcb in enumerate(psb["pcbs"], start=1):
                sensitive = ", ".join(f"{s['segment']} ({s['procopt']})" for s in pcb["sensitive"])
                rows.append(
                    (
                        name,
                        position,
                        pcb["type"],
                        pcb["dbd"] or pcb["destination"] or "",
                        pcb["procopt"],
                        pcb["keylen"] or "",
                        sensitive,
                    )
                )
        lines += _table(
            ["PSB", "PCB", "Type", "DBD or destination", "PROCOPT", "KEYLEN", "Sensitive segments"],
            rows,
        )
    if report["segment_access"]:
        lines += ["## Segment access by program", ""]
        lines += _table(
            ["Segment", "Programs (C create, R read, U update, D delete)"],
            (
                (segment, ", ".join(f"{p} {ops}" for p, ops in programs.items()))
                for segment, programs in report["segment_access"].items()
            ),
        )
    if report["findings"]:
        lines += ["## Findings", ""]
        lines += _table(
            ["Check", "PSB", "Detail"],
            ((f["check"], f["psb"], f["detail"]) for f in report["findings"]),
        )
    if report["warnings"]:
        lines += ["## Warnings", "", *(f"- {warning}" for warning in report["warnings"]), ""]
    return "\n".join(lines)


def load_inventory(path: Path) -> dict[str, Any]:
    """Read members and edges from a mainframe_inventory.py JSON or JSON Lines file."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        inventory: dict[str, list[Any]] = {"members": [], "edges": []}
        for line in filter(str.strip, text.splitlines()):
            record = json.loads(line)
            kind = record.pop("record", None)
            if kind in {"member", "edge"}:
                inventory[f"{kind}s"].append(record)
        return inventory


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, read the sources, and print the model."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, help="DBD and PSB files or directories.")
    parser.add_argument("--inventory", type=Path, help="mainframe_inventory.py JSON or JSONL.")
    parser.add_argument("--format", choices=["json", "markdown", "mermaid", "ddl"], default="json")
    parser.add_argument("--dbd", help="Only generate DDL for this database.")
    parser.add_argument("--codepage", default="037", help="EBCDIC code page (default: 037).")
    args = parser.parse_args(argv)
    missing = [str(path) for path in args.paths if not path.exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    try:
        model = load(args.paths, zos_encoding.normalize_codepage(args.codepage))
        inventory = load_inventory(args.inventory) if args.inventory else None
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not model.databases and not model.psbs:
        print("error: no DBD or PSB source found", file=sys.stderr)
        return 1
    if args.format == "ddl":
        print(to_ddl(model, args.dbd))
    elif args.format == "mermaid":
        print(to_mermaid(model), end="")
    else:
        report = build_report(model, inventory)
        print(to_markdown(report) if args.format == "markdown" else json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
