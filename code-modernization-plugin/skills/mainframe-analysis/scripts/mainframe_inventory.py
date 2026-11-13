#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Inventory mainframe application source exported to a local directory.

Classifies each member (COBOL program or copybook, PL/I, Assembler, JCL job or procedure,
BMS or MFS map, IMS DBD or PSB, CICS CSD definitions, DCLGEN, SQL DDL, utility control
cards, REXX, Easytrieve) and extracts dependencies: COPY and INCLUDE members, static and
dynamic CALLs, CICS LINK, XCTL, and START targets, Db2 tables, IMS DL/I and MQ usage,
file assignments, JCL step programs (including programs run through IKJEFT01 and
DFSRRC00), data sets, and CICS transaction-to-program mappings. It flags modernization
risk indicators per program. Members still in EBCDIC (binary transfers of 80-byte
records) are decoded as code page 037.

The scan is static and heuristic: confirm findings against compiler listings and
cross-reference tools. The script only reads files.

Examples:
    uv run --script mainframe_inventory.py src/mainframe
    uv run --script mainframe_inventory.py COBOL COPYLIB JCL --format markdown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

DEFAULT_MAX_BYTES = 5_000_000
NAME = r"[A-Z0-9@#$][A-Z0-9@#$_-]*"

SOURCE_SUFFIXES = frozenset(
    {
        "",
        ".asm",
        ".bms",
        ".cbl",
        ".ccp",
        ".clist",
        ".cntl",
        ".cob",
        ".cobol",
        ".copy",
        ".cpb",
        ".cpy",
        ".csd",
        ".ctl",
        ".dbd",
        ".dcl",
        ".dclgen",
        ".ddl",
        ".exec",
        ".ezt",
        ".hlasm",
        ".inc",
        ".jcl",
        ".job",
        ".mac",
        ".mfs",
        ".mlc",
        ".parm",
        ".pl1",
        ".pli",
        ".prc",
        ".proc",
        ".psb",
        ".rex",
        ".rexx",
        ".sql",
        ".src",
        ".sysin",
        ".txt",
    }
)
SUFFIX_KIND = {
    ".asm": "assembler",
    ".hlasm": "assembler",
    ".mlc": "assembler",
    ".mac": "assembler-macro",
    ".bms": "bms",
    ".mfs": "mfs",
    ".dbd": "ims-dbd",
    ".psb": "ims-psb",
    ".csd": "cics-csd",
    ".pli": "pli-program",
    ".pl1": "pli-program",
    ".rex": "rexx",
    ".rexx": "rexx",
    ".exec": "rexx",
    ".clist": "clist",
    ".ezt": "easytrieve",
    ".cbl": "cobol-program",
    ".cob": "cobol-program",
    ".cobol": "cobol-program",
    ".ccp": "cobol-program",
    ".cpy": "cobol-copybook",
    ".copy": "cobol-copybook",
    ".cpb": "cobol-copybook",
    ".dcl": "dclgen",
    ".dclgen": "dclgen",
    ".jcl": "jcl-job",
    ".job": "jcl-job",
    ".prc": "jcl-proc",
    ".proc": "jcl-proc",
}
PROGRAM_KINDS = frozenset({"cobol-program", "pli-program", "assembler", "easytrieve", "rexx"})
COPY_KINDS = frozenset({"cobol-copybook", "dclgen", "pli-include", "assembler-macro"})
SYSTEM_COPY_PREFIXES = ("DFH", "CMQ", "SQLCA", "SQLDA", "CEE", "IGZ", "DSN", "IDMS")
INTERFACE_CALLS = {
    "ims": ("CBLTDLI", "AIBTDLI", "CEETDLI", "AERTDLI", "PLITDLI", "ASMTDLI"),
    "mq": (
        "MQCONN",
        "MQCONNX",
        "MQDISC",
        "MQOPEN",
        "MQCLOSE",
        "MQPUT",
        "MQPUT1",
        "MQGET",
        "MQINQ",
        "MQSET",
        "MQBEGIN",
        "MQCMIT",
        "MQBACK",
    ),
    "db2": ("DSNTIAR", "DSNTIAC", "DSNALI", "DSNRLI", "DSNHLI", "DSNELI"),
    "language-environment": ("CEE3ABD", "ILBOABN0", "CEEDAYS", "CEEDATE", "CEELOCT", "CEEMSG"),
}
INTERFACE_FAMILY = {name: family for family, names in INTERFACE_CALLS.items() for name in names}
SYSTEM_PROGRAM_PREFIXES = (
    "ADR",
    "CEE",
    "DFH",
    "DFS",
    "DSN",
    "ICE",
    "IDCAMS",
    "IEB",
    "IEF",
    "IEH",
    "IGY",
    "IKJ",
    "IRX",
    "IEW",
    "EZT",
    "SORT",
    "SYNCSORT",
    "DMBATCH",
    "FTP",
    "BPXBATCH",
)
DB2_TSO_PROGRAMS = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})
UTILITY_PROGRAMS = {
    "IDCAMS": "idcams",
    "SORT": "sort",
    "ICEMAN": "sort",
    "SYNCSORT": "sort",
    "ICETOOL": "sort",
    "SYNCTOOL": "sort",
    "IEBGENER": "copy",
    "ICEGENER": "copy",
    "IEBCOPY": "copy",
    "IEFBR14": "allocate",
    "ADRDSSU": "dump-restore",
    "DSNUTILB": "db2-utility",
    "DSNTEP2": "db2-sql",
    "DSNTEP4": "db2-sql",
    "DSNTIAUL": "db2-unload",
    "EZTPA00": "easytrieve",
    "FTP": "file-transfer",
    "DMBATCH": "file-transfer",
    "IKJEFT01": "tso-batch",
    "IKJEFT1A": "tso-batch",
    "IKJEFT1B": "tso-batch",
    "DFSRRC00": "ims-region",
    "BPXBATCH": "unix-shell",
}
RISK_WEIGHTS = {
    "alter": 5,
    "go_to_depending": 3,
    "dynamic_call": 2,
    "cics_handle": 2,
    "dynamic_sql": 2,
    "go_to": 1,
    "perform_thru": 1,
    "next_sentence": 1,
    "redefines": 1,
    "occurs_depending": 1,
    "pointer": 1,
}


def _word(pattern: str) -> str:
    """Wrap ``pattern`` so it only matches a whole COBOL word."""
    return rf"(?<![A-Z0-9-])(?:{pattern})(?![A-Z0-9-])"


RISK_PATTERNS = {
    "alter": re.compile(_word(r"ALTER\s+" + NAME + r"\s+TO")),
    "go_to": re.compile(_word(r"GO\s+TO")),
    "go_to_depending": re.compile(_word(r"GO\s+TO") + r"[^.]*?" + _word(r"DEPENDING")),
    "perform_thru": re.compile(_word(r"PERFORM\s+" + NAME + r"\s+(?:THRU|THROUGH)")),
    "next_sentence": re.compile(_word(r"NEXT\s+SENTENCE")),
    "redefines": re.compile(_word("REDEFINES")),
    "occurs_depending": re.compile(_word("OCCURS") + r"[^.]*?" + _word(r"DEPENDING")),
    "packed_decimal": re.compile(_word(r"COMP-3|COMPUTATIONAL-3|PACKED-DECIMAL")),
    "binary": re.compile(_word(r"COMP|COMPUTATIONAL|COMP-4|COMPUTATIONAL-4|COMP-5|BINARY")),
    "float": re.compile(_word(r"COMP-1|COMP-2|COMPUTATIONAL-1|COMPUTATIONAL-2")),
    "hex_literal": re.compile(r"(?<![A-Z0-9-])X'[0-9A-F]*'"),
    "high_low_values": re.compile(_word(r"HIGH-VALUES?|LOW-VALUES?")),
    "date_logic": re.compile(
        _word(r"ACCEPT\s+" + NAME + r"\s+FROM\s+(?:DATE|DAY|TIME)|CURRENT-DATE")
    ),
    "sort_merge": re.compile(
        _word(r"(?:SORT|MERGE)\s+" + NAME + r"\s+(?:ON\s+)?(?:ASCENDING|DESCENDING)")
    ),
    "inspect_converting": re.compile(_word("INSPECT") + r"[^.]*?" + _word("CONVERTING")),
    "pointer": re.compile(_word(r"ADDRESS\s+OF|POINTER")),
    "entry_point": re.compile(_word(r"ENTRY") + r"\s+['\"]"),
    "return_code": re.compile(_word("RETURN-CODE")),
    "stop_run": re.compile(_word(r"STOP\s+RUN")),
    "cics_handle": re.compile(_word(r"HANDLE\s+(?:CONDITION|ABEND|AID)|IGNORE\s+CONDITION")),
    "dynamic_sql": re.compile(_word(r"PREPARE|EXECUTE\s+IMMEDIATE")),
}
PROGRAM_ID = re.compile(r"PROGRAM-ID\.?\s+['\"]?(" + NAME + ")", re.IGNORECASE)
COPY_MEMBER = re.compile(_word(r"COPY") + r"\s+['\"]?(" + NAME + ")")
SQL_INCLUDE = re.compile(r"EXEC\s+SQL\s+INCLUDE\s+(" + NAME + ")")
LIBRARIAN_INCLUDE = re.compile(r"^(?:\s*\+\+INCLUDE|-INC)\s+(" + NAME + ")", re.MULTILINE)
STATIC_CALL = re.compile(_word("CALL") + r"\s+['\"](" + NAME + r")['\"]")
DYNAMIC_CALL = re.compile(_word("CALL") + r"\s+(" + NAME + ")")
EXEC_BLOCK = re.compile(r"EXEC\s+(CICS|SQL|DLI)\s+(.*?)(?:END-EXEC|;)", re.DOTALL)
CICS_ARGUMENT = re.compile(
    r"(?<![A-Z0-9-])(PROGRAM|TRANSID|MAPSET|MAP|FILE|DATASET|QUEUE|QNAME|CHANNEL|CONTAINER)"
    r"\s*\(\s*(['\"]?)([^)'\"]+)\2\s*\)"
)
CICS_RELATIONS = {
    "TRANSID": "cics-transid",
    "MAPSET": "bms-mapset",
    "MAP": "bms-map",
    "FILE": "cics-file",
    "DATASET": "cics-file",
    "QUEUE": "cics-queue",
    "QNAME": "cics-queue",
    "CHANNEL": "cics-channel",
    "CONTAINER": "cics-container",
}
CICS_TWO_WORD_COMMANDS = frozenset({"SEND", "RECEIVE", "HANDLE", "WRITEQ", "READQ", "DELETEQ"})
PROGRAM_RELATIONS = frozenset(
    {"call", "cics-link", "cics-xctl", "cics-load", "jcl-exec", "load-link"}
)
COPYBOOK_ENTRY = re.compile(
    r"^.{0,10}?\b\d{1,2}\s+"
    + NAME
    + r"(?:\s+(?:PIC|PICTURE|COMP\S*|VALUE|OCCURS|REDEFINES|USAGE)\b|\s*\.)",
    re.MULTILINE,
)
CLASSIFY_RULES = (
    ("bms", re.compile(r"^\S*\s+DFHMSD\s", re.MULTILINE)),
    ("cics-csd", re.compile(r"^\s*DEFINE\s+(?:TRANSACTION|TRANS|PROGRAM)\(", re.MULTILINE)),
    ("ims-psb", re.compile(r"\bPSBGEN\b")),
    ("ims-dbd", re.compile(r"^\s*DBD\s+NAME=", re.MULTILINE)),
    ("cobol-program", re.compile(r"\b(?:IDENTIFICATION|ID)\s+DIVISION\b|\bPROGRAM-ID\b")),
    ("pli-program", re.compile(r"\bPROC(?:EDURE)?\s+OPTIONS\s*\(\s*MAIN")),
    ("dclgen", re.compile(r"EXEC\s+SQL\s+DECLARE\s+\S+\s+TABLE")),
    ("sql-ddl", re.compile(r"^\s*CREATE\s+(?:TABLE|VIEW|INDEX|TABLESPACE)\b", re.MULTILINE)),
    ("assembler", re.compile(r"^\S*\s+(?:CSECT|RSECT|DSECT)\b", re.MULTILINE)),
    ("easytrieve", re.compile(r"^\s*JOB\s+INPUT\b", re.MULTILINE)),
    ("dfsort-control", re.compile(r"^\s*(?:SORT|MERGE)\s+FIELDS=|^\s*OUTFIL\b", re.MULTILINE)),
    (
        "idcams-control",
        re.compile(r"^\s*(?:DEFINE\s+(?:CLUSTER|GDG|AIX|PATH)|REPRO|LISTCAT)\b", re.MULTILINE),
    ),
    ("tso-db2-control", re.compile(r"^\s*DSN\s+SYSTEM\(", re.MULTILINE)),
    ("cobol-copybook", COPYBOOK_ENTRY),
)
SORT_STATEMENT = re.compile(
    r"^\s*(SORT|MERGE|INCLUDE|OMIT|INREC|OUTREC|OUTFIL|SUM|JOINKEYS)\b", re.MULTILINE
)
SORT_LOGIC = frozenset({"INCLUDE", "OMIT", "INREC", "OUTREC", "OUTFIL", "SUM", "JOINKEYS"})
PROC_PROGRAM_SYMBOLS = ("MBR", "PGM", "PROG", "PROGRAM", "PGMNAME")
SQL_TABLE_CONTEXT = re.compile(
    r"(?<![A-Z0-9_])(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(" + NAME + r"(?:\." + NAME + ")?)"
)
SQL_CLAUSE_END = re.compile(
    r"(?<![A-Z0-9_])(?:WHERE|GROUP|HAVING|ORDER|FETCH|FOR|WITH|UNION|EXCEPT|INTERSECT|"
    r"OPTIMIZE|QUERYNO|SET|VALUES|ON)(?![A-Z0-9_])"
)
SELECT_ASSIGN = re.compile(
    _word("SELECT")
    + r"\s+(?:OPTIONAL\s+)?("
    + NAME
    + r")\s+ASSIGN\s+(?:TO\s+)?['\"]?("
    + NAME
    + r")['\"]?(.*?)\.(?:\s|$)",
    re.DOTALL,
)
ORGANIZATION = re.compile(_word(r"ORGANIZATION") + r"\s+(?:IS\s+)?(INDEXED|RELATIVE|SEQUENTIAL)")
DLI_FUNCTION = re.compile(
    r"VALUE\s+'(GU|GHU|GN|GHN|GNP|GHNP|ISRT|REPL|DLET|CHKP|XRST|ROLB|ROLL|SYNC)\s*'"
)
IDMS_DML = re.compile(_word(r"BIND\s+RUN-UNIT|COPY\s+IDMS|OBTAIN\s+(?:CALC|NEXT|FIRST|OWNER)"))
JCL_PGM = re.compile(r"(?:^|,)PGM=([A-Z0-9@#$*.]+)")
JCL_PROC = re.compile(r"^(?:PROC=)?([A-Z0-9@#$]+)(?:,|$)")
JCL_DSN = re.compile(r"(?:^|,)DSN(?:AME)?=([^,\s]+)")
JCL_DISP = re.compile(r"(?:^|,)DISP=\(?([A-Z]+)")
JCL_PARM = re.compile(r"(?:^|,)PARM=(?:\(?'([^']*)'|\(([^)]*)\)|([^,\s]+))")
JCL_INCLUDE = re.compile(r"MEMBER=([A-Z0-9@#$]+)")
TSO_RUN = re.compile(r"RUN\s+PROGRAM\(\s*(" + NAME + r")\s*\)(?:.*?PLAN\(\s*(" + NAME + r")\s*\))?")
CSD_DEFINE = re.compile(r"DEFINE\s+(TRANSACTION|TRANS|PROGRAM|FILE|MAPSET)\(\s*([^)\s]+)\s*\)")
CSD_ATTRIBUTE = re.compile(r"(PROGRAM|GROUP|DSNAME)\(\s*([^)\s]+)\s*\)")


@dataclass
class Member:
    """One analyzed source member."""

    path: str
    name: str
    kind: str
    lines: int
    code_lines: int
    encoding: str
    program_id: str | None = None
    references: dict[str, set[str]] = field(default_factory=dict)
    subsystems: set[str] = field(default_factory=set)
    risks: Counter[str] = field(default_factory=Counter)
    details: dict[str, Any] = field(default_factory=dict)

    def add(self, relation: str, *targets: str) -> None:
        """Record dependency targets under ``relation``."""
        cleaned = {target.strip().upper() for target in targets if target and target.strip()}
        if cleaned:
            self.references.setdefault(relation, set()).update(cleaned)


def _decode(data: bytes) -> tuple[str, str] | None:
    """Decode source bytes, detecting EBCDIC 80-byte records; None means binary."""
    sample = data[:65536]
    if (
        data
        and b"\n" not in sample
        and len(data) % 80 == 0
        and sample.count(0x40) > max(sample.count(0x20), len(sample) // 20)
    ):
        text = data.decode("cp037", errors="replace")
        records = (text[index : index + 80] for index in range(0, len(text), 80))
        return "\n".join(record.rstrip() for record in records), "ebcdic-cp037"
    if b"\x00" in sample:
        return None
    return data.decode("utf-8", errors="replace"), "text"


def _is_free_format(lines: Sequence[str]) -> bool:
    return any(">>SOURCE" in line.upper() and "FREE" in line.upper() for line in lines)


def _cobol_code(lines: Sequence[str]) -> list[str]:
    """Return COBOL code lines with sequence, indicator, and identification areas removed."""
    if _is_free_format(lines):
        return [line for line in lines if not line.lstrip().startswith(("*>", ">>"))]
    code: list[str] = []
    for line in lines:
        if len(line) < 7 or line[6] in "*/Dd":
            continue
        if line[6] == "-" and code:
            code[-1] = code[-1].rstrip() + line[7:72].lstrip()
        else:
            code.append(line[7:72])
    return code


def _classify(path: Path, lines: Sequence[str], upper: str) -> str:
    """Return the artifact kind for a member, using content first and suffix second."""
    first = next((line for line in lines if line.strip() and not line.startswith("//*")), "")
    if first.startswith("//"):
        if re.search(r"^//\S+\s+JOB\b", upper, re.MULTILINE):
            return "jcl-job"
        if re.search(r"^//\S*\s+PROC\b", upper, re.MULTILINE):
            return "jcl-proc"
        return "jcl-include"
    head = "\n".join(lines[:3]).upper()
    if "/*" in head and "REXX" in head:
        return "rexx"
    if re.search(r"\bMFLD\b", upper) and re.search(r"\bDFLD\b", upper):
        return "mfs"
    for kind, pattern in CLASSIFY_RULES:
        if pattern.search(upper):
            return kind
    return SUFFIX_KIND.get(path.suffix.lower(), "unknown")


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


def _analyze_exec_blocks(member: Member, code: str) -> None:
    cics_commands: set[str] = set()
    sql_kinds: Counter[str] = Counter()
    for match in EXEC_BLOCK.finditer(code):
        interface, body = match.group(1), " ".join(match.group(2).split())
        words = body.split()
        verb = words[0] if words else "?"
        if interface == "CICS":
            member.subsystems.add("cics")
            command = verb
            if verb in CICS_TWO_WORD_COMMANDS and len(words) > 1:
                command = f"{verb} {words[1].split('(')[0]}"
            cics_commands.add(command)
            for option, quote, value in CICS_ARGUMENT.findall(body):
                relation = CICS_RELATIONS.get(option, f"cics-{verb.lower()}")
                if quote:
                    member.add(relation, value)
                elif option == "PROGRAM":
                    member.risks["dynamic_call"] += 1
        elif interface == "SQL":
            member.subsystems.add("db2")
            sql_kinds[verb] += 1
            if verb == "INCLUDE" and len(words) > 1:
                member.add("copy", words[1])
            member.add("db2-table", *_sql_tables(body))
            procedure = re.match(r"CALL\s+(" + NAME + r"(?:\." + NAME + ")?)", body)
            if procedure:
                member.add("db2-procedure", procedure.group(1))
        else:
            member.subsystems.add("ims")
    if cics_commands:
        member.details["cics_commands"] = sorted(cics_commands)
    if sql_kinds:
        member.details["sql_statements"] = dict(sorted(sql_kinds.items()))


def _analyze_cobol(member: Member, lines: Sequence[str]) -> None:
    code_lines = _cobol_code(lines)
    member.code_lines = sum(1 for line in code_lines if line.strip())
    code = "\n".join(code_lines).upper()
    plain = EXEC_BLOCK.sub(" ", code)
    program_id = PROGRAM_ID.search(code)
    member.program_id = program_id.group(1).upper() if program_id else None
    member.add("copy", *COPY_MEMBER.findall(plain))
    member.add("copy", *LIBRARIAN_INCLUDE.findall("\n".join(lines).upper()))
    for target in STATIC_CALL.findall(plain):
        family = INTERFACE_FAMILY.get(target)
        if family:
            member.subsystems.add(family)
            member.add(f"{family}-call", target)
        else:
            member.add("call", target)
    dynamic = sorted(set(DYNAMIC_CALL.findall(plain)))
    if dynamic:
        member.risks["dynamic_call"] += len(dynamic)
        member.details["dynamic_call_via"] = dynamic
    _analyze_exec_blocks(member, code)
    if IDMS_DML.search(code):
        member.subsystems.add("idms")
    dli = sorted(set(DLI_FUNCTION.findall(code)))
    if dli:
        member.subsystems.add("ims")
        member.details["dli_functions"] = dli
    files = []
    for select, assign, tail in SELECT_ASSIGN.findall(code):
        organization = ORGANIZATION.search(tail)
        files.append(
            {
                "select": select,
                "ddname": assign.split("-")[-1],
                "organization": organization.group(1) if organization else "SEQUENTIAL",
            }
        )
    if files:
        member.subsystems.add("files")
        member.details["files"] = files
        member.add("ddname", *(entry["ddname"] for entry in files))
    for risk, pattern in RISK_PATTERNS.items():
        count = len(pattern.findall(code))
        if count:
            member.risks[risk] += count


def _analyze_pli_or_assembler(member: Member, lines: Sequence[str], upper: str) -> None:
    member.code_lines = sum(1 for line in lines if line.strip() and not line.startswith("*"))
    member.add("copy", *re.findall(r"%INCLUDE\s+(" + NAME + ")", upper))
    member.add("call", *re.findall(r"\bCALL\s+(" + NAME + ")", upper))
    member.add("load-link", *re.findall(r"\b(?:LINK|XCTL|LOAD)\s+EP=(" + NAME + ")", upper))
    if member.kind == "assembler":
        member.details["sections"] = sorted(
            set(re.findall(r"^(" + NAME + r")\s+(?:CSECT|RSECT)\b", upper, re.MULTILINE))
        )
        svc_count = len(re.findall(r"\bSVC\s+\d+", upper))
        if svc_count:
            member.risks["svc"] = svc_count
    _analyze_exec_blocks(member, upper)


@dataclass
class _JclStatement:
    name: str
    operation: str
    operands: str
    instream: list[str] = field(default_factory=list)


def _strip_jcl_comment(operands: str) -> str:
    """Return the operand field, dropping the comment that follows the first blank."""
    quoted = False
    for index, char in enumerate(operands):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return operands[:index]
    return operands


def _jcl_statements(lines: Sequence[str]) -> list[_JclStatement]:
    """Parse JCL into logical statements, joining continuations and in-stream data."""
    statements: list[_JclStatement] = []
    instream: _JclStatement | None = None
    delimiter = "/*"
    continuing = False
    for raw in lines:
        line = raw.rstrip()
        if instream is not None:
            if line.startswith(delimiter) or (delimiter == "/*" and line.startswith("//")):
                instream = None
                if not line.startswith("//"):
                    continue
            else:
                instream.instream.append(line[:72])
                continue
        if line.startswith("//*") or not line.startswith("//"):
            continue
        body = line[2:71]
        if continuing and statements and body[:1] == " ":
            statements[-1].operands += _strip_jcl_comment(body.strip())
            continuing = statements[-1].operands.endswith(",")
            continue
        name, _, rest = body.partition(" ") if not body.startswith(" ") else ("", "", body)
        operation, _, operands = rest.strip().partition(" ")
        statement = _JclStatement(name, operation.upper(), _strip_jcl_comment(operands.strip()))
        statements.append(statement)
        continuing = statement.operands.endswith(",")
        if statement.operation == "DD" and re.match(r"(?:\*|DATA)(?:,|$)", statement.operands):
            instream = statement
            custom = re.search(r"DLM=(?:'([^']+)'|([^,\s]+))", statement.operands)
            delimiter = (custom.group(1) or custom.group(2)) if custom else "/*"
    return statements


def _analyze_jcl(member: Member, lines: Sequence[str]) -> None:
    statements = _jcl_statements(lines)
    member.code_lines = len(statements)
    steps: list[dict[str, Any]] = []
    datasets: list[dict[str, str]] = []
    step: dict[str, Any] | None = None
    for statement in statements:
        operands = statement.operands.upper()
        if statement.operation in {"JOB", "PROC"} and not member.details.get("name"):
            member.details["name"] = statement.name.upper()
        elif statement.operation == "EXEC":
            program = JCL_PGM.search(operands)
            proc = None if program else JCL_PROC.match(operands)
            step = {
                "step": statement.name.upper(),
                "program": program.group(1) if program else None,
            }
            if proc:
                step["proc"] = proc.group(1)
                member.add("jcl-proc", proc.group(1))
                overrides = dict(re.findall(r",([A-Z0-9@#$]+)=([^,]+)", operands))
                for symbol in PROC_PROGRAM_SYMBOLS:
                    if symbol in overrides:
                        step["proc_program"] = overrides[symbol].strip("'")
                        member.add("jcl-exec", step["proc_program"])
                        break
            parm = JCL_PARM.search(operands)
            if program and program.group(1) == "DFSRRC00" and parm:
                fields = next(group for group in parm.groups() if group is not None).split(",")
                if len(fields) > 2:
                    step.update(region=fields[0], ims_program=fields[1], psb=fields[2])
                    member.add("jcl-exec", fields[1])
                    member.add("ims-psb", fields[2])
            if program and program.group(1) in UTILITY_PROGRAMS:
                step["utility"] = UTILITY_PROGRAMS[program.group(1)]
            if program and not program.group(1).startswith("*"):
                member.add("jcl-exec", program.group(1))
            steps.append(step)
        elif statement.operation == "DD":
            dsn = JCL_DSN.search(operands)
            disp = JCL_DISP.search(operands)
            if dsn:
                datasets.append(
                    {
                        "step": (step or {}).get("step", ""),
                        "dd": statement.name.upper(),
                        "dsn": dsn.group(1),
                        "disp": disp.group(1) if disp else "",
                    }
                )
                member_ref = re.search(r"\((" + NAME + r")\)$", dsn.group(1))
                if member_ref and not re.fullmatch(r"[+-]?\d+", member_ref.group(1)):
                    member.add("control-member", member_ref.group(1))
            if step is not None and statement.instream:
                data = "\n".join(statement.instream).upper()
                if step.get("program") in DB2_TSO_PROGRAMS:
                    for program, plan in TSO_RUN.findall(data):
                        step.setdefault("db2_programs", []).append(program)
                        member.add("jcl-exec", program)
                        if plan:
                            member.add("db2-plan", plan)
                if step.get("utility") == "sort":
                    sort_statements = set(SORT_STATEMENT.findall(data))
                    step["sort_statements"] = sorted(sort_statements)
                    if sort_statements & SORT_LOGIC:
                        member.risks["business_logic_in_sort"] += 1
        elif statement.operation == "INCLUDE":
            member.add("jcl-include", *JCL_INCLUDE.findall(operands))
    member.details["steps"] = steps
    if datasets:
        member.details["datasets"] = datasets
        gdg = [entry["dsn"] for entry in datasets if re.search(r"\([+-]?\d+\)$", entry["dsn"])]
        if gdg:
            member.risks["gdg_relative_reference"] = len(gdg)


def _analyze_definitions(member: Member, upper: str) -> None:
    """Extract names from BMS, CSD, PSB, DBD, DCLGEN, DDL, and control-card members."""
    kind = member.kind
    if kind == "bms":
        mapset = re.search(r"^(" + NAME + r")\s+DFHMSD\s", upper, re.MULTILINE)
        member.details["mapset"] = mapset.group(1) if mapset else member.name
        member.details["maps"] = re.findall(r"^(" + NAME + r")\s+DFHMDI\s", upper, re.MULTILINE)
    elif kind == "cics-csd":
        flat = " ".join(upper.split())
        transactions: dict[str, str] = {}
        definitions = list(CSD_DEFINE.finditer(flat))
        for index, match in enumerate(definitions):
            end = definitions[index + 1].start() if index + 1 < len(definitions) else len(flat)
            attributes = dict(CSD_ATTRIBUTE.findall(flat[match.end() : end]))
            resource, name = match.group(1), match.group(2)
            if resource in {"TRANSACTION", "TRANS"} and "PROGRAM" in attributes:
                transactions[name] = attributes["PROGRAM"]
                member.add("cics-transaction-program", attributes["PROGRAM"])
            elif resource == "FILE" and "DSNAME" in attributes:
                member.details.setdefault("files", {})[name] = attributes["DSNAME"]
            elif resource == "PROGRAM":
                member.details.setdefault("programs", []).append(name)
        member.details["transactions"] = transactions
    elif kind == "ims-psb":
        member.details["databases"] = sorted(set(re.findall(r"DBDNAME=(" + NAME + ")", upper)))
        member.add("ims-dbd", *member.details["databases"])
    elif kind == "ims-dbd":
        access = re.search(r"ACCESS=\(?(" + NAME + ")", upper)
        member.details["access"] = access.group(1) if access else None
        member.details["segments"] = re.findall(r"SEGM\s+NAME=(" + NAME + ")", upper)
    elif kind == "dclgen":
        member.add("db2-table", *re.findall(r"DECLARE\s+(\S+)\s+TABLE", upper))
    elif kind == "sql-ddl":
        objects = re.findall(r"CREATE\s+(?:UNIQUE\s+)?(TABLE|VIEW|INDEX)\s+(\S+)", upper)
        member.details["objects"] = [f"{object_type} {name}" for object_type, name in objects]
    elif kind == "dfsort-control":
        statements = set(SORT_STATEMENT.findall(upper))
        member.details["statements"] = sorted(statements)
        if statements & SORT_LOGIC:
            member.risks["business_logic_in_sort"] = 1
    elif kind == "tso-db2-control":
        for program, plan in TSO_RUN.findall(" ".join(upper.split())):
            member.add("jcl-exec", program)
            if plan:
                member.add("db2-plan", plan)
    elif kind == "idcams-control":
        member.details["clusters"] = re.findall(r"NAME\(\s*([^)\s]+)\s*\)", upper)


def analyze_member(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> Member | None:
    """Analyze one file, returning None for binary, oversized, or non-source files."""
    if path.suffix.lower() not in SOURCE_SUFFIXES or path.stat().st_size > max_bytes:
        return None
    decoded = _decode(path.read_bytes())
    if decoded is None:
        return None
    text, encoding = decoded
    lines = text.splitlines()
    upper = text.upper()
    kind = _classify(path, lines, upper)
    member = Member(str(path), path.stem.upper(), kind, len(lines), 0, encoding)
    if kind in {"cobol-program", "cobol-copybook", "dclgen"}:
        _analyze_cobol(member, lines)
    elif kind.startswith("jcl"):
        _analyze_jcl(member, lines)
    elif kind in {"pli-program", "assembler", "assembler-macro"}:
        _analyze_pli_or_assembler(member, lines, upper)
    else:
        member.code_lines = sum(1 for line in lines if line.strip())
    _analyze_definitions(member, upper)
    return member


def _walk(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).parts
            if path.is_file() and not any(part.startswith(".") for part in relative):
                yield path


def _is_external(name: str) -> bool:
    return name.startswith(SYSTEM_PROGRAM_PREFIXES) or name in INTERFACE_FAMILY


def build_inventory(roots: Sequence[Path], max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Scan ``roots`` and return the inventory as a JSON-serializable dictionary."""
    members = [m for path in _walk(roots) if (m := analyze_member(path, max_bytes)) is not None]
    names_by_kind: dict[str, set[str]] = {}
    for member in members:
        names_by_kind.setdefault(member.kind, set()).add(member.name)
        if member.program_id:
            names_by_kind.setdefault(member.kind, set()).add(member.program_id)
    programs = set().union(*(names_by_kind.get(kind, set()) for kind in PROGRAM_KINDS))
    copybooks = set().union(*(names_by_kind.get(kind, set()) for kind in COPY_KINDS))
    procs = names_by_kind.get("jcl-proc", set())
    includes = names_by_kind.get("jcl-include", set()) | procs

    edges: list[dict[str, str]] = []
    unresolved: dict[str, set[str]] = {"copybooks": set(), "programs": set(), "jcl": set()}
    external: set[str] = set()
    for member in members:
        source = member.program_id or member.details.get("name") or member.name
        for relation, targets in sorted(member.references.items()):
            for target in sorted(targets):
                edges.append({"from": source, "to": target, "type": relation})
                if relation == "copy" and target not in copybooks:
                    if target.startswith(SYSTEM_COPY_PREFIXES):
                        external.add(target)
                    else:
                        unresolved["copybooks"].add(target)
                elif relation in PROGRAM_RELATIONS:
                    if _is_external(target):
                        external.add(target)
                    elif target not in programs:
                        unresolved["programs"].add(target)
                elif relation in {"jcl-proc", "jcl-include"} and target not in includes:
                    unresolved["jcl"].add(target)

    duplicates = Counter((member.kind, member.name) for member in members)
    transactions: dict[str, str] = {}
    kinds: Counter[str] = Counter()
    loc: Counter[str] = Counter()
    subsystems: Counter[str] = Counter()
    risk_totals: Counter[str] = Counter()
    for member in members:
        transactions.update(member.details.get("transactions", {}))
        kinds[member.kind] += 1
        loc[member.kind] += member.code_lines
        subsystems.update(member.subsystems)
        risk_totals.update(member.risks)

    return {
        "tool": "mainframe_inventory",
        "roots": [str(root) for root in roots],
        "summary": {
            "members": len(members),
            "by_kind": dict(sorted(kinds.items())),
            "code_lines_by_kind": dict(sorted(loc.items())),
            "programs_using": dict(sorted(subsystems.items())),
            "risk_totals": dict(sorted(risk_totals.items())),
            "ebcdic_members": sum(1 for member in members if member.encoding != "text"),
            "duplicate_names": sorted(
                f"{kind}:{name}" for (kind, name), count in duplicates.items() if count > 1
            ),
            "unresolved": {key: sorted(value) for key, value in unresolved.items()},
            "external_or_system": sorted(external),
        },
        "cics_transactions": dict(sorted(transactions.items())),
        "members": [_member_dict(member) for member in members],
        "edges": edges,
    }


def _risk_score(risks: Counter[str]) -> int:
    return sum(RISK_WEIGHTS.get(name, 0) * count for name, count in risks.items())


def _member_dict(member: Member) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": member.path,
        "name": member.name,
        "kind": member.kind,
        "lines": member.lines,
        "code_lines": member.code_lines,
    }
    if member.encoding != "text":
        entry["encoding"] = member.encoding
    if member.program_id and member.program_id != member.name:
        entry["program_id"] = member.program_id
    if member.subsystems:
        entry["subsystems"] = sorted(member.subsystems)
    if member.references:
        entry["references"] = {
            key: sorted(value) for key, value in sorted(member.references.items())
        }
    if member.risks:
        entry["risks"] = dict(sorted(member.risks.items()))
        entry["risk_score"] = _risk_score(member.risks)
    if member.details:
        entry["details"] = member.details
    return entry


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return [*lines, ""]


def inventory_to_markdown(inventory: dict[str, Any], top: int = 15) -> str:
    """Render the inventory as a Markdown report."""
    summary = inventory["summary"]
    lines = ["# Mainframe inventory", "", f"Scanned: {', '.join(inventory['roots'])}", ""]
    lines += ["## Members by kind", ""]
    lines += _table(
        ["Kind", "Members", "Code lines"],
        (
            (kind, count, summary["code_lines_by_kind"].get(kind, 0))
            for kind, count in summary["by_kind"].items()
        ),
    )
    if summary["programs_using"]:
        lines += ["## Subsystem and interface usage", ""]
        lines += _table(["Subsystem", "Members"], summary["programs_using"].items())
    if inventory["cics_transactions"]:
        lines += ["## CICS transactions", ""]
        lines += _table(["Transaction", "Program"], inventory["cics_transactions"].items())
    jobs = [m for m in inventory["members"] if m["kind"] in {"jcl-job", "jcl-proc"}]
    if jobs:
        lines += ["## Batch jobs and procedures", ""]
        rows = []
        for job in jobs:
            for step in job.get("details", {}).get("steps", []):
                runs = step.get("program") or f"PROC {step.get('proc', '?')}"
                hidden = [
                    *step.get("db2_programs", []),
                    step.get("ims_program"),
                    step.get("proc_program"),
                ]
                extra = ", ".join(name for name in hidden if name)
                rows.append((job["name"], step["step"], runs, step.get("utility", ""), extra))
        lines += _table(["Job/Proc", "Step", "Runs", "Utility", "Program behind utility"], rows)
    risky = sorted(
        (m for m in inventory["members"] if m.get("risk_score")),
        key=lambda m: (-m["risk_score"], m["name"]),
    )[:top]
    if risky:
        lines += ["## Highest-risk members", ""]
        lines += _table(
            ["Member", "Kind", "Score", "Indicators"],
            (
                (
                    m["name"],
                    m["kind"],
                    m["risk_score"],
                    ", ".join(f"{name} {count}" for name, count in m["risks"].items()),
                )
                for m in risky
            ),
        )
    unresolved = summary["unresolved"]
    if any(unresolved.values()):
        lines += ["## Unresolved references", ""]
        lines += [
            f"- **{key}**: {', '.join(values)}" for key, values in unresolved.items() if values
        ]
        lines.append("")
    if summary["duplicate_names"]:
        lines += ["## Duplicate member names", "", ", ".join(summary["duplicate_names"]), ""]
    if summary["ebcdic_members"]:
        lines += [f"{summary['ebcdic_members']} members were decoded from EBCDIC (cp037).", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, scan the roots, and print the inventory."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("roots", nargs="+", type=Path, help="Directories or files to scan.")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Skip files larger than this many bytes (default: {DEFAULT_MAX_BYTES}).",
    )
    args = parser.parse_args(argv)
    missing = [str(root) for root in args.roots if not root.exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    inventory = build_inventory(args.roots, args.max_bytes)
    if args.output_format == "markdown":
        print(inventory_to_markdown(inventory))
    else:
        print(json.dumps(inventory, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
