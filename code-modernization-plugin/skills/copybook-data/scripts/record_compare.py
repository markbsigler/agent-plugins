#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compare two mainframe data sets field by field using a record layout.

Built for golden-master and parallel-run evidence: it pairs records by position or by key
fields, compares every field's bytes, and reports differences with field names, positions, and
decoded values. Differences where both values decode to the same number (for example a packed
sign of C versus F, or a zoned sign zone) are counted separately as format-only differences.
It also counts records, compares control totals for numeric fields, and reports invalid numeric
data in each file. Exit status: 0 when the files match, 1 when they differ, 2 on errors. The
script only reads files.

Examples:
    uv run --script record_compare.py CUSTREC.cpy OLD.DATA NEW.DATA --format markdown
    uv run --script record_compare.py CUSTREC.cpy OLD.DATA NEW.DATA --key CUST-ID --total CUST-BAL
    uv run --script record_compare.py TRANREC.cpy A.VB B.VB --recfm V --ignore RUN-TIMESTAMP
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import record_decode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from copybook_layout import Item, Layout
    from record_decode import FieldValue, Selector

NUMERIC = frozenset({"zoned-decimal", "packed-decimal", "binary", "national-decimal", "float"})


@dataclass
class Options:
    """What to compare and how to report it."""

    keys: Sequence[str] = ()
    ignore: Sequence[str] = ()
    totals: Sequence[str] = ()
    numeric_equal: bool = False
    max_diffs: int = 50
    selector: Selector | None = None
    codepage: str = "037"


@dataclass
class _Side:
    records: int = 0
    by_layout: Counter[str] = field(default_factory=Counter)
    invalid: Counter[str] = field(default_factory=Counter)
    totals: dict[str, Decimal] = field(default_factory=dict)


def _base(label: str) -> str:
    """Return a field label without occurrence subscripts or qualification."""
    return label.split("(", 1)[0].rsplit(".", 1)[-1]


def _matches(label: str, names: Sequence[str]) -> bool:
    base = _base(label)
    return any(name.upper() in {base, label.split("(", 1)[0]} for name in names)


def _decode(
    raw: bytes, layout: Layout, selector: Selector | None, codepage: str
) -> tuple[Item | None, list[FieldValue]]:
    record = record_decode.choose_record(raw, layout, selector, codepage)
    values = record_decode.decode_record(record, raw, codepage) if record is not None else []
    return record, values


def _account(side: _Side, record: Item | None, values: list[FieldValue], options: Options) -> None:
    side.records += 1
    side.by_layout[record.name if record else "(no layout)"] += 1
    for value in values:
        if value.issue and value.item.category in NUMERIC:
            side.invalid[_base(value.label)] += 1
        if _matches(value.label, options.totals) and isinstance(value.value, int | Decimal):
            name = _base(value.label)
            side.totals[name] = side.totals.get(name, Decimal(0)) + Decimal(value.value)


def _key(values: list[FieldValue], keys: Sequence[str]) -> tuple[Any, ...]:
    found = {_base(v.label): v for v in values if _matches(v.label, keys)}
    parts: list[Any] = []
    for name in keys:
        value = found.get(name.upper())
        if value is None:
            parts.append(None)
        else:
            decoded = record_decode.json_value(value.value)
            parts.append(decoded if decoded is not None else value.raw.hex().upper())
    return tuple(parts)


def compare_records(
    old: list[FieldValue], new: list[FieldValue], options: Options
) -> list[dict[str, Any]]:
    """Return field differences between two decoded records of the same layout."""
    differences = []
    new_by_label = {value.label: value for value in new}
    for before in old:
        if _matches(before.label, options.ignore):
            continue
        after = new_by_label.get(before.label)
        if after is not None and after.raw == before.raw:
            continue
        kind = "missing" if after is None else "value"
        if (
            after is not None
            and before.item.category in NUMERIC
            and before.value is not None
            and before.value == after.value
        ):
            kind = "format-only"
            if options.numeric_equal:
                continue
        differences.append(
            {
                "field": before.label,
                "position": before.offset + 1,
                "kind": kind,
                "old": record_decode.json_value(before.value),
                "new": record_decode.json_value(after.value) if after else None,
                "old_hex": before.raw.hex().upper(),
                "new_hex": after.raw.hex().upper() if after else None,
            }
        )
    old_labels = {value.label for value in old}
    differences.extend(
        {
            "field": after.label,
            "position": after.offset + 1,
            "kind": "extra",
            "old": None,
            "new": record_decode.json_value(after.value),
            "old_hex": None,
            "new_hex": after.raw.hex().upper(),
        }
        for after in new
        if after.label not in old_labels and not _matches(after.label, options.ignore)
    )
    return differences


def compare_files(
    old_records: Sequence[bytes],
    new_records: Sequence[bytes],
    layout: Layout,
    options: Options | None = None,
) -> dict[str, Any]:
    """Compare two lists of records and return the summary, totals, and differences."""
    options = options or Options()
    selector, codepage = options.selector, options.codepage
    sides = {"old": _Side(), "new": _Side()}
    decoded: dict[str, list[tuple[Item | None, list[FieldValue], bytes]]] = {}
    for name, records in (("old", old_records), ("new", new_records)):
        decoded[name] = []
        for raw in records:
            record, values = _decode(raw, layout, selector, codepage)
            _account(sides[name], record, values, options)
            decoded[name].append((record, values, raw))

    pairs: list[tuple[str, Any, Any]] = []
    only_old: list[str] = []
    only_new: list[str] = []
    duplicates: Counter[str] = Counter()
    if options.keys:
        indexes: dict[str, dict[tuple[Any, ...], Any]] = {"old": {}, "new": {}}
        for name in ("old", "new"):
            for entry in decoded[name]:
                key = _key(entry[1], options.keys)
                if key in indexes[name]:
                    duplicates[name] += 1
                indexes[name].setdefault(key, entry)
        for key, entry in indexes["old"].items():
            label = "/".join(str(part) for part in key)
            if key in indexes["new"]:
                pairs.append((f"key {label}", entry, indexes["new"][key]))
            else:
                only_old.append(label)
        only_new = ["/".join(map(str, k)) for k in indexes["new"] if k not in indexes["old"]]
    else:
        for index, (before, after) in enumerate(
            zip(decoded["old"], decoded["new"], strict=False), start=1
        ):
            pairs.append((f"record {index}", before, after))
        only_old = [f"record {i}" for i in range(len(pairs) + 1, len(decoded["old"]) + 1)]
        only_new = [f"record {i}" for i in range(len(pairs) + 1, len(decoded["new"]) + 1)]

    by_field: Counter[str] = Counter()
    format_only: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    differing = 0
    for label, (old_record, old_values, old_raw), (new_record, new_values, new_raw) in pairs:
        if old_raw == new_raw:
            continue
        if old_record is not new_record:
            differences = [{"field": "(record type)", "kind": "layout", "position": 1}]
            differences[0] |= {
                "old": old_record.name if old_record else None,
                "new": new_record.name if new_record else None,
            }
        else:
            differences = compare_records(old_values, new_values, options)
            if len(old_raw) != len(new_raw):
                differences.append(
                    {
                        "field": "(length)",
                        "kind": "length",
                        "old": len(old_raw),
                        "new": len(new_raw),
                    }
                )
        if not differences:
            continue
        differing += 1
        for difference in differences:
            counter = format_only if difference["kind"] == "format-only" else by_field
            counter[_base(difference["field"])] += 1
            if len(details) < options.max_diffs:
                details.append({"record": label, **difference})

    totals = {
        name: {
            "old": str(sides["old"].totals.get(name, Decimal(0))),
            "new": str(sides["new"].totals.get(name, Decimal(0))),
        }
        for name in sorted(set(sides["old"].totals) | set(sides["new"].totals))
    }
    for entry in totals.values():
        entry["equal"] = Decimal(entry["old"]) == Decimal(entry["new"])
    matches = (
        differing == 0
        and not only_old
        and not only_new
        and all(entry["equal"] for entry in totals.values())
    )
    return {
        "match": matches,
        "summary": {
            "old_records": sides["old"].records,
            "new_records": sides["new"].records,
            "compared": len(pairs),
            "differing_records": differing,
            "only_in_old": len(only_old),
            "only_in_new": len(only_new),
            "duplicate_keys": dict(duplicates),
            "records_by_layout": {name: dict(sides[name].by_layout) for name in ("old", "new")},
        },
        "field_differences": dict(by_field.most_common()),
        "format_only_differences": dict(format_only.most_common()),
        "invalid_numeric": {name: dict(sides[name].invalid) for name in ("old", "new")},
        "totals": totals,
        "only_in_old": only_old[: options.max_diffs],
        "only_in_new": only_new[: options.max_diffs],
        "differences": details,
    }


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def to_markdown(result: dict[str, Any], old: str, new: str) -> str:
    """Render a comparison as a Markdown evidence report."""
    summary = result["summary"]
    verdict = "files match" if result["match"] else "files differ"
    lines = [
        "# Record comparison",
        "",
        f"- **Old:** {old}",
        f"- **New:** {new}",
        f"- **Result:** {verdict}",
        (
            f"- **Records:** {summary['old_records']} old, {summary['new_records']} new, "
            f"{summary['compared']} compared, {summary['differing_records']} differ"
        ),
        (
            f"- **Unmatched:** {summary['only_in_old']} only in old, "
            f"{summary['only_in_new']} only in new"
        ),
        "",
    ]
    sections = (
        ("Differences by field", result["field_differences"]),
        ("Format-only differences (same numeric value)", result["format_only_differences"]),
    )
    for title, counts in sections:
        if counts:
            lines += [f"## {title}", "", "| Field | Records |", "| :-- | --: |"]
            lines += [f"| {name} | {count} |" for name, count in counts.items()]
            lines.append("")
    if result["totals"]:
        lines += [
            "## Control totals",
            "",
            "| Field | Old | New | Equal |",
            "| :-- | --: | --: | :-- |",
        ]
        lines += [
            f"| {name} | {t['old']} | {t['new']} | {'yes' if t['equal'] else 'no'} |"
            for name, t in result["totals"].items()
        ]
        lines.append("")
    invalid = {side: counts for side, counts in result["invalid_numeric"].items() if counts}
    if invalid:
        lines += ["## Invalid numeric data", ""]
        lines += [f"- **{side}:** {counts}" for side, counts in invalid.items()]
        lines.append("")
    if result["differences"]:
        lines += [
            "## First differences",
            "",
            "| Record | Field | Position | Kind | Old | New | Old hex | New hex |",
            "| :-- | :-- | --: | :-- | :-- | :-- | :-- | :-- |",
        ]
        lines += [
            "| "
            + " | ".join(
                _cell(diff.get(key))
                for key in (
                    "record",
                    "field",
                    "position",
                    "kind",
                    "old",
                    "new",
                    "old_hex",
                    "new_hex",
                )
            )
            + " |"
            for diff in result["differences"]
        ]
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Compare two data sets and print the result."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("layout", help="Copybook, PL/I structure, or DSECT source.")
    parser.add_argument("old", type=Path, help="Baseline (golden master) data set, in binary.")
    parser.add_argument("new", type=Path, help="Data set from the changed system, in binary.")
    record_decode.add_data_arguments(parser)
    parser.add_argument("--key", action="append", default=[], help="Pair records by this field.")
    parser.add_argument("--ignore", action="append", default=[], help="Skip this field.")
    parser.add_argument("--total", action="append", default=[], help="Compare its sum.")
    parser.add_argument(
        "--numeric-equal",
        action="store_true",
        help="Treat numerically equal values with different bytes as equal.",
    )
    parser.add_argument("--max-diffs", type=int, default=50, help="Differences to list.")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args(argv)
    try:
        layout, selector, codepage = record_decode.open_inputs(args)
        old = record_decode.read_records(args.old, layout, recfm=args.recfm, lrecl=args.lrecl)
        new = record_decode.read_records(args.new, layout, recfm=args.recfm, lrecl=args.lrecl)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    options = Options(
        args.key, args.ignore, args.total, args.numeric_equal, args.max_diffs, selector, codepage
    )
    result = compare_files(old.records, new.records, layout, options)
    if args.format == "markdown":
        print(to_markdown(result, str(args.old), str(args.new)))
    else:
        print(json.dumps(result, indent=2))
    for warning in [*layout.warnings, *old.warnings, *new.warnings]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
