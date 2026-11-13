#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Model CICS BMS and IMS MFS screens: field tables, 3270 mockups, and screen contracts.

Parses BMS mapsets (DFHMSD, DFHMDI, and DFHMDF macros) and IMS MFS formats and messages
(FMT, DEV, DIV, DPAGE, DFLD, FMTEND, MSG, LPAGE, SEG, MFLD, and MSGEND) written in
assembler macro format, including continuation lines. For every map it reports each
field's position, length, attributes, initial value, edit pictures, and role (constant,
input, output, numeric, hidden, initial cursor), draws a text mockup of the screen, and
lists the named fields that screen scrapers, RPA bots, and terminal-emulator macros depend
on. MFS message fields are linked to the device fields of the same name. With --symbolic it
checks a BMS symbolic-map copybook against the map. The script only reads files.

Examples:
    uv run --script screen_map.py CUSTMAP.bms > CUSTMAP.md
    uv run --script screen_map.py CUSTMAP.bms --symbolic CUSTMAP.cpy
    uv run --script screen_map.py CUSTFMT.mfs --format json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

DEFAULT_SIZE = (24, 80)
CONTINUATION_COLUMN = 72  # a non-blank character here continues the statement
CONTINUE_FROM = 16  # continuation lines resume in this column
MFS_MODEL_SIZES = {"1": (12, 40), "2": (24, 80), "3": (32, 80), "4": (43, 80), "5": (27, 132)}
EXTENDED_SUFFIXES = {
    "COLOR": "C",
    "HILIGHT": "H",
    "PS": "P",
    "VALIDN": "V",
    "OUTLINE": "U",
    "SOSI": "M",
    "TRANSP": "T",
}
EXTATT_ATTRIBUTES = ["COLOR", "HILIGHT", "PS", "VALIDN"]
TIOA_PREFIX = 12
LEGEND = (
    "Legend: constants show their text, `_` marks input positions (`9` for numeric input), "
    "`X` marks output positions, and attribute bytes and hidden fields are blank."
)
NAME = r"[A-Z0-9@#$][A-Z0-9@#$_-]*"
SYMBOLIC_ENTRY = re.compile(r"^(\d{1,2})\s+(" + NAME + r")\b(.*)$", re.DOTALL)
PICTURE = re.compile(r"(?<![A-Z0-9-])(?:PICTURE|PIC)\s+(?:IS\s+)?(\S+)")
REDEFINES = re.compile(r"(?<![A-Z0-9-])REDEFINES\s+(" + NAME + ")")
BINARY = re.compile(
    r"(?<![A-Z0-9-])(?:COMP|COMP-4|COMP-5|BINARY|COMPUTATIONAL(?:-[45])?)(?![A-Z0-9-])"
)
REPEAT = re.compile(r"(.)\((\d+)\)")
EARLY_LEVEL = re.compile(r"^ {0,6}\d{1,2}\s+\S")
FIXED_LEVEL = re.compile(r"^\s*\d{1,2}\s+\S")


@dataclass
class MacroStatement:
    """One assembler macro statement with its continuation lines joined."""

    line: int
    label: str
    operation: str
    operands: str


def _operand_end(text: str, quoted: bool) -> tuple[int, bool]:
    """Return where the operand field ends (first blank outside quotes) and the quote state."""
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return index, quoted
    return len(text), quoted


def read_statements(lines: Sequence[str]) -> list[MacroStatement]:
    """Join continuation lines into statements and drop comments, remarks, and columns 73-80.

    A non-blank character in column 72 continues a statement; the continuation resumes in
    column 16. The operand field ends at the first blank outside a quoted string.
    """
    statements: list[MacroStatement] = []
    current: MacroStatement | None = None
    quoted = False
    for number, line in enumerate(lines, start=1):
        continued = len(line) >= CONTINUATION_COLUMN and line[CONTINUATION_COLUMN - 1] != " "
        if current is not None:
            body = line[CONTINUE_FROM - 1 : CONTINUATION_COLUMN - 1]
            body = body if quoted else body.lstrip()
            end, quoted = _operand_end(body, quoted)
            current.operands += body[:end]
        elif line.strip() and not line.startswith(("*", ".*")):
            area = line[: CONTINUATION_COLUMN - 1]
            label = "" if area[:1].isspace() else area.split()[0]
            operation, _, operands = area[len(label) :].lstrip().partition(" ")
            operands = operands.lstrip()
            end, quoted = _operand_end(operands, False)
            current = MacroStatement(number, label.upper(), operation.upper(), operands[:end])
            statements.append(current)
        else:
            continue
        if not continued:
            current, quoted = None, False
    return statements


def split_operands(text: str) -> list[str]:
    """Split an operand field at commas outside quoted strings and parentheses."""
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part for part in parts if part]


def parse_value(text: str) -> Any:
    """Return a quoted string's text, a parenthesized list as a list, or the text as is."""
    if len(text) > 1 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'").replace("&&", "&")
    if text.startswith("(") and text.endswith(")"):
        return [parse_value(part) for part in split_operands(text[1:-1])]
    return text


def parse_operands(text: str) -> tuple[list[str], dict[str, Any]]:
    """Return the raw positional operands and the parsed keyword operands."""
    positional: list[str] = []
    keywords: dict[str, Any] = {}
    for part in split_operands(text):
        key, sep, value = part.partition("=")
        if sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
            keywords[key.upper()] = parse_value(value)
        else:
            positional.append(part)
    return positional, keywords


def _flags(value: Any) -> list[str]:
    """Return an operand value as a list of upper-case words."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item).upper() for item in items if item]


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None


def _pair(value: Any) -> tuple[int, int] | None:
    """Return the first two numbers of a list operand such as POS=(5,20)."""
    if isinstance(value, list) and len(value) >= 2:
        first, second = _int(value[0]), _int(value[1])
        if first is not None and second is not None:
            return first, second
    return None


def _roles(primary: str, attributes: Iterable[str], hidden: str) -> list[str]:
    """Return the primary role followed by numeric, hidden, and initial-cursor flags."""
    attrs = set(attributes)
    flags = (("NUM", "numeric"), (hidden, "hidden"), ("IC", "initial-cursor"))
    return [primary, *(label for attribute, label in flags if attribute in attrs)]


def _bms_role(name: str | None, attributes: Iterable[str], initial: str | None) -> str:
    """Classify a BMS field the way BMS fills in ATTRB defaults.

    Without ATTRB a field is ASKIP; with any ATTRB value but neither ASKIP nor PROT it is
    UNPROT.
    """
    attrs = set(attributes)
    protected = not attrs or bool(attrs & {"ASKIP", "PROT"})
    if not name or (protected and initial is not None):
        return "constant"
    return "output" if protected else "input"


def _positions(attribute: int, data: int, cols: int) -> dict[str, int]:
    """Return 1-based rows and columns for buffer offsets of an attribute byte and its data."""
    return {
        "row": attribute // cols + 1,
        "col": attribute % cols + 1,
        "data_row": data // cols + 1,
        "data_col": data % cols + 1,
    }


def _offset(field: dict[str, Any], cols: int) -> int:
    """Return the buffer offset of a field's first data position."""
    return (field["data_row"] - 1) * cols + field["data_col"] - 1


class _Parser:
    """Collect mapsets, maps, MFS formats, and messages from macro statements."""

    def __init__(self) -> None:
        self.mapsets: list[dict[str, Any]] = []
        self.screens: list[dict[str, Any]] = []
        self.formats: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.mapset: dict[str, Any] | None = None
        self.screen: dict[str, Any] | None = None
        self.device_format: dict[str, Any] | None = None
        self.message: dict[str, Any] | None = None
        self.group: tuple[str, list[str]] | None = None
        self.page: str | None = None
        self.next_offset = 0
        self.handlers: dict[str, Callable[[MacroStatement, list[str], dict[str, Any]], None]] = {
            "DFHMSD": self._dfhmsd,
            "DFHMDI": self._dfhmdi,
            "DFHMDF": self._dfhmdf,
            "FMT": self._fmt,
            "DEV": self._dev,
            "DIV": self._div,
            "DPAGE": self._dpage,
            "DFLD": self._dfld,
            "FMTEND": self._fmtend,
            "MSG": self._msg,
            "LPAGE": self._lpage,
            "SEG": self._seg,
            "MFLD": self._mfld,
            "MSGEND": self._msgend,
        }

    def feed(self, statement: MacroStatement) -> None:
        """Process one statement; statements other than BMS and MFS macros are ignored."""
        handler = self.handlers.get(statement.operation)
        if handler is not None:
            positional, keywords = parse_operands(statement.operands)
            handler(statement, positional, keywords)

    def _dfhmsd(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        if str(keywords.get("TYPE", "")).upper() == "FINAL":
            self.mapset = self.screen = None
            return
        extatt = str(keywords.get("EXTATT", "NO")).upper()
        mapatts = _flags(keywords.get("MAPATTS")) or (EXTATT_ATTRIBUTES if extatt != "NO" else [])
        dsatts = _flags(keywords.get("DSATTS")) or (EXTATT_ATTRIBUTES if extatt == "YES" else [])
        self.mapset = {
            "name": statement.label,
            "line": statement.line,
            "type": keywords.get("TYPE"),
            "mode": keywords.get("MODE"),
            "lang": keywords.get("LANG"),
            "storage": keywords.get("STORAGE"),
            "ctrl": _flags(keywords.get("CTRL")),
            "tioapfx": str(keywords.get("TIOAPFX", "NO")).upper() == "YES",
            "dsatts": dsatts,
            "mapatts": mapatts,
            "maps": [],
        }
        self.mapsets.append(self.mapset)

    def _dfhmdi(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        mapset = self.mapset
        if mapset is None:
            self.warnings.append(f"line {statement.line}: DFHMDI {statement.label} has no DFHMSD")
            mapset = {"name": None, "tioapfx": False, "dsatts": [], "mapatts": [], "maps": []}
        size = _pair(keywords.get("SIZE")) or DEFAULT_SIZE
        tioapfx = keywords.get("TIOAPFX")
        self.screen = {
            "name": statement.label,
            "kind": "bms-map",
            "parent": mapset["name"],
            "line": statement.line,
            "size": list(size),
            "map_line": keywords.get("LINE"),
            "map_column": keywords.get("COLUMN"),
            "ctrl": _flags(keywords.get("CTRL")),
            "tioapfx": mapset["tioapfx"] if tioapfx is None else str(tioapfx).upper() == "YES",
            "dsatts": _flags(keywords["DSATTS"]) if "DSATTS" in keywords else mapset["dsatts"],
            "mapatts": _flags(keywords["MAPATTS"]) if "MAPATTS" in keywords else mapset["mapatts"],
            "fields": [],
            "warnings": [],
        }
        mapset["maps"].append(statement.label)
        self.screens.append(self.screen)
        self.group = None
        self.next_offset = 0

    def _dfhmdf(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        screen = self.screen
        if screen is None:
            self.warnings.append(f"line {statement.line}: DFHMDF outside a DFHMDI map; ignored")
            return
        cols = screen["size"][1]
        name = statement.label or None
        label = name or f"unnamed field at line {statement.line}"
        position = keywords.get("POS")
        pair = _pair(position)
        if pair is not None:
            offset = (pair[0] - 1) * cols + pair[1] - 1
        elif _int(position) is not None:
            offset = int(position)
        else:
            offset = self.next_offset
            screen["warnings"].append(f"{label}: no POS; placed after the previous field")
        initial = keywords.get("INITIAL") if isinstance(keywords.get("INITIAL"), str) else None
        group = keywords.get("GRPNAME") if isinstance(keywords.get("GRPNAME"), str) else None
        continuing = group is not None and self.group is not None and self.group[0] == group
        attributes = self.group[1] if continuing and self.group else _flags(keywords.get("ATTRB"))
        self.group = (group, attributes) if group else None
        roles = _roles(_bms_role(name, attributes, initial), attributes, "DRK")
        length = _int(keywords.get("LENGTH"))
        if length is None:
            if roles[0] == "input":
                screen["warnings"].append(f"{label}: input field has no LENGTH")
            picout = keywords.get("PICOUT")
            length = _picture_length(picout) if isinstance(picout, str) else len(initial or "")
        occurs = _int(keywords.get("OCCURS")) or 1
        for index in range(occurs):
            attribute = offset + index * (length + 1)
            field: dict[str, Any] = {
                "name": f"{name}({index + 1})" if name and occurs > 1 else name,
                "line": statement.line,
                **_positions(attribute, attribute + 1, cols),
                "length": length,
                "attributes": attributes,
                "initial": initial,
                "picin": keywords.get("PICIN"),
                "picout": keywords.get("PICOUT"),
                "classification": roles,
                "attribute_byte": not continuing,
            }
            field |= {
                key.lower(): keywords[key]
                for key in ("JUSTIFY", "COLOR", "HILIGHT")
                if key in keywords
            }
            if group:
                field["group"] = group
            screen["fields"].append(field)
        self.next_offset = offset + occurs * (length + 1)

    def _fmt(self, statement: MacroStatement, _: list[str], __: dict[str, Any]) -> None:
        self.device_format = {"name": statement.label, "line": statement.line, "screens": []}
        self.formats[statement.label] = self.device_format
        self.screen = None

    def _dev(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        device = self.device_format
        if device is None:
            self.warnings.append(f"line {statement.line}: DEV outside an FMT; ignored")
            return
        device_type = _flags(keywords.get("TYPE"))
        size = DEFAULT_SIZE
        if device_type[:1] == ["3270"] and len(device_type) > 1:
            size = MFS_MODEL_SIZES.get(device_type[1], DEFAULT_SIZE)
        self.screen = {
            "name": device["name"],
            "kind": "mfs-device",
            "parent": device["name"],
            "line": statement.line,
            "size": list(size),
            "device": ",".join(device_type),
            "features": _flags(keywords.get("FEAT")),
            "cursor": [],
            "fields": [],
            "warnings": [],
        }
        device["screens"].append(self.screen)
        self.screens.append(self.screen)
        self.page = None

    def _div(self, _: MacroStatement, __: list[str], keywords: dict[str, Any]) -> None:
        if self.screen is not None and self.screen["kind"] == "mfs-device":
            self.screen["division"] = keywords.get("TYPE")

    def _dpage(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        self.page = statement.label or None
        cursor = keywords.get("CURSOR")
        if self.screen is not None and isinstance(cursor, list):
            pairs = [_pair(item) for item in cursor]
            self.screen["cursor"] += [list(pair) for pair in pairs if pair]

    def _dfld(
        self, statement: MacroStatement, positional: list[str], keywords: dict[str, Any]
    ) -> None:
        screen = self.screen
        if screen is None or screen["kind"] != "mfs-device":
            self.warnings.append(f"line {statement.line}: DFLD outside a DEV; ignored")
            return
        literal = (
            parse_value(positional[0]) if positional[:1] and positional[0][:1] == "'" else None
        )
        name = statement.label or None
        label = name or f"literal at line {statement.line}"
        attributes = _flags(keywords.get("ATTR"))
        pair = _pair(keywords.get("POS"))
        cols = screen["size"][1]
        if pair is None:
            data = self.next_offset + 1
            screen["warnings"].append(f"{label}: no POS; placed after the previous field")
        else:
            data = (pair[0] - 1) * cols + pair[1] - 1
        length = _int(keywords.get("LTH"))
        primary = "constant" if literal is not None else "input"
        if literal is None and "PROT" in attributes:
            primary = "output"
        if length is None:
            if primary == "input":
                screen["warnings"].append(f"{label}: input field has no LTH")
            length = len(literal or "")
        field: dict[str, Any] = {
            "name": name,
            "line": statement.line,
            **_positions(data - 1, data, cols),
            "length": length,
            "attributes": attributes,
            "initial": literal,
            "picin": None,
            "picout": None,
            "classification": _roles(primary, attributes, "NODISP"),
            "attribute_byte": True,
        }
        if self.page:
            field["page"] = self.page
        screen["fields"].append(field)
        self.next_offset = data + length

    def _fmtend(self, _: MacroStatement, __: list[str], ___: dict[str, Any]) -> None:
        self.device_format = self.screen = None

    def _msg(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        source = _flags(keywords.get("SOR"))
        self.message = {
            "name": statement.label,
            "line": statement.line,
            "type": str(keywords.get("TYPE", "")).upper() or None,
            "format": source[0] if source else None,
            "next": keywords.get("NXT"),
            "pages": [],
            "segments": 0,
            "fields": [],
        }
        self.messages.append(self.message)

    def _lpage(self, statement: MacroStatement, _: list[str], keywords: dict[str, Any]) -> None:
        if self.message is not None:
            pages = _flags(keywords.get("SOR"))
            self.message["pages"].append({"name": statement.label or None, "dpage": pages})

    def _seg(self, _: MacroStatement, __: list[str], ___: dict[str, Any]) -> None:
        if self.message is not None:
            self.message["segments"] += 1

    def _mfld(
        self, statement: MacroStatement, positional: list[str], keywords: dict[str, Any]
    ) -> None:
        if self.message is None:
            self.warnings.append(f"line {statement.line}: MFLD outside a MSG; ignored")
            return
        first = positional[0] if positional else ""
        value = parse_value(first)
        items = value if isinstance(value, list) else [value]
        quoted = [first] if not isinstance(value, list) else split_operands(first[1:-1])
        device_field = next(
            (str(v).upper() for v, raw in zip(items, quoted, strict=True) if raw[:1] != "'"), None
        )
        literal = next((v for v, raw in zip(items, quoted, strict=True) if raw[:1] == "'"), None)
        self.message["fields"].append(
            {
                "line": statement.line,
                "dfld": device_field or None,
                "literal": literal,
                "length": _int(keywords.get("LTH")),
                "attr": keywords.get("ATTR"),
                "segment": self.message["segments"],
            }
        )

    def _msgend(self, _: MacroStatement, __: list[str], ___: dict[str, Any]) -> None:
        self.message = None


def _check_screen(screen: dict[str, Any]) -> None:
    """Mark the MFS cursor field and add size and overlap warnings."""
    rows, cols = screen["size"]
    warnings = screen["warnings"]
    spans = []
    for field in screen["fields"]:
        label = field["name"] or f"constant at row {field['data_row']}, column {field['data_col']}"
        if [field["data_row"], field["data_col"]] in screen.get("cursor", []):
            field["classification"] = [*field["classification"], "initial-cursor"]
        start = _offset(field, cols)
        end = start + max(field["length"], 1) - 1
        if field["data_col"] + field["length"] - 1 > cols:
            warnings.append(f"{label}: runs past column {cols} and wraps to the next row")
        if end >= rows * cols or field["data_row"] > rows:
            warnings.append(f"{label}: extends beyond the {rows}x{cols} screen")
        spans.append((start - int(field["attribute_byte"]), end, label))
    spans.sort()
    for index, (_, end, label) in enumerate(spans):
        for other_start, _, other_label in spans[index + 1 :]:
            if other_start > end:
                break
            warnings.append(f"{label} overlaps {other_label}")


def _field_text(field: dict[str, Any]) -> str:
    """Return what a field shows in the mockup."""
    length = field["length"]
    roles = field["classification"]
    if "hidden" in roles and roles[0] != "input":
        return " " * length
    if roles[0] == "constant":
        return (field["initial"] or "").ljust(length)[:length]
    if roles[0] == "input":
        return ("9" if "numeric" in roles else "_") * length
    return "X" * length


def _mockup(screen: dict[str, Any]) -> list[str]:
    """Draw a screen as text, with a column ruler above it."""
    rows, cols = screen["size"]
    buffer = [" "] * (rows * cols)
    for field in screen["fields"]:
        start = _offset(field, cols)
        if field["attribute_byte"] and 0 < start <= len(buffer):
            buffer[start - 1] = " "
        for index, char in enumerate(_field_text(field)):
            if 0 <= start + index < len(buffer):
                buffer[start + index] = char
    width = len(str(rows))
    ruler = "".join(
        str(col // 10 % 10) if col % 10 == 0 else "+" if col % 5 == 0 else "-"
        for col in range(1, cols + 1)
    )
    lines = [" " * (width + 1) + ruler]
    for row in range(rows):
        text = "".join(buffer[row * cols : (row + 1) * cols]).rstrip()
        lines.append(f"{row + 1:0{width}d} {text}".rstrip())
    return lines


def parse_screens(path: Path, *, codepage: str = "037") -> dict[str, Any]:
    """Parse a BMS mapset or MFS source member into screen models.

    Raises:
        OSError: The file cannot be read.
        ValueError: The code page is unsupported or the file is binary.
    """
    codepage = zos_encoding.normalize_codepage(codepage)
    decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
    if decoded is None:
        raise ValueError(f"{path}: binary content, not BMS or MFS source")
    parser = _Parser()
    for statement in read_statements(decoded.text.splitlines()):
        parser.feed(statement)
    warnings = list(decoded.warnings) + parser.warnings
    for screen in parser.screens:
        _check_screen(screen)
        screen["mockup"] = _mockup(screen)
        screen["contract"] = [
            {
                "field": field["name"],
                "row": field["data_row"],
                "col": field["data_col"],
                "length": field["length"],
                "role": field["classification"][0],
            }
            for field in screen["fields"]
            if field["name"]
        ]
        warnings += [f"{screen['name']}: {warning}" for warning in screen["warnings"]]
    for message in parser.messages:
        device_format = parser.formats.get(message["format"] or "")
        for message_field in message["fields"]:
            name = message_field["dfld"]
            if not name:
                continue
            target = next(
                (
                    field
                    for screen in (device_format or {}).get("screens", [])
                    for field in screen["fields"]
                    if field["name"] == name
                ),
                None,
            )
            if target is None:
                warnings.append(
                    f"MSG {message['name']}: MFLD {name} has no DFLD in format {message['format']}"
                )
                continue
            message_field["device_field"] = {
                "row": target["data_row"],
                "col": target["data_col"],
                "length": target["length"],
            }
    bms = bool(parser.mapsets) or any(s["kind"] == "bms-map" for s in parser.screens)
    mfs = bool(parser.formats or parser.messages)
    kind = "+".join(name for name, found in (("bms", bms), ("mfs", mfs)) if found)
    return {
        "tool": "screen_map",
        "source": str(path),
        "encoding": decoded.encoding,
        "kind": kind or "unknown",
        "mapsets": parser.mapsets,
        "formats": [
            {
                "name": name,
                "line": value["line"],
                "devices": [s["device"] for s in value["screens"]],
            }
            for name, value in parser.formats.items()
        ],
        "messages": parser.messages,
        "screens": parser.screens,
        "legend": LEGEND,
        "warnings": warnings,
    }


def _picture_length(picture: str) -> int:
    """Return the character positions in a PICTURE string (S, V, and P take none)."""
    expanded = REPEAT.sub(lambda match: match.group(1) * int(match.group(2)), picture.upper())
    return sum(1 for char in expanded if char not in "SVP")


def _symbolic_items(path: Path, codepage: str) -> dict[str, dict[str, Any]]:
    """Parse a symbolic-map copybook lightly into data items keyed by name."""
    decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
    if decoded is None:
        raise ValueError(f"{path}: binary content, not a copybook")
    lines = decoded.text.splitlines()
    early = sum(1 for line in lines if EARLY_LEVEL.match(line))
    fixed = sum(1 for line in lines if FIXED_LEVEL.match(line[7:72]))
    if early > fixed:
        code = [line for line in lines if not line.lstrip().startswith("*")]
    else:
        code = [line[7:72] for line in lines if line[6:7] not in {"*", "/"}]
    items: dict[str, dict[str, Any]] = {}
    stack: list[dict[str, Any]] = []
    record = ""
    for entry in re.split(r"\.(?=\s|$)", "\n".join(code).upper()):
        match = SYMBOLIC_ENTRY.match(" ".join(entry.split()))
        if not match:
            continue
        level, name, clauses = int(match.group(1)), match.group(2), match.group(3)
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        record = name if level == 1 else record
        picture = PICTURE.search(clauses)
        redefines = REDEFINES.search(clauses)
        item = {
            "level": level,
            "name": name,
            "record": record,
            "parent": stack[-1] if stack else None,
            "redefines": redefines.group(1) if redefines else None,
            "length": _picture_length(picture.group(1)) if picture else None,
            "binary": bool(BINARY.search(clauses)),
            "children": [],
        }
        if stack:
            stack[-1]["children"].append(item)
        stack.append(item)
        if name != "FILLER":
            items.setdefault(name, item)
    return items


def _check_field(
    base: str, field: dict[str, Any], screen: dict[str, Any], items: dict[str, dict[str, Any]]
) -> list[str]:
    """Return findings for the symbolic-map entries generated for one named field."""
    findings = []
    where = screen["name"]
    expected = [] if field.get("group") else [("L", "2-byte binary length"), ("F", "flag byte")]
    expected += [] if field.get("group") else [("A", "attribute byte redefining the flag")]
    expected += [
        (EXTENDED_SUFFIXES[attribute], f"{attribute} attribute")
        for attribute in screen["dsatts"]
        if attribute in EXTENDED_SUFFIXES and not field.get("group")
    ]
    expected += [("I", f"input field of {field['length']} bytes"), ("O", "output field")]
    for suffix, meaning in expected:
        item = items.get(base + suffix)
        if item is None:
            findings.append(f"{where}: missing {base}{suffix} ({meaning})")
        elif suffix == "L" and not (item["binary"] and (item["length"] or 0) <= 4):
            findings.append(f"{where}: {base}L should be PIC S9(4) COMP, a 2-byte binary length")
        elif suffix == "A":
            parent = item["parent"] or {}
            if base + "F" not in {item["redefines"], parent.get("redefines")}:
                findings.append(f"{where}: {base}A does not redefine {base}F")
        elif suffix in {"I", "O"} and item["length"] not in {None, field["length"]}:
            findings.append(
                f"{where}: {base}{suffix} is {item['length']} bytes but the map field is "
                f"{field['length']}"
            )
        elif suffix == "O" and item["record"] != f"{where}O":
            findings.append(f"{where}: {base}O is not in {where}O")
    return findings


def check_symbolic_map(
    result: dict[str, Any], copybook_path: Path, *, codepage: str = "037"
) -> list[str]:
    """Check a BMS symbolic-map copybook against the parsed maps and return findings.

    Expects, for each named field, the length (L), flag (F) with its attribute (A)
    redefinition, any extended attributes that DSATTS requests, input (I), and output (O)
    entries, with the output structure redefining the input. Findings that start with
    ``note:`` are informational.

    Raises:
        OSError: The copybook cannot be read.
        ValueError: The copybook is binary or the code page is unsupported.
    """
    items = _symbolic_items(copybook_path, zos_encoding.normalize_codepage(codepage))
    maps = [screen for screen in result["screens"] if screen["kind"] == "bms-map"]
    if not maps:
        return ["note: no BMS maps to check; MFS formats have no symbolic map"]
    findings: list[str] = []
    for screen in maps:
        name = screen["name"]
        input_record, output_record = items.get(f"{name}I"), items.get(f"{name}O")
        if input_record is None:
            findings.append(f"{name}: missing 01 {name}I (input structure)")
        if output_record is None:
            findings.append(f"{name}: missing 01 {name}O (output structure)")
        elif output_record["redefines"] != f"{name}I":
            findings.append(f"{name}: 01 {name}O does not REDEFINES {name}I")
        if screen["tioapfx"]:
            children = input_record["children"] if input_record else []
            prefix = (
                children[:1]
                and children[0]["name"] == "FILLER"
                and children[0]["length"] == TIOA_PREFIX
            )
            findings.append(
                f"note: {name}: TIOAPFX=YES adds a 12-byte FILLER prefix to {name}I"
                if prefix
                else f"{name}: TIOAPFX=YES, but {name}I does not start with a 12-byte FILLER"
            )
        unexpected = [
            a for a in screen["mapatts"] if a not in screen["dsatts"] and a in EXTENDED_SUFFIXES
        ]
        if unexpected:
            findings.append(
                f"note: {name}: MAPATTS lists {', '.join(unexpected)} but DSATTS does not, so "
                "the symbolic map has no subfields for them"
            )
        checked: set[str] = set()
        for field in screen["fields"]:
            base = (field["name"] or "").split("(")[0]
            if base and base not in checked:
                checked.add(base)
                findings += _check_field(base, field, screen, items)
    return findings


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = ",".join(str(item) for item in value)
    return str(value).replace("|", "\\|")


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)
    return [*lines, ""]


def _md_screen(screen: dict[str, Any]) -> list[str]:
    rows, cols = screen["size"]
    if screen["kind"] == "bms-map":
        title = f"## Map {screen['name']} (mapset {screen['parent']}, {rows}x{cols})"
    else:
        title = f"## MFS format {screen['name']} (DEV TYPE=({screen['device']}), {rows}x{cols})"
    fields = [
        (
            field["name"] or "",
            field["row"],
            field["col"],
            field["data_row"],
            field["data_col"],
            field["length"],
            field["attributes"],
            f"`{field['initial']}`" if field["initial"] else "",
            field["picin"],
            field["picout"],
            ", ".join(field["classification"]),
        )
        for field in screen["fields"]
    ]
    header = ["Field", "Row", "Col", "Data row", "Data col", "Length", "Attributes", "Initial"]
    lines = [title, "", f"Defined at line {screen['line']}.", ""]
    lines += _table([*header, "PICIN", "PICOUT", "Role"], fields)
    lines += ["### Mockup", "", "```text", *screen["mockup"], "```", "", LEGEND, ""]
    lines += [
        "### Screen contract",
        "",
        (
            "Named fields that screen scrapers, RPA bots, and terminal-emulator macros read or "
            "type into. Row and column give the first data position (1-based); the attribute "
            "byte is just before it."
        ),
        "",
    ]
    contract = [
        (c["field"], c["row"], c["col"], c["length"], c["role"]) for c in screen["contract"]
    ]
    lines += (
        _table(["Field", "Row", "Col", "Length", "Role"], contract)
        if contract
        else ["No named fields.", ""]
    )
    return lines


def to_markdown(result: dict[str, Any]) -> str:
    """Render the screen models as Markdown."""
    lines = [
        f"# Screens: {Path(result['source']).name}",
        "",
        f"Source: `{result['source']}` ({result['encoding']}, {result['kind']}).",
        "",
    ]
    for mapset in result["mapsets"]:
        options = [
            f"{key.upper()}={_cell(mapset[key])}"
            for key in ("type", "mode", "lang", "storage", "ctrl", "dsatts", "mapatts")
            if mapset[key]
        ]
        options.append(f"TIOAPFX={'YES' if mapset['tioapfx'] else 'NO'}")
        lines += [f"Mapset **{mapset['name']}** (line {mapset['line']}): {', '.join(options)}.", ""]
    for screen in result["screens"]:
        lines += _md_screen(screen)
    if result["messages"]:
        rows = [
            (
                message["name"],
                message["type"],
                message["format"],
                field["dfld"] or f"'{field['literal']}'",
                field["length"],
                (field.get("device_field") or {}).get("row"),
                (field.get("device_field") or {}).get("col"),
            )
            for message in result["messages"]
            for field in message["fields"]
        ]
        lines += ["## MFS messages", "", "Message fields and the device fields they map to.", ""]
        lines += _table(["Message", "Type", "Format", "Field", "Length", "Row", "Col"], rows)
    check = result.get("symbolic_map_check")
    if check is not None:
        lines += [f"## Symbolic map check: {check['copybook']}", ""]
        lines += [f"- {finding}" for finding in check["findings"]] or ["No findings."]
        lines.append("")
    if result["warnings"]:
        lines += ["## Warnings", "", *(f"- {warning}" for warning in result["warnings"]), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, model the screens, and print them."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("source", type=Path, help="BMS mapset or MFS source member.")
    parser.add_argument(
        "--symbolic", type=Path, metavar="COPYBOOK", help="BMS symbolic-map copybook to check."
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--codepage", default="037", help="EBCDIC code page for EBCDIC members (default: 037)."
    )
    args = parser.parse_args(argv)
    if not args.source.is_file():
        print(f"error: not found: {args.source}", file=sys.stderr)
        return 1
    try:
        result = parse_screens(args.source, codepage=args.codepage)
        if args.symbolic is not None and result["kind"] != "unknown":
            findings = check_symbolic_map(result, args.symbolic, codepage=args.codepage)
            result["symbolic_map_check"] = {"copybook": str(args.symbolic), "findings": findings}
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result["kind"] == "unknown":
        print(
            f"error: {args.source}: no BMS (DFHMSD, DFHMDI, DFHMDF) or MFS (FMT, DFLD, MSG, MFLD) "
            "statements found",
            file=sys.stderr,
        )
        return 1
    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(to_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
