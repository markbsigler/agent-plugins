#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Decode mainframe data records field by field using a record layout.

Reads a data set downloaded in binary (with RDWs for variable-length records) and prints each
record's fields as JSON lines or Markdown. The layout comes from a COBOL copybook, a PL/I
structure, or an HLASM DSECT. Text is decoded with the chosen EBCDIC code page; zoned and
packed decimal stay exact (decimals print as strings); binary, IBM hexadecimal floating
point, national (UTF-16), DBCS, and bit fields are supported, and OCCURS DEPENDING ON tables
use the count found in each record. Invalid numeric data (spaces, low-values, bad digits or
signs) is reported per field instead of stopping the run. The script only reads files.

Examples:
    uv run --script record_decode.py CUSTREC.cpy CUST.DATA --format markdown --max-records 5
    uv run --script record_decode.py CUSTREC.cpy CUST.VB --recfm V --codepage 273
    uv run --script record_decode.py TRANREC.cpy TRAN.DATA --type-field 1:2 --type HD=TRAN-HEADER
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pli_hlasm_layout
import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from copybook_layout import Item, Layout

EBCDIC_PLUS = 0x4E
EBCDIC_MINUS = 0x60
POSITIVE_SIGNS = frozenset({0xA, 0xC, 0xE, 0xF})
NEGATIVE_SIGNS = frozenset({0xB, 0xD})
TEXT_CATEGORIES = frozenset(
    {"alphanumeric", "alphabetic", "alphanumeric-edited", "numeric-edited", "external-float"}
)
NUMERIC_CATEGORIES = frozenset({"zoned-decimal", "packed-decimal", "binary", "national-decimal"})


@dataclass
class FieldValue:
    """One decoded occurrence of an elementary field."""

    label: str
    item: Item
    offset: int
    raw: bytes
    value: Any
    issue: str | None = None


@dataclass
class Selector:
    """Chooses the record layout from a type code at a fixed position."""

    position: int
    length: int
    types: dict[str, str]


@dataclass
class _Context:
    data: bytes
    codepage: str
    labels: dict[str, str]
    depending: set[str]
    values: dict[str, int] = field(default_factory=dict)
    out: list[FieldValue] = field(default_factory=list)


def _special(raw: bytes) -> str | None:
    if raw and all(byte == 0x40 for byte in raw):
        return "spaces"
    if raw and all(byte == 0x00 for byte in raw):
        return "low-values"
    if raw and all(byte == 0xFF for byte in raw):
        return "high-values"
    return None


def _scaled(number: int, scale: int | None) -> int | Decimal:
    if not scale:
        return number
    return Decimal(number).scaleb(-scale)


def _zoned(item: Item, raw: bytes) -> tuple[Any, str | None]:
    body = raw
    negative = False
    issue = None
    if item.signed and item.separate:
        sign = raw[0] if item.leading else raw[-1]
        body = raw[1:] if item.leading else raw[:-1]
        if sign not in {EBCDIC_PLUS, EBCDIC_MINUS}:
            return None, f"invalid separate sign X'{sign:02X}'"
        negative = sign == EBCDIC_MINUS
    digits = []
    for index, byte in enumerate(body):
        zone, digit = byte >> 4, byte & 0x0F
        if digit > 9:
            return None, f"invalid digit X'{byte:02X}'"
        is_sign = (
            item.signed and not item.separate and index == (0 if item.leading else len(body) - 1)
        )
        if is_sign:
            if zone in NEGATIVE_SIGNS:
                negative = True
            elif zone not in POSITIVE_SIGNS:
                return None, f"invalid sign zone X'{byte:02X}'"
        elif zone != 0xF:
            issue = f"zone X'{zone:X}' in a digit position"
        digits.append(str(digit))
    number = int("".join(digits) or "0")
    return _scaled(-number if negative else number, item.scale), issue


def _packed(item: Item, raw: bytes) -> tuple[Any, str | None]:
    nibbles = [nibble for byte in raw for nibble in (byte >> 4, byte & 0x0F)]
    sign = nibbles.pop()
    if any(nibble > 9 for nibble in nibbles):
        return None, "invalid packed digit"
    if sign not in POSITIVE_SIGNS | NEGATIVE_SIGNS:
        return None, f"invalid packed sign X'{sign:X}'"
    number = int("".join(map(str, nibbles)) or "0")
    issue = (
        "unsigned field has a negative sign" if sign in NEGATIVE_SIGNS and not item.signed else None
    )
    return _scaled(-number if sign in NEGATIVE_SIGNS else number, item.scale), issue


def hfp_to_float(raw: bytes) -> float:
    """Convert IBM hexadecimal floating point (COMP-1 or COMP-2) to a Python float."""
    if not any(raw[1:]):
        return 0.0
    sign = -1.0 if raw[0] & 0x80 else 1.0
    exponent = (raw[0] & 0x7F) - 64
    fraction = int.from_bytes(raw[1:], "big") / float(1 << (8 * (len(raw) - 1)))
    return sign * fraction * 16.0**exponent


def decode_value(item: Item, raw: bytes, codepage: str = "037") -> tuple[Any, str | None]:
    """Decode one elementary field's bytes into a value and an optional issue."""
    if len(raw) < item.size:
        return None, "record too short"
    category = item.category
    if category in NUMERIC_CATEGORIES:
        special = _special(raw)
        if special and category != "binary":
            return None, special
        if category == "zoned-decimal":
            return _zoned(item, raw)
        if category == "packed-decimal":
            return _packed(item, raw)
        if category == "binary":
            return _scaled(int.from_bytes(raw, "big", signed=item.signed), item.scale), None
        text = raw.decode("utf-16-be", errors="replace")
        digits = "".join(char for char in text if char.isdigit())
        number = int(digits or "0") * (-1 if "-" in text else 1)
        return _scaled(number, item.scale), None
    if category == "float":
        return hfp_to_float(raw), None
    if category == "binary-float" and len(raw) in {4, 8}:
        return struct.unpack(">f" if len(raw) == 4 else ">d", raw)[0], None
    if category in TEXT_CATEGORIES:
        return zos_encoding.decode(raw, codepage, shift=True).rstrip(" "), None
    if category in {"national", "national-edited"}:
        return raw.decode("utf-16-be", errors="replace").rstrip(" "), None
    if category == "utf-8":
        return raw.decode("utf-8", errors="replace").rstrip(" "), None
    if category == "bit" and item.bits is not None:
        width = 8 * len(raw)
        bits = int.from_bytes(raw, "big") >> (width - (item.bit_offset or 0) - item.bits)
        return format(bits & ((1 << item.bits) - 1), f"0{item.bits}b"), None
    if category == "dbcs":
        return ("" if raw.strip(b"\x40") == b"" else f"<DBCS:{raw.hex().upper()}>"), None
    return raw.hex().upper(), None


def _labels(record: Item) -> dict[str, str]:
    """Map each elementary item path to its label: the name when unique, else the path."""
    paths: dict[str, str] = {}

    def walk(item: Item, path: str) -> None:
        for child in item.children:
            child_path = f"{path}.{child.name}" if path else child.name
            if child.children:
                walk(child, child_path)
            else:
                paths[child_path] = child.name

    walk(record, "")
    counts = Counter(paths.values())
    return {path: name if counts[name] == 1 else path for path, name in paths.items()}


def _depending_names(item: Item) -> set[str]:
    names = {item.depending_on} if item.depending_on else set()
    for child in item.children:
        names |= _depending_names(child)
    return names


def _has_odo(item: Item) -> bool:
    return bool(item.depending_on) or any(_has_odo(child) for child in item.children)


def _visit(item: Item, start: int, path: str, subscripts: tuple[int, ...], ctx: _Context) -> int:
    """Emit the occurrences of ``item`` at ``start``; return the bytes they occupy."""
    if item.occurs_max is None:
        return _visit_one(item, start, path, subscripts, ctx)
    count = item.occurs_max
    actual = ctx.values.get(item.depending_on) if item.depending_on else None
    if actual is not None:
        count = max(item.occurs_min or 0, min(count, actual))
    for index in range(count):
        _visit_one(item, start + index * item.size, path, (*subscripts, index + 1), ctx)
    return count * item.size


def _visit_one(
    item: Item, start: int, path: str, subscripts: tuple[int, ...], ctx: _Context
) -> int:
    if not item.children:
        raw = ctx.data[start : start + item.size]
        value, issue = decode_value(item, raw, ctx.codepage)
        label = ctx.labels.get(path, path)
        if subscripts:
            label += f"({', '.join(map(str, subscripts))})"
        ctx.out.append(FieldValue(label, item, start, raw, value, issue))
        if item.name in ctx.depending and isinstance(value, int | Decimal):
            ctx.values[item.name] = int(value)
        return item.size
    cursor = start
    starts: dict[str, int] = {}
    for child in item.children:
        child_path = f"{path}.{child.name}" if path else child.name
        if child.redefines and child.redefines in starts:
            child_start = starts[child.redefines]
        elif child.variable_offset:
            child_start = cursor + child.slack_before
        else:
            child_start = start + (child.offset - item.offset)
        starts[child.name] = child_start
        used = _visit(child, child_start, child_path, subscripts, ctx)
        if not child.redefines:
            cursor = max(cursor, child_start + used)
    return cursor - start if _has_odo(item) else item.size


def decode_record(record: Item, raw: bytes, codepage: str = "037") -> list[FieldValue]:
    """Decode every elementary field occurrence of one record, in layout order."""
    ctx = _Context(raw, codepage, _labels(record), _depending_names(record))
    _visit_one(record, 0, "" if record.children else record.name, (), ctx)
    return ctx.out


def record_length(record: Item, raw: bytes, codepage: str = "037") -> int:
    """Return the record's length after OCCURS DEPENDING ON counts are applied."""
    ctx = _Context(raw, codepage, _labels(record), _depending_names(record))
    return _visit_one(record, 0, "" if record.children else record.name, (), ctx)


def load_layout(
    source: str | Path,
    *,
    language: str = "auto",
    copylibs: Sequence[Path] = (),
    replacements: Sequence[tuple[str, str]] = (),
    records: Sequence[str] = (),
) -> Layout:
    """Parse a copybook, PL/I structure, or DSECT, keeping only the named records if given."""
    layout = pli_hlasm_layout.parse_source(
        source, language=language, copylibs=copylibs, replacements=replacements
    )
    wanted = {name.upper() for name in records}
    if wanted:
        layout.records = [record for record in layout.records if record.name in wanted]
    return layout


def parse_selector(type_field: str | None, types: Sequence[str]) -> Selector | None:
    """Build a selector from ``POS:LEN`` and ``VALUE=RECORD`` arguments."""
    if type_field is None:
        if types:
            raise ValueError("--type needs --type-field POS:LEN")
        return None
    position, _, length = type_field.partition(":")
    if not (position.isdigit() and length.isdigit()) or int(position) < 1:
        raise ValueError(
            f"--type-field must be POS:LEN with a 1-based position, got {type_field!r}"
        )
    mapping: dict[str, str] = {}
    for entry in types:
        value, separator, record = entry.partition("=")
        if not separator:
            raise ValueError(f"--type must be VALUE=RECORD, got {entry!r}")
        mapping[value] = record.upper()
    return Selector(int(position), int(length), mapping)


def choose_record(
    raw: bytes, layout: Layout, selector: Selector | None, codepage: str = "037"
) -> Item | None:
    """Pick the record layout for one data record; None when the type code is unknown."""
    if selector is None:
        return layout.records[0]
    start = selector.position - 1
    code = zos_encoding.decode(raw[start : start + selector.length], codepage).strip()
    name = selector.types.get(code)
    return next((record for record in layout.records if record.name == name), None)


def read_records(
    path: Path, layout: Layout, *, recfm: str = "auto", lrecl: int | None = None
) -> zos_encoding.RecordSplit:
    """Split a binary download into records; fixed records default to the layout length."""
    data = path.read_bytes()
    if recfm.upper().startswith("F") or (recfm == "auto" and lrecl is None):
        lengths = {record.size for record in layout.records}
        if lrecl is None and len(lengths) == 1 and zos_encoding.rdw_records(data) is None:
            lrecl = lengths.pop()
    return zos_encoding.split_records(data, recfm=recfm, lrecl=lrecl)


def iter_decoded(
    split: zos_encoding.RecordSplit,
    layout: Layout,
    selector: Selector | None,
    codepage: str,
) -> Iterator[tuple[int, Item | None, bytes, list[FieldValue]]]:
    """Yield (record number, layout record, raw bytes, field values) for each record."""
    for number, raw in enumerate(split.records, start=1):
        record = choose_record(raw, layout, selector, codepage)
        values = decode_record(record, raw, codepage) if record is not None else []
        yield number, record, raw, values


def json_value(value: Any) -> Any:
    """Return a JSON-friendly value: decimals become strings to stay exact."""
    return str(value) if isinstance(value, Decimal) else value


def _record_json(
    number: int, record: Item | None, raw: bytes, values: list[FieldValue], *, hex_values: bool
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "record": number,
        "layout": record.name if record else None,
        "length": len(raw),
        "fields": {value.label: json_value(value.value) for value in values},
    }
    issues = {value.label: value.issue for value in values if value.issue}
    if record is None:
        issues["record"] = "no layout matches the record type"
    if issues:
        entry["issues"] = issues
    if hex_values:
        entry["hex"] = {value.label: value.raw.hex().upper() for value in values}
    return entry


def _markdown(rows: list[tuple[int, Item | None, bytes, list[FieldValue]]]) -> str:
    lines = ["# Decoded records", ""]
    for number, record, raw, values in rows:
        name = record.name if record else "no matching layout"
        lines += [
            f"## Record {number}: {name} ({len(raw)} bytes)",
            "",
            "| Field | Position | Length | Value | Hex | Issue |",
            "| :-- | --: | --: | :-- | :-- | :-- |",
        ]
        for value in values:
            text = str(json_value(value.value)) if value.value is not None else ""
            cells = [value.label, value.offset + 1, len(value.raw), text, value.raw.hex().upper()]
            cells.append(value.issue or "")
            lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |")
        lines.append("")
    return "\n".join(lines)


def add_data_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the layout and data-set options shared by the record tools."""
    parser.add_argument("--record", action="append", default=[], help="Use only this record.")
    parser.add_argument("--language", choices=["auto", "cobol", "pli", "hlasm"], default="auto")
    parser.add_argument("--copylib", action="append", default=[], type=Path, metavar="DIR")
    parser.add_argument("--replace", action="append", default=[], nargs=2, metavar=("OLD", "NEW"))
    parser.add_argument("--codepage", default="037", help="EBCDIC code page (default: 037).")
    parser.add_argument(
        "--recfm", default="auto", help="Record format: auto, F, or V with RDWs (default: auto)."
    )
    parser.add_argument("--lrecl", type=int, help="Record length for fixed-length records.")
    parser.add_argument("--type-field", metavar="POS:LEN", help="Position of a record-type code.")
    parser.add_argument(
        "--type", action="append", default=[], metavar="VALUE=RECORD", help="Repeatable."
    )


def open_inputs(
    args: argparse.Namespace,
) -> tuple[Layout, Selector | None, str]:
    """Load the layout and selector named by the shared options."""
    codepage = zos_encoding.normalize_codepage(args.codepage)
    layout = load_layout(
        args.layout,
        language=args.language,
        copylibs=args.copylib,
        replacements=[(old, new) for old, new in args.replace],
        records=args.record,
    )
    if not layout.records:
        raise ValueError("no matching record layouts found")
    return layout, parse_selector(args.type_field, args.type), codepage


def main(argv: list[str] | None = None) -> int:
    """Decode a data set and print its records."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("layout", help="Copybook, PL/I structure, or DSECT source.")
    parser.add_argument("data", type=Path, help="Data set downloaded in binary.")
    add_data_arguments(parser)
    parser.add_argument("--format", choices=["jsonl", "markdown"], default="jsonl")
    parser.add_argument("--max-records", type=int, default=0, help="0 means all records.")
    parser.add_argument("--hex", action="store_true", help="jsonl: include each field's hex.")
    args = parser.parse_args(argv)
    try:
        layout, selector, codepage = open_inputs(args)
        split = read_records(args.data, layout, recfm=args.recfm, lrecl=args.lrecl)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rows = list(iter_decoded(split, layout, selector, codepage))
    rows = rows[: args.max_records or None]
    if args.format == "markdown":
        print(_markdown(rows))
    else:
        for number, record, raw, values in rows:
            print(json.dumps(_record_json(number, record, raw, values, hex_values=args.hex)))
    for warning in [*layout.warnings, *split.warnings]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
