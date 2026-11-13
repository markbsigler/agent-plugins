#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compute record layouts from PL/I structure declarations and HLASM DSECTs.

Builds the same layout model as copybook_layout.py, so every copybook-data output (JSON,
Markdown, schemas, DFSORT symbols, and ``--diff --match position``) and record_decode.py work
for PL/I and Assembler record definitions too. copybook_layout.py uses this module for
``--language pli`` or ``hlasm`` and for sources it recognizes; running this script does the
same. The script only reads files.

PL/I: UNALIGNED structures map byte for byte, and unaligned bit strings pack at the bit level.
ALIGNED binary, floating-point, pointer, and VARYING items are placed on their natural
boundaries relative to the structure start. PL/I structure mapping can place them differently,
so confirm such layouts with the compiler's AGGREGATE listing.

HLASM: DS and DC statements in DSECTs, with duplication factors, length modifiers, implicit
boundary alignment, zero-duplication groups such as ``DS 0CL80``, and ORG overlays.

Examples:
    uv run --script pli_hlasm_layout.py CUSTREC.pli --format markdown
    uv run --script copybook_layout.py CUSTREC.cpy --diff CUSTDSCT.mac --match position
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import copybook_layout
from copybook_layout import Item, Layout

if TYPE_CHECKING:
    from collections.abc import Sequence

PLI_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
PLI_DECLARE = re.compile(r"(?<![\w#@$])(?:DCL|DECLARE)(?![\w#@$])(.*?);", re.DOTALL | re.IGNORECASE)
PLI_DETECT = re.compile(r"(?<![\w#@$])(?:DCL|DECLARE)\s+\d+\s+[\w#@$]+", re.IGNORECASE)
HLASM_DETECT = re.compile(r"^\S+\s+DSECT\b", re.MULTILINE | re.IGNORECASE)
PLI_SUFFIXES = frozenset({".pli", ".pl1", ".plinc"})
HLASM_SUFFIXES = frozenset({".asm", ".mac", ".mlc", ".hlasm", ".dsect"})
BINARY_DIGITS = {1: 2, 2: 4, 4: 9, 8: 18}
IGNORED_PLI = frozenset(
    {
        "STATIC",
        "AUTO",
        "AUTOMATIC",
        "CTL",
        "CONTROLLED",
        "EXT",
        "EXTERNAL",
        "INT",
        "INTERNAL",
        "BYADDR",
        "BYVALUE",
        "ASSIGNABLE",
        "NONASSIGNABLE",
        "CONNECTED",
        "NONCONNECTED",
        "NORMAL",
        "ABNORMAL",
        "NONVAR",
        "NONVARYING",
        "REAL",
        "BIGENDIAN",
        "NATIVE",
    }
)
PLI_WITH_ARGUMENT = frozenset(
    {"INIT", "INITIAL", "VALUE", "DEF", "DEFINED", "POS", "POSITION", "BASED", "DIM", "DIMENSION"}
)
# HLASM type: (implicit length in bytes, boundary when no length modifier, category)
HLASM_TYPES = {
    "C": (1, 1, "alphanumeric"),
    "CA": (1, 1, "alphanumeric"),
    "CE": (1, 1, "alphanumeric"),
    "CU": (2, 1, "national"),
    "G": (2, 1, "dbcs"),
    "X": (1, 1, "hex"),
    "B": (1, 1, "bit"),
    "P": (1, 1, "packed-decimal"),
    "Z": (1, 1, "zoned-decimal"),
    "F": (4, 4, "binary"),
    "FD": (8, 8, "binary"),
    "H": (2, 2, "binary"),
    "E": (4, 4, "float"),
    "EH": (4, 4, "float"),
    "D": (8, 8, "float"),
    "DH": (8, 8, "float"),
    "L": (16, 8, "float"),
    "LH": (16, 8, "float"),
    "EB": (4, 4, "binary-float"),
    "DB": (8, 8, "binary-float"),
    "LB": (16, 8, "binary-float"),
    "ED": (4, 4, "decimal-float"),
    "DD": (8, 8, "decimal-float"),
    "LD": (16, 8, "decimal-float"),
    "A": (4, 4, "pointer"),
    "AD": (8, 8, "pointer"),
    "Y": (2, 2, "pointer"),
    "S": (2, 2, "pointer"),
    "V": (4, 4, "pointer"),
    "VD": (8, 8, "pointer"),
    "Q": (4, 4, "pointer"),
    "J": (4, 4, "pointer"),
    "R": (4, 4, "pointer"),
}
HLASM_OPERAND = re.compile(
    r"(?P<dup>\d+|\(\d+\))?"
    r"(?P<type>CA|CE|CU|FD|EH|DH|LH|EB|DB|LB|ED|DD|LD|AD|VD|[CGXBPZFHEDLAYSVQJR])"
    r"(?:L(?P<length>\d+|\(\d+\)))?(?P<value>'(?:[^']|'')*'|\(.*\))?$",
    re.IGNORECASE,
)


def detect_language(path: Path, text: str) -> str:
    """Return ``pli``, ``hlasm``, or ``cobol`` for a record-definition source."""
    suffix = path.suffix.lower()
    if suffix in PLI_SUFFIXES or (suffix != ".cpy" and PLI_DETECT.search(text)):
        return "pli"
    if suffix in HLASM_SUFFIXES or HLASM_DETECT.search(text):
        return "hlasm"
    return "cobol"


def _strip_sequence(lines: Sequence[str]) -> list[str]:
    """Drop columns 73-80, which hold sequence numbers in exported fixed-format members."""
    return [line.rstrip("\r\n")[:72] for line in lines]


@dataclass
class _Declared:
    """Attributes collected from one PL/I declaration element."""

    level: int
    name: str
    line: int
    dims: str | None = None
    kind: str | None = None  # char, graphic, widechar, bit, arithmetic, picture, pointer, area
    length: int | None = None
    varying: str | None = None
    scale_mode: str | None = None  # fixed or float
    base: str | None = None  # dec or bin
    precision: tuple[int, int] | None = None
    signed: bool = True
    picture: str | None = None
    aligned: bool | None = None
    union: bool = False
    text: list[str] = field(default_factory=list)


def _pli_tokens(text: str) -> list[str]:
    """Split one declaration element into words, quoted strings, and parenthesized groups."""
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        end = index + 1
        if char == "'":
            while end < len(text) and not (text[end] == "'" and text[end + 1 : end + 2] != "'"):
                end += 2 if text[end] == "'" else 1
            end += 1
        elif char == "(":
            depth = 1
            while end < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[end], 0)
                end += 1
        else:
            while end < len(text) and not text[end].isspace() and text[end] not in "()'":
                end += 1
        tokens.append(text[index:end])
        index = end
    return tokens


def _split_top(text: str) -> list[tuple[int, str]]:
    """Split on commas outside parentheses and quotes, keeping each part's start offset."""
    parts: list[tuple[int, str]] = []
    depth, quoted, start = 0, False, 0
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted and char in "()":
            depth += 1 if char == "(" else -1
        elif not quoted and char == "," and depth == 0:
            parts.append((start, text[start:index]))
            start = index + 1
    parts.append((start, text[start:]))
    return parts


def _numbers(group: str) -> list[int]:
    return [int(number) for number in re.findall(r"-?\d+", group)]


def _parse_pli_element(tokens: list[str], line: int, warnings: list[str]) -> _Declared | None:
    if len(tokens) < 2 or not tokens[0].isdigit():
        return None
    item = _Declared(int(tokens[0]), tokens[1].upper(), line)
    rest = tokens[2:]
    if rest and rest[0].startswith("("):
        item.dims = rest.pop(0)
    index = 0
    while index < len(rest):
        word = rest[index].upper()
        following = rest[index + 1] if index + 1 < len(rest) else ""
        argument = following if following.startswith("(") else None
        consumed = 2 if argument is not None else 1
        if word in {"CHAR", "CHARACTER", "GRAPHIC", "G", "WIDECHAR", "WCHAR", "BIT", "AREA"}:
            item.kind = {"CHARACTER": "char", "G": "graphic", "WCHAR": "widechar"}.get(
                word, word.lower()
            )
            numbers = _numbers(argument or "(1)")
            item.length = numbers[0] if numbers else 1
            if argument is not None and "*" in argument:
                warnings.append(f"line {line}: {item.name} has a * length; assumed 1")
        elif word in {"VAR", "VARYING", "VARZ", "VARYINGZ"}:
            item.varying = "varyingz" if word.endswith("Z") else "varying"
        elif word in {"FIXED", "FLOAT", "DEC", "DECIMAL", "BIN", "BINARY"}:
            item.kind = "arithmetic"
            if word in {"FIXED", "FLOAT"}:
                item.scale_mode = word.lower()
            else:
                item.base = "dec" if word.startswith("DEC") else "bin"
            if argument is not None:
                numbers = _numbers(argument)
                item.precision = (numbers[0], numbers[1] if len(numbers) > 1 else 0)
        elif word in {"SIGNED", "UNSIGNED"}:
            item.signed = word == "SIGNED"
            consumed = 1
        elif word in {"PIC", "PICTURE"}:
            item.kind = "picture"
            item.picture = following.strip("'").upper()
            consumed = 2
        elif word in {"PTR", "POINTER", "OFFSET", "HANDLE"}:
            item.kind = "pointer"
            consumed = 1
        elif word in {"ALIGNED", "UNALIGNED"}:
            item.aligned = word == "ALIGNED"
            consumed = 1
        elif word == "UNION":
            item.union = True
            consumed = 1
        elif word == "LIKE":
            warnings.append(f"line {line}: {item.name} uses LIKE, which is not expanded")
            consumed = 2
        elif word in PLI_WITH_ARGUMENT or word in IGNORED_PLI:
            consumed = consumed if word in PLI_WITH_ARGUMENT else 1
        else:
            warnings.append(f"line {line}: ignored {rest[index]} in {item.name}")
            consumed = 1
        item.text.extend(rest[index : index + consumed])
        index += consumed
    return item


def _expand_pli_picture(picture: str) -> str:
    expanded = re.sub(r"\((\d+)\)(.)", lambda m: m.group(2) * int(m.group(1)), picture)
    return re.sub(r"F\(-?\d+\)", "", expanded)


def _pli_picture(item: Item, picture: str) -> None:
    chars = _expand_pli_picture(picture)
    item.size = len(chars.replace("V", "").replace("K", ""))
    symbols = set(chars)
    if "9" in symbols and symbols <= {"9", "V", "S", "+", "-", "T", "I", "R"}:
        body = chars.replace("S", "").replace("+", "").replace("-", "")
        item.category = "zoned-decimal"
        item.digits = sum(1 for char in body if char in "9TIR")
        item.scale = len(body.split("V", 1)[1]) if "V" in body else 0
        item.signed = bool(symbols & {"S", "+", "-", "T", "I", "R"})
        item.separate = bool(symbols & {"S", "+", "-"})
        item.leading = chars[0] in "S+-TIR"
    elif symbols <= {"X", "A", "9"}:
        item.category = "alphanumeric"
    else:
        item.category = "numeric-edited"


def _pli_arithmetic(item: Item, declared: _Declared, warnings: list[str]) -> int:
    """Size an arithmetic item; return the boundary it needs when ALIGNED."""
    mode = declared.scale_mode or ("float" if declared.base else "fixed")
    base = declared.base or "dec"
    if mode == "fixed" and base == "dec":
        digits, scale = declared.precision or (5, 0)
        item.size, item.category = digits // 2 + 1, "packed-decimal"
        item.digits, item.scale, item.signed = digits, scale, True
        item.effective_usage = "PACKED-DECIMAL"
        return 1
    if mode == "fixed":
        bits, scale = declared.precision or (15, 0)
        limits = (8, 16, 32) if not declared.signed else (7, 15, 31)
        sizes = zip((1, 2, 4), limits, strict=True)
        item.size = next((size for size, limit in sizes if bits <= limit), 8)
        item.category, item.signed = "binary", declared.signed
        item.digits, item.scale = BINARY_DIGITS[item.size], 0
        item.effective_usage = "BINARY"
        if scale:
            warnings.append(f"line {item.line}: {item.name} has a binary scale factor of {scale}")
        return item.size
    precision = (declared.precision or ((6, 0) if base == "dec" else (21, 0)))[0]
    short, long = (6, 16) if base == "dec" else (21, 53)
    item.size = 4 if precision <= short else 8 if precision <= long else 16
    item.category = "float"
    item.effective_usage = "COMP-1" if item.size == 4 else "COMP-2"
    return min(item.size, 8)


def _pli_item(declared: _Declared, warnings: list[str]) -> tuple[Item, int, int]:
    """Return the item, its size in bits, and the boundary it needs when ALIGNED."""
    item = Item(level=declared.level, name=declared.name, line=declared.line)
    item.picture = re.sub(r"\s+\(", "(", " ".join(declared.text)) or None
    if declared.dims:
        numbers = _numbers(declared.dims.split("REFER", 1)[0])
        bounds = re.findall(r"(-?\d+)\s*:\s*(-?\d+)", declared.dims)
        count = int(bounds[0][1]) - int(bounds[0][0]) + 1 if bounds else (numbers or [1])[0]
        if not numbers:
            warnings.append(f"line {item.line}: {item.name} has a non-numeric bound; assumed 1")
        refer = re.search(r"REFER\s*\(\s*([\w#@$]+)", declared.dims, re.IGNORECASE)
        item.occurs_min = 1 if refer else count
        item.occurs_max = count
        item.depending_on = refer.group(1).upper() if refer else None
    kind = declared.kind
    boundary = 1
    if kind == "char":
        length = declared.length or 1
        item.category = "alphanumeric"
        item.size = length + (1 if declared.varying == "varyingz" else 0)
        if declared.varying == "varying":
            prefix = Item(level=declared.level + 1, name=f"{item.name}_LENGTH", line=item.line)
            prefix.size, prefix.category, prefix.digits, prefix.scale = 2, "binary", 4, 0
            prefix.effective_usage, prefix.picture = "BINARY", "FIXED BIN(16) UNSIGNED"
            text = Item(level=declared.level + 1, name=f"{item.name}_TEXT", line=item.line)
            text.size, text.category, text.picture = length, "alphanumeric", f"CHAR({length})"
            prefix.offset, text.offset = 0, 2
            item.children = [prefix, text]
            item.category, item.size, boundary = "group", length + 2, 2
    elif kind in {"graphic", "widechar"}:
        item.size = 2 * (declared.length or 1)
        item.category = "dbcs" if kind == "graphic" else "national"
        item.effective_usage = "DISPLAY-1" if kind == "graphic" else "NATIONAL"
    elif kind == "bit":
        item.bits = declared.length or 1
        item.category = "bit"
        return item, item.bits, 1
    elif kind == "arithmetic":
        boundary = _pli_arithmetic(item, declared, warnings)
    elif kind == "picture":
        _pli_picture(item, declared.picture or "")
    elif kind == "pointer":
        item.size, item.category, item.effective_usage, boundary = 4, "pointer", "POINTER", 4
    elif kind == "area":
        item.size, item.category, boundary = (declared.length or 0) + 16, "unknown", 8
    else:
        item.category = "unknown"
    return item, item.size * 8, boundary


@dataclass
class _PliState:
    warnings: list[str]
    padded: bool = False


ALIGNED_BY_DEFAULT = frozenset({"binary", "float", "pointer", "packed-decimal", "unknown"})


def _round(value: int, unit: int) -> int:
    return -(-value // unit) * unit


def _pli_place(node: _Node, start_bits: int, inherited: bool | None, state: _PliState) -> int:
    """Assign offsets within one structure; return the end position in bits.

    An explicit ALIGNED or UNALIGNED is inherited by members; otherwise arithmetic and
    pointer data default to ALIGNED and character, bit, graphic, and picture data to
    UNALIGNED, as in PL/I.
    """
    item, declared = node.item, node.declared
    explicit = declared.aligned if declared.aligned is not None else inherited
    occurrences = item.occurs_max or 1
    if node.children:
        start = _round(start_bits, 8)
        item.offset, item.category = start // 8, "group"
        cursor = end = start
        first: Item | None = None
        for child in node.children:
            if declared.union:
                end = max(end, _pli_place(child, start, explicit, state))
                if first is None:
                    first = child.item
                else:
                    child.item.redefines = first.name
            else:
                cursor = _pli_place(child, cursor, explicit, state)
                end = max(end, cursor)
        item.size = (_round(end, 8) - start) // 8
        return start + item.size * 8 * occurrences
    aligned = explicit if explicit is not None else item.category in ALIGNED_BY_DEFAULT
    if item.category == "bit":
        start = _round(start_bits, 8) if aligned else start_bits
        item.offset, item.bit_offset = start // 8, start % 8
        item.size = _round(item.bit_offset + node.bits, 8) // 8
        width = _round(node.bits, 8) if aligned else node.bits
        return start + width * occurrences
    start = _round(start_bits, 8)
    if aligned and node.boundary > 1:
        padded = _round(start, node.boundary * 8)
        if padded != start:
            item.slack_before = (padded - start) // 8
            state.padded = True
        start = padded
    item.offset = start // 8
    return start + node.bits * occurrences


@dataclass
class _Node:
    declared: _Declared
    item: Item
    bits: int
    boundary: int
    children: list[_Node] = field(default_factory=list)


def parse_pli(text: str, source: str, warnings: list[str]) -> Layout:
    """Parse the level-numbered structures in PL/I declarations into a layout."""
    lines = _strip_sequence(text.splitlines())
    cleaned = PLI_COMMENT.sub(lambda m: "\n" * m.group().count("\n"), "\n".join(lines))
    records: list[Item] = []
    for match in PLI_DECLARE.finditer(cleaned):
        body = match.group(1)
        stack: list[_Node] = []
        roots: list[_Node] = []
        for start, part in _split_top(body):
            line = cleaned[: match.start(1) + start].count("\n") + 1
            leading = len(part) - len(part.lstrip())
            line += part[:leading].count("\n")
            declared = _parse_pli_element(_pli_tokens(part), line, warnings)
            if declared is None:
                continue
            node = _Node(declared, *_pli_item(declared, warnings))
            while stack and stack[-1].declared.level >= declared.level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
        for root in roots:
            if not root.children:
                continue
            _warn_untyped(root, warnings)
            state = _PliState(warnings)
            _pli_place(root, 0, None, state)
            _attach(root)
            if state.padded:
                warnings.append(
                    f"{root.item.name}: ALIGNED items were placed on natural boundaries; "
                    "confirm the offsets with the compiler's AGGREGATE listing"
                )
            records.append(root.item)
    return Layout(source, records, warnings)


def _warn_untyped(node: _Node, warnings: list[str]) -> None:
    for child in node.children:
        if not child.children and child.declared.kind is None:
            item = child.item
            warnings.append(f"line {item.line}: {item.name} has no data attributes; size unknown")
        _warn_untyped(child, warnings)


def _attach(node: _Node) -> None:
    """Copy the parsed tree into the items, keeping VARYING prefixes in place."""
    if node.children:
        node.item.children = [child.item for child in node.children]
        for child in node.children:
            _attach(child)
    elif node.item.children:
        for child in node.item.children:
            child.offset += node.item.offset


@dataclass
class _Location:
    """The location counter and open groups of one DSECT."""

    record: Item
    counter: int = 0
    highest: int = 0
    groups: list[tuple[Item, int]] = field(default_factory=list)
    labels: dict[str, Item] = field(default_factory=dict)


def _hlasm_statements(lines: Sequence[str]) -> list[tuple[int, str, str, str]]:
    """Return (line, name, operation, operands) for each statement, joining continuations."""
    statements: list[tuple[int, str, str, str]] = []
    pending = ""
    first_line = 0
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n").ljust(72)
        if not pending and (line.startswith(("*", ".*")) or not line.strip()):
            continue
        text = line[:71] if not pending else line[15:71]
        if not pending:
            first_line = number
        if line[71] != " ":
            # A literal continues exactly at column 16; other operands use comma-blank style.
            pending += text if _open_quote(pending + text) else text.rstrip()
            continue
        pending += text
        name = pending[:1].strip() and pending.split(None, 1)[0]
        rest = pending[len(name) :].strip() if name else pending.strip()
        operation, _, operands = rest.partition(" ")
        statements.append((first_line, name or "", operation.upper(), _hlasm_operands(operands)))
        pending = ""
    return statements


def _open_quote(text: str) -> bool:
    return text.count("'") % 2 == 1


def _hlasm_operands(text: str) -> str:
    """Return the operand field, which ends at the first blank outside quotes."""
    quoted = False
    for index, char in enumerate(text.strip()):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return text.strip()[:index]
    return text.strip()


def _split_operands(text: str) -> list[str]:
    return [part.strip() for _, part in _split_top(text) if part.strip()]


def _hlasm_value_length(kind: str, value: str | None) -> int | None:
    if not value or not value.startswith("'"):
        return None
    body = value[1:-1].replace("''", "'")
    if kind in {"C", "CA", "CE"}:
        return len(body)
    if kind == "CU":
        return 2 * len(body)
    if kind == "X":
        return -(-len(body.replace(",", "")) // 2)
    if kind == "B":
        return -(-len(body.replace(",", "")) // 8)
    if kind == "P":
        return len(re.sub(r"[^0-9]", "", body)) // 2 + 1
    if kind == "Z":
        return len(re.sub(r"[^0-9]", "", body))
    return None


def _hlasm_field(
    name: str, operand: str, line: int, location: _Location, warnings: list[str]
) -> Item | None:
    match = HLASM_OPERAND.match(operand.upper())
    if match is None:
        warnings.append(f"line {line}: cannot size operand {operand!r}; skipped")
        return None
    kind = match.group("type").upper()
    implicit, boundary, category = HLASM_TYPES[kind]
    dup = int(match.group("dup").strip("()")) if match.group("dup") else 1
    explicit = match.group("length")
    length = int(explicit.strip("()")) if explicit else None
    length = length or _hlasm_value_length(kind, match.group("value")) or implicit
    if explicit:
        boundary = 1
    location.counter += (-location.counter) % boundary
    item = Item(level=2, name=name.upper() or "FILLER", line=line, picture=operand.upper())
    item.offset, item.size, item.category = location.counter, length, category
    usages = {"binary": "BINARY", "float": "COMP-2" if length == 8 else "COMP-1"}
    item.effective_usage = usages.get(category, "DISPLAY")
    if category == "packed-decimal":
        item.digits, item.scale, item.signed = 2 * length - 1, 0, True
        item.effective_usage = "PACKED-DECIMAL"
    elif category == "zoned-decimal":
        item.digits, item.scale, item.signed = length, 0, True
    elif category == "binary":
        item.digits, item.scale, item.signed = BINARY_DIGITS.get(length, 18), 0, True
    elif category in {"binary-float", "decimal-float"}:
        kind_text = category.replace("-", " ")
        warnings.append(f"line {line}: {item.name} is {kind_text}; decode it with care")
    if dup == 0:
        location.counter = item.offset
        return item if name and explicit else None
    if dup > 1:
        item.occurs_min = item.occurs_max = dup
    location.counter = item.offset + length * dup
    location.highest = max(location.highest, location.counter)
    return item


def _hlasm_add(
    location: _Location, item: Item, group_length: int | None, *, overlays: bool
) -> None:
    while location.groups and location.groups[-1][1] <= item.offset:
        location.groups.pop()
    parent = location.groups[-1][0] if location.groups else location.record
    item.level = parent.level + 1
    if overlays:
        overlay = next(
            (s for s in parent.children if s.offset == item.offset and not s.redefines), None
        )
        if overlay is not None and overlay.name != "FILLER":
            item.redefines = overlay.name
    parent.children.append(item)
    if item.name != "FILLER":
        location.labels[item.name] = item
    if group_length:
        item.category = "group"
        item.size = group_length
        location.groups.append((item, item.offset + group_length))


def _hlasm_org(operand: str, location: _Location, line: int, warnings: list[str]) -> None:
    if not operand:
        location.counter = location.highest
        return
    match = re.fullmatch(r"(\*|[\w#@$]+)\s*([+-]\s*\d+)?", operand.upper())
    base: int | None = None
    target: Item | None = None
    if match:
        base = location.counter if match.group(1) == "*" else None
        target = location.labels.get(match.group(1))
        base = target.offset if target is not None else base
    if base is None or match is None:
        warnings.append(f"line {line}: cannot evaluate ORG {operand}; ignored")
        return
    location.counter = base + int((match.group(2) or "0").replace(" ", ""))
    if target is not None and location.counter == target.offset:
        while location.groups and location.groups[-1][0].offset >= target.offset:
            location.groups.pop()


def parse_hlasm(text: str, source: str, warnings: list[str]) -> Layout:
    """Parse DS and DC statements in each DSECT into a record layout."""
    records: list[Item] = []
    location: _Location | None = None
    for line, name, operation, operands in _hlasm_statements(text.splitlines()):
        if operation == "DSECT":
            location = _Location(Item(level=1, name=name.upper() or "DSECT", line=line))
            records.append(location.record)
            continue
        if operation in {"CSECT", "RSECT", "START", "END", "LOCTR"} or location is None:
            if operation != "LOCTR":
                location = None
            continue
        if operation == "ORG":
            _hlasm_org(operands, location, line, warnings)
            continue
        if operation not in {"DS", "DC"}:
            continue
        for index, operand in enumerate(_split_operands(operands)):
            before, highest = location.counter, location.highest
            match = HLASM_OPERAND.match(operand.upper())
            item = _hlasm_field(name if index == 0 else "", operand, line, location, warnings)
            if item is None:
                continue
            group = None
            if match and match.group("dup") and match.group("dup").strip("()") == "0":
                group = item.size
                location.counter = item.offset
            _hlasm_add(location, item, group, overlays=item.offset < highest)
            if item.slack_before == 0 and item.offset > before and not item.redefines:
                item.slack_before = item.offset - before
    for record in records:
        record.category = "group"
        record.size = max((c.offset + c.total_size for c in record.children), default=0)
        _relative_redefines(record)
    return Layout(source, records, warnings)


def _relative_redefines(item: Item) -> None:
    """Drop REDEFINES names that do not refer to an earlier sibling."""
    names: set[str] = set()
    for child in item.children:
        if child.redefines and child.redefines not in names:
            child.redefines = None
        names.add(child.name)
        _relative_redefines(child)


def parse_source(
    path: Path | str,
    *,
    language: str = "auto",
    copylibs: Sequence[Path] = (),
    replacements: Sequence[tuple[str, str]] = (),
) -> Layout:
    """Parse a COBOL copybook, PL/I include, or HLASM DSECT into a layout."""
    if str(path) == "-":
        return copybook_layout.parse_copybook(path, copylibs=copylibs, replacements=replacements)
    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    chosen = detect_language(source, text) if language == "auto" else language
    warnings: list[str] = []
    if chosen == "pli":
        return parse_pli(text, str(source), warnings)
    if chosen == "hlasm":
        return parse_hlasm(text, str(source), warnings)
    return copybook_layout.parse_copybook(source, copylibs=copylibs, replacements=replacements)


def main(argv: list[str] | None = None) -> int:
    """Run copybook_layout.py, which detects PL/I and HLASM sources."""
    return copybook_layout.main(argv)


if __name__ == "__main__":
    sys.exit(main())
