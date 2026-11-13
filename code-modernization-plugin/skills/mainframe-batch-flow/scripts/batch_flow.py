#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Trace z/OS batch flow: expand JCL, follow data sets between jobs, and check schedules.

Reads JCL jobs, cataloged and in-stream procedures, INCLUDE members, and control-card members
exported to local directories, and expands each job the way the JCL converter does: SET
statements, PROC defaults, EXEC overrides, and system symbols given with --set; nested
procedures with PARM, COND, and DD overrides; INCLUDE members; IF/THEN/ELSE and COND
conditions. For each step it reports the program that runs (including programs behind
IKJEFT01, DFSRRC00, and BPXBATCH), the DD statements with backward references resolved, and
what IDCAMS, DFSORT, ICETOOL, IEBGENER, IEBCOPY, FTP, and Connect:Direct steps do according to
their control statements. It then builds data set lineage across jobs (producers, consumers,
external inputs, final outputs, and job dependencies implied by data) and compares those
dependencies with Control-M XML, IBM Z Workload Scheduler batch-loader, or CSV schedule
exports.

The analysis is static. The script only reads files and writes to standard output.

Examples:
    uv run --script batch_flow.py jcl/ --proclib proclib/ --format markdown
    uv run --script batch_flow.py jcl/ --schedule ctm.xml --set SYSUID=BATCH > flow.json
    uv run --script batch_flow.py jcl/ --format mermaid --job PAYD010
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Container, Iterable, Iterator, Mapping, Sequence

DEFAULT_MAX_BYTES = 5_000_000
MAX_NESTING = 15
MAX_MERMAID_NODES = 300
JCL_SUFFIXES = frozenset({"", ".jcl", ".job", ".prc", ".proc", ".cntl", ".txt"})
KNOWN_OPERATIONS = frozenset(
    {"JOB", "EXEC", "DD", "PROC", "PEND", "SET", "INCLUDE", "JCLLIB", "IF", "ELSE", "ENDIF"}
    | {"OUTPUT", "CNTL", "ENDCNTL", "XMIT", "COMMAND", "EXPORT", "SCHEDULE", "NOTIFY"}
    | {"JOBGROUP", "ENDGROUP", "GJOB", "JOBSET", "SJOB", "ENDSET", "AFTER", "BEFORE", "CONCURRENT"}
)
NO_OPERANDS = frozenset({"ELSE", "ENDIF", "PEND", "CNTL", "ENDCNTL"})
PROC_KINDS = frozenset({"proc", "include"})
EXEC_KEYWORDS = frozenset(
    {"PGM", "PROC", "PARM", "PARMDD", "COND", "REGION", "REGIONX", "TIME", "ACCT", "ADDRSPC"}
    | {"DPRTY", "DYNAMNBR", "PERFORM", "RD", "CCSID", "MEMLIMIT"}
)
KEYWORD_ALIASES = {"DSNAME": "DSN"}
DATASET_KEYS = frozenset(
    {"DSN", "DISP", "UNIT", "VOL", "SPACE", "LABEL", "LIKE", "REFDD", "DATACLAS", "STORCLAS"}
    | {"MGMTCLAS", "DSNTYPE", "RECORG", "AVGREC", "RETPD", "EXPDT"}
)
PATH_KEYS = frozenset({"PATH", "PATHOPTS", "PATHMODE", "PATHDISP", "FILEDATA"})
DD_ATTRIBUTES = (
    *("SPACE", "UNIT", "LIKE", "REFDD", "DATACLAS", "STORCLAS", "MGMTCLAS"),
    *("DEST", "OUTPUT"),
)
DCB_KEYWORDS = ("RECFM", "LRECL", "BLKSIZE", "DSORG")
LIBRARY_DDS = frozenset({"JOBLIB", "STEPLIB", "JOBCAT", "STEPCAT", "SYSPROC", "SYSEXEC"})
MESSAGE_DDS = frozenset(
    {"SYSPRINT", "SYSOUT", "SYSUDUMP", "SYSABEND", "SYSMDUMP", "CEEDUMP", "SYSTSPRT", "SYSDBOUT"}
    | {"SYSABOUT", "SYSERR", "SYSLIST", "TOOLMSG", "DFSMSG", "OUTPUT", "STDOUT", "STDERR"}
)
PATH_WRITE_OPTIONS = frozenset({"OWRONLY", "ORDWR", "OCREAT", "OAPPEND", "OTRUNC"})
PATH_READ_OPTIONS = frozenset({"ORDONLY", "ORDWR"})
UTILITY_KINDS = {
    **dict.fromkeys(("SORT", "ICEMAN", "SYNCSORT", "ICETOOL", "SYNCTOOL"), "sort"),
    **dict.fromkeys(("IEBGENER", "ICEGENER"), "copy"),
    **dict.fromkeys(("IKJEFT01", "IKJEFT1A", "IKJEFT1B"), "tso-batch"),
    **dict.fromkeys(("BPXBATCH", "BPXBATSL"), "unix-shell"),
    **dict.fromkeys(("DSNTEP2", "DSNTEP4"), "db2-sql"),
    "IDCAMS": "idcams",
    "IEBCOPY": "pds-copy",
    "IEFBR14": "allocate",
    "DFSRRC00": "ims-region",
    "FTP": "ftp",
    "DMBATCH": "connect-direct",
    "ADRDSSU": "dump-restore",
    "DSNUTILB": "db2-utility",
    "DSNTIAUL": "db2-unload",
    "EZTPA00": "easytrieve",
}
# In-stream data of file-transfer steps often holds user IDs and passwords, so it is not echoed.
TRANSFER_KINDS = frozenset({"ftp", "connect-direct"})
SORT_VERBS = frozenset(
    {"SORT", "MERGE", "INCLUDE", "OMIT", "INREC", "OUTREC", "OUTFIL", "SUM", "JOINKEYS", "JOIN"}
    | {"REFORMAT", "OPTION", "RECORD", "ALTSEQ", "MODS", "DEBUG", "END"}
)
SORT_LOGIC = frozenset({"INCLUDE", "OMIT", "INREC", "OUTREC", "OUTFIL", "SUM", "JOINKEYS"})
SORT_LOGIC_FLAG = "business logic in sort control cards"
ICETOOL_OPERATORS = frozenset(
    {"COPY", "COUNT", "DATASORT", "DEFAULTS", "DISPLAY", "MODE", "OCCUR", "RANGE", "RESIZE"}
    | {"SELECT", "SORT", "SPLICE", "STATS", "SUBSET", "UNIQUE", "VERIFY"}
)
IEBCOPY_COPY = frozenset({"COPY", "C", "COPYMOD", "CM", "COPYGRP", "CG"})
IEBCOPY_VERBS = IEBCOPY_COPY | {"SELECT", "S", "EXCLUDE", "E", "ALTERMOD"}
IEBGENER_VERBS = frozenset({"GENERATE", "RECORD", "MEMBER", "LABELS", "EXITS"})
IDCAMS_VERBS = {"DEF": "DEFINE", "DEL": "DELETE", "LISTC": "LISTCAT"}
IDCAMS_OBJECTS = {"CL": "CLUSTER", "NVSAM": "NONVSAM", "UCAT": "USERCATALOG"}
IDCAMS_DATA_OBJECTS = frozenset({"CLUSTER", "GDG", "AIX", "PATH", "NONVSAM"})
FTP_DIRECTIONS = {
    **dict.fromkeys(("PUT", "MPUT", "APPEND"), "outbound"),
    **dict.fromkeys(("GET", "MGET"), "inbound"),
}
# COND tests read "code operator RC"; the symbol states the same test with RC first.
COND_OPERATORS = {
    "GT": ("greater than", "<"),
    "GE": ("greater than or equal to", "<="),
    "EQ": ("equal to", "="),
    "LT": ("less than", ">"),
    "LE": ("less than or equal to", ">="),
    "NE": ("not equal to", "!="),
}
UNRECOGNIZED_COND = "Unrecognized COND value; check it by hand."
CONTROLM_CONTAINERS = frozenset(
    {"DEFTABLE", "FOLDER", "SMART_FOLDER", "SUB_FOLDER", "SCHED_TABLE", "TABLE", "SMART_TABLE"}
)
CONTROLM_ATTRIBUTES = (
    *("JOBNAME", "MEMNAME", "MEMLIB", "APPLICATION", "SUB_APPLICATION", "NODEID", "TASKTYPE"),
    *("DAYS", "WEEKDAYS", "TIMEFROM", "CYCLIC"),
)
CONTROLM_ADD_SIGNS = frozenset({"+", "ADD", ""})
TEMPORARY_BUCKETS = {"write": "written_by", "read": "read_by", "delete": "deleted_by"}

SYMBOL = re.compile(r"&&|&([A-Z@#$][A-Z0-9@#$_]*)\.?", re.IGNORECASE)
KEYWORD = re.compile(r"([A-Z0-9@#$]+(?:\.[A-Z0-9@#$]+)?)=(.*)", re.IGNORECASE | re.DOTALL)
THEN = re.compile(r"(?<![A-Z0-9@#$.])THEN(?![A-Z0-9@#$])", re.IGNORECASE)
RELATIVE_GENERATION = re.compile(r"(.+)\(([+-]?\d+)\)")
MEMBER_NAME = re.compile(r"(.+)\(([^()]+)\)")
ABSOLUTE_GENERATION = re.compile(r"(.+)\.(G\d{4}V\d{2})")
IDCAMS_PREFIX = re.compile(r"(?:IF\s.*?\sTHEN|ELSE|DO|END)(?![A-Z0-9@#$.])\s*", re.IGNORECASE)
SET_ARGUMENT = re.compile(r"&?([A-Z@#$][A-Z0-9@#$_]*)=(.*)", re.IGNORECASE | re.DOTALL)
IWS_PARAMETER = re.compile(r"([A-Z][A-Z0-9]*)\s*\(", re.IGNORECASE)
XML_DECLARATION = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>")


class FlowError(Exception):
    """An input problem the user can fix, such as a missing path or an unreadable export."""


# Operand parsing -------------------------------------------------------------------------


def _split_top(text: str, separator: str = ",") -> list[str]:
    """Split ``text`` at separators that are outside apostrophes and parentheses."""
    items: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == separator and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    return items


def _enclosed(value: str) -> bool:
    """Return True when one pair of parentheses encloses all of ``value``."""
    if len(value) < 2 or value[0] != "(" or value[-1] != ")":
        return False
    depth = 0
    quoted = False
    for index, char in enumerate(value):
        if char == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index < len(value) - 1:
                return False
    return True


def _split_list(value: str) -> list[str]:
    """Split a parameter value such as ``(NEW,CATLG,DELETE)`` into its subparameters."""
    value = value.strip()
    if _enclosed(value):
        value = value[1:-1].strip()
    return [item.strip() for item in _split_top(value)] if value else []


def _unquote(value: str) -> str:
    """Remove enclosing apostrophes and undouble the apostrophes inside them."""
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


@dataclass
class _Params:
    positional: list[str] = field(default_factory=list)
    keywords: dict[str, str] = field(default_factory=dict)


def _parse_params(text: str) -> _Params:
    """Parse operands into positional and keyword parameters, respecting nesting."""
    params = _Params()
    if not text.strip():
        return params
    for item in _split_top(text):
        match = KEYWORD.fullmatch(item.strip())
        if match is None:
            params.positional.append(item.strip())
        else:
            key = match.group(1).upper()
            params.keywords[KEYWORD_ALIASES.get(key, key)] = match.group(2).strip()
    return params


# JCL statements ----------------------------------------------------------------------------


@dataclass
class Statement:
    """One logical JCL statement, with continuations joined and comments removed.

    ``instream`` holds the in-stream data lines of a ``DD *`` or ``DD DATA`` statement.
    """

    name: str
    operation: str
    operands: str
    line: int
    instream: list[str] | None = None


def _scan(text: str, *, quoted: bool) -> tuple[str, bool]:
    """Return the operand part of ``text`` and whether it ends inside an apostrophe string."""
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return text[:index], False
    return text, quoted


class _JclParser:
    """Line-by-line state machine behind :func:`parse_jcl`."""

    def __init__(self) -> None:
        self.statements: list[Statement] = []
        self.warnings: list[str] = []
        self._pending: Statement | None = None
        self._quoted = False
        self._data: list[str] | None = None
        self._delimiter = "/*"
        self._jcl_ends_data = True
        self._in_cntl = False

    def feed(self, number: int, raw: str) -> None:
        """Process one line."""
        if self._data is not None and self._take_data(self._data, raw):
            return
        pending = self._pending
        if pending is not None:
            if raw.startswith("//*") or self._continue(pending, raw):
                return
            self._abandon(pending)
            if self._data is not None and self._take_data(self._data, raw):
                return
        if raw.startswith("//*"):
            return
        if raw.startswith("//"):
            self._start(number, raw)
        else:
            self._loose(number, raw)

    def close(self) -> None:
        """Finish the member, closing a statement that still expects a continuation."""
        if self._pending is not None:
            self._abandon(self._pending)

    def _take_data(self, data: list[str], raw: str) -> bool:
        """Consume an in-stream data line; return False when ``raw`` is JCL that ends the data."""
        if raw.startswith(self._delimiter):
            self._data = None
            return True
        if self._jcl_ends_data and raw.startswith("//"):
            self._data = None
            return False
        data.append(raw[:80].rstrip())
        return True

    def _continue(self, pending: Statement, raw: str) -> bool:
        """Append ``raw`` to the pending statement when it is a continuation line."""
        padded = raw[:71].ljust(71)
        if self._quoted:
            # An apostrophe string that reaches column 71 resumes in column 16.
            if not raw.startswith("//") or padded[2:15].strip():
                return False
            text, self._quoted = _scan(padded[15:], quoted=True)
            pending.operands += text
        else:
            body = padded[2:].strip()
            if not raw.startswith("//") or padded[2] != " " or not body:
                return False
            if pending.operation == "IF":
                then = THEN.search(body)
                expression = body[: then.start()] if then else body
                pending.operands = " ".join(f"{pending.operands} {expression}".split())
                if then is not None:
                    self._pending = None
                return True
            text, self._quoted = _scan(body, quoted=False)
            pending.operands += text
        if not self._quoted and not pending.operands.endswith(","):
            self._pending = None
            self._complete(pending)
        return True

    def _abandon(self, pending: Statement) -> None:
        """Close a statement whose expected continuation never came."""
        self._pending = None
        if pending.operation == "IF":
            self.warnings.append(f"line {pending.line}: IF statement has no THEN")
            return
        problem = (
            "apostrophe string is not closed"
            if self._quoted
            else "statement ends with a comma but is not continued"
        )
        self.warnings.append(f"line {pending.line}: {problem}")
        self._quoted = False
        pending.operands = pending.operands.rstrip(", ")
        self._complete(pending)

    def _complete(self, statement: Statement) -> None:
        """Start collecting in-stream data after a complete ``DD *`` or ``DD DATA``."""
        if statement.operation != "DD":
            return
        params = _parse_params(statement.operands)
        kind = params.positional[0].upper() if params.positional else ""
        if kind not in {"*", "DATA"}:
            return
        delimiter = _unquote(params.keywords.get("DLM", ""))
        statement.instream = self._data = []
        self._delimiter = delimiter or "/*"
        self._jcl_ends_data = kind == "*" and not delimiter

    def _start(self, number: int, raw: str) -> None:
        """Begin a statement from a line that starts with ``//``."""
        text = raw[:71].ljust(71)[2:]
        if not text.strip():
            self.statements.append(Statement("", "NULL", "", number))
            return
        if text[0] == " ":
            name, rest = "", text
        else:
            name, _, rest = text.partition(" ")
        operation, _, operands = rest.lstrip().partition(" ")
        statement = Statement(name.upper(), operation.upper(), "", number)
        self.statements.append(statement)
        kind = statement.operation
        # Program control statements between CNTL and ENDCNTL are not JCL operations.
        self._in_cntl = kind == "CNTL" or (self._in_cntl and kind != "ENDCNTL")
        if kind not in KNOWN_OPERATIONS:
            if not self._in_cntl:
                self.warnings.append(f"line {number}: unrecognized statement {operation or name!r}")
        elif kind == "IF":
            then = THEN.search(operands)
            statement.operands = " ".join((operands[: then.start()] if then else operands).split())
            if then is None:
                self._pending = statement
        elif statement.operation not in NO_OPERANDS:
            statement.operands, self._quoted = _scan(operands.lstrip(), quoted=False)
            if self._quoted or statement.operands.endswith(","):
                self._pending = statement
            else:
                self._complete(statement)

    def _loose(self, number: int, raw: str) -> None:
        """Handle a line outside statements: a delimiter, a blank, or data without DD *."""
        if raw.startswith("/*") or not raw.strip():
            return
        if self.statements and self.statements[-1].operation in {"EXEC", "DD"}:
            statement = Statement("SYSIN", "DD", "*", number)
            statement.instream = self._data = [raw[:80].rstrip()]
            self._delimiter, self._jcl_ends_data = "/*", True
            self.statements.append(statement)
            self.warnings.append(f"line {number}: data without a DD statement read as //SYSIN DD *")


def parse_jcl(text: str) -> tuple[list[Statement], list[str]]:
    """Split JCL text into logical statements.

    Handles comment statements, columns 72-80, continued operands (including apostrophe
    strings continued in column 16 and IF statements continued until THEN), comments after
    the operand field, in-stream data for ``DD *`` and ``DD DATA`` with ``DLM=``, the ``/*``
    delimiter, and the null statement. Returns the statements and line-numbered warnings.
    """
    parser = _JclParser()
    for number, raw in enumerate(text.splitlines(), start=1):
        parser.feed(number, raw)
    parser.close()
    return parser.statements, parser.warnings


# Members and libraries ------------------------------------------------------------------------


@dataclass
class _Member:
    name: str
    path: Path
    kind: str  # job, proc, include, or control (text without JCL statements)
    statements: list[Statement]
    lines: list[str]
    encoding: str
    warnings: list[str]


def _walk(root: Path) -> Iterator[Path]:
    """Yield ``root`` if it is a file, else candidate members below it, skipping hidden paths."""
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        hidden = any(part.startswith(".") for part in path.relative_to(root).parts)
        if path.is_file() and not hidden and path.suffix.lower() in JCL_SUFFIXES:
            yield path


def _load_members(
    roots: Iterable[Path], codepage: str, max_bytes: int, warnings: list[str]
) -> list[_Member]:
    """Decode and classify every member under ``roots`` by its content."""
    members: list[_Member] = []
    for root in roots:
        for path in _walk(root):
            if path.stat().st_size > max_bytes:
                warnings.append(f"{path}: skipped, larger than {max_bytes} bytes")
                continue
            decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
            if decoded is None:
                continue
            statements, problems = parse_jcl(decoded.text)
            operations = [s.operation for s in statements if s.operation != "NULL"]
            if "JOB" in operations:
                kind = "job"
            elif operations and operations[0] == "PROC":
                kind = "proc"
            else:
                kind = "include" if operations else "control"
            notes = [f"{path}: {problem}" for problem in problems] if operations else []
            lines = decoded.text.splitlines()
            members.append(
                _Member(path.stem.upper(), path, kind, statements, lines, decoded.encoding, notes)
            )
    return members


class _Library:
    """Members searched by name: --proclib directories in order, then the roots."""

    def __init__(self, layers: Sequence[Sequence[_Member]]) -> None:
        self._layers: list[dict[str, list[_Member]]] = []
        for members in layers:
            layer: dict[str, list[_Member]] = {}
            for member in members:
                layer.setdefault(member.name, []).append(member)
            self._layers.append(layer)

    def find(self, name: str, kinds: Container[str]) -> _Member | None:
        """Return the first member called ``name`` whose kind is in ``kinds``."""
        for layer in self._layers:
            for member in layer.get(name, []):
                if member.kind in kinds:
                    return member
        return None


def _split_jobs(
    member: _Member, warnings: list[str]
) -> list[tuple[Statement, list[Statement], dict[str, list[Statement]]]]:
    """Split a member into jobs, each with its statements and its in-stream procedures."""
    jobs: list[tuple[Statement, list[Statement], dict[str, list[Statement]]]] = []
    body: list[Statement] | None = None
    procs: dict[str, list[Statement]] = {}
    proc: list[Statement] | None = None
    for statement in member.statements:
        operation = statement.operation
        if operation == "JOB":
            if proc is not None:
                warnings.append(f"{member.path}: in-stream procedure {proc[0].name} has no PEND")
            body, procs, proc = [], {}, None
            jobs.append((statement, body, procs))
        elif body is None:
            continue
        elif proc is not None:
            if operation == "PEND":
                proc = None
            else:
                proc.append(statement)
        elif operation == "PROC":
            proc = procs[statement.name] = [statement]
        elif operation == "NULL":
            body = None
        else:
            body.append(statement)
    if proc is not None:
        warnings.append(f"{member.path}: in-stream procedure {proc[0].name} has no PEND")
    return jobs


# Expansion --------------------------------------------------------------------------------


@dataclass
class _DDEntry:
    params: _Params
    instream: list[str] | None
    line: int
    status: str = ""


@dataclass
class _DDGroup:
    name: str
    entries: list[_DDEntry]


@dataclass
class _Overrides:
    """PARM, COND, and DD overrides coded on the EXEC statement that calls a procedure."""

    parm: str | None = None
    parm_steps: dict[str, str] = field(default_factory=dict)
    cond: str | None = None
    cond_steps: dict[str, str] = field(default_factory=dict)
    dds: list[tuple[str | None, _DDGroup]] = field(default_factory=list)
    used: set[str] = field(default_factory=set)

    def labels(self) -> list[str]:
        """Return a label for every step-specific override, as recorded in ``used``."""
        labels = [f"PARM.{step}" for step in self.parm_steps]
        labels += [f"COND.{step}" for step in self.cond_steps]
        labels += [f"{target}.{group.name}" if target else group.name for target, group in self.dds]
        return labels


@dataclass
class _Step:
    path: tuple[str, ...]
    procstep: str | None
    proc: str | None
    program: str | None
    cond: str | None
    if_context: list[str]
    groups: list[_DDGroup]
    parm: str | None = None
    flags: list[str] = field(default_factory=list)
    dds: list[dict[str, Any]] = field(default_factory=list)
    entries: list[_DDEntry] = field(default_factory=list)
    utility: str | None = None
    runs: list[str] = field(default_factory=list)
    control: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Return the dotted step name, such as ``JOBSTEP.PROCSTEP``."""
        return ".".join(self.path)


@dataclass
class _Job:
    name: str
    member: _Member
    statement: Statement
    instream_procs: dict[str, list[Statement]]
    keywords: dict[str, str] = field(default_factory=dict)
    steps: list[_Step] = field(default_factory=list)
    symbols: dict[str, set[str]] = field(default_factory=dict)
    unresolved_symbols: set[str] = field(default_factory=set)
    jcllib: list[str] = field(default_factory=list)
    procs: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    dds: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    temporary: dict[str, dict[str, list[str]]] = field(default_factory=dict)


@dataclass
class _Scope:
    job: _Job
    path: tuple[str, ...]
    symbols: dict[str, str]
    if_stack: list[str]
    if_base: int = 0
    procs: tuple[str, ...] = ()
    proc: str | None = None
    overrides: _Overrides | None = None
    steps: int = 0


@dataclass
class _Effects:
    """What a utility step does, read from its control statements."""

    inputs: set[str] = field(default_factory=set)
    outputs: set[str] = field(default_factory=set)
    datasets: list[tuple[str, str, str]] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    control: dict[str, Any] = field(default_factory=dict)
    transfers: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


class _Pushback:
    """Statement iterator that can take back one statement it has already returned."""

    def __init__(self, iterator: Iterator[Statement]) -> None:
        self._iterator = iterator
        self._buffer: list[Statement] = []

    def __iter__(self) -> _Pushback:
        """Return the iterator itself."""
        return self

    def __next__(self) -> Statement:
        """Return the next statement."""
        if self._buffer:
            return self._buffer.pop()
        return next(self._iterator)

    def push(self, statement: Statement) -> None:
        """Return ``statement`` to the stream so that it is read next."""
        self._buffer.append(statement)


class _Analyzer:
    """Expands jobs and records their steps, data set accesses, transfers, and reports."""

    def __init__(self, library: _Library, system: Mapping[str, str]) -> None:
        self.library = library
        self.system = dict(system)
        self.warnings: list[str] = []
        self.unresolved: dict[str, set[str]] = {"procs": set(), "includes": set(), "symbols": set()}
        self.accesses: dict[str, list[dict[str, Any]]] = {}
        self.transfers: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []
        self._reported: set[Path] = set()

    def report(self, member: _Member) -> None:
        """Add a member's parse warnings the first time the member is used."""
        if member.path not in self._reported:
            self._reported.add(member.path)
            self.warnings.extend(member.warnings)

    def run_job(self, job: _Job, statements: list[Statement]) -> None:
        """Expand one job and analyze its steps."""
        scope = _Scope(job, (), {}, [])
        job.keywords = _parse_params(self._subst(job.statement.operands, scope)).keywords
        self._run(statements, scope)
        if scope.if_stack:
            self._warn(job, (), "IF statement without ENDIF")

    def _warn(self, job: _Job, path: tuple[str, ...], message: str) -> None:
        where = f"{job.name} {'.'.join(path)}" if path else job.name
        self.warnings.append(f"{where}: {message}")

    def _subst(self, text: str, scope: _Scope) -> str:
        """Replace symbols in ``text``; ``&&`` names and unknown symbols stay as written."""
        job = scope.job

        def substitute(match: re.Match[str]) -> str:
            if match.group(1) is None:
                return match.group(0)
            name = match.group(1).upper()
            value = self.system.get(name)
            if value is None:
                value = scope.symbols.get(name)
            values = job.symbols.setdefault(name, set())
            if value is None:
                job.unresolved_symbols.add(name)
                self.unresolved["symbols"].add(name)
                return match.group(0)
            values.add(value)
            return value

        return SYMBOL.sub(substitute, text)

    def _flatten(
        self, statements: list[Statement], scope: _Scope, chain: tuple[str, ...]
    ) -> Iterator[Statement]:
        """Yield statements with INCLUDE members expanded in place."""
        for statement in statements:
            if statement.operation != "INCLUDE":
                yield statement
                continue
            params = _parse_params(self._subst(statement.operands, scope))
            name = _unquote(params.keywords.get("MEMBER", "")).upper()
            member = self.library.find(name, {"include"})
            if not name:
                self._warn(scope.job, scope.path, "INCLUDE statement names no member")
            elif name in chain:
                self._warn(scope.job, scope.path, f"INCLUDE member {name} includes itself")
            elif len(chain) >= MAX_NESTING:
                self._warn(scope.job, scope.path, f"INCLUDE members nest deeper than {MAX_NESTING}")
            elif member is None:
                self.unresolved["includes"].add(name)
                self._warn(scope.job, scope.path, f"INCLUDE member {name} not found")
            else:
                self.report(member)
                if name not in scope.job.includes:
                    scope.job.includes.append(name)
                yield from self._flatten(member.statements, scope, (*chain, name))

    def _run(self, statements: list[Statement], scope: _Scope) -> None:
        """Process statements in order, expanding INCLUDE members and procedures."""
        stream = _Pushback(self._flatten(statements, scope, ()))
        in_cntl = False
        for statement in stream:
            operation = statement.operation
            if in_cntl or operation == "CNTL":
                in_cntl = operation != "ENDCNTL"
            elif operation == "EXEC":
                dds: list[Statement] = []
                for extra in stream:
                    if in_cntl or extra.operation == "CNTL":
                        in_cntl = extra.operation != "ENDCNTL"
                    elif extra.operation == "DD":
                        dds.append(extra)
                    elif extra.operation == "OUTPUT":
                        self._output(extra, scope)
                    else:
                        stream.push(extra)
                        break
                self._exec(statement, dds, scope)
            elif operation == "DD":
                self._loose_dd(statement, scope)
            elif operation == "SET":
                params = _parse_params(self._subst(statement.operands, scope))
                for key, value in params.keywords.items():
                    scope.symbols[key] = _unquote(value)
            elif operation == "IF":
                scope.if_stack.append(f"IF {self._subst(statement.operands, scope)} THEN")
            elif operation == "ELSE":
                if len(scope.if_stack) > scope.if_base and scope.if_stack[-1].endswith(" THEN"):
                    scope.if_stack[-1] = scope.if_stack[-1][: -len("THEN")] + "ELSE"
                else:
                    self._warn(scope.job, scope.path, f"ELSE at line {statement.line} has no IF")
            elif operation == "ENDIF":
                if len(scope.if_stack) > scope.if_base:
                    scope.if_stack.pop()
                else:
                    self._warn(scope.job, scope.path, f"ENDIF at line {statement.line} has no IF")
            elif operation == "JCLLIB":
                params = _parse_params(self._subst(statement.operands, scope))
                order = _split_list(params.keywords.get("ORDER", ""))
                scope.job.jcllib.extend(_unquote(name).upper() for name in order)
            elif operation == "OUTPUT":
                self._output(statement, scope)

    def _output(self, statement: Statement, scope: _Scope) -> None:
        """Record an OUTPUT statement, which SYSOUT DDs can refer to."""
        keywords = _parse_params(self._subst(statement.operands, scope)).keywords
        scope.job.outputs[statement.name] = {
            key: _unquote(value) for key, value in keywords.items()
        }

    def _loose_dd(self, statement: Statement, scope: _Scope) -> None:
        """Record a job-level DD statement such as JOBLIB, or warn about a misplaced DD."""
        job = scope.job
        if scope.path or job.steps:
            self._warn(job, scope.path, f"DD at line {statement.line} does not follow an EXEC")
            return
        params = _parse_params(self._subst(statement.operands, scope))
        job.dds.append(self._dd_detail(job, None, statement.name, _DDEntry(params, None, 0)))

    def _exec(self, statement: Statement, dd_statements: list[Statement], scope: _Scope) -> None:
        """Analyze an EXEC statement and its DD statements."""
        params = _parse_params(self._subst(statement.operands, scope))
        scope.steps += 1
        name = statement.name or f"#{scope.steps}"
        program = params.keywords.get("PGM")
        proc = params.keywords.get("PROC") or (params.positional[0] if params.positional else "")
        step = _Step(
            path=(*scope.path, name),
            procstep=name if scope.proc else None,
            proc=scope.proc,
            program=_unquote(program).upper() if program else None,
            cond=params.keywords.get("COND"),
            if_context=list(scope.if_stack),
            groups=self._dd_groups(dd_statements, scope),
        )
        if program:
            self._program_step(step, params, scope)
        elif proc:
            self._proc_step(step, _unquote(proc).upper(), params, scope)
        else:
            self._warn(scope.job, step.path, "EXEC names no program or procedure")

    def _dd_groups(self, statements: list[Statement], scope: _Scope) -> list[_DDGroup]:
        """Parse DD statements into named groups, each with its concatenated entries."""
        groups: list[_DDGroup] = []
        for statement in statements:
            params = _parse_params(self._subst(statement.operands, scope))
            instream = statement.instream
            if instream is not None and "SYMBOLS" in params.keywords:
                instream = [self._subst(line, scope) for line in instream]
            entry = _DDEntry(params, instream, statement.line)
            if statement.name:
                groups.append(_DDGroup(statement.name, [entry]))
            elif groups:
                groups[-1].entries.append(entry)
            else:
                self._warn(
                    scope.job, scope.path, f"unnamed DD at line {statement.line} follows no DD"
                )
        return groups

    def _program_step(self, step: _Step, params: _Params, scope: _Scope) -> None:
        """Apply the caller's overrides to a program step, then analyze it."""
        name = step.path[-1]
        parm = params.keywords.get("PARM")
        overrides = scope.overrides
        if overrides is not None:
            first = scope.steps == 1
            if name in overrides.parm_steps:
                parm = overrides.parm_steps[name]
                overrides.used.add(f"PARM.{name}")
            elif overrides.parm is not None:
                # PARM on the calling EXEC replaces the first step's PARM and nullifies the rest.
                parm = overrides.parm if first else None
            if name in overrides.cond_steps:
                step.cond = overrides.cond_steps[name]
                overrides.used.add(f"COND.{name}")
            elif overrides.cond is not None:
                step.cond = overrides.cond
            self._apply_dd_overrides(step, overrides, first=first)
        step.parm = _parm_value(parm)
        self._analyze(step, scope)

    def _apply_dd_overrides(self, step: _Step, overrides: _Overrides, *, first: bool) -> None:
        """Merge ``//PROCSTEP.DD`` overrides into the step's DDs and add new DD names."""
        name = step.path[-1]
        for target, override in overrides.dds:
            if target != name and (target is not None or not first):
                continue
            overrides.used.add(f"{target}.{override.name}" if target else override.name)
            group = next((group for group in step.groups if group.name == override.name), None)
            if group is None:
                entries = [replace(entry, status="added") for entry in override.entries]
                step.groups.append(_DDGroup(override.name, entries))
                continue
            for index, entry in enumerate(override.entries):
                if index >= len(group.entries):
                    group.entries.append(replace(entry, status="added"))
                elif entry.params.positional or entry.params.keywords or entry.instream is not None:
                    group.entries[index] = _merge_dd(group.entries[index], entry)

    def _proc_step(self, step: _Step, proc: str, params: _Params, scope: _Scope) -> None:
        """Expand a procedure call with its symbol values and overrides."""
        job = scope.job
        body = job.instream_procs.get(proc)
        if body is None:
            member = self.library.find(proc, PROC_KINDS)
            if member is not None:
                self.report(member)
                body = member.statements
        if proc in scope.procs:
            problem = f"procedure {proc} calls itself"
        elif len(scope.procs) >= MAX_NESTING:
            problem = f"procedure {proc} is nested more than {MAX_NESTING} levels deep"
        elif body is None:
            problem = f"procedure {proc} not found"
            self.unresolved["procs"].add(proc)
        else:
            problem = ""
        if problem or body is None:
            self._warn(job, step.path, problem)
            step.proc = proc
            step.flags.append(problem)
            self._analyze(step, scope)
            return
        if proc not in job.procs:
            job.procs.append(proc)
        header = body[0] if body[0].operation == "PROC" else None
        statements = [s for s in body[1 if header else 0 :] if s.operation != "PEND"]
        symbols = dict(scope.symbols)
        if header is not None:
            for key, value in _parse_params(self._subst(header.operands, scope)).keywords.items():
                symbols[key] = _unquote(value)
        overrides = _Overrides()
        for key, value in params.keywords.items():
            base, _, target = key.partition(".")
            if base == "PARM" and target:
                overrides.parm_steps[target] = value
            elif base == "PARM":
                overrides.parm = value
            elif base == "COND" and target:
                overrides.cond_steps[target] = value
            elif base == "COND":
                overrides.cond = value
            elif base not in EXEC_KEYWORDS and not target:
                symbols[key] = _unquote(value)
        for group in step.groups:
            target, _, ddname = group.name.rpartition(".")
            overrides.dds.append((target or None, replace(group, name=ddname)))
        child = _Scope(
            job=job,
            path=step.path,
            symbols=symbols,
            if_stack=list(scope.if_stack),
            if_base=len(scope.if_stack),
            procs=(*scope.procs, proc),
            proc=proc,
            overrides=overrides,
        )
        self._run(statements, child)
        if len(child.if_stack) > child.if_base:
            self._warn(job, step.path, f"procedure {proc} leaves an IF without ENDIF")
        for label in overrides.labels():
            if label not in overrides.used:
                self._warn(job, step.path, f"override {label} matches no step in {proc}")

    def _analyze(self, step: _Step, scope: _Scope) -> None:
        """Describe a step's DDs, read its utility control statements, and record lineage."""
        job = scope.job
        for group in step.groups:
            for index, entry in enumerate(group.entries):
                detail = self._dd_detail(job, step, group.name, entry)
                detail["concat"] = index
                step.dds.append(detail)
                step.entries.append(entry)
        effects = self._utility(step)
        step.runs = effects.runs
        step.control = effects.control
        step.flags.extend(effects.flags)
        self._lineage(job, step, effects)
        self.transfers.extend(
            {"job": job.name, "step": step.name, **transfer} for transfer in effects.transfers
        )
        self._reports(job, step)
        job.steps.append(step)

    def _dd_detail(
        self, job: _Job, step: _Step | None, ddname: str, entry: _DDEntry
    ) -> dict[str, Any]:
        """Describe one DD statement."""
        keywords = entry.params.keywords
        positional = [item.upper() for item in entry.params.positional]
        detail: dict[str, Any] = {"ddname": ddname, "concat": 0}
        if entry.status:
            detail["override"] = entry.status
        dsn = _unquote(keywords.get("DSN", "")).upper()
        if positional[:1] == ["DUMMY"] or dsn == "NULLFILE":
            detail["dummy"] = True
        if positional[:1] in (["*"], ["DATA"]):
            detail["instream_lines"] = len(entry.instream or [])
        if dsn:
            if dsn.startswith("*."):
                detail["backref"] = dsn
                resolved = self._backref(job, step, dsn) if step is not None else None
                if resolved is None:
                    self._warn(job, step.path if step else (), f"{dsn} does not resolve")
                dsn = resolved or dsn
            detail["dsn"] = dsn
            detail.update(_dataset_parts(dsn))
        if "DISP" in keywords or ("dsn" in detail and not detail.get("dummy")):
            detail["disp"] = _disp(keywords.get("DISP"))
        dcb = _dcb(keywords)
        if dcb:
            detail["dcb"] = dcb
        for key in DD_ATTRIBUTES:
            if key in keywords:
                detail[key.lower()] = _unquote(keywords[key])
        if "SYSOUT" in keywords:
            detail["sysout"] = _sysout(keywords["SYSOUT"])
        if "PATH" in keywords:
            detail["path"] = _unquote(keywords["PATH"])
            detail["pathopts"] = [o.upper() for o in _split_list(keywords.get("PATHOPTS", ""))]
        if ddname in LIBRARY_DDS:
            detail["library"] = True
        return detail

    def _backref(self, job: _Job, step: _Step, reference: str) -> str | None:
        """Return the data set that ``*.DD``, ``*.STEP.DD``, or ``*.STEP.PROCSTEP.DD`` names."""
        *names, ddname = reference[2:].split(".")
        candidates = [step]
        if names:
            wanted = tuple(names)
            candidates = (
                [s for s in job.steps if s.path == (*step.path[:-1], *wanted)]
                or [s for s in job.steps if s.path == wanted]
                or [s for s in job.steps if s.path[-len(wanted) :] == wanted]
            )
        for candidate in reversed(candidates):
            for detail in candidate.dds:
                if detail["ddname"] == ddname and detail["concat"] == 0:
                    return detail.get("dsn")
        return None

    def _control_lines(self, step: _Step, *ddnames: str) -> list[str]:
        """Return the control statements of the named DDs: in-stream data or scanned members."""
        lines: list[str] = []
        for detail, entry in zip(step.dds, step.entries, strict=True):
            if detail["ddname"] not in ddnames or detail.get("dummy"):
                continue
            if entry.instream is not None:
                lines.extend(entry.instream)
                continue
            member = (
                self.library.find(detail["member"], {"control"}) if "member" in detail else None
            )
            if member is not None:
                detail["control_member"] = str(member.path)
                lines.extend(member.lines)
            else:
                source = detail.get("dsn") or detail.get("path") or f"DD {detail['ddname']}"
                step.flags.append(f"control statements in {source} were not found")
        return lines

    def _utility(self, step: _Step) -> _Effects:
        """Read what a utility step does from its control statements."""
        effects = _Effects()
        program = step.program or ""
        step.utility = kind = UTILITY_KINDS.get(program)
        if kind == "idcams":
            _idcams(effects, self._control_lines(step, "SYSIN"))
        elif kind == "sort":
            _sort(effects, step, self._control_lines(step, "SYSIN", "DFSPARM", "$ORTPARM"))
            if program in {"ICETOOL", "SYNCTOOL"}:
                self._icetool(effects, step)
        elif kind == "copy":
            effects.inputs.add("SYSUT1")
            effects.outputs.add("SYSUT2")
            statements = _card_statements(self._control_lines(step, "SYSIN"), IEBGENER_VERBS)
            verbs = sorted({verb for verb, _ in statements if verb in IEBGENER_VERBS})
            if verbs:
                effects.control["statements"] = verbs
        elif kind == "pds-copy":
            _iebcopy(effects, self._control_lines(step, "SYSIN"))
        elif kind == "tso-batch":
            _tso(effects, self._control_lines(step, "SYSTSIN"))
        elif kind == "ims-region":
            _ims(effects, step.parm)
        elif kind == "ftp":
            self._ftp(effects, step)
        elif kind == "connect-direct":
            _connect_direct(effects, self._control_lines(step, "SYSIN"))
        elif kind == "unix-shell":
            _bpxbatch(effects, step.parm, self._control_lines(step, "STDPARM"))
        return effects

    def _icetool(self, effects: _Effects, step: _Step) -> None:
        """Read ICETOOL operators in TOOLIN and the DFSORT statements their USING DDs name."""
        operators: set[str] = set()
        lines = [line for line in self._control_lines(step, "TOOLIN") if line[:1] != "*"]
        for command in _commands(lines):
            operator = command.split()[0].upper()
            if operator not in ICETOOL_OPERATORS:
                continue
            operators.add(operator)
            for key, targets in (
                ("FROM", effects.inputs),
                ("TO", effects.outputs),
                ("LIST", effects.outputs),
            ):
                value = _paren_value(command, key)
                if value:
                    targets.update(name.strip() for name in value.split(",") if name.strip())
            using = _paren_value(command, "USING")
            if using:
                _sort(effects, step, self._control_lines(step, f"{using}CNTL"))
        effects.control["operators"] = sorted(operators)

    def _ftp(self, effects: _Effects, step: _Step) -> None:
        """Read z/OS FTP client commands: the host, LCD and CD, and PUT and GET transfers."""
        lines = self._control_lines(step, "INPUT") or self._control_lines(step, "SYSIN")
        commands = [line.strip() for line in lines if line.strip()]
        words = (step.parm or "").split()
        host = words[0] if words and not words[0].startswith("(") else None
        if host is None and commands:
            host = commands.pop(0).split()[0]
        local_prefix = remote_dir = ""
        for command in commands:
            verb, *arguments = command.split()
            verb = verb.upper()
            arguments = [argument for argument in arguments if not argument.startswith("(")]
            if verb == "LCD" and arguments:
                local_prefix = _unquote(arguments[0]).upper().rstrip(".") + "."
            elif verb == "CD" and arguments:
                remote_dir = arguments[0]
            elif verb in FTP_DIRECTIONS and arguments:
                direction = FTP_DIRECTIONS[verb]
                second = arguments[1] if len(arguments) > 1 else None
                local, remote = (
                    (arguments[0], second) if direction == "outbound" else (second, arguments[0])
                )
                if remote and remote_dir and not remote.startswith(("/", "'")):
                    remote = f"{remote_dir.rstrip('/')}/{remote}"
                transfer: dict[str, Any] = {
                    "protocol": "ftp",
                    "command": verb,
                    "direction": direction,
                    "host": host,
                    "local": local,
                    "remote": remote,
                }
                dataset, ddname = _ftp_local(step, local, local_prefix)
                if ddname:
                    (effects.inputs if direction == "outbound" else effects.outputs).add(ddname)
                if dataset:
                    transfer["dataset"] = dataset
                    if ddname is None:
                        action = "read" if direction == "outbound" else "write"
                        effects.datasets.append((dataset, action, f"FTP {verb}"))
                effects.transfers.append(transfer)

    def _lineage(self, job: _Job, step: _Step, effects: _Effects) -> None:
        """Record the reads, writes, and deletes of the step's data sets and files."""
        for detail in step.dds:
            target = detail.get("dsn") or detail.get("path")
            skip = detail.get("dummy") or detail.get("library")
            if not target or target.startswith("*.") or skip:
                continue
            disp = detail.get("disp")
            for action in _actions(step, detail, effects):
                access: dict[str, Any] = {"action": action, "dd": detail["ddname"]}
                if disp:
                    access["disp"] = disp["raw"] or disp["status"]
                self._record(job, step, target, access)
        for dataset, action, via in effects.datasets:
            self._record(job, step, dataset, {"action": action, "via": via})

    def _record(self, job: _Job, step: _Step, name: str, access: dict[str, Any]) -> None:
        """Record one access; temporary data sets stay inside their job."""
        parts = _dataset_parts(name)
        key = parts["dataset"]
        if parts.get("temporary"):
            usage = job.temporary.setdefault(
                key, {bucket: [] for bucket in TEMPORARY_BUCKETS.values()}
            )
            steps = usage[TEMPORARY_BUCKETS[access["action"]]]
            if step.name not in steps:
                steps.append(step.name)
            return
        record = {"job": job.name, "step": step.name, **access}
        record.update({part: parts[part] for part in ("generation", "member") if part in parts})
        self.accesses.setdefault(key, []).append(record)

    def _reports(self, job: _Job, step: _Step) -> None:
        """Record SYSOUT DDs as reports, with class and destination."""
        for detail in step.dds:
            sysout = detail.get("sysout")
            if sysout is None:
                continue
            report: dict[str, Any] = {
                "job": job.name,
                "step": step.name,
                "dd": detail["ddname"],
                **sysout,
            }
            for reference in _split_list(detail.get("output", "")):
                statement = job.outputs.get(reference.rsplit(".", 1)[-1].upper(), {})
                for key in ("CLASS", "DEST", "WRITER"):
                    if key in statement:
                        report.setdefault(key.lower(), statement[key])
            if "dest" in detail:
                report["dest"] = detail["dest"]
            if report.get("class") == "*" and "MSGCLASS" in job.keywords:
                report["msgclass"] = job.keywords["MSGCLASS"]
            report["kind"] = "messages" if detail["ddname"] in MESSAGE_DDS else "report"
            self.reports.append(report)

    def job_dict(self, job: _Job) -> dict[str, Any]:
        """Return the JSON form of an analyzed job."""
        keywords = job.keywords
        return {
            "member": job.member.name,
            "path": str(job.member.path),
            "encoding": job.member.encoding,
            "class": keywords.get("CLASS"),
            "msgclass": keywords.get("MSGCLASS"),
            "parameters": {key: value for key, value in keywords.items() if key != "PASSWORD"},
            "cond": _cond_dict(keywords.get("COND"), job=True),
            "jcllib": job.jcllib,
            "symbols": {name: sorted(values) for name, values in sorted(job.symbols.items())},
            "unresolved_symbols": sorted(job.unresolved_symbols),
            "procs": job.procs,
            "includes": job.includes,
            "dds": job.dds,
            "steps": [_step_dict(step) for step in job.steps],
            "temporary_datasets": dict(sorted(job.temporary.items())),
        }


def _parm_value(raw: str | None) -> str | None:
    """Return a PARM value as the program receives it."""
    if raw is None:
        return None
    value = raw.strip()
    value = value[1:-1] if _enclosed(value) else _unquote(value)
    return value or None


def _merge_dd(base: _DDEntry, override: _DDEntry) -> _DDEntry:
    """Merge an override DD into a procedure DD, following the JCL override rules."""
    keywords = dict(base.params.keywords)
    positional = list(base.params.positional)
    new = override.params
    dropped: set[str] = set()
    if new.positional:
        positional = list(new.positional)
        if positional[0].upper() in {"*", "DATA"}:
            dropped |= DATASET_KEYS | PATH_KEYS | {"SYSOUT"}
    elif {"DSN", "PATH", "SYSOUT"} & set(new.keywords):
        positional = []
    if "SYSOUT" in new.keywords:
        dropped |= DATASET_KEYS | PATH_KEYS
    if "DSN" in new.keywords:
        dropped |= PATH_KEYS | {"SYSOUT"}
    if "PATH" in new.keywords:
        dropped |= DATASET_KEYS | {"SYSOUT"}
    for key in dropped - set(new.keywords):
        keywords.pop(key, None)
    for key, value in new.keywords.items():
        if not value:
            keywords.pop(key, None)
        elif key == "DCB" and "DCB" in keywords:
            keywords["DCB"] = _merge_dcb(keywords["DCB"], value)
        else:
            keywords[key] = value
    instream = override.instream
    if instream is None and positional[:1] and positional[0].upper() in {"*", "DATA"}:
        instream = base.instream
    return _DDEntry(_Params(positional, keywords), instream, override.line, "overridden")


def _merge_dcb(base: str, new: str) -> str:
    """Merge DCB subparameters: those in ``new`` replace the same ones in ``base``."""
    merged: dict[str, str] = {}
    for item in [*_split_list(base), *_split_list(new)]:
        key, separator, _ = item.partition("=")
        merged[key.upper() if separator else ""] = item
    return "(" + ",".join(merged.values()) + ")"


def _dataset_parts(name: str) -> dict[str, Any]:
    """Split a data set name into its lineage key and its generation or member."""
    parts: dict[str, Any] = {"dataset": name}
    if match := RELATIVE_GENERATION.fullmatch(name):
        number = int(match.group(2))
        parts.update(dataset=match.group(1), generation=f"{number:+d}" if number else "0")
    elif match := MEMBER_NAME.fullmatch(name):
        parts.update(dataset=match.group(1), member=match.group(2))
    elif match := ABSOLUTE_GENERATION.fullmatch(name):
        parts.update(dataset=match.group(1), generation=match.group(2))
    if name.startswith("&&"):
        parts["temporary"] = True
    return parts


def _disp(raw: str | None) -> dict[str, Any]:
    """Return DISP status and normal and abnormal dispositions, with the JCL defaults."""
    items = [item.upper() for item in _split_list(raw)] if raw else []
    status = items[0] if items and items[0] else "NEW"
    normal = items[1] if len(items) > 1 and items[1] else ("DELETE" if status == "NEW" else "KEEP")
    abnormal = items[2] if len(items) > 2 and items[2] else normal
    if abnormal == "PASS":
        abnormal = "DELETE" if status == "NEW" else "KEEP"
    return {"raw": raw, "status": status, "normal": normal, "abnormal": abnormal}


def _dcb(keywords: Mapping[str, str]) -> dict[str, str]:
    """Return DCB subparameters merged with standalone RECFM, LRECL, BLKSIZE, and DSORG."""
    dcb: dict[str, str] = {}
    for item in filter(None, _split_list(keywords.get("DCB", ""))):
        key, separator, value = item.partition("=")
        if separator:
            dcb[key.strip().upper()] = value.strip()
        else:
            dcb["MODEL"] = item.upper()
    dcb.update({key: keywords[key] for key in DCB_KEYWORDS if key in keywords})
    return dcb


def _sysout(value: str) -> dict[str, str]:
    """Return the class, writer, and form of a SYSOUT parameter."""
    items = _split_list(value)
    names = ("class", "writer", "form")
    return {name: item.upper() for name, item in zip(names, items, strict=False) if item}


def _actions(step: _Step, detail: Mapping[str, Any], effects: _Effects) -> list[str]:
    """Return what the step does to the data set or file of one DD: read, write, or delete."""
    ddname = detail["ddname"]
    output = ddname in effects.outputs
    actions: list[str] = []
    if "dsn" not in detail:
        options = set(detail.get("pathopts", []))
        if output or options & PATH_WRITE_OPTIONS:
            actions.append("write")
        if ddname in effects.inputs or options & PATH_READ_OPTIONS or not (options or output):
            actions.append("read")
        return actions
    status, normal = detail["disp"]["status"], detail["disp"]["normal"]
    if step.program == "IEFBR14":
        writes, reads = status == "NEW", False
    else:
        writes = status in {"NEW", "MOD"} or output
        reads = (status in {"SHR", "OLD"} and not output) or ddname in effects.inputs
    if writes:
        actions.append("write")
    if reads:
        actions.append("read")
    if normal == "DELETE":
        actions.append("delete")
    return actions


# Utility control statements -------------------------------------------------------------------


def _strip_comments(text: str, *, in_comment: bool) -> tuple[str, bool]:
    """Remove ``/* ... */`` comments, which may continue onto the next line."""
    kept: list[str] = []
    index = 0
    while index < len(text):
        if in_comment:
            end = text.find("*/", index)
            if end < 0:
                return "".join(kept), True
            index, in_comment = end + 2, False
        else:
            start = text.find("/*", index)
            if start < 0:
                kept.append(text[index:])
                break
            kept.append(text[index:start])
            index, in_comment = start + 2, True
    return "".join(kept), in_comment


def _commands(lines: Iterable[str]) -> list[str]:
    """Join commands continued with a trailing hyphen or plus sign, dropping comments.

    This is the convention of IDCAMS, TSO, ICETOOL, and Connect:Direct: a hyphen continues
    with a blank and a plus sign continues within a word.
    """
    commands: list[str] = []
    current: str | None = None
    glue = " "
    in_comment = False
    for raw in lines:
        text, in_comment = _strip_comments(raw[:72], in_comment=in_comment)
        text = text.strip()
        if current is not None:
            text = current + glue + text
        elif not text:
            continue
        if text.endswith(("-", "+")):
            glue = " " if text.endswith("-") else ""
            current = text[:-1].rstrip()
            continue
        current = None
        commands.append(text)
    if current:
        commands.append(current)
    return commands


def _card_statements(lines: Iterable[str], verbs: Container[str]) -> list[tuple[str, str]]:
    """Return (verb, operands) for DFSORT-style control statements in columns 1-71.

    Comment lines start with an asterisk, a word in column 1 that is not a known verb is a
    label, and a statement continues while its operand field ends with a comma.
    """
    statements: list[tuple[str, str]] = []
    continuing = False
    for raw in lines:
        line = raw[:71]
        if not line.strip() or line.startswith("*"):
            continue
        if continuing:
            verb, operands = statements[-1]
            more, _ = _scan(line.strip(), quoted=False)
            statements[-1] = (verb, operands + more)
            continuing = more.endswith(",")
            continue
        text = line.strip()
        if line[0] != " " and text.split()[0].upper() not in verbs:
            text = text.partition(" ")[2].strip()
        verb, _, rest = text.partition(" ")
        operands, _ = _scan(rest.lstrip(), quoted=False)
        statements.append((verb.upper(), operands))
        continuing = operands.endswith(",")
    return statements


def _paren_value(text: str, *keys: str) -> str | None:
    """Return the upper-cased value of the first ``KEY(value)`` in ``text``."""
    pattern = r"(?<![A-Z0-9@#$])(?:" + "|".join(keys) + r")\s*\(\s*([^()]*?)\s*\)"
    match = re.search(pattern, text, re.IGNORECASE)
    return _unquote(match.group(1)).upper() if match else None


def _idcams(effects: _Effects, lines: list[str]) -> None:
    """Read IDCAMS commands: DEFINE, DELETE, REPRO, PRINT, LISTCAT, and IF or SET logic."""
    commands: list[dict[str, Any]] = []
    for command in _commands(lines):
        text = command
        while (prefix := IDCAMS_PREFIX.match(text)) is not None:
            if prefix.group(0)[:2].upper() == "IF":
                effects.control["conditional"] = True
            text = text[prefix.end() :]
        words = text.upper().split()
        if not words:
            continue
        verb = IDCAMS_VERBS.get(words[0], words[0])
        entry: dict[str, Any] = {"command": verb}
        if verb == "DEFINE" and len(words) > 1:
            kind = re.split(r"[(\s]", words[1], maxsplit=1)[0]
            kind = IDCAMS_OBJECTS.get(kind, kind)
            entry["command"] = f"DEFINE {kind}"
            name = _paren_value(text, "NAME")
            if name:
                entry["dataset"] = name
                if kind in IDCAMS_DATA_OBJECTS:
                    effects.datasets.append((name, "write", f"IDCAMS DEFINE {kind}"))
        elif verb == "DELETE":
            names = _idcams_names(text.partition(" ")[2])
            entry["datasets"] = names
            effects.datasets.extend((name, "delete", "IDCAMS DELETE") for name in names)
        elif verb in {"REPRO", "PRINT", "BLDINDEX"}:
            _idcams_copy(effects, text, entry)
        elif verb == "LISTCAT":
            entries = _paren_value(text, "ENTRIES", "ENT", "LEVEL", "LVL")
            if entries:
                entry["entries"] = entries.split()
        commands.append(entry)
    if commands:
        effects.control["commands"] = commands


def _idcams_names(rest: str) -> list[str]:
    """Return the entry names of an IDCAMS DELETE: one name or a parenthesized list."""
    rest = rest.strip()
    if rest.startswith("("):
        tokens = re.split(r"[\s,]+", rest[1:].split(")", 1)[0])
    else:
        tokens = rest.split()[:1]
    return [_unquote(token).split("/")[0].upper() for token in tokens if token]


def _idcams_copy(effects: _Effects, text: str, entry: dict[str, Any]) -> None:
    """Record the input and output of REPRO, PRINT, or BLDINDEX."""
    verb = entry["command"]
    for keys, action, label in (
        (("INDATASET", "IDS"), "read", "from"),
        (("OUTDATASET", "ODS"), "write", "to"),
    ):
        value = _paren_value(text, *keys)
        if value:
            entry[label] = value.split("/")[0]
            effects.datasets.append((entry[label], action, f"IDCAMS {verb}"))
    for keys, targets, label in (
        (("INFILE", "IFILE"), effects.inputs, "infile"),
        (("OUTFILE", "OFILE"), effects.outputs, "outfile"),
    ):
        value = _paren_value(text, *keys)
        if value:
            entry[label] = value.split("/")[0]
            targets.add(entry[label])


def _sort(effects: _Effects, step: _Step, lines: list[str]) -> None:
    """Read DFSORT or Syncsort control statements and the SORTIN and SORTOUT DD names."""
    statements = _card_statements(lines, SORT_VERBS)
    verbs = {verb for verb, _ in statements if verb in SORT_VERBS}
    if verbs:
        effects.control["statements"] = sorted(verbs | set(effects.control.get("statements", [])))
    if verbs & SORT_LOGIC and SORT_LOGIC_FLAG not in effects.flags:
        effects.flags.append(SORT_LOGIC_FLAG)
    for detail in step.dds:
        if re.fullmatch(r"SORTIN\d{0,2}", detail["ddname"]):
            effects.inputs.add(detail["ddname"])
        elif detail["ddname"] == "SORTOUT":
            effects.outputs.add("SORTOUT")
    for verb, operands in statements:
        keywords = _parse_params(operands).keywords
        if verb == "OUTFIL":
            names = keywords.get("FNAMES") or keywords.get("FNAME")
            files = keywords.get("FILES") or keywords.get("FILE")
            if names:
                effects.outputs.update(name.upper() for name in _split_list(names))
            elif files:
                effects.outputs.update(f"SORTOF{name.upper()}" for name in _split_list(files))
            else:
                effects.outputs.add("SORTOUT")
        elif verb == "JOINKEYS":
            effects.inputs.update(keywords[key].upper() for key in ("F1", "F2") if key in keywords)
            if "FILE" in keywords:
                effects.inputs.add(f"SORTJN{keywords['FILE'].upper()}")


def _iebcopy(effects: _Effects, lines: list[str]) -> None:
    """Read IEBCOPY COPY statements; without them IEBCOPY copies SYSUT1 to SYSUT2."""
    statements = _card_statements(lines, IEBCOPY_VERBS)
    copies = [operands for verb, operands in statements if verb in IEBCOPY_COPY]
    for operands in copies:
        keywords = _parse_params(operands).keywords
        output = keywords.get("OUTDD") or keywords.get("O")
        if output:
            effects.outputs.add(output.upper())
        for item in _split_list(keywords.get("INDD") or keywords.get("I") or ""):
            name = _split_list(item)[0] if _enclosed(item) else item
            effects.inputs.add(name.upper())
    if not copies:
        effects.inputs.add("SYSUT1")
        effects.outputs.add("SYSUT2")
    verbs = sorted({verb for verb, _ in statements if verb in IEBCOPY_VERBS})
    if verbs:
        effects.control["statements"] = verbs


def _tso(effects: _Effects, lines: list[str]) -> None:
    """Read TSO commands in SYSTSIN: DSN SYSTEM, RUN PROGRAM, BIND, and %exec calls."""
    runs: list[dict[str, str | None]] = []
    binds: list[str] = []
    execs: list[str] = []
    for command in _commands(lines):
        text = " ".join(command.split())
        verb = text.split()[0].upper()
        if verb == "DSN":
            effects.control["db2_system"] = _paren_value(text, "SYSTEM")
        elif verb == "RUN":
            program = _paren_value(text, "PROGRAM", "PROG")
            if program:
                runs.append({"program": program, "plan": _paren_value(text, "PLAN")})
                effects.runs.append(program)
        elif verb == "BIND":
            binds.append(text)
        elif verb.startswith("%"):
            execs.append(verb[1:])
    effects.runs.extend(execs)
    for key, values in (("run", runs), ("binds", binds), ("execs", execs)):
        if values:
            effects.control[key] = values


def _ims(effects: _Effects, parm: str | None) -> None:
    """Read the region type, program, and PSB from a DFSRRC00 PARM."""
    fields = [item.strip().upper() for item in _split_top(parm or "")]
    if len(fields) < 2 or not fields[1]:
        return
    region, program = fields[0], fields[1]
    psb = fields[2] if len(fields) > 2 and fields[2] else None
    effects.control.update(region=region, program=program, psb=psb or program)
    effects.runs.append(program)


def _ftp_local(step: _Step, name: str | None, prefix: str) -> tuple[str | None, str | None]:
    """Return the data set and DD name behind an FTP local file name."""
    if name and name.upper().startswith("//DD:"):
        ddname = name[5:].upper()
        dataset = next((d.get("dsn") for d in step.dds if d["ddname"] == ddname), None)
        return dataset, ddname
    if not name or "*" in name or name.startswith("/"):
        return None, None
    if name.startswith("'"):
        return _unquote(name).upper(), None
    return ((prefix + name).upper() if prefix else None), None


def _block(text: str, key: str) -> str | None:
    """Return the text inside ``KEY ( ... )``, with nested parentheses."""
    match = re.search(rf"(?<![A-Z0-9@#$&.]){key}\s*\(", text, re.IGNORECASE)
    if match is None:
        return None
    depth = 1
    for index in range(match.end(), len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[match.end() : index]
    return text[match.end() :]


def _keyword_value(text: str, key: str) -> str | None:
    """Return the value of ``KEY=value`` in Connect:Direct statements."""
    pattern = rf"(?<![A-Z0-9@#$&]){key}\s*=\s*('(?:[^']|'')*'|[^\s,()]+(?:\([^()]*\))?)"
    match = re.search(pattern, text, re.IGNORECASE)
    return _unquote(match.group(1)) if match else None


def _connect_direct(effects: _Effects, lines: list[str]) -> None:
    """Read Connect:Direct DMBATCH input: SUBMIT and PROCESS statements and COPY steps."""
    process: str | None = None
    node: str | None = None
    submits: list[dict[str, Any]] = []
    for command in _commands(lines):
        text = " ".join(command.split())
        words = text.upper().split()
        if words[0] == "SUBMIT":
            proc = _keyword_value(text, "PROC")
            snode = _keyword_value(text, "SNODE")
            submits.append({"process": proc and proc.upper(), "host": snode})
        elif words[1:2] == ["PROCESS"]:
            process, node = words[0], _keyword_value(text, "SNODE")
        elif "COPY" in words[:2]:
            effects.transfers.append(_cd_copy(effects, text, process, node))
    if not effects.transfers:
        effects.transfers.extend(
            {"protocol": "connect-direct", "command": "SUBMIT", "direction": "unknown", **submit}
            for submit in submits
        )


def _cd_copy(effects: _Effects, text: str, process: str | None, node: str | None) -> dict[str, Any]:
    """Describe a Connect:Direct COPY; the side without SNODE is this system (PNODE)."""
    source = _block(text, "FROM") or ""
    outbound = re.search(r"(?<![A-Z0-9@#$=.])SNODE(?![A-Z0-9@#$=.])", source, re.IGNORECASE) is None
    from_dsn = _keyword_value(source, "DSN")
    to_dsn = _keyword_value(_block(text, "TO") or "", "DSN")
    local, remote = (from_dsn, to_dsn) if outbound else (to_dsn, from_dsn)
    transfer: dict[str, Any] = {
        "protocol": "connect-direct",
        "command": "COPY",
        "direction": "outbound" if outbound else "inbound",
        "host": node,
        "process": process,
        "local": local,
        "remote": remote,
    }
    if local and not local.startswith("/"):
        transfer["dataset"] = local.upper()
        action = "read" if outbound else "write"
        effects.datasets.append((local.upper(), action, "Connect:Direct COPY"))
    return transfer


def _bpxbatch(effects: _Effects, parm: str | None, lines: list[str]) -> None:
    """Read the BPXBATCH command from STDPARM or PARM: SH command or PGM path."""
    text = " ".join(line.strip() for line in lines) if lines else (parm or "")
    mode, _, command = text.strip().partition(" ")
    if mode.upper() in {"SH", "PGM"}:
        effects.control.update(mode=mode.upper(), command=command.strip())
        effects.runs.extend(command.split()[:1])
    effects.inputs.add("STDIN")
    effects.outputs.update({"STDOUT", "STDERR"})


# COND explanations and JSON shapes ------------------------------------------------------------


def explain_cond(raw: str, *, job: bool = False) -> str:
    """Explain a COND parameter in words.

    A COND test bypasses the step when it is true, which inverts the usual reading:
    ``COND=(4,LT)`` bypasses the step if 4 is less than the return code of any earlier step.
    EVEN and ONLY on an EXEC statement say whether the step runs after an abend. On the JOB
    statement (``job=True``) a true test bypasses all remaining steps.
    """
    items = _split_list(raw.upper())
    tests: list[list[str]] = []
    modifier = ""
    if items and items[0].isdigit():
        tests.append(items)
    else:
        for item in items:
            if item in {"EVEN", "ONLY"} and not job:
                modifier = item
            elif _enclosed(item):
                tests.append(_split_list(item))
            else:
                return UNRECOGNIZED_COND
    phrases: list[str] = []
    for test in tests:
        valid = len(test) in {2, 3} and test[0].isdigit() and test[1] in COND_OPERATORS
        if not valid or (job and len(test) == 3):
            return UNRECOGNIZED_COND
        words, symbol = COND_OPERATORS[test[1]]
        code = int(test[0])
        if len(test) == 3:
            target, subject = f"the return code of {test[2]}", f"{test[2]} RC"
        else:
            target = "the return code of any step" if job else "the return code of any earlier step"
            subject = "any RC"
        phrases.append(f"{code} is {words} {target} ({subject} {symbol} {code})")
    condition = phrases[0] if len(phrases) == 1 else "any of these is true: " + "; ".join(phrases)
    if job:
        return f"Bypass all remaining steps if {condition}." if phrases else UNRECOGNIZED_COND
    if modifier:
        lead = (
            f"Run this step {'even' if modifier == 'EVEN' else 'only'} if an earlier step abended"
        )
        return f"{lead}; bypass it if {condition}." if phrases else f"{lead}."
    return f"Bypass this step if {condition}." if phrases else UNRECOGNIZED_COND


def _cond_dict(raw: str | None, *, job: bool = False) -> dict[str, str] | None:
    if raw is None or not raw.strip():
        return None
    return {"raw": raw, "explanation": explain_cond(raw, job=job)}


def _step_dict(step: _Step) -> dict[str, Any]:
    dds: list[dict[str, Any]] = []
    for detail, entry in zip(step.dds, step.entries, strict=True):
        dd = dict(detail)
        if entry.instream is not None and step.utility not in TRANSFER_KINDS:
            dd["instream"] = entry.instream
        dds.append(dd)
    return {
        "name": step.name,
        "procstep": step.procstep,
        "proc": step.proc,
        "program": step.program,
        "runs": step.runs,
        "utility": step.utility,
        "parm": step.parm,
        "cond": _cond_dict(step.cond),
        "if_context": step.if_context,
        "flags": step.flags,
        "control": step.control,
        "dds": dds,
    }


# Lineage ------------------------------------------------------------------------------------


def _jobs_doing(records: Iterable[Mapping[str, Any]], action: str) -> list[str]:
    return sorted({record["job"] for record in records if record["action"] == action})


def _scratch(records: Iterable[Mapping[str, Any]]) -> bool:
    """Return True when the same step deletes every write: a work data set, not an output."""
    records = list(records)
    deleted = {(r["job"], r["step"]) for r in records if r["action"] == "delete"}
    return all((r["job"], r["step"]) in deleted for r in records if r["action"] == "write")


def _same_member(write: Mapping[str, Any], read: Mapping[str, Any]) -> bool:
    return "member" not in write or "member" not in read or write["member"] == read["member"]


def _datasets(accesses: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "producers": _jobs_doing(records, "write"),
            "consumers": _jobs_doing(records, "read"),
            "deleted_by": _jobs_doing(records, "delete"),
            "generations": sorted({r["generation"] for r in records if "generation" in r}),
            "members": sorted({r["member"] for r in records if "member" in r}),
            "accesses": records,
        }
        for name, records in sorted(accesses.items())
    }


def _data_dependencies(
    accesses: Mapping[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], set[str]]:
    """Return job pairs where the first writes a data set that the second reads."""
    dependencies: dict[tuple[str, str], set[str]] = {}
    for name, records in accesses.items():
        writes = [record for record in records if record["action"] == "write"]
        reads = [record for record in records if record["action"] == "read"]
        for write in writes:
            for read in reads:
                if write["job"] != read["job"] and _same_member(write, read):
                    dependencies.setdefault((write["job"], read["job"]), set()).add(name)
    return dependencies


def _reachable(graph: Mapping[str, set[str]], start: str, goal: str) -> bool:
    seen = {start}
    queue = deque([start])
    while queue:
        for following in graph.get(queue.popleft(), set()):
            if following == goal:
                return True
            if following not in seen:
                seen.add(following)
                queue.append(following)
    return False


# Schedules ----------------------------------------------------------------------------------


@dataclass
class _ScheduleData:
    sources: list[dict[str, str]] = field(default_factory=list)
    controlm: list[dict[str, Any]] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    iws_dependencies: list[tuple[dict[str, Any], str, str]] = field(default_factory=list)
    run_cycles: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    csv_edges: list[tuple[str, str, str | None]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def _read_controlm(data: _ScheduleData, path: Path, text: str) -> None:
    """Read JOB elements, with their INCOND and OUTCOND children, from Control-M XML."""
    try:
        # The input is a local export file the user chose; expat in Python 3.11+ does not
        # expand external entities.
        root = ElementTree.fromstring(XML_DECLARATION.sub("", text))  # noqa: S314
    except ElementTree.ParseError as exc:
        raise FlowError(f"{path}: not well-formed XML: {exc}") from exc
    pending = [(root, root.get("FOLDER_NAME") or root.get("TABLE_NAME"))]
    found = 0
    while pending:
        element, folder = pending.pop(0)
        for child in element:
            tag = _tag(child)
            if tag == "JOB":
                data.controlm.append(_controlm_job(child, folder))
                found += 1
            elif tag in CONTROLM_CONTAINERS:
                name = child.get("FOLDER_NAME") or child.get("TABLE_NAME") or child.get("JOBNAME")
                pending.append((child, name or folder))
    if not found:
        data.warnings.append(f"{path}: no Control-M JOB elements")


def _controlm_job(element: ElementTree.Element, folder: str | None) -> dict[str, Any]:
    job: dict[str, Any] = {"source": "control-m"}
    if folder:
        job["folder"] = folder
    job.update(
        {name.lower(): element.get(name) for name in CONTROLM_ATTRIBUTES if element.get(name)}
    )
    job["inconds"] = [
        {key: value for key in ("NAME", "ODATE", "AND_OR") if (value := child.get(key))}
        for child in element
        if _tag(child) == "INCOND"
    ]
    job["outconds"] = [
        {key: value for key in ("NAME", "ODATE", "SIGN") if (value := child.get(key))}
        for child in element
        if _tag(child) == "OUTCOND"
    ]
    return job


def _read_csv(data: _ScheduleData, path: Path, text: str) -> None:
    """Read predecessor and successor columns (and an optional condition) from CSV."""
    header = text.lstrip("\ufeff").splitlines()[0]
    delimiter = max((",", ";", "\t", "|"), key=header.count)
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=delimiter)
    columns = {name.strip().lower(): name for name in reader.fieldnames or []}
    if "predecessor" not in columns or "successor" not in columns:
        raise FlowError(f"{path}: CSV needs predecessor and successor columns")
    for row in reader:
        before = (row.get(columns["predecessor"]) or "").strip().upper()
        after = (row.get(columns["successor"]) or "").strip().upper()
        condition = (row.get(columns.get("condition", "")) or "").strip() or None
        if before and after:
            data.csv_edges.append((before, after, condition))


def _iws_statements(text: str) -> list[tuple[str, dict[str, str]]]:
    """Return (keyword, parameters) for batch-loader statements; indented lines continue."""
    lines: list[str] = []
    for line in re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL).splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and lines:
            lines[-1] += " " + line.strip()
        else:
            lines.append(line.strip())
    statements: list[tuple[str, dict[str, str]]] = []
    for line in lines:
        keyword, _, rest = line.partition(" ")
        params: dict[str, str] = {}
        position = 0
        while match := IWS_PARAMETER.search(rest, position):
            depth, quoted, index = 1, False, match.end()
            while index < len(rest) and depth:
                char = rest[index]
                if char == "'":
                    quoted = not quoted
                elif not quoted and char in "()":
                    depth += 1 if char == "(" else -1
                index += 1
            value = rest[match.end() : index - 1 if depth == 0 else index]
            params.setdefault(match.group(1).upper(), _unquote(value))
            position = index
        statements.append((keyword.upper(), params))
    return statements


def _read_iws(data: _ScheduleData, path: Path, text: str) -> None:
    """Read applications, operations, and dependencies from IBM Z Workload Scheduler input."""
    application: str | None = None
    operation: dict[str, Any] | None = None
    for keyword, params in _iws_statements(text):
        if keyword == "ADSTART" and "ADID" in params:
            application, operation = params["ADID"].upper(), None
        elif keyword == "ADOP" and application:
            operation = {
                "adid": application,
                "opno": params.get("OPNO", ""),
                "wsid": params.get("WSID"),
                "jobn": params.get("JOBN", "").upper() or None,
                "desc": params.get("DESC") or params.get("DESCR"),
                "predecessors": [],
            }
            data.operations.append(operation)
            for number in re.split(r"[\s,]+", params.get("PREOP", "")):
                if number:
                    data.iws_dependencies.append((operation, application, number))
        elif keyword == "ADDEP" and operation:
            adid = params.get("PREADID") or params.get("PREAD") or operation["adid"]
            data.iws_dependencies.append((operation, adid.upper(), params.get("PREOP", "")))
        elif keyword in {"ADRUN", "ADRULE"} and application:
            data.run_cycles.setdefault(application, []).append({"statement": keyword, **params})
        elif keyword in {"ADOP", "ADDEP"}:
            data.warnings.append(f"{path}: {keyword} outside an application is ignored")


def _opno(number: str) -> int | str:
    number = number.strip()
    return int(number) if number.isdigit() else number.upper()


def _load_schedules(
    paths: Sequence[Path], codepage: str, aliases: Mapping[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """Read schedule exports, detecting the format of each from its content."""
    data = _ScheduleData()
    for path in paths:
        decoded = zos_encoding.decode_member(path.read_bytes(), codepage=codepage)
        text = decoded.text if decoded is not None else ""
        head = text.lstrip("\ufeff \t\r\n")
        first_line = head.split("\n", 1)[0].lower()
        if head.startswith("<"):
            fmt = "control-m"
            _read_controlm(data, path, text)
        elif "predecessor" in first_line and "successor" in first_line:
            fmt = "csv"
            _read_csv(data, path, head)
        elif re.search(r"^AD(?:START|OP)\b", text, re.MULTILINE | re.IGNORECASE):
            fmt = "iws-batch-loader"
            _read_iws(data, path, text)
        else:
            raise FlowError(
                f"{path}: not a Control-M XML, IBM Z Workload Scheduler batch-loader, or CSV "
                "(predecessor, successor) export"
            )
        data.sources.append({"path": str(path), "format": fmt})
    return _resolve_schedule(data, aliases)


def _resolve_schedule(
    data: _ScheduleData, aliases: Mapping[str, str]
) -> tuple[dict[str, Any], list[str]]:
    """Name scheduled jobs after the JCL jobs they run and build job-to-job edges."""

    def canonical(*names: str | None) -> str:
        candidates = [name.upper() for name in names if name]
        known = [aliases[name] for name in candidates if name in aliases]
        return (known or candidates or ["?"])[0]

    jobs: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    warnings = list(data.warnings)

    named = [(canonical(job.get("memname"), job.get("jobname")), job) for job in data.controlm]
    adders: dict[str, list[str]] = {}
    for name, job in named:
        jobs.setdefault(name, job)
        for condition in job["outconds"]:
            if condition.get("SIGN", "+").upper() in CONTROLM_ADD_SIGNS:
                adders.setdefault(condition.get("NAME", ""), []).append(name)
    unmatched: set[str] = set()
    for name, job in named:
        for condition in job["inconds"]:
            label = condition.get("NAME", "")
            producers = adders.get(label, [])
            if not producers:
                unmatched.add(label)
            edges.extend(
                {"from": producer, "to": name, "source": "control-m", "via": label}
                for producer in producers
                if producer != name
            )

    index = {(op["adid"], _opno(op["opno"])): op for op in data.operations}
    for op in data.operations:
        if op["jobn"]:
            entry = jobs.setdefault(
                canonical(op["jobn"]),
                {"source": "iws-batch-loader", "application": op["adid"], "operations": []},
            )
            entry.setdefault("operations", []).append(op["opno"])
    for successor, adid, number in data.iws_dependencies:
        predecessor = index.get((adid, _opno(number)))
        if predecessor is None:
            warnings.append(
                f"schedule: predecessor {adid} operation {number} of {successor['adid']} "
                f"operation {successor['opno']} is not in the loaded schedules"
            )
            continue
        successor["predecessors"].append({"adid": adid, "opno": predecessor["opno"]})
        if predecessor["jobn"] and successor["jobn"]:
            edges.append(
                {
                    "from": canonical(predecessor["jobn"]),
                    "to": canonical(successor["jobn"]),
                    "source": "iws-batch-loader",
                    "via": f"{adid} {predecessor['opno']} -> "
                    f"{successor['adid']} {successor['opno']}",
                }
            )

    for before, after, condition in data.csv_edges:
        source, target = canonical(before), canonical(after)
        for name in (source, target):
            jobs.setdefault(name, {"source": "csv"})
        edges.append({"from": source, "to": target, "source": "csv", "via": condition})

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for edge in edges:
        if edge["from"] != edge["to"]:
            unique.setdefault(tuple(edge.values()), edge)
    schedule = {
        "sources": data.sources,
        "jobs": dict(sorted(jobs.items())),
        "operations": data.operations,
        "run_cycles": data.run_cycles,
        "edges": list(unique.values()),
        "unmatched_conditions": sorted(unmatched),
    }
    return schedule, warnings


# Flow ---------------------------------------------------------------------------------------


def build_flow(  # noqa: PLR0913  # one keyword per command-line option
    roots: Sequence[Path],
    *,
    proclibs: Sequence[Path] = (),
    schedules: Sequence[Path] = (),
    symbols: Mapping[str, str] | None = None,
    codepage: str = "037",
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Analyze the JCL under ``roots`` and return the batch flow as a JSON-serializable dict.

    Args:
        roots: Directories or files with jobs, procedures, INCLUDE members, and control cards.
        proclibs: Procedure library directories, searched in order before the roots.
        schedules: Control-M XML, IBM Z Workload Scheduler batch-loader, or CSV exports.
        symbols: System symbols such as SYSUID; they take precedence over JCL symbols.
        codepage: EBCDIC code page of members that are still in EBCDIC.
        max_bytes: Members larger than this are skipped with a warning.

    Raises:
        FlowError: A path does not exist or a schedule export cannot be read.
        ValueError: The code page is not supported.
    """
    codepage = zos_encoding.normalize_codepage(codepage)
    missing = [str(path) for path in (*roots, *proclibs, *schedules) if not path.exists()]
    if missing:
        raise FlowError(f"not found: {', '.join(missing)}")
    warnings: list[str] = []
    system = {name.upper().lstrip("&"): value for name, value in (symbols or {}).items()}
    layers = [_load_members([path], codepage, max_bytes, warnings) for path in proclibs]
    root_members = _load_members(roots, codepage, max_bytes, warnings)
    analyzer = _Analyzer(_Library([*layers, root_members]), system)

    jobs: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for member in (member for member in root_members if member.kind == "job"):
        analyzer.report(member)
        for statement, body, procs in _split_jobs(member, analyzer.warnings):
            name = key = statement.name or member.name
            number = 1
            while key in jobs:
                number += 1
                key = f"{name}#{number}"
            if key != name:
                analyzer.warnings.append(f"{member.path}: job {name} is repeated; shown as {key}")
            job = _Job(key, member, statement, procs)
            analyzer.run_job(job, body)
            jobs[key] = analyzer.job_dict(job)
            aliases[key] = key
            aliases.setdefault(member.name, key)

    datasets = _datasets(analyzer.accesses)
    dependencies = _data_dependencies(analyzer.accesses)
    schedule: dict[str, Any] | None = None
    schedule_warnings: list[str] = []
    graph: dict[str, set[str]] = {}
    if schedules:
        schedule, schedule_warnings = _load_schedules(schedules, codepage, aliases)
        schedule["jobs_without_jcl"] = sorted(set(schedule["jobs"]) - set(jobs))
        schedule["unscheduled_jobs"] = sorted(set(jobs) - set(schedule["jobs"]))
        for edge in schedule["edges"]:
            graph.setdefault(edge["from"], set()).add(edge["to"])

    job_dependencies: list[dict[str, Any]] = []
    for (source, target), names in sorted(dependencies.items()):
        scheduled = None
        if schedule is not None and {source, target} <= set(schedule["jobs"]):
            scheduled = _reachable(graph, source, target)
            if not scheduled:
                schedule_warnings.append(
                    f"missing scheduler dependency: {source} writes {', '.join(sorted(names))}, "
                    f"which {target} reads, but the schedule has no path from {source} to {target}"
                )
        job_dependencies.append(
            {
                "from": source,
                "to": target,
                "type": "data",
                "datasets": sorted(names),
                "scheduled": scheduled,
            }
        )
    edges: list[dict[str, Any]] = []
    for name, info in datasets.items():
        edges += [{"from": job, "to": name, "type": "writes"} for job in info["producers"]]
        edges += [{"from": name, "to": job, "type": "reads"} for job in info["consumers"]]
        edges += [{"from": job, "to": name, "type": "deletes"} for job in info["deleted_by"]]
    if schedule is not None:
        job_dependencies += [
            {
                "from": edge["from"],
                "to": edge["to"],
                "type": "schedule",
                "source": edge["source"],
                "via": edge["via"],
            }
            for edge in schedule["edges"]
        ]
        pairs = dict.fromkeys((edge["from"], edge["to"]) for edge in schedule["edges"])
        edges += [{"from": source, "to": target, "type": "schedule"} for source, target in pairs]

    return {
        "tool": "batch_flow",
        "roots": [str(root) for root in roots],
        "proclibs": [str(path) for path in proclibs],
        "jobs": jobs,
        "datasets": datasets,
        "transfers": analyzer.transfers,
        "reports": analyzer.reports,
        "schedule": schedule,
        "edges": edges,
        "external_inputs": [
            name for name, info in datasets.items() if info["consumers"] and not info["producers"]
        ],
        "final_outputs": [
            name
            for name, info in datasets.items()
            if info["producers"] and not info["consumers"] and not _scratch(info["accesses"])
        ],
        "job_dependencies": job_dependencies,
        "unresolved": {key: sorted(values) for key, values in analyzer.unresolved.items()},
        "warnings": [*warnings, *analyzer.warnings, *schedule_warnings],
    }


def select_jobs(flow: Mapping[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """Return a copy of ``flow`` limited to the named jobs and the data sets they use."""
    wanted = {name.upper() for name in names}
    datasets = {
        name: info
        for name, info in flow["datasets"].items()
        if wanted & {*info["producers"], *info["consumers"], *info["deleted_by"]}
    }
    nodes = wanted | set(datasets)
    return {
        **flow,
        "jobs": {name: job for name, job in flow["jobs"].items() if name in wanted},
        "datasets": datasets,
        "transfers": [item for item in flow["transfers"] if item["job"] in wanted],
        "reports": [item for item in flow["reports"] if item["job"] in wanted],
        "edges": [
            edge
            for edge in flow["edges"]
            if {edge["from"], edge["to"]} <= nodes and wanted & {edge["from"], edge["to"]}
        ],
        "external_inputs": [name for name in flow["external_inputs"] if name in datasets],
        "final_outputs": [name for name in flow["final_outputs"] if name in datasets],
        "job_dependencies": [
            item for item in flow["job_dependencies"] if wanted & {item["from"], item["to"]}
        ],
    }


# Rendering ----------------------------------------------------------------------------------


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def _by(info: Mapping[str, Any], action: str) -> str:
    """Return ``JOB (STEP, STEP); JOB (STEP)`` for the steps that perform ``action``."""
    steps: dict[str, list[str]] = {}
    for record in info["accesses"]:
        if record["action"] == action:
            names = steps.setdefault(record["job"], [])
            if record["step"] not in names:
                names.append(record["step"])
    return "; ".join(f"{job} ({', '.join(names)})" for job, names in steps.items())


def _condition(step: Mapping[str, Any]) -> str:
    parts = list(step["if_context"])
    if step["cond"]:
        parts.append(f"COND={step['cond']['raw']}: {step['cond']['explanation']}")
    return "; ".join(parts)


def flow_to_markdown(flow: Mapping[str, Any]) -> str:
    """Render the flow as a Markdown report."""
    lines = ["# Batch flow", "", f"Scanned: {', '.join(flow['roots'])}", ""]
    rows: list[tuple[Any, ...]] = []
    for name, job in flow["jobs"].items():
        if job["cond"]:
            cond = job["cond"]
            rows.append((name, "(job)", "", "", f"COND={cond['raw']}: {cond['explanation']}", ""))
        for step in job["steps"]:
            program = step["program"] or "(not found)"
            if step["runs"]:
                program += " -> " + ", ".join(step["runs"])
            notes = ", ".join(
                [step["utility"], *step["flags"]] if step["utility"] else step["flags"]
            )
            rows.append((name, step["name"], step["proc"], program, _condition(step), notes))
    lines += ["## Jobs and steps", ""]
    lines += _table(("Job", "Step", "Proc", "Program", "Condition", "Notes"), rows)
    datasets = flow["datasets"]
    if datasets:
        lines += ["## Data set lineage", ""]
        lines += _table(
            ("Data set", "Written by", "Read by"),
            ((name, _by(info, "write"), _by(info, "read")) for name, info in datasets.items()),
        )
    if flow["external_inputs"]:
        lines += ["## External inputs", "", "Read but never written by the scanned jobs.", ""]
        lines += _table(
            ("Data set", "Read by"),
            ((name, _by(datasets[name], "read")) for name in flow["external_inputs"]),
        )
    if flow["final_outputs"]:
        lines += ["## Final outputs", "", "Written but never read by the scanned jobs.", ""]
        lines += _table(
            ("Data set", "Written by"),
            ((name, _by(datasets[name], "write")) for name in flow["final_outputs"]),
        )
    if flow["job_dependencies"]:
        rows = []
        for item in flow["job_dependencies"]:
            if item["type"] == "data":
                evidence = ", ".join(item["datasets"])
                if item["scheduled"] is False:
                    evidence += " (no path in the schedule)"
            else:
                evidence = f"{item['source']}: {item['via']}" if item["via"] else item["source"]
            rows.append((item["from"], item["to"], item["type"], evidence))
        lines += ["## Job dependencies", "", *_table(("From", "To", "Type", "Evidence"), rows)]
    if flow["transfers"]:
        lines += ["## Transfers", ""]
        lines += _table(
            ("Job", "Step", "Protocol", "Direction", "Host or node", "Local", "Remote"),
            (
                [t["job"], t["step"], t["protocol"], t["direction"]]
                + [t.get(key) for key in ("host", "local", "remote")]
                for t in flow["transfers"]
            ),
        )
    reports = [report for report in flow["reports"] if report["kind"] == "report"]
    messages = len(flow["reports"]) - len(reports)
    if flow["reports"]:
        lines += ["## Reports", ""]
        if reports:
            lines += _table(
                ("Job", "Step", "DD", "Class", "Destination"),
                ((r["job"], r["step"], r["dd"], r.get("class"), r.get("dest")) for r in reports),
            )
        if messages:
            lines += [f"{messages} SYSOUT DDs that carry messages or dumps are not listed.", ""]
    unresolved = flow["unresolved"]
    if any(unresolved.values()):
        labels = {"procs": "Procedures", "includes": "INCLUDE members", "symbols": "Symbols"}
        lines += ["## Unresolved", ""]
        for key, values in unresolved.items():
            if values:
                shown = [f"&{value}" for value in values] if key == "symbols" else values
                lines.append(f"- **{labels[key]}:** {', '.join(shown)}")
        lines.append("")
    if flow["warnings"]:
        lines += ["## Warnings", "", *(f"- {warning}" for warning in flow["warnings"]), ""]
    return "\n".join(lines)


def _node_id(kind: str, name: str, used: set[str]) -> str:
    base = f"{kind}_{re.sub(r'[^A-Za-z0-9_]', '_', name)}"
    node_id, number = base, 1
    while node_id in used:
        number += 1
        node_id = f"{base}_{number}"
    used.add(node_id)
    return node_id


def flow_to_mermaid(flow: Mapping[str, Any], jobs: Sequence[str] | None = None) -> str:
    """Render jobs and data sets as a Mermaid flowchart.

    Jobs are rounded nodes and data sets are cylinders; writes point from the job to the data
    set, reads from the data set to the job, and schedule dependencies are dotted. ``jobs``
    limits the chart to those jobs and their data sets. Charts stop at 300 nodes.
    """
    if jobs:
        flow = select_jobs(flow, jobs)
    job_names = list(flow["jobs"])
    for edge in flow["edges"]:
        if edge["type"] == "schedule":
            job_names += [name for name in (edge["from"], edge["to"]) if name not in job_names]
    datasets = [
        name for name, info in flow["datasets"].items() if info["producers"] or info["consumers"]
    ]
    nodes = [("job", name) for name in job_names] + [("dataset", name) for name in datasets]
    lines = ["flowchart LR"]
    if len(nodes) > MAX_MERMAID_NODES:
        lines.append(
            f"    %% truncated: {MAX_MERMAID_NODES} of {len(nodes)} nodes shown; "
            "use --job to focus on fewer jobs"
        )
        nodes = nodes[:MAX_MERMAID_NODES]
    ids: dict[tuple[str, str], str] = {}
    used: set[str] = set()
    for kind, name in nodes:
        node_id = ids[kind, name] = _node_id(kind, name, used)
        label = name.replace('"', "#quot;")
        lines.append(
            f'    {node_id}("{label}")' if kind == "job" else f'    {node_id}[("{label}")]'
        )
    shapes = {
        "writes": ("job", "dataset", "-->"),
        "reads": ("dataset", "job", "-->"),
        "schedule": ("job", "job", "-.->"),
    }
    for edge in flow["edges"]:
        if edge["type"] not in shapes:
            continue
        source_kind, target_kind, arrow = shapes[edge["type"]]
        source = ids.get((source_kind, edge["from"]))
        target = ids.get((target_kind, edge["to"]))
        if source and target:
            lines.append(f"    {source} {arrow} {target}")
    return "\n".join(lines)


# Command line -------------------------------------------------------------------------------


def _parse_set(values: Sequence[str]) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for value in values:
        match = SET_ARGUMENT.fullmatch(value)
        if match is None:
            raise FlowError(f"--set expects NAME=VALUE, got {value!r}")
        symbols[match.group(1).upper()] = match.group(2)
    return symbols


def _check_jobs(flow: Mapping[str, Any], names: Sequence[str]) -> None:
    unknown = sorted({name.upper() for name in names} - set(flow["jobs"]))
    if unknown:
        raise FlowError(f"no such job: {', '.join(unknown)}")


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number of bytes")
    return number


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, analyze the JCL, and print the flow."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="Directories or files with jobs, procedures, INCLUDE members, and control cards.",
    )
    parser.add_argument(
        "--proclib",
        action="append",
        type=Path,
        default=[],
        help="Procedure library directory, searched before the roots; repeat in order.",
    )
    parser.add_argument(
        "--schedule",
        action="append",
        type=Path,
        default=[],
        help="Control-M XML, IBM Z Workload Scheduler batch-loader, or CSV export; repeatable.",
    )
    parser.add_argument(
        "--set",
        dest="symbols",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="System symbol such as SYSUID=BATCH; overrides JCL symbols; repeatable.",
    )
    parser.add_argument(
        "--job",
        dest="jobs",
        action="append",
        default=[],
        metavar="NAME",
        help="Limit the output to these jobs and their data sets; repeatable.",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "markdown", "mermaid"),
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--codepage", default="037", help="EBCDIC code page of unconverted members (default: 037)."
    )
    parser.add_argument(
        "--max-bytes",
        type=_positive,
        default=DEFAULT_MAX_BYTES,
        help=f"Skip members larger than this many bytes (default: {DEFAULT_MAX_BYTES}).",
    )
    args = parser.parse_args(argv)
    try:
        flow = build_flow(
            args.roots,
            proclibs=args.proclib,
            schedules=args.schedule,
            symbols=_parse_set(args.symbols),
            codepage=args.codepage,
            max_bytes=args.max_bytes,
        )
        _check_jobs(flow, args.jobs)
    except (FlowError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.output_format == "mermaid":
        print(flow_to_mermaid(flow, args.jobs or None))
        return 0
    if args.jobs:
        flow = select_jobs(flow, args.jobs)
    print(
        flow_to_markdown(flow) if args.output_format == "markdown" else json.dumps(flow, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
