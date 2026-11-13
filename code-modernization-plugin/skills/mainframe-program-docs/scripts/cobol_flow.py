#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Document a COBOL program: paragraph flow, unreachable code, rule candidates, interfaces.

Reads one IBM Enterprise COBOL program in fixed or free format, expands COPY members (and
EXEC SQL INCLUDE members) from copy libraries, and builds the section and paragraph flow
graph from PERFORM (THRU ranges and sections), GO TO (including DEPENDING ON), ALTER, SORT
and MERGE procedures, CICS HANDLE labels, ENTRY points, DECLARATIVES, and fall-through. It
reports paragraphs that no entry point reaches, structure risks, business-rule candidates,
and the program's interfaces: static and dynamic CALLs, CICS commands and resources, SQL
statements and tables, DL/I and MQ calls, and file I/O per file.

The default output is a Markdown documentation skeleton with a Mermaid flowchart; JSON (the
full model) and Mermaid alone are also available. Members still in EBCDIC are decoded with
--codepage. The script only reads files.

The analysis is static. ALTER, GO TO DEPENDING ON, CICS HANDLE, and dynamic CALLs make it
approximate: confirm unreachable candidates with runtime coverage, and have subject-matter
experts confirm every business-rule candidate.

Examples:
    uv run --script cobol_flow.py CUSTINQ.cbl --copylib copybooks > CUSTINQ.md
    uv run --script cobol_flow.py CUSTINQ.cbl --copylib copybooks --format mermaid
    uv run --script cobol_flow.py PAYROLL --codepage 1140 --format json > PAYROLL.json
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_MAX_NODES = 200
FIXED_AREA_WIDTH = 65  # columns 8-72 of a fixed-format line
AREA_A_WIDTH = 4  # columns 8-11
MAX_COPY_DEPTH = 16
MAX_RULE_TEXT = 200
MAX_HEADER_COMMENTS = 40
MAX_DESCRIPTION = 120
NAME = r"[A-Z0-9@#$][A-Z0-9@#$_-]*"
START = "(start)"

APPROXIMATE = (
    "Dynamic constructs (ALTER, GO TO DEPENDING ON, CICS HANDLE) make static reachability "
    "approximate: confirm unreachable candidates with runtime coverage before removing code."
)
RULE_NOTE = (
    "Business-rule candidates are found by pattern and need confirmation by a subject-matter "
    "expert; keep the line reference with every confirmed rule."
)
SYSTEM_COPY_PREFIXES = ("DFH", "CMQ", "SQLCA", "SQLDA", "CEE", "IGZ", "DSN", "IDMS")
COPY_SUFFIXES = frozenset({".cpy", ".copy", ".cpb", ".inc", ""})


def _words(text: str) -> frozenset[str]:
    """Return the set of blank-separated words in ``text``."""
    return frozenset(text.split())


LITERAL_PREFIXES = _words("B BX G N NX U UX X Z")
IGNORED_WORDS = _words("EJECT SKIP1 SKIP2 SKIP3")
DECORATION = frozenset("-=*+#_/.~ ")
VERBS = _words(
    """
    ACCEPT ADD ALLOCATE ALTER CALL CANCEL CLOSE COMPUTE CONTINUE DELETE DISPLAY DIVIDE
    ENTRY EVALUATE EXIT GENERATE GO GOBACK IF INITIALIZE INITIATE INSPECT INVOKE JSON
    MERGE MOVE MULTIPLY OPEN PERFORM READ RELEASE RETURN REWRITE SEARCH SET SORT START
    STOP STRING SUBTRACT TERMINATE UNSTRING USE WRITE XML
    """
)
SCOPE_TERMINATORS = _words(
    """
    END-ACCEPT END-ADD END-CALL END-COMPUTE END-DELETE END-DISPLAY END-DIVIDE
    END-EVALUATE END-IF END-INVOKE END-JSON END-MULTIPLY END-PERFORM END-READ
    END-RETURN END-REWRITE END-SEARCH END-START END-STRING END-SUBTRACT END-UNSTRING
    END-WRITE END-XML
    """
)
KEYWORDS = _words(
    """
    ADDRESS AFTER ALL ALPHABETIC ALPHABETIC-LOWER ALPHABETIC-UPPER ALSO AND ARE AT
    BEFORE BY CHARACTERS CONTENT CONVERTING CORR CORRESPONDING DELIMITED DEPENDING DOWN
    END EQUAL EQUALS ERROR EXCEPTION FALSE FIRST FROM FUNCTION GIVING GREATER
    HIGH-VALUE HIGH-VALUES IN INITIAL INTO INVALID IS KEY LEADING LENGTH LESS LOW-VALUE
    LOW-VALUES NEGATIVE NEXT NOT NULL NULLS NUMERIC OF ON OR OTHER OVERFLOW POINTER
    POSITIVE PROCEED QUOTE QUOTES RECORD REFERENCE REMAINDER REPLACING RETURNING
    ROUNDED SENTENCE SIZE SPACE SPACES TALLYING TEST THAN THEN THROUGH THRU TIMES TO
    TRUE UNTIL UP USING VALUE VARYING WITH ZERO ZEROES ZEROS
    """
)
SCOPES = {
    "END-IF": "IF",
    "END-EVALUATE": "EVALUATE",
    "END-SEARCH": "SEARCH",
    "END-PERFORM": "PERFORM",
}
MARKERS = SCOPE_TERMINATORS | {"ELSE", "WHEN"}
RESERVED = VERBS | MARKERS | KEYWORDS
NOT_PROCEDURE_NAMES = VERBS | MARKERS | {"THEN"}
VERB_PREFIXES = _words("EXIT XML JSON")  # EXIT PERFORM, XML GENERATE, JSON GENERATE
PHRASE_WORDS = _words("END-OF-PAGE EOP INVALID EXCEPTION OVERFLOW")
PHRASE_LEADERS = _words("NOT AT ON SIZE")
INLINE_PERFORM_WORDS = _words("UNTIL VARYING WITH TEST FOREVER")
THRU = _words("THRU THROUGH")
ARITHMETIC = _words("ADD SUBTRACT MULTIPLY DIVIDE")
RELATIONAL = _words("= < > <= >= <> EQUAL EQUALS GREATER LESS")
FILE_VERBS = _words("OPEN CLOSE READ WRITE REWRITE DELETE START RETURN RELEASE")
FILE_MODES = _words("INPUT OUTPUT I-O EXTEND")
FILE_NOISE = _words("WITH NO REWIND REVERSED LOCK REEL UNIT FOR REMOVAL")
CALL_NOISE = _words("BY REFERENCE CONTENT VALUE OMITTED ADDRESS OF LENGTH")
CALL_END = _words("RETURNING ON NOT EXCEPTION OVERFLOW END-CALL")
HANDLE_NON_LABELS = _words("PROGRAM RESP RESP2 SYSID")
CICS_SECOND_WORDS = _words("MAP TEXT CONTROL PAGE CONDITION ABEND AID HANDLE TS TD CONTAINER")
DATA_CLAUSES = _words(
    "PIC PICTURE VALUE VALUES REDEFINES OCCURS USAGE COMP COMP-3 COMP-5 BINARY DISPLAY SIGN SYNC"
)
TECHNICAL_NAMES = _words(
    "SQLCODE SQLSTATE SQLERRD EIBRESP EIBRESP2 EIBAID EIBCALEN EIBTRNID DFHRESP RETURN-CODE"
)
INTERFACE_CALLS = {
    "ims": _words("CBLTDLI AIBTDLI CEETDLI AERTDLI"),
    "mq": _words(
        "MQCONN MQCONNX MQDISC MQOPEN MQCLOSE MQPUT MQPUT1 MQGET MQINQ MQSET MQBEGIN MQCMIT MQBACK"
    ),
    "db2": _words("DSNTIAR DSNTIAC DSNALI DSNRLI DSNHLI DSNELI"),
    "language-environment": _words("CEE3ABD ILBOABN0 CEEDAYS CEEDATE CEELOCT CEEMSG"),
}
INTERFACE_FAMILY = {name: family for family, names in INTERFACE_CALLS.items() for name in names}


def _word(pattern: str) -> str:
    """Wrap ``pattern`` so it only matches a whole COBOL word."""
    return rf"(?<![A-Z0-9-])(?:{pattern})(?![A-Z0-9-])"


DIVISION = re.compile(
    r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.IGNORECASE
)
PROGRAM_ID = re.compile(_word("PROGRAM-ID") + r"\s*\.?\s*['\"]?(" + NAME + ")", re.IGNORECASE)
END_PROGRAM = re.compile(r"^\s*END\s+PROGRAM\s+['\"]?(" + NAME + ")", re.IGNORECASE)
ID_PARAGRAPH = re.compile(
    r"^\s*(PROGRAM-ID|AUTHOR|INSTALLATION|DATE-WRITTEN|DATE-COMPILED|SECURITY|REMARKS)\s*\.?(.*)$",
    re.IGNORECASE,
)
DATA_SECTION = re.compile(
    r"^\s*(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE|COMMUNICATION|REPORT|SCREEN)\s+SECTION\b",
    re.IGNORECASE,
)
COPY_STATEMENT = re.compile(
    r"(?<![A-Z0-9-])(?:COPY\s+(?P<member>'[^']+'|\"[^\"]+\"|[A-Z0-9@#$_-]+)"
    r"(?:\s+(?:OF|IN)\s+[A-Z0-9@#$_-]+)?(?:\s+SUPPRESS)?"
    r"(?P<replacing>\s+REPLACING\s.*?)?\s*\.(?=\s|$)"
    r"|EXEC\s+SQL\s+INCLUDE\s+(?P<include>[A-Z0-9@#$_-]+)\s+END-EXEC(?:\s*\.(?=\s|$))?)",
    re.IGNORECASE | re.DOTALL,
)
REPLACING_OPERAND = re.compile(
    r"(?:(?P<mode>LEADING|TRAILING)\s+)?"
    r"(?P<old>==.*?==|'[^']*'|\"[^\"]*\"|[^\s=]+)\s+BY\s+"
    r"(?P<new>==.*?==|'[^']*'|\"[^\"]*\"|[^\s=]+)",
    re.IGNORECASE | re.DOTALL,
)
SELECT_ASSIGN = re.compile(
    _word("ASSIGN") + r"\s+(?:TO\s+)?(?:USING\s+)?('[^']*'|\"[^\"]*\"|" + NAME + ")",
    re.IGNORECASE,
)
ORGANIZATION = re.compile(
    _word("ORGANIZATION") + r"\s+(?:IS\s+)?(LINE\s+SEQUENTIAL|INDEXED|RELATIVE|SEQUENTIAL)"
)
BARE_ORGANIZATION = re.compile(_word("INDEXED|RELATIVE") + r"(?!\s+KEY)")
ACCESS = re.compile(_word("ACCESS") + r"\s+(?:MODE\s+)?(?:IS\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)")
RECORD_KEY = re.compile(r"(?<!ALTERNATE )" + _word("RECORD") + r"\s+KEY\s+(?:IS\s+)?(" + NAME + ")")
ALTERNATE_KEY = re.compile(_word("ALTERNATE") + r"\s+(?:RECORD\s+)?KEY\s+(?:IS\s+)?(" + NAME + ")")
FILE_STATUS = re.compile(_word("STATUS") + r"\s+(?:IS\s+)?(" + NAME + ")")
CICS_HANDLE = re.compile(r"EXEC\s+CICS\s+HANDLE\s+(CONDITION|AID|ABEND)\b(.*)")
HANDLE_OPERAND = re.compile(r"([A-Z][A-Z0-9-]*)\s*\(\s*(" + NAME + r")\s*\)")
CICS_ARGUMENT = re.compile(
    r"(?<![A-Z0-9-])(PROGRAM|TRANSID|MAPSET|MAP|FILE|DATASET|QUEUE|QNAME|CHANNEL|CONTAINER)"
    r"\s*\(\s*(['\"]?)([^)'\"]+)\2\s*\)"
)
SQL_TABLE_CONTEXT = re.compile(
    r"(?<![A-Z0-9_])(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(" + NAME + r"(?:\." + NAME + ")?)"
)
SQL_CLAUSE_END = re.compile(
    r"(?<![A-Z0-9_])(?:WHERE|GROUP|HAVING|ORDER|FETCH|FOR|WITH|UNION|EXCEPT|INTERSECT|"
    r"OPTIMIZE|QUERYNO|SET|VALUES|ON)(?![A-Z0-9_])"
)
DLI_SEGMENT = re.compile(r"SEGMENT\s*\(\s*(" + NAME + r")\s*\)")
IDENTIFIER = re.compile(NAME)
NUMERIC_LITERAL = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
DFHRESP_ARGUMENT = re.compile(r"(DFHRESP|DFHVALUE)\([^)]*\)")


@dataclass
class SourceLine:
    """A source line after format handling; COPY statements are replaced by member text."""

    number: int  # line in the main program; lines from a copybook carry the COPY line
    text: str = ""
    kind: str = "code"  # code, comment, blank, directive, or copy (a COPY marker)
    area_a: bool | None = None  # fixed format: code starts in columns 8-11; None: free format
    copybook: str | None = None
    detail: str = ""  # copy markers: resolved, unresolved, system, or skipped


@dataclass
class Token:
    """A COBOL word, literal, sentence period, or whole EXEC block."""

    text: str
    index: int  # position of the source line in the expanded line list
    kind: str = "word"  # word, literal, period, or exec

    @property
    def upper(self) -> str:
        """Return the token text in upper case."""
        return self.text.upper()


@dataclass(eq=False)
class Statement:
    """A statement, or a scope marker (ELSE, WHEN, END-IF), inside one procedure."""

    verb: str
    tokens: list[Token]
    depth: int
    owner: Statement | None = None
    inline: bool = False

    @property
    def words(self) -> list[str]:
        """Return the upper-cased token texts."""
        return [token.upper for token in self.tokens]


@dataclass(eq=False)
class Procedure:
    """A section, a paragraph, or the implicit start of the PROCEDURE DIVISION."""

    name: str
    kind: str  # section, paragraph, or start
    index: int
    section: str | None
    declaratives: bool = False
    tokens: list[Token] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    description: str = ""


@dataclass
class Edge:
    """A transfer of control from one procedure to another."""

    source: int
    target: int
    kind: str  # perform, thru, sort-input, sort-output, go-to, go-to-depending, ...
    line: int
    name: str
    thru: str = ""
    label: str = ""
    covers: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Replacement:
    mode: str  # pseudo, word, leading, or trailing
    old: str
    new: str


Reference = tuple[str, str | None]


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


def _split_comment(text: str) -> tuple[str, str | None]:
    """Split ``text`` at a floating ``*>`` comment outside literals."""
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif text.startswith("*>", index):
            return text[:index], text[index + 2 :]
    return text, None


def normalize_source(lines: Sequence[str]) -> tuple[list[SourceLine], str]:
    """Return lines without sequence and identification areas, continuations joined.

    Fixed format is the default; ``>>SOURCE FORMAT FREE`` and ``>>SOURCE FORMAT FIXED``
    switch formats. Comment lines are kept because the comment block above a paragraph
    describes it. The second value is ``fixed``, ``free``, or ``mixed``.
    """
    out: list[SourceLine] = []
    free = False
    formats: set[str] = set()
    last = -1
    for number, line in enumerate(lines, start=1):
        indicator = "" if free else line[6:7]
        if indicator in {"*", "/"}:
            out.append(SourceLine(number, line[7:72].strip(), "comment"))
            continue
        if indicator in {"D", "d"}:
            out.append(SourceLine(number, "", "blank"))  # debugging line: compiled as a comment
            continue
        body = line if free else line[7:72]
        if line.lstrip().startswith(">>") or body.lstrip().startswith(">>"):
            directive = " ".join(line[line.index(">>") :].split()).upper()
            if directive.startswith(">>SOURCE"):
                free = "FREE" in directive.split()
            out.append(SourceLine(number, directive, "directive"))
            continue
        code, comment = _split_comment(body)
        if not code.strip():
            kind = "blank" if comment is None else "comment"
            out.append(SourceLine(number, (comment or "").strip(), kind))
            continue
        formats.add("free" if free else "fixed")
        if indicator == "-" and last >= 0:
            continuation = code.ljust(FIXED_AREA_WIDTH).lstrip()
            previous = out[last].text
            if continuation[:1] in {"'", '"'} and _has_open_literal(previous):
                out[last].text = previous + continuation[1:]
            else:
                out[last].text = previous.rstrip() + continuation
            continue
        indent = len(code) - len(code.lstrip())
        text = code if free else code.ljust(FIXED_AREA_WIDTH)
        out.append(SourceLine(number, text, "code", None if free else indent < AREA_A_WIDTH))
        last = len(out) - 1
    for entry in out:
        entry.text = entry.text.rstrip()
    return out, "mixed" if len(formats) > 1 else next(iter(formats), "fixed")


class _Library:
    """Index of the members of one copy library directory, by upper-case file stem."""

    def __init__(self, root: Path, *, recursive: bool) -> None:
        self.root = root
        self.members: dict[str, list[Path]] = {}
        if root.is_dir():
            paths = root.rglob("*") if recursive else root.iterdir()
            for path in sorted(paths):
                if path.is_file() and not path.name.startswith("."):
                    self.members.setdefault(path.stem.upper(), []).append(path)
        for candidates in self.members.values():
            candidates.sort(key=lambda path: (path.suffix.lower() not in COPY_SUFFIXES, str(path)))

    def find(self, name: str) -> list[Path]:
        """Return the files whose stem matches ``name``, copybook suffixes first."""
        return self.members.get(name.upper(), [])


@dataclass
class _CopyContext:
    libraries: list[_Library]
    codepage: str
    warnings: list[str]
    paths: dict[str, str] = field(default_factory=dict)


def _mask(text: str) -> str:
    """Return ``text`` with literal contents replaced by ``x``, keeping every offset."""
    out = list(text)
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            else:
                out[index] = "x"
        elif char in "'\"":
            quote = char
    return "".join(out)


def _locate(starts: Sequence[int], offset: int) -> tuple[int, int]:
    """Return the line index and column of an offset into newline-joined text."""
    line = bisect.bisect_right(starts, offset) - 1
    return line, offset - starts[line]


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


def _rest(line: SourceLine, column: int) -> SourceLine:
    """Return the part of ``line`` from ``column``, which follows a COPY statement."""
    if not column:
        return line
    text = line.text[column:]
    area_a = None if line.area_a is None else False
    return replace(line, text=text, area_a=area_a, kind="code" if text.strip() else "blank")


def _include(
    match: re.Match[str],
    joined: str,
    at: SourceLine,
    context: _CopyContext,
    stack: tuple[Path, ...],
) -> list[SourceLine]:
    """Return a COPY marker followed by the expanded lines of the member."""
    group = "member" if match.start("member") >= 0 else "include"
    member = joined[match.start(group) : match.end(group)].strip("'\"").upper()
    replacing = ""
    if match.start("replacing") >= 0:
        replacing = joined[match.start("replacing") : match.end("replacing")]
    marker = SourceLine(at.number, member, "copy", copybook=at.copybook)
    found = next((paths for library in context.libraries if (paths := library.find(member))), [])
    if not found:
        marker.detail = "system" if member.startswith(SYSTEM_COPY_PREFIXES) else "unresolved"
        return [marker]
    if len(found) > 1:
        context.warnings.append(f"COPY {member}: {len(found)} candidates; used {found[0]}")
    path = found[0]
    resolved = path.resolve()
    decoded = None
    if resolved in stack or len(stack) > MAX_COPY_DEPTH:
        context.warnings.append(f"COPY {member}: recursive or nested too deeply; not expanded")
    else:
        decoded = zos_encoding.decode_member(path.read_bytes(), codepage=context.codepage)
        if decoded is None:
            context.warnings.append(f"COPY {member}: {path} is binary; not expanded")
    if decoded is None:
        marker.detail = "skipped"
        return [marker]
    marker.detail = "resolved"
    context.paths.setdefault(member, str(path))
    normalized, _ = normalize_source(decoded.text.splitlines())
    expanded = _expand(normalized, context, (*stack, resolved))
    pairs = _parse_replacing(replacing)
    lines = [marker]
    for line in expanded:
        text = _apply_replacements(line.text, pairs) if line.kind == "code" else line.text
        lines.append(replace(line, number=at.number, text=text, copybook=line.copybook or member))
    return lines


def _expand(
    lines: list[SourceLine], context: _CopyContext, stack: tuple[Path, ...]
) -> list[SourceLine]:
    """Replace COPY and EXEC SQL INCLUDE statements with the text of their members."""
    texts = [line.text if line.kind == "code" else "" for line in lines]
    joined = "\n".join(texts)
    masked = "\n".join(_mask(text) for text in texts)
    starts = [0]
    for text in texts[:-1]:
        starts.append(starts[-1] + len(text) + 1)
    out: list[SourceLine] = []
    position, column = 0, 0
    for match in COPY_STATEMENT.finditer(masked):
        first, first_column = _locate(starts, match.start())
        last, last_column = _locate(starts, match.end())
        while position < first:
            out.append(_rest(lines[position], column))
            position, column = position + 1, 0
        prefix = lines[first].text[column:first_column]
        if prefix.strip():
            area_a = lines[first].area_a and not column
            out.append(replace(lines[first], text=prefix, area_a=area_a))
        out.extend(_include(match, joined, lines[first], context, stack))
        position, column = last, last_column
    while position < len(lines):
        out.append(_rest(lines[position], column))
        position, column = position + 1, 0
    return out


def _literal_end(text: str, start: int) -> int:
    """Return the index just past the literal that starts at ``start``."""
    quote = text[start]
    position = start + 1
    while position < len(text):
        if text[position] == quote:
            if text[position + 1 : position + 2] == quote:
                position += 2
                continue
            return position + 1
        position += 1
    return position


def _ends_sentence(text: str, position: int) -> bool:
    return text[position] == "." and not text[position + 1 : position + 2].strip()


def _tokenize(lines: Sequence[SourceLine], start: int, end: int) -> list[Token]:
    """Split the code lines in ``lines[start:end]`` into tokens."""
    tokens: list[Token] = []
    for index in range(start, end):
        line = lines[index]
        if line.kind != "code":
            continue
        text = line.text
        position = 0
        while position < len(text):
            char = text[position]
            if char.isspace():
                position += 1
                continue
            if char in "'\"":
                stop = _literal_end(text, position)
                tokens.append(Token(text[position:stop], index, "literal"))
                position = stop
                continue
            if _ends_sentence(text, position):
                tokens.append(Token(".", index, "period"))
                position += 1
                continue
            begin = position
            while (
                position < len(text)
                and not text[position].isspace()
                and text[position] not in "'\""
                and not _ends_sentence(text, position)
            ):
                position += 1
            word = text[begin:position]
            if (
                position < len(text)
                and text[position] in "'\""
                and word.upper() in LITERAL_PREFIXES
            ):
                stop = _literal_end(text, position)
                tokens.append(Token(word + text[position:stop], index, "literal"))
                position = stop
                continue
            word = word.rstrip(",;")
            if word and word.upper() not in IGNORED_WORDS:
                tokens.append(Token(word, index))
    return tokens


def _merge_exec(tokens: Sequence[Token]) -> list[Token]:
    """Merge each EXEC ... END-EXEC block into one token."""
    merged: list[Token] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token.kind == "word" and token.upper in {"EXEC", "EXECUTE"}:
            end = position + 1
            while end < len(tokens) and tokens[end].upper != "END-EXEC":
                end += 1
            body = " ".join(part.text for part in tokens[position : end + 1])
            merged.append(Token(body, token.index, "exec"))
            position = end + 1
            continue
        merged.append(token)
        position += 1
    return merged


def _entries(tokens: Iterable[Token]) -> list[list[Token]]:
    """Group tokens into period-terminated entries."""
    entries: list[list[Token]] = [[]]
    for token in tokens:
        if token.kind == "period":
            entries.append([])
        else:
            entries[-1].append(token)
    return [entry for entry in entries if entry]


def _literal_value(text: str) -> str:
    """Return the contents of a quoted literal without its quotes or trailing blanks."""
    if text[:1] in {"'", '"'}:
        quote = text[0]
        inner = text[1:-1] if len(text) > 1 and text.endswith(quote) else text[1:]
        return inner.replace(quote * 2, quote).rstrip()
    return text


def _is_inline_perform(tokens: Sequence[Token], position: int, names: set[str]) -> bool:
    """Return whether the PERFORM at ``position`` has no procedure name (ends at END-PERFORM)."""
    following = tokens[position + 1] if position + 1 < len(tokens) else None
    if following is None or following.kind != "word" or following.upper in INLINE_PERFORM_WORDS:
        return True
    if following.upper in names:
        return False
    after = tokens[position + 2] if position + 2 < len(tokens) else None
    return after is not None and after.upper == "TIMES"


def _parse_statements(tokens: Sequence[Token], names: set[str]) -> list[Statement]:
    """Split procedure tokens into statements, tracking how deeply each one is nested."""
    statements: list[Statement] = []
    stack: list[tuple[str, Statement | None]] = []
    else_seen: set[Statement | None] = set()
    current: Statement | None = None
    for position, token in enumerate(tokens):
        if token.kind == "period":
            stack.clear()
            current = None
            continue
        if token.kind == "exec":
            current = Statement("EXEC", [token], len(stack))
            statements.append(current)
            continue
        word = token.upper if token.kind == "word" else ""
        previous = tokens[position - 1].upper if position else ""
        following = tokens[position + 1].upper if position + 1 < len(tokens) else ""
        if word == "ELSE":
            while stack and (stack[-1][0] == "PHRASE" or stack[-1][1] in else_seen):
                stack.pop()
            if stack and stack[-1][0] == "IF":
                else_seen.add(stack[-1][1])
            statements.append(Statement(word, [token], max(len(stack) - 1, 0)))
            current = None
        elif word == "WHEN":
            owners = [i for i, (kind, _) in enumerate(stack) if kind in {"EVALUATE", "SEARCH"}]
            if owners:
                del stack[owners[-1] + 1 :]
            owner = stack[owners[-1]][1] if owners else None
            current = Statement(word, [token], max(len(stack) - 1, 0), owner)
            statements.append(current)
        elif word in SCOPE_TERMINATORS:
            construct = SCOPES.get(word)
            opened = [i for i, (kind, _) in enumerate(stack) if kind == construct]
            if opened:
                del stack[opened[-1] :]
            elif construct is None and stack and stack[-1][0] == "PHRASE":
                stack.pop()
            statements.append(Statement(word, [token], len(stack)))
            current = None
        elif (word in VERBS and previous not in VERB_PREFIXES) or (
            word == "NEXT" and following == "SENTENCE"
        ):
            current = Statement(word, [token], len(stack))
            statements.append(current)
            if word in {"IF", "EVALUATE", "SEARCH"}:
                stack.append((word, current))
            elif word == "PERFORM" and _is_inline_perform(tokens, position, names):
                current.inline = True
                stack.append((word, current))
        elif word in PHRASE_WORDS or (word, previous) in {("END", "AT"), ("ERROR", "SIZE")}:
            if not stack or stack[-1][0] != "PHRASE":
                stack.append(("PHRASE", current))
                if current is not None:
                    current.tokens.append(token)
            elif current is not None:
                # NOT AT END and similar phrases belong to the I/O statement, not the last one.
                while len(current.tokens) > 1 and current.tokens[-1].upper in PHRASE_LEADERS:
                    current.tokens.pop()
                current = None
        elif current is not None:
            current.tokens.append(token)
    return statements


def _ends_with_transfer(statements: Sequence[Statement]) -> bool:
    """Return whether the last statement unconditionally transfers control elsewhere."""
    if not statements or statements[-1].depth:
        return False
    last = statements[-1]
    words = last.words
    if last.verb == "GO":
        return "DEPENDING" not in words
    if last.verb == "STOP":
        return words[1:2] == ["RUN"]
    if last.verb == "EXIT":
        return words[1:2] == ["PROGRAM"]
    if last.verb == "EXEC":
        parts = words[0].split()
        command = parts[2].split("(")[0] if len(parts) > 2 and parts[1] == "CICS" else ""
        transid = any(part.startswith("TRANSID") for part in parts)
        return command == "XCTL" or (command == "RETURN" and not transid)
    return last.verb == "GOBACK"


def _procedure_header(
    tokens: Sequence[Token], position: int, lines: Sequence[SourceLine]
) -> tuple[str, int] | None:
    """Classify the token at ``position`` as a procedure header and return its width."""
    token = tokens[position]
    previous = tokens[position - 1] if position else None
    if token.kind != "word" or (previous is not None and previous.index == token.index):
        return None
    area_a = lines[token.index].area_a
    if area_a is False or (area_a is None and previous is not None and previous.kind != "period"):
        return None
    words = [following.upper for following in tokens[position + 1 : position + 4]]
    word = token.upper
    if word == "END" and words[:2] == ["DECLARATIVES", "."]:
        return "end-declaratives", 3
    if word in NOT_PROCEDURE_NAMES or not words:
        return None
    if word == "DECLARATIVES" and words[0] == ".":
        return "declaratives", 2
    if words[0] == ".":
        return "paragraph", 2
    if words[0] == "SECTION" and words[1:2] == ["."]:
        return "section", 3
    if words[0] == "SECTION" and len(words) > 2 and words[1].isdigit() and words[2] == ".":
        return "section", 4
    return None


def _reference(words: Sequence[str], position: int) -> tuple[Reference, int]:
    """Read a procedure name with an optional OF or IN section qualifier."""
    name = words[position]
    if position + 2 < len(words) and words[position + 1] in {"OF", "IN"}:
        return (name, words[position + 2]), position + 3
    return (name, None), position + 1


def _clean_comments(texts: Iterable[str]) -> list[str]:
    """Return comment texts without box-drawing decoration."""
    cleaned = []
    for text in texts:
        value = text.strip().strip("*").strip()
        if value and not set(value) <= DECORATION:
            cleaned.append(" ".join(value.split()))
    return cleaned


def _identifiers(tokens: Iterable[Token], exclude: set[str]) -> list[str]:
    """Return the data names that tokens reference, in order of appearance."""
    names: dict[str, None] = {}
    skip = False
    for token in tokens:
        if token.kind != "word":
            continue
        for word in IDENTIFIER.findall(DFHRESP_ARGUMENT.sub(r"\1", token.upper)):
            if skip:
                skip = False
            elif word == "FUNCTION":
                skip = True
            elif word not in RESERVED and word not in exclude and any(c.isalpha() for c in word):
                names[word] = None
    return list(names)


def _rule_tokens(
    statement: Statement, statements: Sequence[Statement]
) -> tuple[str, list[Token]] | None:
    """Return the kind and tokens of a business-rule candidate, or None."""
    words = statement.words
    verb = statement.verb
    if verb == "IF":
        return "if", statement.tokens[:-1] if words[-1] == "THEN" else statement.tokens
    if verb == "EVALUATE":
        tokens = list(statement.tokens)
        for other in statements:
            if other.owner is statement:
                tokens.extend(other.tokens)
        return "evaluate", tokens
    if verb == "COMPUTE":
        return "compute", statement.tokens
    if verb in ARITHMETIC and "GIVING" in words:
        return "arithmetic", statement.tokens
    if verb == "SET" and words[-1] in {"TRUE", "FALSE"}:
        return "set-condition", statement.tokens
    if verb == "PERFORM" and "UNTIL" in words:
        return "condition", statement.tokens
    if verb == "WHEN" and statement.owner is not None and statement.owner.verb == "SEARCH":
        return "condition", statement.tokens
    return None


def _signals(
    tokens: Sequence[Token], conditions: set[str], technical: set[str], kind: str
) -> tuple[list[str], list[str]]:
    """Return why a rule candidate matters, and the literals it compares or uses."""
    names = set(_identifiers(tokens, set()))
    literals = [
        token.text
        for token in tokens
        if token.kind == "literal"
        or (token.kind == "word" and NUMERIC_LITERAL.fullmatch(token.text))
    ]
    signals = []
    if names & conditions:
        signals.append("condition-name")
    if literals and kind in {"compute", "arithmetic"}:
        signals.append("literal-constant")
    elif literals and (kind == "evaluate" or {token.upper for token in tokens} & RELATIONAL):
        signals.append("literal-comparison")
    if names & technical:
        signals.append("technical")
    return signals, literals


def _rule_text(tokens: Iterable[Token]) -> str:
    text = " ".join(" ".join(token.text for token in tokens).split())
    return text if len(text) <= MAX_RULE_TEXT else text[: MAX_RULE_TEXT - 3] + "..."


def _call_arguments(tokens: Sequence[Token]) -> list[Token]:
    """Return the USING arguments of a CALL statement."""
    words = [token.upper for token in tokens]
    if "USING" not in words:
        return []
    arguments = []
    for token in tokens[words.index("USING") + 1 :]:
        if token.upper in CALL_END:
            break
        if token.upper not in CALL_NOISE:
            arguments.append(token)
    return arguments


def _cics_command(words: Sequence[str]) -> str:
    """Return a CICS command name such as LINK, SEND MAP, or READQ TS."""
    command = words[0].split("(")[0] if words else "?"
    second = words[1].split("(")[0] if len(words) > 1 else ""
    return f"{command} {second}" if second in CICS_SECOND_WORDS else command


def _sql_kind(words: Sequence[str]) -> str:
    """Return the kind of an embedded SQL statement, such as SELECT or DECLARE CURSOR."""
    first = words[0] if words else "?"
    return "DECLARE CURSOR" if first == "DECLARE" and "CURSOR" in words else first


def _sql_tables(statement: str) -> set[str]:
    """Return table names referenced by one embedded SQL statement."""
    if re.match(r"\s*(?:FETCH|OPEN|CLOSE|WHENEVER|INCLUDE|COMMIT|ROLLBACK)\b", statement):
        return set()
    tables = set(SQL_TABLE_CONTEXT.findall(statement))
    for match in re.finditer(r"(?<![A-Z0-9_])FROM\s+", statement):
        tail = statement[match.end() :]
        end = SQL_CLAUSE_END.search(tail)
        segment = tail[: end.start()] if end else tail
        for part in re.split(r",|(?<![A-Z0-9_])JOIN(?![A-Z0-9_])", segment):
            words = part.split()
            if words and re.fullmatch(NAME + r"(?:\." + NAME + ")?", words[0]):
                tables.add(words[0])
    return {table for table in tables if not table.startswith(":")}


def _components(count: int, adjacency: dict[int, set[int]]) -> list[list[int]]:
    """Return the strongly connected components of a graph (iterative Tarjan)."""
    order: dict[int, int] = {}
    low: dict[int, int] = {}
    stack: list[int] = []
    on_stack: set[int] = set()
    components: list[list[int]] = []
    for root in range(count):
        if root in order:
            continue
        order[root] = low[root] = len(order)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(sorted(adjacency.get(root, ()))))]
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in order:
                    order[child] = low[child] = len(order)
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(adjacency.get(child, ())))))
                elif child in on_stack:
                    low[node] = min(low[node], order[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == order[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
    return components


def _range_name(edge: Edge) -> str:
    return f"{edge.name} THRU {edge.thru}" if edge.thru else edge.name


class _Analyzer:
    """Build the documentation model of one program from its expanded source lines."""

    def __init__(self, lines: list[SourceLine], warnings: list[str]) -> None:
        self.lines = lines
        self.warnings = warnings
        self.model: dict[str, Any] = {}
        self.procedures: list[Procedure] = []
        self.by_name: dict[str, list[int]] = {}
        self.edges: list[Edge] = []
        self.unresolved: list[dict[str, Any]] = []
        self.alters: list[dict[str, Any]] = []
        self.alterable: list[dict[str, Any]] = []
        self.depending: list[dict[str, Any]] = []
        self.handles: list[dict[str, Any]] = []
        self.entry_points: list[dict[str, Any]] = []
        self.conditions: dict[str, dict[str, str]] = {}
        self.values: dict[str, list[str]] = {}
        self.record_files: dict[str, str] = {}
        self.status_names: set[str] = set()
        self.queues: set[str] = set()
        self.interfaces: dict[str, Any] = {
            "calls": [],
            "cics": [],
            "sql": [],
            "dli": [],
            "mq": [],
            "file_io": {},
        }

    def number(self, index: int) -> int:
        """Return the main-program line number of an expanded line."""
        return self.lines[index].number

    def run(self) -> dict[str, Any]:
        """Analyze the program and return the model."""
        end = self._program_bounds()
        divisions: dict[str, int] = {}
        for index in range(end):
            line = self.lines[index]
            match = DIVISION.match(line.text) if line.kind == "code" else None
            if match:
                name = match.group(1).upper()
                divisions.setdefault("IDENTIFICATION" if name == "ID" else name, index)
        if "PROCEDURE" not in divisions:
            raise ValueError("no PROCEDURE DIVISION found; is this a COBOL program?")
        order = sorted(divisions.values())
        regions = {
            name: (start, next((bound for bound in order if bound > start), end))
            for name, start in divisions.items()
        }
        self._identification(*regions.get("IDENTIFICATION", (0, 0)))
        code_start = min(divisions.get(name, end) for name in ("ENVIRONMENT", "DATA", "PROCEDURE"))
        self.model["header_comments"] = _clean_comments(
            line.text
            for line in self.lines[:code_start]
            if line.kind == "comment" and line.copybook is None
        )[:MAX_HEADER_COMMENTS]
        self._environment(*regions.get("ENVIRONMENT", (0, 0)))
        self._data(*regions.get("DATA", (0, 0)))
        self._procedure(*regions["PROCEDURE"])
        self._edges()
        self._collect_moves()
        self._collect_interfaces()
        reached, roots = self._reach()
        self._finish(reached, roots)
        return self.model

    def _program_bounds(self) -> int:
        """Record the PROGRAM-ID and nested programs; return where the outer program ends."""
        starts = [
            (index, match.group(1).upper())
            for index, line in enumerate(self.lines)
            if line.kind == "code" and (match := PROGRAM_ID.search(line.text))
        ]
        program_id = starts[0][1] if starts else ""
        self.model["program_id"] = program_id
        ends = [
            (index, match.group(1).upper())
            for index, line in enumerate(self.lines)
            if line.kind == "code" and (match := END_PROGRAM.match(line.text))
        ]
        outer_end = next((index for index, name in ends if name == program_id), None)
        self.model["nested_programs"] = [
            {
                "name": name,
                "line": self.number(index),
                "relation": "nested" if outer_end is None or index < outer_end else "following",
            }
            for index, name in starts[1:]
        ]
        end = len(self.lines)
        if len(starts) > 1:
            end = starts[1][0]
            previous = next((i for i in range(end - 1, -1, -1) if self.lines[i].kind == "code"), 0)
            header = DIVISION.match(self.lines[previous].text)
            if header and header.group(1).upper() in {"IDENTIFICATION", "ID"}:
                end = previous
        return min([end, *(index for index, _ in ends)])

    def _identification(self, start: int, end: int) -> None:
        paragraphs: dict[str, list[str]] = {}
        current: str | None = None
        for line in self.lines[start + 1 : end]:
            if line.kind != "code":
                continue
            match = ID_PARAGRAPH.match(line.text)
            if match:
                key = match.group(1).upper()
                current = None if key == "PROGRAM-ID" else key
                if current:
                    paragraphs[current] = [match.group(2)]
            elif current and not line.area_a:
                paragraphs[current].append(line.text)
        self.model["identification"] = {
            key: " ".join(" ".join(parts).split()).rstrip(".").strip()
            for key, parts in paragraphs.items()
        }

    def _environment(self, start: int, end: int) -> None:
        files = []
        for entry in _entries(_tokenize(self.lines, start, end)):
            if entry[0].upper != "SELECT" or len(entry) < 2:
                continue
            original = " ".join(" ".join(token.text for token in entry).split())
            text = original.upper()
            words = text.split()
            optional = words[1] == "OPTIONAL" and len(words) > 2
            assign = SELECT_ASSIGN.search(original)
            target = assign.group(1) if assign else ""
            quoted = target.startswith(("'", '"'))
            organization = ORGANIZATION.search(text) or BARE_ORGANIZATION.search(text)
            access = ACCESS.search(text)
            key = RECORD_KEY.search(text)
            status = FILE_STATUS.search(text)
            if status:
                self.status_names.add(status.group(1))
            files.append(
                {
                    "select": words[2] if optional else words[1],
                    "assign": target.strip("'\""),
                    "ddname": target.strip("'\"") if quoted else target.split("-")[-1].upper(),
                    "organization": " ".join(organization.group(1).split())
                    if organization
                    else "SEQUENTIAL",
                    "access": access.group(1) if access else "SEQUENTIAL",
                    "record_key": key.group(1) if key else None,
                    "alternate_keys": ALTERNATE_KEY.findall(text),
                    "file_status": status.group(1) if status else None,
                    "optional": optional,
                    "line": self.number(entry[0].index),
                }
            )
        self.model["files"] = files

    def _data(self, start: int, end: int) -> None:
        sections: dict[str, dict[str, list[dict[str, Any]]]] = {}
        section = "(none)"
        for line in self.lines[start:end]:
            match = DATA_SECTION.match(line.text) if line.kind == "code" else None
            if match:
                section = match.group(1).upper()
            elif line.kind == "copy":
                sections.setdefault(section, {"records": [], "copybooks": []})["copybooks"].append(
                    {"member": line.text, "line": line.number, "status": line.detail}
                    | ({"in": line.copybook} if line.copybook else {})
                )
        section, file_name, parent = "(none)", None, ""
        for entry in _entries(_merge_exec(_tokenize(self.lines, start, end))):
            words = [token.upper for token in entry]
            if len(words) > 1 and words[1] == "SECTION":
                section, file_name = words[0], None
                continue
            if words[0] in {"FD", "SD", "RD"} and len(words) > 1:
                file_name = words[1]
                continue
            if entry[0].kind != "word" or not re.fullmatch(r"\d{1,2}", words[0]):
                continue
            level = int(words[0])
            named = len(entry) > 1 and entry[1].kind == "word" and words[1] not in DATA_CLAUSES
            name = words[1] if named else "FILLER"
            value = self._value(entry, words)
            if level == 88:
                self.conditions[name] = {"of": parent, "values": value}
                continue
            parent = name
            literal = next((t for t in entry[2:] if t.kind == "literal"), None)
            if "VALUE" in words and literal is not None:
                self.values.setdefault(name, []).append(_literal_value(literal.text))
            if level in {1, 77}:
                line = self.lines[entry[0].index]
                record: dict[str, Any] = {"name": name, "level": level, "line": line.number}
                if line.copybook:
                    record["copybook"] = line.copybook
                if section == "FILE" and file_name:
                    record["file"] = file_name
                    self.record_files[name] = file_name
                sections.setdefault(section, {"records": [], "copybooks": []})["records"].append(
                    record
                )
        self.model["data"] = sections

    @staticmethod
    def _value(entry: Sequence[Token], words: Sequence[str]) -> str:
        """Return the text of a VALUE clause, or an empty string."""
        for keyword in ("VALUE", "VALUES"):
            if keyword in words:
                rest = [t.text for t in entry[words.index(keyword) + 1 :]]
                while rest and rest[0].upper() in {"IS", "ARE"}:
                    rest = rest[1:]
                return " ".join(rest)
        return ""

    def _procedure(self, start: int, end: int) -> None:
        tokens = _merge_exec(_tokenize(self.lines, start, end))
        stop = next((i for i, token in enumerate(tokens) if token.kind == "period"), len(tokens))
        header = [token.upper for token in tokens[2:stop]]
        using = header[header.index("USING") + 1 :] if "USING" in header else []
        if "RETURNING" in using:
            using = using[: using.index("RETURNING")]
        returning = header[header.index("RETURNING") + 1 :] if "RETURNING" in header else []
        self.model["procedure_division"] = {
            "line": self.number(start),
            "using": [word for word in using if word not in CALL_NOISE | {"OPTIONAL"}],
            "returning": returning[0] if returning else None,
        }
        body = tokens[stop + 1 :]
        position = 0
        section: str | None = None
        declaratives = False
        current: Procedure | None = None
        while position < len(body):
            token = body[position]
            header_kind = _procedure_header(body, position, self.lines)
            if header_kind is None:
                if current is None:
                    current = Procedure(START, "start", token.index, None, declaratives)
                    self.procedures.append(current)
                current.tokens.append(token)
                position += 1
                continue
            kind, width = header_kind
            if kind in {"section", "paragraph"}:
                section = token.upper if kind == "section" else section
                current = Procedure(token.upper, kind, token.index, section, declaratives)
                self.procedures.append(current)
            else:
                declaratives = kind == "declaratives"
                section, current = None, None
            position += width
        names = {procedure.name for procedure in self.procedures}
        for index, procedure in enumerate(self.procedures):
            self.by_name.setdefault(procedure.name, []).append(index)
            procedure.statements = _parse_statements(procedure.tokens, names)
            procedure.description = self._describe(procedure)

    def _describe(self, procedure: Procedure) -> str:
        """Return the comment block directly above a procedure header, cleaned up."""
        texts: list[str] = []
        index = procedure.index - 1
        while index >= 0 and self.lines[index].kind in {"blank", "directive"}:
            index -= 1
        while index >= 0 and self.lines[index].kind == "comment":
            texts.append(self.lines[index].text)
            index -= 1
        text = " ".join(_clean_comments(reversed(texts)))
        if text.upper().startswith(procedure.name):
            text = text[len(procedure.name) :].lstrip(" :.-")
        return text

    def _target(self, source: int, reference: Reference, line: int) -> int | None:
        """Resolve a procedure name the way COBOL does: same section first, then anywhere."""
        name, qualifier = reference
        candidates = self.by_name.get(name, [])
        if qualifier:
            candidates = [i for i in candidates if self.procedures[i].section == qualifier]
        section = self.procedures[source].section
        chosen = [i for i in candidates if self.procedures[i].section == section] or candidates
        if not chosen:
            self.unresolved.append(
                {"name": name, "from": self.procedures[source].name, "line": line}
            )
            return None
        return chosen[0]

    def _section_end(self, index: int) -> int:
        """Return the last procedure that belongs to ``index`` (itself unless a section)."""
        procedure = self.procedures[index]
        end = index
        while (
            procedure.kind == "section"
            and end + 1 < len(self.procedures)
            and self.procedures[end + 1].kind == "paragraph"
            and self.procedures[end + 1].section == procedure.name
        ):
            end += 1
        return end

    def _range_edge(
        self, source: int, kind: str, line: int, references: tuple[Reference, Reference | None]
    ) -> None:
        """Add a PERFORM-like edge that covers a procedure, a section, or a THRU range."""
        first_ref, last_ref = references
        first = self._target(source, first_ref, line)
        last = self._target(source, last_ref, line) if last_ref else first
        if first is None or last is None:
            return
        if last < first:
            self.warnings.append(f"line {line}: THRU {last_ref[0]} precedes {first_ref[0]}")
        covers = tuple(range(first, self._section_end(max(first, last)) + 1))
        thru = self.procedures[last].name if last_ref else ""
        edge_kind = "thru" if kind == "perform" and last_ref else kind
        name = self.procedures[first].name
        self.edges.append(Edge(source, first, edge_kind, line, name, thru=thru, covers=covers))

    def _perform(self, source: int, words: list[str], line: int) -> None:
        first, position = _reference(words, 1)
        last = None
        if position + 1 < len(words) and words[position] in THRU:
            last, _ = _reference(words, position + 1)
        self._range_edge(source, "perform", line, (first, last))

    def _go_to(self, source: int, words: list[str], line: int) -> None:
        rest = words[2:] if words[1:2] == ["TO"] else words[1:]
        depending = "DEPENDING" in rest
        names = rest[: rest.index("DEPENDING")] if depending else rest
        references = []
        position = 0
        while position < len(names):
            reference, position = _reference(names, position)
            references.append(reference)
        here = {"paragraph": self.procedures[source].name, "line": line}
        if not references:
            self.alterable.append(here)
        if depending:
            after = rest[rest.index("DEPENDING") + 1 :]
            after = after[1:] if after[:1] == ["ON"] else after
            self.depending.append(
                here
                | {
                    "targets": [name for name, _ in references],
                    "depending_on": after[0] if after else None,
                }
            )
        kind = "go-to-depending" if depending else "go-to"
        for reference in references:
            target = self._target(source, reference, line)
            if target is not None:
                self.edges.append(Edge(source, target, kind, line, self.procedures[target].name))

    def _alter(self, source: int, words: list[str], line: int) -> None:
        position = 1
        while position < len(words):
            altered, position = _reference(words, position)
            while position < len(words) and words[position] in {"TO", "PROCEED"}:
                position += 1
            if position >= len(words):
                break
            proceed, position = _reference(words, position)
            self.alters.append(
                {
                    "paragraph": self.procedures[source].name,
                    "line": line,
                    "altered": altered[0],
                    "proceeds_to": proceed[0],
                }
            )
            altered_index = self._target(source, altered, line)
            proceed_index = self._target(source, proceed, line)
            if altered_index is not None and proceed_index is not None:
                self.edges.append(Edge(altered_index, proceed_index, "altered", line, proceed[0]))

    def _sort(self, source: int, words: list[str], line: int) -> None:
        for phrase in ("INPUT", "OUTPUT"):
            for position in range(len(words) - 2):
                if words[position] != phrase or words[position + 1] != "PROCEDURE":
                    continue
                start = position + 3 if words[position + 2] == "IS" else position + 2
                if start >= len(words):
                    break
                first, after = _reference(words, start)
                last = None
                if after + 1 < len(words) and words[after] in THRU:
                    last = _reference(words, after + 1)[0]
                self._range_edge(source, f"sort-{phrase.lower()}", line, (first, last))
                break

    def _handle(self, source: int, text: str, line: int) -> None:
        match = CICS_HANDLE.match(text)
        if not match:
            return
        labels = {}
        for option, label in HANDLE_OPERAND.findall(match.group(2)):
            if option in HANDLE_NON_LABELS:
                continue
            labels[option] = label
            target = self._target(source, (label, None), line)
            if target is not None:
                self.edges.append(
                    Edge(source, target, "cics-handle", line, label, label=f"handle {option}")
                )
        self.handles.append(
            {
                "paragraph": self.procedures[source].name,
                "line": line,
                "command": f"HANDLE {match.group(1)}",
                "labels": labels,
            }
        )

    def _edges(self) -> None:
        for source, procedure in enumerate(self.procedures):
            for statement in procedure.statements:
                line = self.number(statement.tokens[0].index)
                words = statement.words
                if statement.verb == "PERFORM" and not statement.inline and len(words) > 1:
                    self._perform(source, words, line)
                elif statement.verb == "GO":
                    self._go_to(source, words, line)
                elif statement.verb == "ALTER":
                    self._alter(source, words, line)
                elif statement.verb in {"SORT", "MERGE"}:
                    self._sort(source, words, line)
                elif statement.verb == "EXEC":
                    self._handle(source, words[0], line)
                elif statement.verb == "ENTRY" and len(words) > 1:
                    self.entry_points.append(
                        {
                            "name": _literal_value(statement.tokens[1].text),
                            "paragraph": procedure.name,
                            "line": line,
                            "id": source,
                        }
                    )
            following = source + 1
            if following >= len(self.procedures) or _ends_with_transfer(procedure.statements):
                continue
            target = self.procedures[following]
            if procedure.kind == "start" or (
                target.section == procedure.section
                and target.declaratives == procedure.declaratives
            ):
                line = self.number(target.index)
                self.edges.append(Edge(source, following, "next", line, target.name))

    def _collect_moves(self) -> None:
        """Record literals moved into data items, to resolve dynamic CALLs and resources."""
        for procedure in self.procedures:
            for statement in procedure.statements:
                tokens = statement.tokens
                if (
                    statement.verb != "MOVE"
                    or len(tokens) < 4
                    or tokens[1].kind != "literal"
                    or tokens[2].upper != "TO"
                ):
                    continue
                value = _literal_value(tokens[1].text)
                for target in tokens[3:]:
                    match = IDENTIFIER.match(target.upper)
                    if target.kind != "word" or not match:
                        continue
                    known = self.values.setdefault(match.group(), [])
                    if value not in known:
                        known.append(value)
                    if match.group().endswith("OBJECTNAME"):
                        self.queues.add(value)

    def _collect_interfaces(self) -> None:
        for procedure in self.procedures:
            for statement in procedure.statements:
                where = {
                    "paragraph": procedure.name,
                    "line": self.number(statement.tokens[0].index),
                }
                if statement.verb == "CALL" and len(statement.tokens) > 1:
                    self._call(statement, where)
                elif statement.verb == "EXEC":
                    self._exec(statement.tokens[0].upper, where)
                elif statement.verb in FILE_VERBS:
                    self._file_io(statement, where)
                elif statement.verb in {"SORT", "MERGE"}:
                    self._sort_files(statement, where)
        self.interfaces["mq_queues"] = sorted(self.queues)

    def _call(self, statement: Statement, where: dict[str, Any]) -> None:
        target = statement.tokens[1]
        arguments = _call_arguments(statement.tokens)
        if target.kind == "literal":
            name = _literal_value(target.text).upper()
            entry: dict[str, Any] = {"target": name, "type": "static"} | where
            family = INTERFACE_FAMILY.get(name)
            if family:
                entry["interface"] = family
            if family == "ims":
                self._dli_call(name, arguments, where)
            elif family == "mq":
                self.interfaces["mq"].append({"call": name} | where)
        else:
            name = target.upper
            resolved = self.values.get(name, [])
            entry = {"target": name, "type": "dynamic", "resolved": resolved} | where
        entry["using"] = [argument.text for argument in arguments]
        self.interfaces["calls"].append(entry)

    def _dli_call(self, name: str, arguments: Sequence[Token], where: dict[str, Any]) -> None:
        function = None
        if arguments:
            first = arguments[0]
            resolved = self.values.get(first.upper, [])
            if first.kind == "literal":
                function = _literal_value(first.text)
            else:
                function = resolved[0] if resolved else first.upper
        pcb = arguments[1].upper if len(arguments) > 1 else None
        self.interfaces["dli"].append(
            {"via": f"CALL {name}", "function": function, "pcb": pcb} | where
        )

    def _exec(self, text: str, where: dict[str, Any]) -> None:
        words = text.split()
        interface = words[1] if len(words) > 1 else ""
        body = " ".join(word for word in words[2:] if word != "END-EXEC")
        if interface == "CICS":
            resources = []
            for option, quote, value in CICS_ARGUMENT.findall(body):
                name = value.strip()
                resource: dict[str, Any] = {"option": option, "name": name}
                if not quote:
                    resource |= {"dynamic": True, "resolved": self.values.get(name, [])}
                resources.append(resource)
            command = _cics_command(words[2:])
            self.interfaces["cics"].append({"command": command, "resources": resources} | where)
        elif interface == "SQL":
            kind = _sql_kind(body.split())
            tables = sorted(_sql_tables(body))
            self.interfaces["sql"].append({"statement": kind, "tables": tables} | where)
        elif interface == "DLI":
            function = words[2] if len(words) > 2 else None
            segments = DLI_SEGMENT.findall(body)
            self.interfaces["dli"].append(
                {"via": "EXEC DLI", "function": function, "segments": segments} | where
            )

    def _io(self, name: str, verb: str, where: dict[str, Any]) -> None:
        self.interfaces["file_io"].setdefault(name, []).append({"verb": verb} | where)

    def _file_io(self, statement: Statement, where: dict[str, Any]) -> None:
        words = [token.upper for token in statement.tokens if token.kind == "word"]
        verb = statement.verb
        if verb == "OPEN":
            mode = ""
            for word in words[1:]:
                if word in FILE_MODES:
                    mode = word
                elif mode and word not in FILE_NOISE:
                    self._io(word, f"OPEN {mode}", where)
        elif verb == "CLOSE":
            for word in words[1:]:
                if word not in FILE_NOISE:
                    self._io(word, verb, where)
        elif len(words) > 1:
            name = words[1]
            if verb in {"WRITE", "REWRITE", "RELEASE"}:
                name = self.record_files.get(name, name)
            self._io(name, verb, where)

    def _sort_files(self, statement: Statement, where: dict[str, Any]) -> None:
        words = statement.words
        if len(words) > 1:
            self._io(words[1], statement.verb, where)
        mode = ""
        for word in words[2:]:
            if word in {"USING", "GIVING"}:
                mode = word
            elif word in {"INPUT", "OUTPUT"}:
                mode = ""
            elif mode:
                self._io(word, f"{statement.verb} {mode}", where)

    def _roots(self) -> list[int]:
        roots = {
            index
            for index, procedure in enumerate(self.procedures)
            if procedure.declaratives and procedure.kind == "section"
        }
        main = next((i for i, p in enumerate(self.procedures) if not p.declaratives), None)
        if main is not None:
            roots.add(main)
        roots.update(entry["id"] for entry in self.entry_points)
        return sorted(roots)

    def _reach(self) -> tuple[set[int], list[int]]:
        """Return the reachable procedures and the roots.

        A PERFORM covers its whole range and returns at the end of the range, so the last
        procedure of a performed range does not fall through. A GO TO that stays inside the
        active range keeps that return point; other transfers start unbounded flow.
        """
        roots = self._roots()
        outgoing: dict[int, list[Edge]] = {}
        for edge in self.edges:
            outgoing.setdefault(edge.source, []).append(edge)
        seen: set[tuple[int, tuple[int, int] | None]] = set()
        queue: deque[tuple[int, tuple[int, int] | None]] = deque((root, None) for root in roots)
        while queue:
            state = queue.popleft()
            if state in seen:
                continue
            seen.add(state)
            index, bound = state
            for edge in outgoing.get(index, []):
                if edge.covers:
                    span = (edge.covers[0], edge.covers[-1])
                    queue.extend((covered, span) for covered in edge.covers)
                elif edge.kind == "next":
                    if bound is None or index != bound[1]:
                        queue.append((edge.target, bound))
                elif bound and bound[0] <= edge.target <= bound[1] and edge.kind != "cics-handle":
                    queue.append((edge.target, bound))
                else:
                    queue.append((edge.target, None))
        return {index for index, _ in seen}, roots

    def _risks(self, reached: set[int]) -> dict[str, Any]:
        names = [procedure.name for procedure in self.procedures]
        ranges = [edge for edge in self.edges if edge.covers and edge.source in reached]
        leaving = []
        for edge in self.edges:
            if edge.kind not in {"go-to", "go-to-depending"} or edge.source not in reached:
                continue
            perform = next(
                (r for r in ranges if edge.source in r.covers and edge.target not in r.covers),
                None,
            )
            if perform is not None:
                leaving.append(
                    {
                        "paragraph": names[edge.source],
                        "line": edge.line,
                        "go_to": names[edge.target],
                        "range": _range_name(perform),
                        "performed_from": names[perform.source],
                        "perform_line": perform.line,
                    }
                )
        adjacency: dict[int, set[int]] = {}
        for edge in self.edges:
            if edge.covers:
                adjacency.setdefault(edge.source, set()).update(edge.covers)
        cycles = [
            [names[index] for index in component]
            for component in _components(len(names), adjacency)
            if len(component) > 1 or component[0] in adjacency.get(component[0], set())
        ]
        return {
            "go_to_leaves_perform_range": leaving,
            "perform_cycles": cycles,
            "alter": self.alters,
            "alterable_go_to": self.alterable,
            "go_to_depending": self.depending,
            "cics_handle": self.handles,
            "unresolved_procedures": self.unresolved,
        }

    def _rules(self, reached: set[int]) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        conditions = set(self.conditions)
        technical = TECHNICAL_NAMES | self.status_names
        procedure_names = set(self.by_name)
        for index, procedure in enumerate(self.procedures):
            for statement in procedure.statements:
                found = _rule_tokens(statement, procedure.statements)
                if found is None:
                    continue
                kind, tokens = found
                signals, literals = _signals(tokens, conditions, technical, kind)
                if kind == "condition" and not {"condition-name", "literal-comparison"} & set(
                    signals
                ):
                    continue
                line = self.lines[statement.tokens[0].index]
                rule: dict[str, Any] = {
                    "id": f"BR-{len(rules) + 1:03d}",
                    "paragraph": procedure.name,
                    "line": line.number,
                    "kind": kind,
                    "text": _rule_text(tokens),
                    "data_names": _identifiers(tokens, procedure_names),
                    "signals": signals,
                    "literals": literals,
                    "reachable": index in reached,
                }
                if line.copybook:
                    rule["copybook"] = line.copybook
                if kind == "evaluate":
                    rule["whens"] = [
                        {
                            "line": self.number(other.tokens[0].index),
                            "text": _rule_text(other.tokens),
                        }
                        for other in procedure.statements
                        if other.owner is statement
                    ]
                rules.append(rule)
        return rules

    def _finish(self, reached: set[int], roots: list[int]) -> None:
        names = [procedure.name for procedure in self.procedures]
        unreachable = []
        for index, procedure in enumerate(self.procedures):
            if index in reached:
                continue
            members = range(index + 1, self._section_end(index) + 1)
            if procedure.kind == "section" and not procedure.statements and reached & set(members):
                continue
            unreachable.append(index)
        outgoing_edges: dict[int, list[Edge]] = {}
        for edge in self.edges:
            outgoing_edges.setdefault(edge.source, []).append(edge)
        procedures = []
        for index, procedure in enumerate(self.procedures):
            line = self.lines[procedure.index]
            outgoing = outgoing_edges.get(index, [])
            use = next((s for s in procedure.statements if s.verb == "USE"), None)
            entry: dict[str, Any] = {
                "id": index,
                "name": procedure.name,
                "kind": procedure.kind,
                "section": procedure.section,
                "line": line.number,
                "description": procedure.description,
                "statements": sum(s.verb not in MARKERS for s in procedure.statements),
                "performs": list(dict.fromkeys(_range_name(e) for e in outgoing if e.covers)),
                "go_tos": list(
                    dict.fromkeys(e.name for e in outgoing if e.kind.startswith("go-to"))
                ),
                "falls_through": not _ends_with_transfer(procedure.statements),
                "declaratives": procedure.declaratives,
                "root": index in roots,
                "reachable": index not in unreachable,
            }
            if line.copybook:
                entry["copybook"] = line.copybook
            if use is not None:
                entry["use"] = _rule_text(use.tokens)
            procedures.append(entry)
        statements = [s for procedure in self.procedures for s in procedure.statements]
        self.model["procedure_division"]["entry_points"] = [
            {key: value for key, value in entry.items() if key != "id"}
            for entry in self.entry_points
        ]
        self.model["counts"] = {
            "sections": sum(p.kind == "section" for p in self.procedures),
            "paragraphs": sum(p.kind == "paragraph" for p in self.procedures),
            "statements": sum(s.verb not in MARKERS for s in statements),
            "performs": sum(s.verb == "PERFORM" and not s.inline for s in statements),
            "inline_performs": sum(s.verb == "PERFORM" and s.inline for s in statements),
            "go_tos": sum(s.verb == "GO" for s in statements),
            "alters": sum(s.verb == "ALTER" for s in statements),
            "unreachable": len(unreachable),
        }
        self.model["condition_names"] = self.conditions
        self.model["procedures"] = procedures
        self.model["edges"] = [
            {
                "from": names[edge.source],
                "to": names[edge.target],
                "kind": edge.kind,
                "line": edge.line,
                "source": edge.source,
                "target": edge.target,
            }
            | ({"thru": edge.thru} if edge.thru else {})
            | ({"label": edge.label} if edge.label else {})
            for edge in self.edges
        ]
        self.model["unreachable"] = [names[index] for index in unreachable]
        self.model["risks"] = self._risks(reached)
        self.model["rules"] = self._rules(reached)
        self.model["interfaces"] = self.interfaces
        self.model["notes"] = [APPROXIMATE, RULE_NOTE]


def analyze_program(
    path: Path, *, copylibs: Sequence[Path] = (), codepage: str = "037"
) -> dict[str, Any]:
    """Analyze one COBOL program and return its documentation model.

    Copy members are searched in ``copylibs`` (recursively, in order), then in the
    program's own directory.

    Raises:
        OSError: The program or a copy member cannot be read.
        ValueError: The code page is unsupported, the file is binary, or it has no
            PROCEDURE DIVISION.
    """
    codepage = zos_encoding.normalize_codepage(codepage)
    decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
    if decoded is None:
        raise ValueError(f"{path}: binary content, not COBOL source")
    warnings = list(decoded.warnings)
    libraries = [_Library(Path(directory), recursive=True) for directory in copylibs]
    warnings += [
        f"copy library not found: {lib.root}" for lib in libraries if not lib.root.is_dir()
    ]
    libraries.append(_Library(path.parent, recursive=False))
    context = _CopyContext(libraries, codepage, warnings)
    source_lines = decoded.text.splitlines()
    normalized, source_format = normalize_source(source_lines)
    lines = _expand(normalized, context, (path.resolve(),))
    model = _Analyzer(lines, warnings).run()
    copybooks = [
        {"member": line.text, "line": line.number, "status": line.detail}
        | ({"path": context.paths[line.text]} if line.text in context.paths else {})
        | ({"in": line.copybook} if line.copybook else {})
        for line in lines
        if line.kind == "copy"
    ]
    return (
        {
            "tool": "cobol_flow",
            "source": str(path),
            "encoding": decoded.encoding,
            "format": source_format,
            "lines": len(source_lines),
            "copybooks": copybooks,
        }
        | model
        | {"warnings": warnings}
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list | tuple):
        value = ", ".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)
    return [*lines, ""]


def _md_overview(result: dict[str, Any]) -> list[str]:
    procedure = result["procedure_division"]
    counts = result["counts"]
    rows: list[tuple[str, Any]] = [
        ("Program-ID", result["program_id"] or "(none)"),
        (
            "Source",
            (
                f"{result['source']} ({result['format']} format, {result['encoding']}, "
                f"{result['lines']} lines)"
            ),
        ),
    ]
    rows += [
        (key.replace("-", " ").capitalize(), value)
        for key, value in result["identification"].items()
    ]
    if result["nested_programs"]:
        nested = [
            f"{p['name']} (line {p['line']}, {p['relation']})" for p in result["nested_programs"]
        ]
        rows.append(("Other programs in the source", nested))
    if procedure["using"]:
        rows.append(("PROCEDURE DIVISION USING", procedure["using"]))
    if procedure["returning"]:
        rows.append(("RETURNING", procedure["returning"]))
    if procedure["entry_points"]:
        entries = [
            f"{e['name']} ({e['paragraph']}, line {e['line']})" for e in procedure["entry_points"]
        ]
        rows.append(("ENTRY points", entries))
    rows.append(
        (
            "Size",
            (
                f"{counts['sections']} sections, {counts['paragraphs']} paragraphs, "
                f"{counts['statements']} statements"
            ),
        )
    )
    lines = ["## Overview", "", *_table(["Item", "Value"], rows)]
    if result["header_comments"]:
        lines += ["Header comments:", "", "```text", *result["header_comments"], "```", ""]
    lines += [
        (
            "**Purpose:** _To complete: what the program does, for whom, and when it runs "
            "(online transaction, batch step, or called subprogram)._"
        ),
        "",
    ]
    return lines


def _md_files(result: dict[str, Any]) -> list[str]:
    lines = ["## Files", ""]
    if not result["files"]:
        return [*lines, "No FILE-CONTROL entries.", ""]
    file_io = result["interfaces"]["file_io"]
    rows = [
        (
            entry["select"],
            entry["ddname"],
            entry["organization"],
            entry["access"],
            entry["record_key"],
            entry["file_status"],
            list(dict.fromkeys(use["verb"] for use in file_io.get(entry["select"], []))),
        )
        for entry in result["files"]
    ]
    header = ["File", "DD name", "Organization", "Access", "Record key", "File status", "I/O"]
    return [*lines, *_table(header, rows)]


def _md_data(result: dict[str, Any]) -> list[str]:
    lines = ["## Data", ""]
    for section, content in result["data"].items():
        lines += [f"### {section} SECTION", ""]
        if content["records"]:
            rows = [
                (r["name"], f"{r['level']:02d}", r["line"], r.get("copybook"), r.get("file"))
                for r in content["records"]
            ]
            lines += _table(["Record", "Level", "Line", "Copybook", "File"], rows)
        if content["copybooks"]:
            used = [
                f"{c['member']} (line {c['line']}, {c['status']})" for c in content["copybooks"]
            ]
            lines += [f"Copybooks: {', '.join(used)}", ""]
    missing = [c for c in result["copybooks"] if c["status"] in {"unresolved", "skipped"}]
    if missing:
        names = ", ".join(f"{c['member']} (line {c['line']})" for c in missing)
        lines += [f"**Copybooks not expanded:** {names}. Pass --copylib to resolve them.", ""]
    if result["condition_names"]:
        rows = [
            (name, info["of"], info["values"]) for name, info in result["condition_names"].items()
        ]
        lines += ["Condition names (88 levels):", "", *_table(["Name", "Of", "Values"], rows)]
    return lines


def _md_interfaces(result: dict[str, Any]) -> list[str]:
    interfaces = result["interfaces"]
    lines = ["## Interfaces", ""]
    if interfaces["calls"]:
        rows = [
            (
                call["target"],
                call.get("interface") or call["type"],
                call.get("resolved", ""),
                call["paragraph"],
                call["line"],
            )
            for call in interfaces["calls"]
        ]
        lines += [
            "### CALL",
            "",
            *_table(["Target", "Type", "Resolved to", "Paragraph", "Line"], rows),
        ]
    if interfaces["cics"]:
        rows = [
            (
                cics["command"],
                [
                    f"{r['option']}({r['name']})"
                    + (f" = {', '.join(r['resolved']) or '?'}" if r.get("dynamic") else "")
                    for r in cics["resources"]
                ],
                cics["paragraph"],
                cics["line"],
            )
            for cics in interfaces["cics"]
        ]
        lines += ["### CICS", "", *_table(["Command", "Resources", "Paragraph", "Line"], rows)]
    if interfaces["sql"]:
        rows = [(s["statement"], s["tables"], s["paragraph"], s["line"]) for s in interfaces["sql"]]
        lines += ["### SQL", "", *_table(["Statement", "Tables", "Paragraph", "Line"], rows)]
    if interfaces["dli"]:
        rows = [
            (d["via"], d["function"], d.get("pcb") or d.get("segments"), d["paragraph"], d["line"])
            for d in interfaces["dli"]
        ]
        lines += [
            "### IMS DL/I",
            "",
            *_table(["Via", "Function", "PCB or segments", "Paragraph", "Line"], rows),
        ]
    if interfaces["mq"]:
        rows = [(m["call"], m["paragraph"], m["line"]) for m in interfaces["mq"]]
        lines += ["### MQ", "", *_table(["Call", "Paragraph", "Line"], rows)]
        if interfaces["mq_queues"]:
            lines += [
                f"Queue names moved to an object descriptor: {', '.join(interfaces['mq_queues'])}",
                "",
            ]
    if len(lines) == 2:
        lines += ["No CALL, CICS, SQL, DL/I, or MQ interfaces found.", ""]
    return lines


def _md_structure(result: dict[str, Any]) -> list[str]:
    rows = []
    for procedure in result["procedures"]:
        description = procedure["description"]
        if len(description) > MAX_DESCRIPTION:
            description = description[: MAX_DESCRIPTION - 3] + "..."
        name = procedure["name"]
        if procedure["kind"] == "section":
            name = f"**{name} SECTION**"
        rows.append(
            (
                name,
                procedure["line"],
                description or "_To complete_",
                procedure["performs"],
                procedure["go_tos"],
                "entry point"
                if procedure["root"]
                else ""
                if procedure["reachable"]
                else "unreachable?",
            )
        )
    header = ["Procedure", "Line", "Description", "Performs", "Go to", "Note"]
    return ["## Procedure structure", "", *_table(header, rows)]


def _md_unreachable(result: dict[str, Any]) -> list[str]:
    lines = ["## Unreachable candidates", ""]
    unreachable = [p for p in result["procedures"] if not p["reachable"]]
    if not unreachable:
        return [*lines, "Every procedure is reachable from an entry point.", ""]
    lines += [
        (
            "No PERFORM, GO TO, fall-through, SORT procedure, CICS HANDLE label, or entry point "
            "reaches these procedures. They are candidates to confirm with runtime coverage, not "
            "dead code yet."
        ),
        "",
    ]
    rows = [(p["name"], p["kind"], p["line"], p.get("copybook")) for p in unreachable]
    return [*lines, *_table(["Procedure", "Kind", "Line", "Copybook"], rows)]


def _md_risks(result: dict[str, Any]) -> list[str]:
    risks = result["risks"]
    items = [
        f"GO TO {r['go_to']} in {r['paragraph']} (line {r['line']}) leaves the PERFORM range "
        f"{r['range']} performed from {r['performed_from']} (line {r['perform_line']})."
        for r in risks["go_to_leaves_perform_range"]
    ]
    items += [
        f"Recursive PERFORM cycle: {' -> '.join(cycle)}." for cycle in risks["perform_cycles"]
    ]
    items += [
        f"ALTER in {r['paragraph']} (line {r['line']}) changes the GO TO in {r['altered']} "
        f"to go to {r['proceeds_to']}."
        for r in risks["alter"]
    ]
    items += [
        f"GO TO without a target in {r['paragraph']} (line {r['line']}): set by ALTER at run time."
        for r in risks["alterable_go_to"]
    ]
    items += [
        f"GO TO ... DEPENDING ON {r['depending_on'] or '?'} in {r['paragraph']} "
        f"(line {r['line']}) jumps to {', '.join(r['targets'])}."
        for r in risks["go_to_depending"]
    ]
    items += [
        f"{r['command']} in {r['paragraph']} (line {r['line']}): "
        + (", ".join(f"{k} -> {v}" for k, v in r["labels"].items()) or "no labels")
        + "; handlers act like GO TO from inside later commands."
        for r in risks["cics_handle"]
    ]
    items += [
        f"Procedure {r['name']} referenced in {r['from']} (line {r['line']}) is not defined; "
        "it may be in a missing copybook."
        for r in risks["unresolved_procedures"]
    ]
    lines = ["## Structure risks", ""]
    lines += [f"- {item}" for item in items] or ["No structure risks found."]
    return [*lines, "", f"_{APPROXIMATE}_", ""]


def _md_rules(result: dict[str, Any]) -> list[str]:
    lines = ["## Business-rule candidates", "", f"_{RULE_NOTE}_", ""]
    if not result["rules"]:
        return [*lines, "No candidates found.", ""]
    rows = [
        (
            rule["id"],
            rule["paragraph"],
            rule["line"],
            rule["kind"],
            f"`{rule['text']}`",
            rule["data_names"],
            rule["signals"],
        )
        for rule in result["rules"]
    ]
    header = ["ID", "Paragraph", "Line", "Kind", "Rule text", "Data names", "Signals"]
    return [*lines, *_table(header, rows)]


def _md_to_complete(result: dict[str, Any]) -> list[str]:
    procedures = result["procedures"]
    undescribed = [p["name"] for p in procedures if not p["description"]]
    notes = [
        (
            "Write the purpose in the Overview from the code, the JCL or CICS definitions "
            "that run the program, and its callers."
        ),
        (
            f"Describe the {len(undescribed)} of {len(procedures)} procedures without a "
            "comment block, and check the descriptions taken from comments against the code."
        ),
        (
            "Confirm each business-rule candidate with a subject-matter expert; record the "
            "rule in business terms with its BR id and line reference, and drop technical checks."
        ),
    ]
    if result["unreachable"]:
        notes.append(
            "Confirm the unreachable candidates with runtime coverage before calling them "
            "dead code."
        )
    missing = [c["member"] for c in result["copybooks"] if c["status"] in {"unresolved", "skipped"}]
    if missing:
        notes.append(f"Obtain the copybooks {', '.join(missing)} and rerun with --copylib.")
    dynamic = [
        c["target"]
        for c in result["interfaces"]["calls"]
        if c["type"] == "dynamic" and not c["resolved"]
    ]
    if dynamic:
        notes.append(
            f"Find the run-time values of {', '.join(dict.fromkeys(dynamic))}, the dynamic CALL "
            "targets the source does not show."
        )
    if result["files"]:
        notes.append("Map each DD name to its data set from the JCL or CICS file definitions.")
    if any(result["risks"][key] for key in ("alter", "go_to_depending", "cics_handle")):
        notes.append(
            "Trace ALTER, GO TO DEPENDING ON, and CICS HANDLE paths by hand; the flow graph is "
            "approximate there."
        )
    return ["## To complete", "", *(f"- [ ] {note}" for note in notes), ""]


def to_markdown(result: dict[str, Any], *, max_nodes: int = DEFAULT_MAX_NODES) -> str:
    """Render the program model as a Markdown documentation skeleton."""
    title = result["program_id"] or Path(result["source"]).stem.upper()
    lines = [
        f"# {title}: program documentation",
        "",
        (
            f"Skeleton generated by `cobol_flow.py` from `{result['source']}`. Replace every "
            "_To complete_ note after reading the code, and treat the rest as static analysis "
            "to verify."
        ),
        "",
    ]
    for render in (_md_overview, _md_files, _md_data, _md_interfaces, _md_structure):
        lines += render(result)
    lines += ["## Flow", "", "```mermaid", to_mermaid(result, max_nodes), "```", ""]
    for render in (_md_unreachable, _md_risks, _md_rules, _md_to_complete):
        lines += render(result)
    return "\n".join(lines)


def _node_id(procedure: dict[str, Any]) -> str:
    return f"n{procedure['id']}_" + re.sub(r"[^A-Za-z0-9]", "_", procedure["name"])


def _arrow(edge: dict[str, Any]) -> str:
    kind = edge["kind"]
    thru = f" thru {edge['thru']}" if edge.get("thru") else ""
    if kind in {"perform", "thru"}:
        return f"-->|{thru.strip() or 'perform'}|"
    if kind.startswith("sort-"):
        return f"-->|{kind.replace('-', ' ')}{thru}|"
    if kind == "altered":
        return "==>|altered|"
    if kind == "cics-handle":
        return f"-.->|{edge['label']}|"
    labels = {"go-to": "go to", "go-to-depending": "go to depending", "next": "next"}
    return f"-.->|{labels[kind]}|"


def to_mermaid(result: dict[str, Any], max_nodes: int = DEFAULT_MAX_NODES) -> str:
    """Render the paragraph flow as a Mermaid flowchart, truncated to ``max_nodes`` nodes."""
    procedures = result["procedures"]
    shown = procedures[:max_nodes]
    ids = {procedure["id"]: _node_id(procedure) for procedure in shown}
    lines = ["flowchart TD"]
    if len(shown) < len(procedures):
        lines.append(
            f"  %% truncated: showing {len(shown)} of {len(procedures)} procedures; "
            "use --format json for the full graph"
        )
    for procedure in shown:
        label = procedure["name"] + (" SECTION" if procedure["kind"] == "section" else "")
        lines.append(f'  {ids[procedure["id"]]}["{label.replace(chr(34), "#quot;")}"]')
    seen: set[tuple[int, int, str]] = set()
    for edge in result["edges"]:
        arrow = _arrow(edge)
        key = (edge["source"], edge["target"], arrow)
        if edge["source"] in ids and edge["target"] in ids and key not in seen:
            seen.add(key)
            lines.append(f"  {ids[edge['source']]} {arrow} {ids[edge['target']]}")
    roots = [ids[p["id"]] for p in shown if p["root"]]
    unreachable = [ids[p["id"]] for p in shown if not p["reachable"]]
    lines.append("  classDef entry stroke-width:3px")
    lines.append("  classDef unreachable fill:#fde2e1,stroke:#b03a2e,stroke-dasharray:4 3")
    if roots:
        lines.append(f"  class {','.join(roots)} entry")
    if unreachable:
        lines.append(f"  class {','.join(unreachable)} unreachable")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, analyze the program, and print the documentation."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("program", type=Path, help="COBOL program source file.")
    parser.add_argument(
        "--copylib",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="Directory searched, in order, for COPY members. Repeatable. The program's "
        "own directory is searched last.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["markdown", "json", "mermaid"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--codepage", default="037", help="EBCDIC code page for EBCDIC members (default: 037)."
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=DEFAULT_MAX_NODES,
        help=f"Most procedures drawn in the Mermaid flowchart (default: {DEFAULT_MAX_NODES}).",
    )
    args = parser.parse_args(argv)
    if args.max_nodes < 1:
        print("error: --max-nodes must be at least 1", file=sys.stderr)
        return 1
    if not args.program.is_file():
        print(f"error: not found: {args.program}", file=sys.stderr)
        return 1
    try:
        result = analyze_program(args.program, copylibs=args.copylib, codepage=args.codepage)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    elif args.output_format == "mermaid":
        print(to_mermaid(result, args.max_nodes))
    else:
        print(to_markdown(result, max_nodes=args.max_nodes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
