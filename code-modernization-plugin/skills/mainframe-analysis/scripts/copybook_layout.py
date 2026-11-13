#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compute byte offsets and lengths for COBOL copybook record layouts.

Parses IBM Enterprise COBOL data description entries in fixed or free format and reports
each field's 1-based position, byte length, picture, usage, digits, scale, OCCURS and
REDEFINES structure, 88-level conditions, and a DFSORT format hint. It can also draft a
JSON Schema for API contracts. The script only reads files.

Storage rules follow IBM Enterprise COBOL with LP(32). SYNCHRONIZED slack bytes are not
computed; confirm such layouts against the compiler MAP listing.

Examples:
    uv run --script copybook_layout.py CUSTREC.cpy
    uv run --script copybook_layout.py CUSTREC.cpy --format markdown
    uv run --script copybook_layout.py CUSTREC.cpy --format json-schema
    uv run --script copybook_layout.py ORDERS.cpy --copylib copybooks --replace :PFX: WS
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

FIXED_AREA_WIDTH = 65  # columns 8-72 of a fixed-format line
MAX_COPY_DEPTH = 16
MAX_SAFE_INTEGER = 2**53 - 1
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

ASSUMPTIONS = (
    (
        "IBM Enterprise COBOL storage: BINARY, COMP, COMP-4, and COMP-5 take 2, 4, or 8 bytes "
        "for 1-4, 5-9, or 10-18 digits; PACKED-DECIMAL (COMP-3) takes digits // 2 + 1 bytes."
    ),
    (
        "LP(32): POINTER, POINTER-32, INDEX, and FUNCTION-POINTER take 4 bytes; "
        "PROCEDURE-POINTER takes 8 bytes."
    ),
    "offset is 0-based; position is 1-based, as in DFSORT statements and compiler MAP listings.",
    (
        "Fields inside an OCCURS table describe the first occurrence; occurrence n starts "
        "(n - 1) * stride bytes later."
    ),
    "SYNCHRONIZED slack bytes are not computed.",
)

USAGE_ALIASES = {
    "DISPLAY": "DISPLAY",
    "DISPLAY-1": "DISPLAY-1",
    "NATIONAL": "NATIONAL",
    "UTF-8": "UTF-8",
    "BINARY": "BINARY",
    "COMP": "BINARY",
    "COMPUTATIONAL": "BINARY",
    "COMP-4": "BINARY",
    "COMPUTATIONAL-4": "BINARY",
    "COMP-5": "COMP-5",
    "COMPUTATIONAL-5": "COMP-5",
    "COMP-3": "PACKED-DECIMAL",
    "COMPUTATIONAL-3": "PACKED-DECIMAL",
    "PACKED-DECIMAL": "PACKED-DECIMAL",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-1": "COMP-1",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-2": "COMP-2",
    "INDEX": "INDEX",
    "POINTER": "POINTER",
    "POINTER-32": "POINTER-32",
    "PROCEDURE-POINTER": "PROCEDURE-POINTER",
    "FUNCTION-POINTER": "FUNCTION-POINTER",
}
FIXED_SIZE_USAGES = {
    "COMP-1": 4,
    "COMP-2": 8,
    "INDEX": 4,
    "POINTER": 4,
    "POINTER-32": 4,
    "PROCEDURE-POINTER": 8,
    "FUNCTION-POINTER": 4,
}
CLAUSE_WORDS = frozenset(
    {
        "ARE",
        "ASCENDING",
        "BLANK",
        "BY",
        "DATE",
        "DEPENDING",
        "DESCENDING",
        "EXTERNAL",
        "FALSE",
        "GLOBAL",
        "GROUP-USAGE",
        "INDEXED",
        "IS",
        "JUST",
        "JUSTIFIED",
        "KEY",
        "LEADING",
        "NATIVE",
        "OBJECT",
        "OCCURS",
        "ON",
        "PIC",
        "PICTURE",
        "REDEFINES",
        "RENAMES",
        "SIGN",
        "SYNC",
        "SYNCHRONIZED",
        "TIMES",
        "TO",
        "TRAILING",
        "USAGE",
        "VALUE",
        "VALUES",
        "VOLATILE",
        "WHEN",
        *USAGE_ALIASES,
    }
)
LITERAL_PREFIXES = frozenset({"B", "BX", "G", "N", "NX", "U", "UX", "X", "Z"})
NUMERIC_CATEGORIES = frozenset({"zoned-decimal", "packed-decimal", "binary", "national-decimal"})
CHARACTER_WIDTH = {"national": 2, "national-edited": 2, "dbcs": 2, "utf-8": 4}
DFSORT_FORMATS = {
    "packed-decimal": "PD",
    "float": "FL",
    "alphanumeric": "CH",
    "alphabetic": "CH",
    "alphanumeric-edited": "CH",
    "numeric-edited": "CH",
}

EARLY_LEVEL = re.compile(r"^ {0,6}\d{1,2}\s+\S")
FIXED_LEVEL = re.compile(r"^\s*\d{1,2}\s+\S")
REPEAT = re.compile(r"(.)\((\d+)\)")
COPY_STATEMENT = re.compile(
    r"(?<![A-Z0-9-])COPY\s+(?P<member>'[^']+'|\"[^\"]+\"|[A-Z0-9@#$_-]+)"
    r"(?:\s+(?:OF|IN)\s+[A-Z0-9@#$_-]+)?(?:\s+SUPPRESS)?"
    r"(?P<replacing>\s+REPLACING\s.*?)?\.(?=\s|$)",
    re.IGNORECASE | re.DOTALL,
)
REPLACING_OPERAND = re.compile(
    r"(?:(?P<mode>LEADING|TRAILING)\s+)?"
    r"(?P<old>==.*?==|'[^']*'|\"[^\"]*\"|[^\s=]+)\s+BY\s+"
    r"(?P<new>==.*?==|'[^']*'|\"[^\"]*\"|[^\s=]+)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class Token:
    """One COBOL text word or literal and the line it starts on."""

    text: str
    line: int
    literal: bool = False

    @property
    def upper(self) -> str:
        """Return the token text in upper case."""
        return self.text.upper()


@dataclass(eq=False)
class Condition:
    """An 88-level condition name and the values that make it true."""

    name: str
    values: list[str]


@dataclass(eq=False)
class Item:
    """A data description entry and its computed storage."""

    level: int
    name: str
    line: int
    picture: str | None = None
    usage: str | None = None
    occurs_min: int | None = None
    occurs_max: int | None = None
    depending_on: str | None = None
    redefines: str | None = None
    renames: tuple[str, str | None] | None = None
    values: list[str] = field(default_factory=list)
    sign_leading: bool | None = None
    sign_separate: bool | None = None
    sync: bool = False
    justified: bool = False
    blank_when_zero: bool = False
    synthetic: bool = False
    children: list[Item] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    aliases: list[Item] = field(default_factory=list)
    offset: int = 0
    size: int = 0
    category: str = "group"
    effective_usage: str = "DISPLAY"
    digits: int | None = None
    scale: int | None = None
    signed: bool = False
    leading: bool = False
    separate: bool = False
    variable_offset: bool = False

    @property
    def total_size(self) -> int:
        """Return the bytes occupied by all occurrences of the item."""
        return self.size * (self.occurs_max or 1)


@dataclass
class Layout:
    """Computed records for one copybook, plus warnings raised while parsing."""

    source: str
    records: list[Item]
    warnings: list[str]


@dataclass(frozen=True)
class _Picture:
    category: str
    positions: int
    digits: int
    scale: int
    signed: bool


@dataclass(frozen=True)
class _Replacement:
    mode: str  # pseudo, word, leading, or trailing
    old: str
    new: str


class _Library:
    """Index of the members in one copy library directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.members: dict[str, list[Path]] = {}
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    self.members.setdefault(path.stem.upper(), []).append(path)

    def find(self, name: str) -> list[Path]:
        """Return the files whose name, without extension, matches ``name``."""
        return self.members.get(name.upper(), [])


def _is_free_format(lines: Sequence[str]) -> bool:
    """Guess whether source uses free format rather than fixed columns."""
    if any(">>SOURCE" in line.upper() and "FREE" in line.upper() for line in lines):
        return True
    early = sum(1 for line in lines if EARLY_LEVEL.match(line))
    fixed = sum(1 for line in lines if len(line) > 7 and FIXED_LEVEL.match(line[7:72]))
    return early > fixed


def _has_open_literal(text: str) -> bool:
    """Return whether ``text`` ends inside an alphanumeric literal."""
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote and text[index + 1 : index + 2] == quote:
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        index += 1
    return bool(quote)


def normalize_source(lines: Sequence[str], *, free: bool | None = None) -> str:
    """Return code text without sequence areas, comment lines, or continuation markers.

    Every physical line keeps its own output line, so token line numbers stay accurate.
    """
    if free is None:
        free = _is_free_format(lines)
    out: list[str] = []
    last = -1
    for raw in lines:
        line = raw.rstrip("\r\n")
        if free:
            out.append("" if line.lstrip().startswith(">>") else line)
        elif len(line) < 7 or line[6] in "*/Dd" or line[7:72].lstrip().startswith(">>"):
            out.append("")
        elif line[6] == "-" and last >= 0:
            continuation = line[7:72].ljust(FIXED_AREA_WIDTH).lstrip()
            previous = out[last]
            if continuation[:1] in {"'", '"'} and _has_open_literal(previous):
                out[last] = previous + continuation[1:]
            else:
                out[last] = previous.rstrip() + continuation
            out.append("")
            continue
        else:
            out.append(line[7:72].ljust(FIXED_AREA_WIDTH))
        if out[-1].strip():
            last = len(out) - 1
    return "\n".join(out)


class _Lexer:
    """Split normalized COBOL text into period-terminated entries of tokens."""

    def __init__(self, text: str, warnings: list[str]) -> None:
        self.text = text
        self.warnings = warnings
        self.entries: list[list[Token]] = []
        self.current: list[Token] = []
        self.word: list[str] = []
        self.word_line = 1
        self.line = 1

    def run(self) -> list[list[Token]]:
        """Tokenize the whole text and return its entries."""
        text = self.text
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\n":
                self._flush()
                self.line += 1
                index += 1
            elif char in " \t":
                self._flush()
                index += 1
            elif text.startswith("*>", index):
                self._flush()
                end = text.find("\n", index)
                index = len(text) if end < 0 else end
            elif char in "'\"":
                index = self._literal(index)
            elif char == "." and text[index + 1 : index + 2] in {"", " ", "\t", "\n"}:
                self._flush()
                self._end_entry()
                index += 1
            else:
                if not self.word:
                    self.word_line = self.line
                self.word.append(char)
                index += 1
        self._flush()
        self._end_entry()
        return self.entries

    def _flush(self) -> None:
        text = "".join(self.word).rstrip(",;")
        self.word = []
        if text and text.upper() not in {"EJECT", "SKIP1", "SKIP2", "SKIP3"}:
            self.current.append(Token(text, self.word_line))

    def _end_entry(self) -> None:
        if self.current:
            self.entries.append(self.current)
            self.current = []

    def _literal(self, start: int) -> int:
        text = self.text
        quote = text[start]
        prefix = "".join(self.word)
        if prefix.upper() in LITERAL_PREFIXES:
            self.word = []
        else:
            self._flush()
            prefix = ""
        index = start + 1
        closed = False
        while index < len(text) and text[index] != "\n":
            if text[index] == quote and text[index + 1 : index + 2] == quote:
                index += 2
                continue
            index += 1
            if text[index - 1] == quote:
                closed = True
                break
        if not closed:
            self.warnings.append(f"line {self.line}: unterminated literal")
        self.current.append(Token(prefix + text[start:index], self.line, literal=True))
        return index


class _Cursor:
    """Sequential reader over the tokens of one entry."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self) -> str:
        """Return the upper-cased current token, or an empty string at the end."""
        if self.index < len(self.tokens):
            return self.tokens[self.index].upper
        return ""

    def take(self) -> Token | None:
        """Consume and return the current token."""
        if self.index >= len(self.tokens):
            return None
        self.index += 1
        return self.tokens[self.index - 1]

    def take_int(self) -> int | None:
        """Consume the current token if it is an unsigned integer."""
        if not self.peek().isdigit():
            return None
        token = self.take()
        return int(token.text) if token else None

    def skip(self, *words: str) -> None:
        """Consume any run of the given optional words."""
        while self.peek() and self.peek() in words:
            self.index += 1


def _parse_usage(item: Item, cursor: _Cursor, warnings: list[str]) -> None:
    token = cursor.take()
    if token is None:
        return
    if token.upper == "OBJECT":
        cursor.skip("REFERENCE")
        if cursor.peek() and cursor.peek() not in CLAUSE_WORDS:
            cursor.take()
        item.usage = "OBJECT-REFERENCE"
    elif token.upper in USAGE_ALIASES:
        item.usage = USAGE_ALIASES[token.upper]
    else:
        warnings.append(f"line {token.line}: unknown USAGE {token.text} in {item.name}")
    cursor.skip("NATIVE")


def _parse_occurs(item: Item, cursor: _Cursor, warnings: list[str]) -> None:
    low = cursor.take_int()
    if low is None:
        warnings.append(f"line {item.line}: OCCURS without a count in {item.name}")
        return
    high: int | None = low
    if cursor.peek() == "TO":
        cursor.take()
        if cursor.peek() == "UNBOUNDED":
            cursor.take()
            high = None
            warnings.append(
                f"line {item.line}: {item.name} OCCURS TO UNBOUNDED; size uses the minimum count"
            )
        else:
            high = cursor.take_int()
    cursor.skip("TIMES")
    if cursor.peek() == "DEPENDING":
        cursor.take()
        cursor.skip("ON")
        target = cursor.take()
        item.depending_on = target.upper if target else None
    while cursor.peek() in {"ASCENDING", "DESCENDING", "INDEXED"}:
        cursor.take()
        cursor.skip("KEY", "IS", "BY")
        while cursor.peek() and cursor.peek() not in CLAUSE_WORDS:
            cursor.take()
    item.occurs_min = low
    item.occurs_max = high if high is not None else low


def _parse_values(item: Item, cursor: _Cursor) -> None:
    words: list[str] = []
    while cursor.index < len(cursor.tokens):
        token = cursor.tokens[cursor.index]
        if not token.literal and token.upper in CLAUSE_WORDS:
            break
        words.append(token.text)
        cursor.index += 1
    index = 0
    while index < len(words):
        word = words[index]
        has_next = index + 1 < len(words)
        if word.upper() == "ALL" and has_next:
            item.values.append(f"ALL {words[index + 1]}")
            index += 2
        elif word.upper() in {"THRU", "THROUGH"} and item.values and has_next:
            item.values[-1] = f"{item.values[-1]} THRU {words[index + 1]}"
            index += 2
        else:
            item.values.append(word)
            index += 1


def _parse_clauses(item: Item, cursor: _Cursor, warnings: list[str]) -> None:
    while (token := cursor.take()) is not None:
        word = token.upper
        if word in {"PIC", "PICTURE"}:
            cursor.skip("IS")
            picture = cursor.take()
            item.picture = picture.upper if picture else None
        elif word == "USAGE":
            cursor.skip("IS")
            _parse_usage(item, cursor, warnings)
        elif word in USAGE_ALIASES or word == "OBJECT":
            cursor.index -= 1
            _parse_usage(item, cursor, warnings)
        elif word == "GROUP-USAGE":
            cursor.skip("IS")
            group_usage = cursor.take()
            if group_usage is not None:
                item.usage = USAGE_ALIASES.get(group_usage.upper, item.usage)
        elif word == "REDEFINES":
            target = cursor.take()
            item.redefines = target.upper if target else None
        elif word == "OCCURS":
            _parse_occurs(item, cursor, warnings)
        elif word in {"VALUE", "VALUES"}:
            cursor.skip("IS", "ARE")
            _parse_values(item, cursor)
        elif word in {"LEADING", "TRAILING"}:
            item.sign_leading = word == "LEADING"
            item.sign_separate = cursor.peek() == "SEPARATE"
            cursor.skip("SEPARATE", "CHARACTER")
        elif word in {"SYNC", "SYNCHRONIZED"}:
            item.sync = True
            cursor.skip("LEFT", "RIGHT")
        elif word in {"JUST", "JUSTIFIED"}:
            item.justified = True
            cursor.skip("RIGHT")
        elif word == "BLANK":
            cursor.skip("WHEN", "ZERO", "ZEROS", "ZEROES")
            item.blank_when_zero = True
        elif word == "RENAMES":
            first = cursor.take()
            last = None
            if cursor.peek() in {"THRU", "THROUGH"}:
                cursor.take()
                end = cursor.take()
                last = end.upper if end else None
            item.renames = (first.upper if first else "", last)
        elif word in {"DATE", "WHEN", "FALSE"}:
            cursor.skip("FORMAT", "SET", "TO", "FALSE", "IS")
            cursor.take()
        elif word not in {"SIGN", "IS", "GLOBAL", "EXTERNAL", "VOLATILE", "NATIVE"}:
            warnings.append(f"line {token.line}: ignored {token.text} in {item.name}")


def _parse_entry(tokens: list[Token], warnings: list[str]) -> Item | None:
    head = tokens[0]
    if not head.text.isdigit():
        return None
    level = int(head.text)
    if not (1 <= level <= 49 or level in {66, 77, 88}):
        warnings.append(f"line {head.line}: {head.text} is not a valid level number")
        return None
    cursor = _Cursor(tokens[1:])
    name = "FILLER"
    if cursor.tokens and not cursor.tokens[0].literal:
        candidate = cursor.tokens[0].upper
        if candidate not in CLAUSE_WORDS:
            name = candidate
            cursor.index = 1
    item = Item(level=level, name=name, line=head.line)
    _parse_clauses(item, cursor, warnings)
    return item


def _build_records(items: list[Item], warnings: list[str], default_name: str) -> list[Item]:
    records: list[Item] = []
    stack: list[Item] = []
    last: Item | None = None
    for item in items:
        if item.level == 88:
            if last is None:
                warnings.append(f"line {item.line}: 88-level {item.name} has no data item")
            else:
                last.conditions.append(Condition(item.name, item.values))
            continue
        if item.level == 66:
            if records:
                records[-1].aliases.append(item)
            else:
                warnings.append(f"line {item.line}: 66-level {item.name} has no record")
            continue
        if item.level in {1, 77}:
            records.append(item)
            stack = [item]
        else:
            while stack and stack[-1].level >= item.level:
                stack.pop()
            if not stack:
                root = Item(level=1, name=default_name, line=item.line, synthetic=True)
                warnings.append(
                    f"line {item.line}: no 01-level item; fields are grouped under a synthetic "
                    f"record {default_name} and offsets are relative to its start"
                )
                records.append(root)
                stack = [root]
            stack[-1].children.append(item)
            stack.append(item)
        last = item
    return records


def _expand_picture(picture: str) -> str:
    return REPEAT.sub(lambda match: match.group(1) * int(match.group(2)), picture.upper())


def _analyze_picture(picture: str) -> _Picture:
    """Classify a PICTURE string and count its storage positions, digits, and scale."""
    expanded = _expand_picture(picture)
    symbols = set(expanded)
    if "N" in symbols:
        category = "national" if symbols <= {"N"} else "national-edited"
    elif "G" in symbols:
        category = "dbcs"
    elif "U" in symbols:
        category = "utf-8"
    elif "E" in symbols and "9" in symbols and symbols & {"+", "-"}:
        category = "external-float"
    elif symbols <= {"A", "B"}:
        category = "alphabetic"
    elif symbols <= {"9", "S", "V", "P"}:
        category = "numeric"
    elif "X" in symbols or "A" in symbols:
        category = "alphanumeric" if symbols <= {"X", "A", "9"} else "alphanumeric-edited"
    else:
        category = "numeric-edited"
    if category != "numeric":
        positions = sum(1 for char in expanded if char not in "SVP")
        return _Picture(category, positions, 0, 0, signed=False)
    body = expanded.replace("S", "")
    digits = body.count("9")
    if "V" in body:
        left, right = body.split("V", 1)
        scale = len(right) - left.count("P")
    elif body.startswith("P"):
        scale = len(body)
    else:
        scale = -(len(body) - len(body.rstrip("P")))
    return _Picture(category, digits, digits, scale, signed=expanded.startswith("S"))


def _size_numeric(item: Item, picture: _Picture, warnings: list[str]) -> None:
    item.digits = picture.digits
    item.scale = picture.scale
    item.signed = picture.signed
    usage = item.effective_usage
    sign_byte = 1 if item.signed and item.separate else 0
    if usage in {"BINARY", "COMP-5"}:
        if picture.digits > 18:
            warnings.append(f"line {item.line}: binary item {item.name} has more than 18 digits")
        item.size = 2 if picture.digits <= 4 else 4 if picture.digits <= 9 else 8
        item.category = "binary"
    elif usage == "PACKED-DECIMAL":
        item.size = picture.digits // 2 + 1
        item.category = "packed-decimal"
    elif usage == "NATIONAL":
        item.size = 2 * (picture.digits + sign_byte)
        item.category = "national-decimal"
    else:
        if usage != "DISPLAY":
            warnings.append(f"line {item.line}: numeric item {item.name} has USAGE {usage}")
        item.size = picture.digits + sign_byte
        item.category = "zoned-decimal"
    if picture.digits > 31:
        warnings.append(f"line {item.line}: {item.name} exceeds 31 digits")


def _size_elementary(item: Item, warnings: list[str]) -> None:
    usage = item.effective_usage
    if usage in FIXED_SIZE_USAGES:
        item.size = FIXED_SIZE_USAGES[usage]
        item.category = "float" if usage in {"COMP-1", "COMP-2"} else usage.lower()
        return
    if usage == "OBJECT-REFERENCE":
        item.size = 4
        item.category = "object-reference"
        return
    if not item.picture:
        warnings.append(f"line {item.line}: elementary item {item.name} has no PICTURE")
        item.category = "unknown"
        return
    picture = _analyze_picture(item.picture)
    item.category = picture.category
    if picture.category == "numeric":
        _size_numeric(item, picture, warnings)
        return
    if usage in {"BINARY", "COMP-5", "PACKED-DECIMAL"}:
        warnings.append(f"line {item.line}: {item.name} has USAGE {usage} but is not numeric")
    width = CHARACTER_WIDTH.get(picture.category, 1)
    if usage in {"NATIONAL", "DISPLAY-1"}:
        width = 2
        if usage == "DISPLAY-1":
            item.category = "dbcs"
    item.size = picture.positions * width


@dataclass
class _LayoutState:
    warnings: list[str]
    after_odo: bool = False


def _layout(
    item: Item, offset: int, inherited: tuple[str, bool, bool], state: _LayoutState
) -> None:
    usage, leading, separate = inherited
    item.offset = offset
    item.variable_offset = state.after_odo
    item.effective_usage = item.usage or usage
    item.leading = leading if item.sign_leading is None else item.sign_leading
    item.separate = separate if item.sign_separate is None else item.sign_separate
    if item.sync:
        state.warnings.append(
            f"line {item.line}: {item.name} is SYNCHRONIZED; slack bytes are not computed, "
            "so verify offsets against the compiler MAP listing"
        )
    if not item.children:
        _size_elementary(item, state.warnings)
        return
    if item.picture:
        state.warnings.append(f"line {item.line}: group {item.name} has a PICTURE; ignored")
    context = (item.effective_usage, item.leading, item.separate)
    cursor = offset
    end = offset
    seen: dict[str, Item] = {}
    for child in item.children:
        target = seen.get(child.redefines) if child.redefines else None
        if child.redefines and target is None:
            state.warnings.append(
                f"line {child.line}: {child.name} REDEFINES {child.redefines}, "
                "which is not an earlier sibling"
            )
        start = target.offset if target is not None else cursor
        _layout(child, start, context, state)
        if target is not None and child.total_size > target.total_size:
            state.warnings.append(
                f"line {child.line}: {child.name} is longer than {target.name}, which it "
                "redefines; verify the following offsets against the compiler MAP listing"
            )
        if target is None:
            cursor = start + child.total_size
        end = max(end, start + child.total_size)
        seen[child.name] = child
        if child.depending_on:
            state.after_odo = True
    item.size = end - offset


def _find(item: Item, name: str) -> Item | None:
    for child in item.children:
        if child.name == name:
            return child
        found = _find(child, name)
        if found is not None:
            return found
    return None


def _resolve_aliases(record: Item, warnings: list[str]) -> None:
    for alias in record.aliases:
        first_name, last_name = alias.renames or ("", None)
        first = _find(record, first_name)
        last = _find(record, last_name) if last_name else first
        if first is None or last is None:
            warnings.append(f"line {alias.line}: cannot resolve RENAMES for {alias.name}")
            continue
        alias.offset = first.offset
        alias.size = last.offset + last.total_size - first.offset
        alias.category = "renames"


def _parse_replacing(clause: str) -> list[_Replacement]:
    body = re.sub(r"^\s*REPLACING\s+", "", clause, flags=re.IGNORECASE)
    pairs: list[_Replacement] = []
    for match in REPLACING_OPERAND.finditer(body):
        old, new = match.group("old"), match.group("new")
        mode = (match.group("mode") or "").lower()
        if old.startswith("=="):
            old, mode = old[2:-2].strip(), mode or "pseudo"
        else:
            mode = mode or "word"
        if new.startswith("=="):
            new = new[2:-2].strip()
        pairs.append(_Replacement(mode, old, new))
    return pairs


def _apply_replacements(text: str, pairs: Sequence[_Replacement]) -> str:
    """Apply COPY REPLACING operands in one pass, so replaced text is never rescanned."""
    usable = [pair for pair in pairs if pair.old.strip()]
    if not usable:
        return text
    alternatives = []
    for index, pair in enumerate(usable):
        core = r"\s+".join(re.escape(word) for word in pair.old.split())
        if pair.mode == "word":
            core = rf"(?<![A-Z0-9-]){core}(?![A-Z0-9-])"
        elif pair.mode == "leading":
            core = rf"(?<![A-Z0-9-]){core}(?=[A-Z0-9-])"
        elif pair.mode == "trailing":
            core = rf"(?<=[A-Z0-9-]){core}(?![A-Z0-9-])"
        alternatives.append(f"(?P<r{index}>{core})")
    pattern = re.compile("|".join(alternatives), re.IGNORECASE)

    def substitute(match: re.Match[str]) -> str:
        return usable[int((match.lastgroup or "r0")[1:])].new

    return pattern.sub(substitute, text)


def _expand(
    lines: Sequence[str],
    libraries: Sequence[_Library],
    replacements: Sequence[_Replacement],
    warnings: list[str],
    stack: Sequence[Path],
) -> str:
    """Normalize source, inline nested COPY members, and apply replacements."""

    def include(match: re.Match[str]) -> str:
        filler = "\n" * match.group(0).count("\n")
        member = match.group("member").strip("'\"").upper()
        found: list[Path] = []
        for library in libraries:
            found = library.find(member)
            if found:
                if len(found) > 1:
                    warnings.append(
                        f"COPY {member}: {len(found)} candidates in {library.root}; used {found[0]}"
                    )
                break
        if not found:
            warnings.append(f"COPY {member}: member not found; pass --copylib to resolve it")
            return filler
        if found[0] in stack or len(stack) >= MAX_COPY_DEPTH:
            warnings.append(f"COPY {member}: recursive or too deeply nested; skipped")
            return filler
        nested = found[0].read_text(encoding="utf-8", errors="replace").splitlines()
        pairs = _parse_replacing(match.group("replacing") or "")
        body = _expand(nested, libraries, pairs, warnings, [*stack, found[0]])
        return f"{body}\n{filler}"

    expanded = COPY_STATEMENT.sub(include, normalize_source(lines))
    return _apply_replacements(expanded, replacements)


def parse_copybook(
    source: str | Path,
    *,
    copylibs: Sequence[Path] = (),
    replacements: Sequence[tuple[str, str]] = (),
) -> Layout:
    """Parse a copybook file, or ``-`` for standard input, into computed record layouts."""
    warnings: list[str] = []
    if str(source) == "-":
        lines = sys.stdin.read().splitlines()
        default_name, stack = "STDIN", []
    else:
        path = Path(source)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        default_name, stack = path.stem.upper(), [path]
    libraries = [_Library(Path(directory)) for directory in copylibs]
    pairs = [_Replacement("pseudo", old, new) for old, new in replacements]
    text = _expand(lines, libraries, pairs, warnings, stack)
    items: list[Item] = []
    for entry in _Lexer(text, warnings).run():
        if entry[0].upper == "PROCEDURE" and len(entry) > 1 and entry[1].upper == "DIVISION":
            break
        item = _parse_entry(entry, warnings)
        if item is not None:
            items.append(item)
    records = _build_records(items, warnings, default_name)
    for record in records:
        _layout(record, 0, ("DISPLAY", False, False), _LayoutState(warnings))
        _resolve_aliases(record, warnings)
    return Layout(str(source), records, warnings)


def _dfsort_format(item: Item) -> str | None:
    if item.category == "zoned-decimal":
        if not item.signed:
            return "ZD"
        if item.leading:
            return "CSL" if item.separate else "CLO"
        return "CST" if item.separate else "ZD"
    if item.category == "binary":
        return "FI" if item.signed else "BI"
    return DFSORT_FORMATS.get(item.category)


def _field(item: Item, path: str, occurs_in: list[dict[str, Any]]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "level": item.level,
        "name": item.name,
        "path": path,
        "offset": item.offset,
        "position": item.offset + 1,
        "length": item.size,
        "total_length": item.total_size,
        "category": item.category,
    }
    if not item.children:
        entry["picture"] = item.picture
        entry["usage"] = item.effective_usage
    elif item.usage:
        entry["usage"] = item.usage
    if item.digits is not None:
        entry.update(digits=item.digits, scale=item.scale, signed=item.signed)
        if item.signed and item.category in {"zoned-decimal", "national-decimal"}:
            position = "leading" if item.leading else "trailing"
            entry["sign"] = {"position": position, "separate": item.separate}
    dfsort = _dfsort_format(item)
    if dfsort:
        entry["dfsort"] = dfsort
    if item.occurs_max is not None:
        entry["occurs"] = {
            "min": item.occurs_min,
            "max": item.occurs_max,
            "depending_on": item.depending_on,
        }
    if occurs_in:
        entry["occurs_in"] = occurs_in
    if item.redefines:
        entry["redefines"] = item.redefines
    if item.values:
        entry["value"] = " ".join(item.values)
    if item.conditions:
        entry["conditions"] = [{"name": c.name, "values": c.values} for c in item.conditions]
    flags = {
        "sync": item.sync,
        "justified": item.justified,
        "blank_when_zero": item.blank_when_zero,
        "variable_offset": item.variable_offset,
    }
    entry.update({flag: True for flag, enabled in flags.items() if enabled})
    return entry


def _flatten(
    item: Item, path: str, occurs_in: list[dict[str, Any]], out: list[dict[str, Any]]
) -> None:
    for child in item.children:
        child_path = f"{path}.{child.name}"
        out.append(_field(child, child_path, occurs_in))
        nested = occurs_in
        if child.occurs_max is not None:
            stride = {"name": child.name, "max": child.occurs_max, "stride": child.size}
            nested = [*occurs_in, stride]
        _flatten(child, child_path, nested, out)


def layout_to_dict(layout: Layout) -> dict[str, Any]:
    """Return the layout as a JSON-serializable dictionary."""
    records = []
    for record in layout.records:
        fields: list[dict[str, Any]] = []
        _flatten(record, record.name, [], fields)
        entry: dict[str, Any] = {
            "name": record.name,
            "level": record.level,
            "length": record.size,
            "variable_length": any(f.get("occurs", {}).get("depending_on") for f in fields),
        }
        if record.synthetic:
            entry["synthetic"] = True
        if not record.children:
            entry.update(
                {k: v for k, v in _field(record, record.name, []).items() if k not in entry}
            )
        entry["fields"] = fields
        if record.aliases:
            entry["renames"] = [
                {
                    "name": alias.name,
                    "offset": alias.offset,
                    "position": alias.offset + 1,
                    "length": alias.size,
                    "renames": list(alias.renames or ()),
                }
                for alias in record.aliases
                if alias.category == "renames"
            ]
        records.append(entry)
    return {
        "source": layout.source,
        "assumptions": list(ASSUMPTIONS),
        "records": records,
        "warnings": layout.warnings,
    }


def _camel(name: str) -> str:
    parts = [part for part in name.lower().split("-") if part]
    if not parts:
        return name.lower()
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _numeric_schema(item: Item) -> dict[str, Any]:
    digits = item.digits or 0
    scale = item.scale or 0
    sign = "-?" if item.signed else ""
    if scale <= 0:
        maximum = (10**digits - 1) * 10 ** (-scale)
        if maximum <= MAX_SAFE_INTEGER:
            schema: dict[str, Any] = {
                "type": "integer",
                "minimum": -maximum if item.signed else 0,
                "maximum": maximum,
            }
            if scale < 0:
                schema["multipleOf"] = 10 ** (-scale)
            if item.category == "binary":
                schema["description"] = (
                    "Range follows the PICTURE (TRUNC(STD)); COMP-5 or TRUNC(BIN) can hold more"
                )
            return schema
        return {"type": "string", "pattern": f"^{sign}[0-9]{{1,{digits - scale}}}$"}
    whole = digits - scale
    if whole > 0:
        pattern = f"^{sign}[0-9]{{1,{whole}}}(\\.[0-9]{{1,{scale}}})?$"
    else:
        pattern = f"^{sign}0?\\.[0-9]{{1,{scale}}}$"
    return {
        "type": "string",
        "pattern": pattern,
        "description": "Decimal carried as a string to keep exact precision",
    }


def _elementary_schema(item: Item) -> dict[str, Any] | None:
    if item.category in NUMERIC_CATEGORIES:
        return _numeric_schema(item)
    if item.category == "float":
        return {
            "type": "number",
            "description": "IBM hexadecimal floating point on z/OS; convert explicitly",
        }
    if item.category in {"index", "pointer", "pointer-32", "procedure-pointer"}:
        return None
    if item.category in {"function-pointer", "object-reference", "unknown"}:
        return None
    width = CHARACTER_WIDTH.get(item.category, 1)
    return {"type": "string", "maxLength": item.size // width}


def _schema(item: Item, names: str, warnings: list[str]) -> dict[str, Any] | None:
    annotation: dict[str, Any] = {"name": item.name, "offset": item.offset, "length": item.size}
    if item.children:
        properties: dict[str, Any] = {}
        for child in item.children:
            if child.name == "FILLER":
                continue
            child_schema = _schema(child, names, warnings)
            if child_schema is None:
                continue
            key = child.name if names == "cobol" else _camel(child.name)
            base, suffix = key, 2
            while key in properties:
                key, suffix = f"{base}_{suffix}", suffix + 1
            properties[key] = child_schema
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
    else:
        elementary = _elementary_schema(item)
        if elementary is None:
            warnings.append(f"{item.name}: {item.category} items have no JSON form; omitted")
            return None
        schema = elementary
        annotation.update(picture=item.picture, usage=item.effective_usage)
    if item.redefines:
        annotation["redefines"] = item.redefines
    if item.conditions:
        annotation["conditions"] = {c.name: c.values for c in item.conditions}
    schema["x-cobol"] = annotation
    if item.occurs_max is None:
        return schema
    array: dict[str, Any] = {"type": "array", "items": schema, "maxItems": item.occurs_max}
    if item.depending_on:
        array["minItems"] = item.occurs_min or 0
        array["x-cobol-depending-on"] = item.depending_on
    return array


def layout_to_json_schema(layout: Layout, names: str = "camel") -> dict[str, Any]:
    """Draft a JSON Schema (2020-12) for each record, with decimals carried as strings."""
    warnings: list[str] = []
    definitions: dict[str, Any] = {}
    for record in layout.records:
        schema = _schema(record, names, warnings) or {}
        schema["title"] = record.name
        definitions[record.name] = schema
    if len(definitions) == 1:
        result: dict[str, Any] = {"$schema": SCHEMA_DIALECT, **next(iter(definitions.values()))}
    else:
        result = {
            "$schema": SCHEMA_DIALECT,
            "title": Path(layout.source).name,
            "$defs": definitions,
            "oneOf": [{"$ref": f"#/$defs/{name}"} for name in definitions],
        }
    all_warnings = [*layout.warnings, *warnings]
    if all_warnings:
        result["x-cobol-warnings"] = all_warnings
    return result


def _notes(entry: dict[str, Any]) -> str:
    notes: list[str] = []
    occurs = entry.get("occurs")
    if occurs:
        if occurs["depending_on"]:
            notes.append(
                f"OCCURS {occurs['min']} TO {occurs['max']} DEPENDING ON {occurs['depending_on']}"
            )
        else:
            notes.append(f"OCCURS {occurs['max']}")
    notes.extend(
        f"in {table['name']} (stride {table['stride']})" for table in entry.get("occurs_in", [])
    )
    if entry.get("redefines"):
        notes.append(f"REDEFINES {entry['redefines']}")
    notes.extend(
        f"88 {condition['name']} = {', '.join(condition['values'])}"
        for condition in entry.get("conditions", [])
    )
    if entry.get("dfsort"):
        notes.append(f"DFSORT {entry['dfsort']}")
    if entry.get("variable_offset"):
        notes.append("offset assumes maximum OCCURS")
    if entry.get("sync"):
        notes.append("SYNC")
    return "; ".join(notes).replace("|", "\\|")


def layout_to_markdown(layout: Layout) -> str:
    """Render the layout as Markdown tables, one per record."""
    data = layout_to_dict(layout)
    lines = [f"# Copybook layout: {data['source']}", ""]
    for record in data["records"]:
        variable = ", variable length" if record["variable_length"] else ""
        lines += [
            f"## {record['name']} ({record['length']} bytes{variable})",
            "",
            "| Position | Length | Level | Field | Picture | Usage | Notes |",
            "| ---: | ---: | :-- | :-- | :-- | :-- | :-- |",
        ]
        for entry in record["fields"]:
            picture = (entry.get("picture") or "").replace("|", "\\|")
            lines.append(
                f"| {entry['position']} | {entry['length']} | {entry['level']:02d} "
                f"| {entry['name']} | {picture} | {entry.get('usage') or ''} | {_notes(entry)} |"
            )
        lines.append("")
    if data["warnings"]:
        lines += ["## Warnings", "", *(f"- {warning}" for warning in data["warnings"]), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, compute the layout, and print it."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("copybook", help="Copybook file to analyze, or - for standard input.")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "markdown", "json-schema"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument("--record", help="Only report the 01-level record with this name.")
    parser.add_argument(
        "--copylib",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="Directory searched, in order, for nested COPY members. Repeatable.",
    )
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Apply COPY REPLACING ==OLD== BY ==NEW== to the copybook text. Repeatable.",
    )
    parser.add_argument(
        "--names",
        choices=["camel", "cobol"],
        default="camel",
        help="Property names for --format json-schema (default: camel).",
    )
    args = parser.parse_args(argv)

    try:
        layout = parse_copybook(
            args.copybook,
            copylibs=args.copylib,
            replacements=[(old, new) for old, new in args.replace],
        )
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.record:
        layout.records = [r for r in layout.records if r.name == args.record.upper()]
    if not layout.records:
        print("error: no matching data description entries found", file=sys.stderr)
        return 1

    if args.output_format == "markdown":
        print(layout_to_markdown(layout))
    elif args.output_format == "json-schema":
        print(json.dumps(layout_to_json_schema(layout, args.names), indent=2))
    else:
        print(json.dumps(layout_to_dict(layout), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
