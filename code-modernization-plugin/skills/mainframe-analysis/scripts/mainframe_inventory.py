#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Inventory mainframe application source exported to a local directory.

Classifies each member (COBOL program or copybook, PL/I program or include, Assembler program
or macro, JCL job, procedure, or include, BMS or MFS map, IMS DBD or PSB, CICS CSD extract,
DCLGEN, SQL DDL, utility control cards, IDCAMS LISTCAT report, MQSC definitions, scheduler
export, compiler or binder listing, REXX, CLIST, ISPF panel or skeleton, Easytrieve, Natural)
and extracts dependencies: COPY and INCLUDE members, static and dynamic CALLs (resolved through
VALUE clauses and MOVE statements when they name the target), CICS LINK, XCTL, START, and
RETURN TRANSID targets, Db2 tables and remote locations, IMS segments, MQ queues, file
assignments, JCL step programs (including programs run through IKJEFT01 and DFSRRC00), data
sets, file transfers, and CICS transaction-to-program mappings.

It tags how each member uses each resource (C create, R read, U update, D delete); reads the
CSD, IDCAMS (DEFINE and LISTCAT), MQSC, Db2 BIND, listing, and scheduler definitions it finds;
cross-checks COBOL file definitions against VSAM clusters; flags data sets that CICS and batch
both update; assesses CICS threadsafe readiness; and lists unreferenced members as dead-code
candidates, confirmed with usage evidence passed through --usage. Roots are searched in order,
like a library concatenation: when names repeat, the first member wins and the rest are
shadowed.

Members exported in binary are decoded from EBCDIC with --codepage (default 037), as fixed
80-byte records, RDW-prefixed variable records, or z/OS UNIX new-line text.

The scan is static and heuristic: confirm findings against compiler listings and
cross-reference tools. The script only reads files.

Examples:
    uv run --script mainframe_inventory.py src/mainframe
    uv run --script mainframe_inventory.py COBOL COPYLIB JCL --format markdown
    uv run --script mainframe_inventory.py exports --codepage 1141 --usage smf-programs.csv
    uv run --script mainframe_inventory.py exports --previous last.json > inventory.json
    uv run --script mainframe_inventory.py exports --format jsonl > inventory.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import zos_definitions
import zos_encoding

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

DEFAULT_MAX_BYTES = 5_000_000
NAME = r"[A-Z0-9@#$][A-Z0-9@#$_-]*"

SOURCE_SUFFIXES = frozenset(
    {
        "",
        ".asm",
        ".bind",
        ".bms",
        ".cbl",
        ".ccp",
        ".clist",
        ".csv",
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
        ".list",
        ".listing",
        ".lst",
        ".mac",
        ".map",
        ".mfs",
        ".mlc",
        ".mqsc",
        ".nat",
        ".nsn",
        ".nsp",
        ".panel",
        ".parm",
        ".pl1",
        ".pli",
        ".pnl",
        ".prc",
        ".proc",
        ".psb",
        ".rex",
        ".rexx",
        ".skel",
        ".sql",
        ".src",
        ".sysin",
        ".txt",
        ".xml",
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
    ".nat": "natural",
    ".nsp": "natural",
    ".nsn": "natural",
    ".skel": "ispf-skeleton",
    ".pnl": "ispf-panel",
    ".panel": "ispf-panel",
    ".mqsc": "mqsc",
}
PROGRAM_KINDS = frozenset(
    {"cobol-program", "pli-program", "assembler", "easytrieve", "rexx", "clist", "natural"}
)
COPY_KINDS = frozenset({"cobol-copybook", "dclgen", "pli-include", "assembler-macro"})
SYSTEM_COPY_PREFIXES = ("DFH", "CMQ", "SQLCA", "SQLDA", "CEE", "IGZ", "DSN", "IDMS")
INTERFACE_CALLS = {
    "ims": ("CBLTDLI", "AIBTDLI", "CEETDLI", "AERTDLI", "PLITDLI", "ASMTDLI", "CTDLI"),
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
    "SDSF",
    "ISF",
    "CSQ",
    "IRR",
    "ICH",
    "ASMA",
    "IFASMF",
    "GIM",
    "AMASPZAP",
    "AMBLIST",
    "HEWL",
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
    (
        "mqsc",
        re.compile(
            r"^\s*DEFINE\s+(?:QLOCAL|QL|QREMOTE|QR|QALIAS|QA|QMODEL|QM|CHANNEL|CHL|PROCESS)\s*\(",
            re.MULTILINE,
        ),
    ),
    (
        "schedule",
        re.compile(r"<(?:DEFTABLE|FOLDER|SMART_FOLDER|SCHED_TABLE)\b|^ADSTART\b", re.MULTILINE),
    ),
    ("natural", re.compile(r"^\s*DEFINE\s+DATA\b[\s\S]*\bEND-DEFINE\b", re.MULTILINE)),
    ("ims-psb", re.compile(r"\bPSBGEN\b")),
    ("ims-dbd", re.compile(r"^\s*DBD\s+NAME=", re.MULTILINE)),
    ("cobol-program", re.compile(r"\b(?:IDENTIFICATION|ID)\s+DIVISION\b|\bPROGRAM-ID\b")),
    ("pli-program", re.compile(r"\bPROC(?:EDURE)?\s+OPTIONS\s*\(\s*MAIN")),
    ("pli-program", re.compile(r"^\s*[A-Z0-9_#@$]+\s*:\s*PROC(?:EDURE)?\b", re.MULTILINE)),
    ("pli-include", re.compile(r"^\s*(?:DCL|DECLARE)\s+\d+\s+[A-Z0-9_#@$]+", re.MULTILINE)),
    ("dclgen", re.compile(r"EXEC\s+SQL\s+DECLARE\s+\S+\s+TABLE")),
    (
        "sql-ddl",
        re.compile(
            r"^\s*(?:CREATE|ALTER|DROP)\s+(?:UNIQUE\s+|AUXILIARY\s+|LOB\s+)?"
            r"(?:TABLE|VIEW|INDEX|TABLESPACE|DATABASE|STOGROUP|ALIAS|SYNONYM|TRIGGER|PROCEDURE)\b",
            re.MULTILINE,
        ),
    ),
    (
        "sql-dml",
        re.compile(
            r"^\s*(?:INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|UPDATE\s+\S+\s+SET)\b",
            re.MULTILINE,
        ),
    ),
    ("assembler", re.compile(r"^\S*\s+(?:CSECT|RSECT)\b", re.MULTILINE)),
    ("assembler-macro", re.compile(r"^\S*\s+DSECT\b|^\s+MACRO\s*$", re.MULTILINE)),
    ("clist", re.compile(r"^\s*PROC\s+\d+\b", re.MULTILINE)),
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
    r"(?<![A-Z0-9_])(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(" + NAME + r"(?:\." + NAME + "){0,2})"
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


DEFINITION_PARSERS = {
    "cics-csd": "cics-csd",
    "idcams-control": "idcams",
    "idcams-listcat": "listcat",
    "mqsc": "mqsc",
    "schedule": "schedule",
    "compile-listing": "compile-listing",
    "binder-listing": "binder-listing",
}
CRUD = "CRUD"
DLI_OPERATIONS = {
    "GU": "R",
    "GHU": "R",
    "GN": "R",
    "GHN": "R",
    "GNP": "R",
    "GHNP": "R",
    "ISRT": "C",
    "REPL": "U",
    "DLET": "D",
}
CICS_FILE_OPERATIONS = {
    "READ": "R",
    "READNEXT": "R",
    "READPREV": "R",
    "STARTBR": "R",
    "RESETBR": "R",
    "WRITE": "C",
    "REWRITE": "U",
    "DELETE": "D",
}
CICS_QUEUE_OPERATIONS = {
    "WRITEQ TS": "C",
    "WRITEQ TD": "C",
    "READQ TS": "R",
    "READQ TD": "R",
    "DELETEQ TS": "D",
    "DELETEQ TD": "D",
}
OPEN_MODES = {"INPUT": "R", "OUTPUT": "C", "I-O": "RU", "EXTEND": "C"}
NATURAL_DML = {
    "READ": "R",
    "FIND": "R",
    "HISTOGRAM": "R",
    "GET": "R",
    "STORE": "C",
    "UPDATE": "U",
    "DELETE": "D",
}
UTILITY_OUTPUT_DDS = re.compile(r"^(?:SORTOUT|SORTOF\w*|SYSUT2|OUTDD\w*)$")
MACRO_PURPOSE = {
    "io": ("GET", "PUT", "OPEN", "CLOSE", "READ", "WRITE", "CHECK", "POINT", "DCB", "ACB", "RPL"),
    "storage": ("GETMAIN", "FREEMAIN", "STORAGE", "CPOOL"),
    "time": ("TIME", "STCK", "STCKF", "STIMER", "STIMERM", "CONVTOD"),
    "serialization": ("ENQ", "DEQ", "RESERVE", "ISGENQ"),
    "recovery": ("ESTAE", "ESTAEX", "ESPIE", "SPIE", "SETRP", "SDUMP", "SDUMPX"),
    "messages": ("WTO", "WTOR", "WTL", "MGCRE"),
    "dynamic-allocation": ("DYNALLOC",),
    "security": ("RACROUTE", "RACHECK", "RACINIT"),
    "program-control": ("LINK", "LINKX", "LOAD", "XCTL", "XCTLX", "ATTACH", "ATTACHX"),
}
MACRO_CATEGORY = {macro: purpose for purpose, names in MACRO_PURPOSE.items() for macro in names}
EXIT_NAME = re.compile(
    r"^(?:IEFU\w+|IEFACTRT|IEFUJV|ICHRTX\d\d|ICHRIX\d\d|DFHXCOPT|DFHPEP|E15\w*|E35\w*)$"
)
FIXED_LISTS = frozenset({"shareoptions"})
DEFAULT_RESERVED_WORDS = frozenset({"JSON", "END-JSON", "JSON-CODE", "JSON-STATUS"})
STOP_WORDS = frozenset(
    {
        "ACCEPT",
        "ADD",
        "AND",
        "BY",
        "CALL",
        "CLOSE",
        "COMPUTE",
        "CONTINUE",
        "DELETE",
        "DISPLAY",
        "DIVIDE",
        "ELSE",
        "END-CALL",
        "END-IF",
        "END-PERFORM",
        "END-EVALUATE",
        "EVALUATE",
        "EXEC",
        "EXIT",
        "GO",
        "GOBACK",
        "IF",
        "INITIALIZE",
        "INSPECT",
        "MOVE",
        "MULTIPLY",
        "NOT",
        "OPEN",
        "OR",
        "PERFORM",
        "READ",
        "RETURNING",
        "REWRITE",
        "SEARCH",
        "SET",
        "START",
        "STOP",
        "STRING",
        "SUBTRACT",
        "THEN",
        "UNSTRING",
        "USING",
        "WHEN",
        "WRITE",
    }
)
PASSING_WORDS = frozenset(
    {"BY", "REFERENCE", "CONTENT", "VALUE", "ADDRESS", "OF", "LENGTH", "OMITTED"}
)
DATA_ENTRY = re.compile(
    r"(?<![A-Z0-9-])(\d{1,2})\s+(" + NAME + r")((?:'[^']*'|\"[^\"]*\"|[^.'\"])*)\.(?=\s|$)"
)
VALUE_LITERAL = re.compile(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(?:'([^']*)'|\"([^\"]*)\")")
MOVE_LITERAL = re.compile(r"\bMOVE\s+(?:'([^']*)'|\"([^\"]*)\")\s+TO\s+((?:" + NAME + r"[\s,]*)+)")
DLI_CALL = re.compile(
    r"\bCALL\s+['\"](CBLTDLI|AIBTDLI|CEETDLI|AERTDLI)['\"]\s+USING\s+((?:" + NAME + r"[\s,]*)+)"
)
EXEC_DLI = re.compile(r"^\s*(" + "|".join(DLI_OPERATIONS) + r")\b")
SEGMENT_OPTION = re.compile(r"SEGMENT\s*\(\s*['\"]?(" + NAME + r")['\"]?\s*\)")
PSB_OPTION = re.compile(r"PSB\s*\(\s*\(?\s*(['\"]?)(" + NAME + r")\1\s*\)?\s*\)")
MQ_NAME_FIELD = re.compile(r"OBJECTNAME|QNAME|Q-NAME|QUEUE-?(?:NAME|NM|ID)\b|QUEUENAME")
JCL_SYMBOL = re.compile(r"(?<!&)&([A-Z@#$][A-Z0-9@#$]{0,7})\.?")
JCL_SYMBOL_VALUE = re.compile(r"(?:^|,)([A-Z@#$][A-Z0-9@#$]{0,7})=('[^']*'|[^,]*)")
OPEN_STATEMENT = re.compile(
    _word("OPEN") + r"((?:\s+(?:INPUT|OUTPUT|I-O|EXTEND)\b(?:\s+" + NAME + r")+)+)"
)
DELETE_FILE = re.compile(_word("DELETE") + r"\s+(" + NAME + r")\s+RECORD\b")
FD_ENTRY = re.compile(_word(r"FD|SD") + r"\s+(" + NAME + r")((?:'[^']*'|[^.'])*)\.")
RECORD_SIZE = re.compile(
    r"RECORD\s+(?:CONTAINS\s+)?(?:\d+\s+TO\s+)?(\d+)\s+CHARACTERS"
    r"|RECORD\s+(?:IS\s+)?VARYING[^.]*?\bTO\s+(\d+)"
)
COMPILE_OPTIONS = re.compile(r"^\s*(?:CBL|PROCESS)\s+(.+?)\s*$")
CONNECT_TO = re.compile(r"\bCONNECT\s+TO\s+(" + NAME + r")")
THREADSAFE_INDICATORS = {
    "cwa": re.compile(r"\bADDRESS\b[^.]*?\bCWA\b"),
    "shared_getmain": re.compile(r"\bGETMAIN\b[^.]*?\bSHARED\b"),
    "external_data": re.compile(_word("EXTERNAL")),
    "global_work_area": re.compile(r"\bEXTRACT\s+EXIT\b[^.]*?\bGASET\b"),
}
CICS_ENQ = re.compile(r"EXEC\s+CICS\s+ENQ\b")
PLI_RISKS = {
    "go_to": re.compile(r"\bGO\s*TO\b"),
    "on_condition": re.compile(
        r"\bON\s+(?:ERROR|ENDFILE|CONVERSION|ZERODIVIDE|FIXEDOVERFLOW|SIZE|KEY|UNDEFINEDFILE)\b"
    ),
    "pointer": re.compile(r"\b(?:BASED|POINTER|PTR|ADDR)\b"),
    "dynamic_call": re.compile(r"\bFETCH\s+[A-Z0-9_#@$]+"),
    "dynamic_sql": re.compile(r"\b(?:PREPARE|EXECUTE\s+IMMEDIATE)\b"),
}
PLI_FILE = re.compile(r"\b(?:DCL|DECLARE)\s+([A-Z0-9_#@$]+)\s+FILE\b([^;]*);")
PLI_IO = re.compile(r"\b(READ|WRITE|REWRITE|DELETE|LOCATE)\s+FILE\s*\(\s*([A-Z0-9_#@$]+)\s*\)")
PLI_PROCEDURE = re.compile(r"^\s*([A-Z0-9_#@$]+)\s*:\s*PROC(?:EDURE)?\b", re.MULTILINE)
REXX_DATASET = re.compile(r"\b(?:DA|DSN|DATASET)\s*\(\s*['\"]?([A-Z0-9@#$.()+-]+?)['\"]?\s*\)")
REXX_SUBMIT = re.compile(r"\bSUBMIT\s+['\"]{0,2}([A-Z0-9@#$.]+)\(([A-Z0-9@#$]+)\)")
REXX_SKELETON = re.compile(r"\bFTINCL\s+(" + NAME + r")")
REXX_SELECT = re.compile(r"\bSELECT\s+(?:PGM|CMD)\(\s*%?(" + NAME + r")")
REXX_EXECIO = re.compile(r"\bEXECIO\s+\S+\s+(DISKR|DISKRU|DISKW)\s+(" + NAME + r")")
NATURAL_CALL = re.compile(r"\b(?:CALLNAT|FETCH(?:\s+RETURN)?|FETCH\s+REPEAT)\s+'(" + NAME + r")'")
NATURAL_INCLUDE = re.compile(r"^\s*INCLUDE\s+(" + NAME + r")", re.MULTILINE)
NATURAL_USING = re.compile(r"\b(?:LOCAL|PARAMETER|GLOBAL)\s+USING\s+(" + NAME + r")")
NATURAL_VIEW = re.compile(r"\b\d+\s+(" + NAME + r")\s+VIEW\s+(?:OF\s+)?(" + NAME + r")")
# Optional label ("RD."), verb, modifiers such as "(10)" or "(RD.)", then the view, if any.
NATURAL_DML_STATEMENT = re.compile(
    r"(?:(?<![A-Z0-9-])(" + NAME + r")\.\s+)?"
    r"(?<![A-Z0-9-])(READ|FIND|HISTOGRAM|GET|STORE|UPDATE|DELETE)(?![A-Z0-9-])"
    r"((?:\s+(?:\([^)]*\)|MULTI-FETCH|PHYSICAL|LOGICAL|NUMBER|FIRST|UNIQUE|RECORDS?|IN|FILE"
    r"|STATEMENT|FROM|OF|ON|OFF|\d+)(?![A-Z0-9-]))*)"
    r"(?:\s+(" + NAME + r"))?"
)
NATURAL_COMMENT = re.compile(r"^(?:\d{4}\s)?\s*\*(?:[\s*].*)?$|/\*.*$", re.MULTILINE)
NATURAL_REFERENCE = re.compile(r"\(\s*(" + NAME + r")\.?\s*\)")
FTP_COMMAND = re.compile(r"^\s*(PUT|GET|MPUT|MGET|APPEND|APPE)\s+(\S+)(?:\s+(\S+))?", re.IGNORECASE)
CD_COPY = re.compile(r"\bCOPY\s+FROM\s*\((.*?)\)\s*TO\s*\((.*?)\)", re.DOTALL)
CD_DSN = re.compile(r"\bDSN\s*=\s*'?([^\s,)']+)")
HOST_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*(?:\s+\d+)?$")


@dataclass
class ScanOptions:
    """How to read and check members."""

    max_bytes: int = DEFAULT_MAX_BYTES
    codepage: str = "cp037"
    recfm: str = "AUTO"
    lrecl: int | None = None
    reserved_words: frozenset[str] = DEFAULT_RESERVED_WORDS


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
    access: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    stat: list[int] | None = None

    def add(self, relation: str, *targets: str) -> None:
        """Record dependency targets under ``relation``."""
        cleaned = {target.strip().upper() for target in targets if target and target.strip()}
        if cleaned:
            self.references.setdefault(relation, set()).update(cleaned)

    def touch(self, kind: str, name: str, operations: str) -> None:
        """Record that this member creates, reads, updates, or deletes a resource."""
        name = name.strip().upper()
        if name and operations:
            self.access.setdefault((kind, name), set()).update(operations)


def _crud(operations: Iterable[str]) -> str:
    present = set(operations)
    return "".join(letter for letter in CRUD if letter in present)


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


SKELETON = re.compile(r"^\)(?:SEL|DOT|IM|CM|SETF|DEFAULT|TBA|TB|BLANK|ITERATE)\b", re.MULTILINE)
PANEL = re.compile(r"^\)(?:ATTR|BODY|PANEL)\b", re.MULTILINE)


def _classify(path: Path, lines: Sequence[str], upper: str) -> str:
    """Return the artifact kind for a member, using content first and suffix second."""
    if "IBM ENTERPRISE COBOL FOR Z/OS" in upper and "OPTIONS IN EFFECT" in upper:
        return "compile-listing"
    if re.search(r"M ?O ?D ?U ?L ?E +M ?A ?P", upper) and re.search(r"\bIEW\d{4}I\b", upper):
        return "binder-listing"
    if any(zos_definitions.LISTCAT_ENTRY.match(line) for line in upper.splitlines()[:200]):
        return "idcams-listcat"
    if SKELETON.search(upper):
        return "ispf-skeleton"
    if PANEL.search(upper):
        return "ispf-panel"
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
    if path.suffix.lower() == ".csv" and zos_definitions.scheduled_jobs(upper)["jobs"]:
        return "schedule"
    return SUFFIX_KIND.get(path.suffix.lower(), "unknown")


def _sql_tables(statement: str) -> set[str]:
    """Return table names referenced by one embedded SQL statement."""
    if re.match(
        r"\s*(?:FETCH|OPEN|CLOSE|WHENEVER|INCLUDE|COMMIT|ROLLBACK|CONNECT|SET)\b", statement
    ):
        return set()
    common = set(re.findall(r"(?:\bWITH|,)\s*(" + NAME + r")\s+AS\s*\(", statement))
    tables = set(SQL_TABLE_CONTEXT.findall(statement))
    for match in re.finditer(r"(?<![A-Z0-9_])FROM\s+", statement):
        tail = statement[match.end() :]
        end = SQL_CLAUSE_END.search(tail)
        segment = tail[: end.start()] if end else tail
        for part in re.split(r",|(?<![A-Z0-9_])JOIN(?![A-Z0-9_])", segment):
            words = part.split()
            if words and re.fullmatch(NAME + r"(?:\." + NAME + "){0,2}", words[0]):
                tables.add(words[0])
    return {table for table in tables - common if not table.startswith((":", "SYSIBM.SYSDUMMY"))}


def _sql_target(verb: str, statement: str) -> tuple[str | None, str]:
    """Return the table a data-changing statement writes, with its operations."""
    patterns = {
        "INSERT": (r"INSERT\s+INTO\s+", "C"),
        "UPDATE": (r"UPDATE\s+", "U"),
        "DELETE": (r"DELETE\s+FROM\s+", "D"),
        "MERGE": (r"MERGE\s+INTO\s+", "CU"),
        "TRUNCATE": (r"TRUNCATE\s+(?:TABLE\s+)?", "D"),
    }
    if verb not in patterns:
        return None, ""
    prefix, operations = patterns[verb]
    match = re.match(prefix + r"(" + NAME + r"(?:\." + NAME + r"){0,2})", statement)
    return (match.group(1) if match else None), operations


class _Resolver:
    """Resolve data names to the literals that VALUE clauses and MOVE statements give them.

    A group has no VALUE of its own, but the literal of the item at its offset 0 is its
    prefix: a DL/I SSA group starts with the segment name. Prefixes identify segments only;
    program and resource names resolve only from literals given to the name itself.
    """

    def __init__(self, code: str) -> None:
        self.values: dict[str, list[str]] = {}
        self.prefixes: dict[str, str] = {}
        data = code.split("PROCEDURE DIVISION", 1)[0]
        stack: list[tuple[int, str, bool]] = []  # level, name, first item of its parent
        started: set[str] = set()
        for level_text, name, clauses in DATA_ENTRY.findall(data):
            level = int(level_text)
            if level == 88:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            first = bool(stack) and stack[-1][1] not in started
            if stack:
                started.add(stack[-1][1])
            literal = VALUE_LITERAL.search(clauses)
            if literal:
                text = literal.group(1) if literal.group(1) is not None else literal.group(2)
                self._add(name, text)
                if first:
                    for _, ancestor, ancestor_first in reversed(stack):
                        self.prefixes.setdefault(ancestor, text)
                        if not ancestor_first:
                            break
            stack.append((level, name, first))
        for single, double, targets in MOVE_LITERAL.findall(code):
            text = single if single or not double else double
            for target in _names(targets):
                self._add(target, text)

    def _add(self, name: str, text: str) -> None:
        values = self.values.setdefault(name, [])
        if text not in values:
            values.append(text)

    def literals(self, name: str) -> list[str]:
        """Return every literal the data name is given, or else the prefix of a group."""
        if name in self.values:
            return self.values[name]
        return [self.prefixes[name]] if name in self.prefixes else []

    def names(self, name: str, width: int = 8) -> list[str]:
        """Return the literals given to ``name`` that look like a resource name.

        Group prefixes do not count: a name built from several items is not resolved.
        """
        found = []
        for literal in self.values.get(name, []):
            candidate = literal.strip().upper()
            if candidate and len(candidate) <= width and re.fullmatch(NAME, candidate):
                found.append(candidate)
        return found


def _names(text: str) -> list[str]:
    """Return the data names in a list of operands, skipping qualifiers and passing words."""
    words = re.findall(NAME, text)
    names: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
            continue
        if word in {"OF", "IN"}:
            skip = True
            continue
        if word in STOP_WORDS:
            break
        if word in PASSING_WORDS:
            continue
        names.append(word)
    return names


def _analyze_exec_blocks(member: Member, code: str, resolver: _Resolver | None = None) -> None:
    cics_commands: set[str] = set()
    sql_kinds: Counter[str] = Counter()
    dynamic_targets: dict[str, list[str]] = {}
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
            if verb == "SYNCPOINT":
                member.details["syncpoints"] = member.details.get("syncpoints", 0) + 1
            for option, quote, value in CICS_ARGUMENT.findall(body):
                names = [value] if quote else (resolver.names(value) if resolver else [])
                if not quote:
                    if names:
                        dynamic_targets[value] = sorted({*dynamic_targets.get(value, []), *names})
                    if option == "PROGRAM":
                        member.risks["dynamic_call"] += 1
                relation = CICS_RELATIONS.get(option, f"cics-{verb.lower()}")
                if option == "TRANSID" and verb in {"RETURN", "START"}:
                    relation = f"cics-{verb.lower()}-transid"
                member.add(relation, *names)
                for name in names:
                    if option in {"FILE", "DATASET"} and verb in CICS_FILE_OPERATIONS:
                        update = "U" if verb == "READ" and " UPDATE" in f" {body}" else ""
                        member.touch("cics-file", name, CICS_FILE_OPERATIONS[verb] + update)
                    elif option in {"QUEUE", "QNAME"} and command in CICS_QUEUE_OPERATIONS:
                        rewrite = (
                            "U" if " REWRITE" in f" {body}" else CICS_QUEUE_OPERATIONS[command]
                        )
                        member.touch("cics-queue", name, rewrite)
        elif interface == "SQL":
            member.subsystems.add("db2")
            sql_kinds[verb] += 1
            if verb == "INCLUDE" and len(words) > 1:
                member.add("copy", words[1])
            tables = _sql_tables(body)
            member.add("db2-table", *tables)
            target, operations = _sql_target(verb, body)
            for table in tables:
                member.touch("db2-table", table, operations if table == target else "R")
                if table.count(".") == 2:
                    member.details.setdefault("db2_locations", [])
                    location = table.split(".", 1)[0]
                    if location not in member.details["db2_locations"]:
                        member.details["db2_locations"].append(location)
            connect = CONNECT_TO.search(body)
            if connect and not connect.group(1).startswith(":"):
                member.details.setdefault("db2_locations", []).append(connect.group(1))
            procedure = re.match(r"CALL\s+(" + NAME + r"(?:\." + NAME + ")?)", body)
            if procedure:
                member.add("db2-procedure", procedure.group(1))
        else:
            member.subsystems.add("ims")
            function = EXEC_DLI.match(body)
            psb = PSB_OPTION.search(body) if verb in {"SCHD", "SCHEDULE"} else None
            if psb:
                quoted, name = psb.group(1), psb.group(2)
                member.add(
                    "ims-psb", *([name] if quoted else resolver.names(name) if resolver else [])
                )
            segments = list(SEGMENT_OPTION.finditer(body))
            for index, segment in enumerate(segments):
                member.add("ims-segment", segment.group(1))
                if function:
                    # Parent segments only position the call unless they carry an I/O area.
                    end = segments[index + 1].start() if index + 1 < len(segments) else len(body)
                    io_area = re.search(r"\b(?:INTO|FROM)\s*\(", body[segment.end() : end])
                    last = index == len(segments) - 1
                    operation = DLI_OPERATIONS[function.group(1)] if last or io_area else "R"
                    member.touch("ims-segment", segment.group(1), operation)
    if cics_commands:
        member.details["cics_commands"] = sorted(cics_commands)
    if sql_kinds:
        member.details["sql_statements"] = dict(sorted(sql_kinds.items()))
    if dynamic_targets:
        merged = {**member.details.get("dynamic_targets", {}), **dynamic_targets}
        member.details["dynamic_targets"] = dict(sorted(merged.items()))


def _analyze_dli_calls(member: Member, code: str, resolver: _Resolver) -> None:
    """Find the IMS segments each CALL 'CBLTDLI' names through its function and SSAs."""
    for _, operands in DLI_CALL.findall(code):
        names = _names(operands)
        functions = [(index, resolver.literals(name)) for index, name in enumerate(names[:2])]
        position = next(
            (
                index
                for index, literals in functions
                if any(literal.strip() in DLI_OPERATIONS for literal in literals)
            ),
            None,
        )
        if position is None:
            if (
                any(literal.strip() == "PCB" for _, literals in functions for literal in literals)
                and len(names) > 1
            ):
                member.add("ims-psb", *resolver.names(names[1]))
            continue
        operations = {
            DLI_OPERATIONS[literal.strip()]
            for literal in resolver.literals(names[position])
            if literal.strip() in DLI_OPERATIONS
        }
        ssas = names[position + 3 :]
        for index, ssa in enumerate(ssas):
            for literal in resolver.literals(ssa):
                segment = literal[:8].strip()
                if re.fullmatch(NAME, segment):
                    # Parent SSAs only position the call unless the D command code (path
                    # call) asks for the segment too.
                    codes = re.match(r"\*([A-Z0-9-]*)", literal[8:])
                    path = bool(codes and "D" in codes.group(1))
                    last = index == len(ssas) - 1
                    member.add("ims-segment", segment)
                    member.touch(
                        "ims-segment", segment, "".join(operations) if last or path else "R"
                    )


def _analyze_mq(member: Member, resolver: _Resolver) -> None:
    calls = set(member.references.get("mq-call", set()))
    operations = ("C" if calls & {"MQPUT", "MQPUT1"} else "") + ("R" if "MQGET" in calls else "")
    queues: set[str] = set()
    for name, literals in resolver.values.items():
        if MQ_NAME_FIELD.search(name):
            queues.update(
                literal.strip().upper()
                for literal in literals
                if re.fullmatch(r"[A-Z0-9._/%-]{2,48}", literal.strip().upper())
            )
    for queue in sorted(queues):
        member.add("mq-queue", queue)
        if operations:
            member.touch("mq-queue", queue, operations)


def _analyze_files(member: Member, code: str, files: list[dict[str, str]]) -> None:
    """Tag file access from OPEN modes and DELETE statements, using SELECT ddnames."""
    ddnames = {entry["select"]: entry["ddname"] for entry in files}
    for match in OPEN_STATEMENT.finditer(code):
        mode = ""
        for word in re.findall(NAME, match.group(1)):
            if word in OPEN_MODES:
                mode = OPEN_MODES[word]
            elif word in STOP_WORDS:
                mode = ""  # the next statement started; its operands are not files to open
            elif word in ddnames:
                member.touch("ddname", ddnames[word], mode)
    for name in DELETE_FILE.findall(code):
        if name in ddnames:
            member.touch("ddname", ddnames[name], "D")
    sizes: dict[str, int] = {}
    for name, clauses in FD_ENTRY.findall(code):
        size = RECORD_SIZE.search(clauses)
        if size:
            sizes[name] = int(size.group(1) or size.group(2))
    if sizes:
        member.details["record_lengths"] = sizes


def _analyze_cobol(member: Member, lines: Sequence[str], options: ScanOptions) -> None:
    code_lines = _cobol_code(lines)
    member.code_lines = sum(1 for line in code_lines if line.strip())
    code = "\n".join(code_lines).upper()
    plain = EXEC_BLOCK.sub(" ", code)
    program_id = PROGRAM_ID.search(code)
    member.program_id = program_id.group(1).upper() if program_id else None
    member.add("copy", *COPY_MEMBER.findall(plain))
    member.add("copy", *LIBRARIAN_INCLUDE.findall("\n".join(lines).upper()))
    resolver = _Resolver(plain)
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
        resolved = {name: resolver.names(name) for name in dynamic}
        resolved = {name: targets for name, targets in resolved.items() if targets}
        for targets in resolved.values():
            member.add("call", *targets)
        if resolved:
            member.details["dynamic_targets"] = resolved
    _analyze_exec_blocks(member, code, resolver)
    _analyze_dli_calls(member, plain, resolver)
    if "mq-call" in member.references:
        _analyze_mq(member, resolver)
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
        _analyze_files(member, plain, files)
    for risk, pattern in RISK_PATTERNS.items():
        count = len(pattern.findall(code))
        if count:
            member.risks[risk] += count
    compile_options = []
    for line in lines[:20]:
        content = (line[6:72] if re.fullmatch(r"[\d ]{6}", line[:6]) else line[:72]).upper()
        if "DIVISION" in content:
            break
        option = COMPILE_OPTIONS.match(content)
        if option:
            compile_options.append(option.group(1))
    if compile_options:
        member.details["compile_options"] = compile_options
    if "cics" in member.subsystems:
        indicators = [
            name for name, pattern in THREADSAFE_INDICATORS.items() if pattern.search(code)
        ]
        if indicators:
            member.details["shared_storage"] = indicators
        if CICS_ENQ.search(code):
            member.details["cics_enq"] = True
    names = {name for _, name, _ in DATA_ENTRY.findall(plain.split("PROCEDURE DIVISION", 1)[0])}
    names |= set(
        re.findall(
            r"^\s{0,3}(" + NAME + r")\s*\.\s*$",
            plain.split("PROCEDURE DIVISION", 1)[-1],
            re.MULTILINE,
        )
    )
    reserved = sorted(names & options.reserved_words)
    if reserved:
        member.risks["reserved_word"] += len(reserved)
        member.details["reserved_words"] = reserved


def _analyze_pli(member: Member, lines: Sequence[str], upper: str) -> None:
    text = re.sub(
        r"/\*.*?\*/", " ", "\n".join(line[:72] for line in lines).upper(), flags=re.DOTALL
    )
    member.code_lines = sum(1 for line in text.splitlines() if line.strip())
    procedures = set(PLI_PROCEDURE.findall(text))
    main = re.search(r"([A-Z0-9_#@$]+)\s*:\s*PROC(?:EDURE)?\s+OPTIONS\s*\(\s*MAIN", text)
    member.program_id = main.group(1) if main else None
    if procedures:
        member.details["procedures"] = sorted(procedures)
    member.add("copy", *re.findall(r"%INCLUDE\s+(?:[A-Z0-9_#@$]+\s*\(\s*)?(" + NAME + ")", text))
    calls = set(re.findall(r"\bCALL\s+(" + NAME + ")", text)) - procedures
    for target in calls:
        family = INTERFACE_FAMILY.get(target)
        if family:
            member.subsystems.add(family)
            member.add(f"{family}-call", target)
        else:
            member.add("call", target)
    member.add("call", *re.findall(r"\bFETCH\s+(" + NAME + ")", text))
    ddnames: dict[str, str] = {}
    for name, attributes in PLI_FILE.findall(text):
        title = re.search(r"TITLE\s*\(\s*'([^']+)'", attributes)
        ddname = title.group(1).split(".")[0].upper() if title else name
        ddnames[name] = ddname
        member.add("ddname", ddname)
        member.subsystems.add("files")
        mode = "RU" if "UPDATE" in attributes else "C" if "OUTPUT" in attributes else "R"
        member.touch("ddname", ddname, mode)
    for verb, name in PLI_IO.findall(text):
        member.touch(
            "ddname",
            ddnames.get(name, name),
            {"READ": "R", "WRITE": "C", "LOCATE": "C"}.get(verb, "U" if verb == "REWRITE" else "D"),
        )
    for risk, pattern in PLI_RISKS.items():
        count = len(pattern.findall(text))
        if count:
            member.risks[risk] += count
    _analyze_exec_blocks(member, upper)


def _analyze_assembler(member: Member, lines: Sequence[str], upper: str) -> None:
    code = [line[:71] for line in lines if line.strip() and not line.startswith(("*", ".*"))]
    member.code_lines = len(code)
    member.add(
        "copy", *re.findall(r"^\S*\s+COPY\s+(" + NAME + ")", "\n".join(code).upper(), re.MULTILINE)
    )
    member.add("call", *re.findall(r"\bCALL\s+(" + NAME + ")", upper))
    member.add("load-link", *re.findall(r"\b(?:LINK|XCTL|LOAD)\s+EP=(" + NAME + ")", upper))
    for target in list(member.references.get("call", set())):
        family = INTERFACE_FAMILY.get(target)
        if family:
            member.references["call"].discard(target)
            member.subsystems.add(family)
            member.add(f"{family}-call", target)
    if not member.references.get("call", True):
        member.references.pop("call")
    if member.kind == "assembler":
        member.details["sections"] = sorted(
            set(re.findall(r"^(" + NAME + r")\s+(?:CSECT|RSECT)\b", upper, re.MULTILINE))
        )
        svc_count = len(re.findall(r"\bSVC\s+\d+", upper))
        if svc_count:
            member.risks["svc"] = svc_count
        purposes: Counter[str] = Counter()
        for line in code:
            parts = line.upper().split()
            operation = (
                parts[1] if len(parts) > 1 and not line[:1].isspace() else parts[0] if parts else ""
            )
            if operation in MACRO_CATEGORY:
                purposes[MACRO_CATEGORY[operation]] += 1
            elif re.fullmatch(r"DFH(?:PC|FC|TS|TD|SC|KC|BMS|TC|DI|IC|JC|SP)", operation):
                purposes["cics-macro-level"] += 1
                member.risks["cics_macro_level"] += 1
        if re.search(r"\bSVC\s+99\b", upper):
            purposes["dynamic-allocation"] += 1
        if any(EXIT_NAME.match(section) for section in member.details["sections"]):
            purposes["exit"] += 1
        if purposes:
            member.details["purpose"] = [name for name, _ in purposes.most_common()]
    _analyze_exec_blocks(member, upper)


def _analyze_rexx(member: Member, upper: str) -> None:
    member.code_lines = sum(1 for line in upper.splitlines() if line.strip())
    for dataset in REXX_DATASET.findall(upper):
        member.add("dataset", dataset)
    for _, job in REXX_SUBMIT.findall(upper):
        member.add("submits", job)
    member.add("ispf-skeleton", *REXX_SKELETON.findall(upper))
    member.add("exec", *REXX_SELECT.findall(upper))
    for mode, ddname in REXX_EXECIO.findall(upper):
        member.touch(
            "ddname", ddname, "C" if mode == "DISKW" else "RU" if mode == "DISKRU" else "R"
        )
        member.add("ddname", ddname)


def _analyze_natural(member: Member, upper: str) -> None:
    member.code_lines = sum(1 for line in upper.splitlines() if line.strip())
    member.subsystems.add("adabas")
    member.add("call", *NATURAL_CALL.findall(upper))
    member.add("copy", *NATURAL_INCLUDE.findall(upper), *NATURAL_USING.findall(upper))
    views = dict(NATURAL_VIEW.findall(upper))
    code = re.sub(r"'[^'\n]*'", "''", NATURAL_COMMENT.sub("", upper))
    labels: dict[str, str] = {}
    current = ""
    for label, verb, modifiers, name in NATURAL_DML_STATEMENT.findall(code):
        if verb in {"UPDATE", "DELETE"}:
            # UPDATE and DELETE act on the record of a READ, FIND, or GET: the one their
            # "(label.)" names, or the innermost one; Natural SQL names the view instead.
            reference = NATURAL_REFERENCE.search(modifiers)
            ddm = views.get(name) or labels.get(reference.group(1) if reference else "") or current
        else:
            ddm = views.get(name, "")
            if ddm and verb != "STORE":
                current = ddm
                if label:
                    labels[label] = ddm
        if ddm:
            member.add("adabas-file", ddm)
            member.touch("adabas-file", ddm, NATURAL_DML[verb])


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


def _dataset_access(dd: str, disp: str, normal: str, utility: str | None) -> str:
    """Return CRUD letters for a DD statement from its DISP and the step's utility."""
    if utility and UTILITY_OUTPUT_DDS.match(dd):
        operations = "C"
    else:
        operations = {"NEW": "C", "MOD": "C", "OLD": "U", "SHR": "R"}.get(disp or "NEW", "R")
    return operations + ("D" if normal == "DELETE" else "")


def _transfers(step: dict[str, Any], data: str, parm: str) -> list[dict[str, str]]:
    """Return file transfers coded in an FTP or Connect:Direct step's control statements."""
    found: list[dict[str, str]] = []
    if step.get("utility") != "file-transfer":
        return found
    if step.get("program") == "FTP":
        lines = data.splitlines()
        host = parm.split(maxsplit=1)[0] if parm.split() else ""
        if not host and lines and HOST_LINE.match(lines[0].strip()):
            host = lines[0].strip().split()[0]
        for line in lines:
            match = FTP_COMMAND.match(line)
            if not match:
                continue
            verb, first, second = match.group(1).upper(), match.group(2), match.group(3) or ""
            send = verb in {"PUT", "MPUT", "APPEND", "APPE"}
            local, remote = (first, second) if send else (second, first)
            found.append(
                {
                    "step": step["step"],
                    "tool": "ftp",
                    "direction": "send" if send else "receive",
                    "local": local.strip("'\""),
                    "remote": remote.strip("'\""),
                    "host": host,
                }
            )
    else:
        node = re.search(r"\bSNODE\s*=\s*([A-Z0-9.@#$-]+)", data)
        for source, target in CD_COPY.findall(data):
            from_dsn, to_dsn = CD_DSN.search(source), CD_DSN.search(target)
            receive = "SNODE" in source and "PNODE" not in source
            found.append(
                {
                    "step": step["step"],
                    "tool": "connect-direct",
                    "direction": "receive" if receive else "send",
                    "local": (to_dsn if receive else from_dsn).group(1)
                    if (to_dsn if receive else from_dsn)
                    else "",
                    "remote": (from_dsn if receive else to_dsn).group(1)
                    if (from_dsn if receive else to_dsn)
                    else "",
                    "host": node.group(1) if node else "",
                }
            )
    return found


def _analyze_instream(member: Member, step: dict[str, Any], dd: str, data: str, parm: str) -> None:
    upper = data.upper()
    if step.get("program") in DB2_TSO_PROGRAMS:
        for program, plan in TSO_RUN.findall(upper):
            step.setdefault("db2_programs", []).append(program)
            member.add("jcl-exec", program)
            if plan:
                member.add("db2-plan", plan)
        binds = zos_definitions.parse_binds(upper)
        if binds:
            member.details.setdefault("db2_binds", []).extend(binds)
    if step.get("utility") == "sort":
        sort_statements = set(SORT_STATEMENT.findall(upper))
        step["sort_statements"] = sorted(sort_statements)
        if sort_statements & SORT_LOGIC:
            member.risks["business_logic_in_sort"] += 1
    if step.get("utility") == "idcams":
        definitions = zos_definitions.parse_idcams(upper)
        if definitions:
            existing = member.details.setdefault("idcams", {})
            for key, value in definitions.items():
                if isinstance(value, dict):
                    existing.setdefault(key, {}).update(value)
                else:
                    existing.setdefault(key, []).extend(value)
    if dd in {"SYSIN", "INPUT", "SYSTSIN"}:
        transfers = _transfers(step, data, parm)
        if transfers:
            member.details.setdefault("transfers", []).extend(transfers)


def _analyze_jcl(member: Member, lines: Sequence[str]) -> None:
    statements = _jcl_statements(lines)
    member.code_lines = len(statements)
    steps: list[dict[str, Any]] = []
    datasets: list[dict[str, str]] = []
    step: dict[str, Any] | None = None
    parm_text = ""
    symbols: dict[str, str] = {}
    for statement in statements:
        operands = statement.operands.upper()
        if statement.operation in {"SET", "PROC"}:
            symbols.update(
                (name, value.strip("'")) for name, value in JCL_SYMBOL_VALUE.findall(operands)
            )
        if symbols and "&" in operands:
            operands = JCL_SYMBOL.sub(lambda m: symbols.get(m.group(1), m.group(0)), operands)
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
            parm_text = next((g for g in parm.groups() if g is not None), "") if parm else ""
            if program and program.group(1) == "DFSRRC00" and parm:
                fields = parm_text.split(",")
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
            disp = re.search(r"(?:^|,)DISP=\(?([A-Z]*)(?:,([A-Z]*))?", operands)
            dd = statement.name.upper()
            if dsn:
                status = disp.group(1) if disp else ""
                normal = (disp.group(2) or "") if disp else ""
                name = dsn.group(1)
                base = re.sub(r"\([+-]?\d+\)$", "", name)
                entry = {
                    "step": (step or {}).get("step", ""),
                    "dd": dd,
                    "dsn": name,
                    "disp": status,
                }
                if not base.startswith("&&") and not base.startswith("*."):
                    operations = _dataset_access(dd, status, normal, (step or {}).get("utility"))
                    entry["access"] = operations
                    member.add("dataset", re.sub(r"\(" + NAME + r"\)$", "", base))
                    member.touch("dataset", re.sub(r"\(" + NAME + r"\)$", "", base), operations)
                datasets.append(entry)
                member_ref = re.search(r"\((" + NAME + r")\)$", name)
                if member_ref and not re.fullmatch(r"[+-]?\d+", member_ref.group(1)):
                    member.add("control-member", member_ref.group(1))
            sysout = re.search(r"(?:^|,)SYSOUT=\(?([A-Z0-9*$])", operands)
            if (
                sysout
                and step is not None
                and dd
                not in {
                    "SYSOUT",
                    "SYSPRINT",
                    "SYSUDUMP",
                    "SYSABEND",
                    "SYSDBOUT",
                    "CEEDUMP",
                    "SYSTSPRT",
                }
            ):
                destination = re.search(r"(?:^|,)DEST=\(?([A-Z0-9.@#$]+)", operands)
                report = {"step": step["step"], "dd": dd, "class": sysout.group(1)}
                if destination:
                    report["dest"] = destination.group(1)
                member.details.setdefault("reports", []).append(report)
            if step is not None and statement.instream:
                _analyze_instream(member, step, dd, "\n".join(statement.instream), parm_text)
        elif statement.operation == "INCLUDE":
            member.add("jcl-include", *JCL_INCLUDE.findall(operands))
    member.details["steps"] = steps
    if datasets:
        member.details["datasets"] = datasets
        gdg = [entry["dsn"] for entry in datasets if re.search(r"\([+-]?\d+\)$", entry["dsn"])]
        if gdg:
            member.risks["gdg_relative_reference"] = len(gdg)


def _analyze_definitions(member: Member, text: str, upper: str) -> None:
    """Extract names from BMS, CSD, PSB, DBD, DCLGEN, DDL, and control-card members."""
    kind = member.kind
    if kind in DEFINITION_PARSERS:
        member.details[kind.split("-")[0] if kind != "idcams-control" else "idcams"] = (
            zos_definitions.PARSERS[DEFINITION_PARSERS[kind]](text)
        )
    if kind == "bms":
        mapset = re.search(r"^(" + NAME + r")\s+DFHMSD\s", upper, re.MULTILINE)
        member.details["mapset"] = mapset.group(1) if mapset else member.name
        member.details["maps"] = re.findall(r"^(" + NAME + r")\s+DFHMDI\s", upper, re.MULTILINE)
    elif kind == "cics-csd":
        summary = member.details["cics"]
        transactions = {
            name: attrs["program"]
            for name, attrs in summary["transactions"].items()
            if attrs.get("program")
        }
        member.details["transactions"] = transactions
        member.add("cics-transaction-program", *transactions.values())
        urimaps = summary["web"]["urimaps"]
        member.add("urimap-program", *(u["program"] for u in urimaps.values() if u.get("program")))
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
    elif kind == "sql-dml":
        script = re.sub(r"/\*.*?\*/|--[^\n]*", " ", upper, flags=re.DOTALL)
        for statement in filter(None, (" ".join(s.split()) for s in script.split(";"))):
            verb = statement.split()[0]
            tables = _sql_tables(statement)
            target, operations = _sql_target(verb, statement)
            member.add("db2-table", *tables)
            for table in tables:
                member.touch("db2-table", table, operations if table == target else "R")
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
        binds = zos_definitions.parse_binds(upper)
        if binds:
            member.details["db2_binds"] = binds
    elif kind == "idcams-control":
        member.details["clusters"] = re.findall(r"NAME\(\s*([^)\s]+)\s*\)", upper)
    elif kind == "mqsc":
        processes = member.details["mqsc"].get("processes", {})
        member.add("mq-trigger", *(p["applicid"] for p in processes.values() if p.get("applicid")))
    elif kind == "schedule":
        member.add("scheduled-job", *member.details["schedule"]["jobs"])
    elif kind == "ispf-skeleton":
        member.add("ispf-skeleton", *re.findall(r"^\)IM\s+(" + NAME + ")", upper, re.MULTILINE))
        member.add(
            "jcl-proc",
            *re.findall(
                r"^//\S*\s+EXEC\s+(?:PROC=)?([A-Z0-9@#$]+)(?:,|\s|$)(?!.*PGM=)", upper, re.MULTILINE
            ),
        )
        member.add("jcl-exec", *re.findall(r"\bPGM=([A-Z0-9@#$]+)", upper))


def analyze_member(
    path: Path, options: ScanOptions | None = None, *, stat: list[int] | None = None
) -> Member | None:
    """Analyze one file, returning None for binary, oversized, or non-source files.

    Raises ValueError when an explicit record format does not fit the file.
    """
    options = options or ScanOptions()
    if path.suffix.lower() not in SOURCE_SUFFIXES or path.stat().st_size > options.max_bytes:
        return None
    data = path.read_bytes()
    sample = data[: zos_encoding.SAMPLE_BYTES]
    ebcdic = b"\n" not in sample and zos_encoding.looks_like_ebcdic(sample)
    decoded = zos_encoding.decode_member(
        data,
        codepage=options.codepage,
        recfm=options.recfm if ebcdic else "auto",
        lrecl=options.lrecl if ebcdic else None,
    )
    if decoded is None:
        return None
    text = decoded.text
    lines = text.splitlines()
    upper = text.upper()
    kind = _classify(path, lines, upper)
    if kind == "unknown" and path.suffix.lower() in {".csv", ".xml"}:
        return None
    member = Member(str(path), path.stem.upper(), kind, len(lines), 0, decoded.encoding)
    member.stat = stat
    if decoded.dbcs_spans:
        member.details["dbcs_spans"] = decoded.dbcs_spans
    if kind in {"cobol-program", "cobol-copybook", "dclgen"}:
        _analyze_cobol(member, lines, options)
    elif kind.startswith("jcl"):
        _analyze_jcl(member, lines)
    elif kind in {"pli-program", "pli-include"}:
        _analyze_pli(member, lines, upper)
    elif kind in {"assembler", "assembler-macro"}:
        _analyze_assembler(member, lines, upper)
    elif kind in {"rexx", "clist"}:
        _analyze_rexx(member, upper)
    elif kind == "natural":
        _analyze_natural(member, upper)
    else:
        member.code_lines = sum(1 for line in lines if line.strip())
    _analyze_definitions(member, text, upper)
    return member


def _walk(roots: Iterable[Path]) -> Iterator[tuple[int, Path]]:
    """Yield (root index, path) for every file under the roots, skipping hidden ones."""
    for index, root in enumerate(roots):
        if root.is_file():
            yield index, root
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).parts
            if path.is_file() and not any(part.startswith(".") for part in relative):
                yield index, path


def _is_external(name: str) -> bool:
    return name.startswith(SYSTEM_PROGRAM_PREFIXES) or name in INTERFACE_FAMILY


def load_usage(paths: Sequence[Path]) -> dict[str, int]:
    """Read usage evidence CSVs: a name column and an optional use count.

    Accepts columns named name, program, member, package, job, or transaction for the name,
    and count, uses, or executions for the count. Rows without a count count as one use.
    """
    usage: dict[str, int] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                lowered = {
                    key.strip().lower(): value.strip()
                    for key, value in row.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
                name = next(
                    (
                        lowered[key]
                        for key in ("name", "program", "member", "package", "job", "transaction")
                        if lowered.get(key)
                    ),
                    "",
                ).upper()
                if not name:
                    continue
                count_text = next(
                    (lowered[key] for key in ("count", "uses", "executions") if key in lowered), "1"
                )
                count = int(count_text) if count_text.isdigit() else 1
                usage[name] = usage.get(name, 0) + count
    return usage


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge another member's definitions into ``target``.

    New names are added. When two members define the same name, the first in search order
    keeps its values and only missing attributes are filled in. Lists of names are combined,
    fixed-shape lists such as SHAREOPTIONS are kept whole, and resource counts add up.
    """
    for key, value in source.items():
        if key == "resource_counts":
            counts = target.setdefault(key, {})
            for kind, count in value.items():
                counts[kind] = counts.get(kind, 0) + count
        elif isinstance(value, dict):
            _merge(target.setdefault(key, {}), value)
        elif isinstance(value, list) and key not in FIXED_LISTS:
            existing = target.setdefault(key, [])
            existing.extend(item for item in value if item not in existing)
        elif key not in target:
            target[key] = list(value) if isinstance(value, list) else value


def _cross_checks(members: Sequence[Member], clusters: dict[str, Any]) -> list[dict[str, str]]:
    """Compare COBOL file definitions with the VSAM clusters their JCL DDs name."""
    programs = {m.program_id or m.name: m for m in members if m.kind in PROGRAM_KINDS}
    expected = {"INDEXED": "KSDS", "RELATIVE": "RRDS", "SEQUENTIAL": "ESDS"}
    findings: list[dict[str, str]] = []
    for job in (m for m in members if m.kind in {"jcl-job", "jcl-proc"}):
        for step in job.details.get("steps", []):
            dds = {d["dd"]: d for d in job.details.get("datasets", []) if d["step"] == step["step"]}
            names = [step.get("program"), step.get("proc_program"), step.get("ims_program")]
            for name in [*names, *step.get("db2_programs", [])]:
                program = programs.get(name or "")
                if program is None:
                    continue
                lengths = program.details.get("record_lengths", {})
                for file in program.details.get("files", []):
                    dd = dds.get(file["ddname"])
                    cluster = clusters.get(dd["dsn"]) if dd else None
                    if cluster is None or dd is None:
                        continue
                    where = f"{job.details.get('name') or job.name}.{step['step']} {file['ddname']}"
                    if cluster["type"] != expected[file["organization"]]:
                        findings.append(
                            {
                                "check": "organization",
                                "program": name or "",
                                "where": where,
                                "detail": f"{file['select']} is {file['organization']} but "
                                f"{dd['dsn']} is defined as {cluster['type']}",
                            }
                        )
                    maximum = cluster.get("recordsize", {}).get("maximum")
                    length = lengths.get(file["select"])
                    if maximum and length and maximum != length:
                        findings.append(
                            {
                                "check": "record-length",
                                "program": name or "",
                                "where": where,
                                "detail": f"{file['select']} records are {length} bytes but "
                                f"{dd['dsn']} RECORDSIZE maximum is {maximum}",
                            }
                        )
    return findings


def _vsam_value(key: str, value: Any) -> str:
    if value is None:
        return "none"
    if key == "keys":
        return f"{value['length']} bytes at offset {value['offset']}"
    if key == "recordsize":
        return f"{value['average']} average and {value['maximum']} maximum"
    return str(value)


def _catalog_drift(defined: dict[str, Any], cataloged: dict[str, Any]) -> list[dict[str, str]]:
    """Compare clusters in IDCAMS DEFINE statements with the catalog's LISTCAT entries."""
    findings = []
    for name in sorted(set(defined) & set(cataloged)):
        differences = [
            f"{label} {_vsam_value(key, defined[name].get(key))} in DEFINE statements, "
            f"{_vsam_value(key, cataloged[name].get(key))} in the catalog"
            for key, label in (("type", "type"), ("keys", "key"), ("recordsize", "record size"))
            if defined[name].get(key) != cataloged[name].get(key)
        ]
        if differences:
            findings.append(
                {
                    "check": "catalog-drift",
                    "program": "",
                    "where": name,
                    "detail": "; ".join(differences),
                }
            )
    return findings


def _shared_updates(members: Sequence[Member], cics: dict[str, Any]) -> list[dict[str, Any]]:
    """Return data sets that CICS files update and batch steps also write.

    A batch step writes a data set when its DISP says so or, because VSAM files are usually
    allocated DISP=SHR, when a program the step runs opens the DD for output or update.
    """
    online = {
        attrs["dsname"]: name
        for name, attrs in cics.get("files", {}).items()
        if attrs.get("dsname") and set(attrs.get("operations", "")) & set("CUD")
    }
    opened = {
        (member.program_id or member.name, name): operations
        for member in members
        for (kind, name), operations in member.access.items()
        if kind == "ddname"
    }
    shared: dict[str, dict[str, Any]] = {}
    for job in (m for m in members if m.kind in {"jcl-job", "jcl-proc"}):
        steps = {step["step"]: step for step in job.details.get("steps", [])}
        for entry in job.details.get("datasets", []):
            step = steps.get(entry["step"], {})
            programs = [
                step.get("program"),
                step.get("proc_program"),
                step.get("ims_program"),
                *step.get("db2_programs", []),
            ]
            operations = set(entry.get("access", "")).union(
                *(opened.get((p, entry["dd"]), set()) for p in programs if p)
            )
            if entry["dsn"] in online and operations & set("CUD"):
                record = shared.setdefault(
                    entry["dsn"],
                    {"dataset": entry["dsn"], "cics_file": online[entry["dsn"]], "batch": []},
                )
                record["batch"].append(f"{job.details.get('name') or job.name}.{entry['step']}")
    return sorted(shared.values(), key=lambda item: item["dataset"])


def _threadsafe(members: Sequence[Member], cics: dict[str, Any]) -> list[dict[str, Any]]:
    """Assess CICS programs for threadsafe readiness from their code and CSD definitions."""
    results = []
    for member in members:
        if "cics" not in member.subsystems or member.kind != "cobol-program":
            continue
        name = member.program_id or member.name
        concurrency = cics.get("programs", {}).get(name, {}).get("concurrency")
        indicators = member.details.get("shared_storage", [])
        enq = bool(member.details.get("cics_enq"))
        if concurrency in {"THREADSAFE", "REQUIRED"}:
            assessment = (
                "risk: shared storage without ENQ"
                if indicators and not enq
                else "defined threadsafe; confirm serialization"
            )
        elif indicators:
            assessment = "serialize shared storage before defining it threadsafe"
        elif member.subsystems & {"db2", "mq"}:
            assessment = "candidate: Db2 or MQ calls and no shared-storage indicators"
        else:
            assessment = "no shared-storage indicators"
        results.append(
            {
                "program": name,
                "concurrency": concurrency or "QUASIRENT (default)",
                "indicators": indicators,
                "enq": enq,
                "assessment": assessment,
            }
        )
    return results


def _dead_code(
    members: Sequence[Member],
    edges: Sequence[dict[str, str]],
    schedules: set[str],
    usage: dict[str, int],
) -> dict[str, Any]:
    """List unreferenced members, and classify them with usage evidence when given."""
    targets: dict[str, set[str]] = {}
    for edge in edges:
        targets.setdefault(edge["type"], set()).add(edge["to"])
    called = set().union(
        *(
            targets.get(relation, set())
            for relation in (
                *PROGRAM_RELATIONS,
                "cics-transaction-program",
                "urimap-program",
                "mq-trigger",
                "exec",
            )
        )
    )
    programs = {
        m.program_id or m.name
        for m in members
        if m.kind in PROGRAM_KINDS and m.kind not in {"rexx", "clist"}
    }
    copybooks = {m.name for m in members if m.kind in COPY_KINDS}
    procs = {m.details.get("name") or m.name for m in members if m.kind == "jcl-proc"}
    includes = {m.name for m in members if m.kind == "jcl-include"}
    jobs = {m.details.get("name") or m.name for m in members if m.kind == "jcl-job"}
    result: dict[str, Any] = {
        "unreferenced_programs": sorted(programs - called),
        "unreferenced_copybooks": sorted(copybooks - targets.get("copy", set())),
        "unreferenced_procs": sorted(procs - targets.get("jcl-proc", set())),
        "unreferenced_includes": sorted(includes - targets.get("jcl-include", set())),
        "unscheduled_jobs": sorted(jobs - schedules) if schedules else [],
        "evidence": "static references" + (" and usage" if usage else ""),
    }
    if usage:
        used = {name for name, count in usage.items() if count > 0}
        unreferenced = set(result["unreferenced_programs"])
        result["unreferenced_and_unused"] = sorted(unreferenced - used)
        result["used_but_unreferenced"] = sorted(unreferenced & used)
        result["referenced_but_unused"] = sorted((programs - unreferenced) - used)
        if jobs & set(usage):
            result["jobs_without_runs"] = sorted(jobs - used)
    return result


def build_inventory(
    roots: Sequence[Path],
    options: ScanOptions | None = None,
    *,
    usage: dict[str, int] | None = None,
    previous: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan ``roots`` and return the inventory as a JSON-serializable dictionary.

    ``previous`` maps paths to member entries from an earlier inventory; unchanged files
    (same size and modification time) reuse them instead of being analyzed again.
    """
    options = options or ScanOptions()
    usage = usage or {}
    members: list[Member] = []
    warnings: list[str] = []
    reused = 0
    effective: list[Member] = []
    first_root: dict[tuple[str, str], tuple[int, str]] = {}
    shadowed: dict[tuple[str, str], list[str]] = {}
    for root_index, path in _walk(roots):
        status = path.stat()
        stamp = [status.st_size, status.st_mtime_ns]
        entry = (previous or {}).get(str(path))
        if entry is not None and entry.get("stat") == stamp:
            member: Member | None = _member_from_dict(entry)
            reused += 1
        else:
            try:
                member = analyze_member(path, options, stat=stamp)
            except ValueError as exc:
                warnings.append(f"{path}: {exc}")
                continue
            except (LookupError, TypeError, AttributeError) as exc:
                # The parsers are heuristic; report the member and keep scanning the estate.
                warnings.append(f"{path}: could not be analyzed ({type(exc).__name__}: {exc})")
                continue
        if member is None:
            continue
        members.append(member)
        key = (member.kind, member.name)
        earlier = first_root.setdefault(key, (root_index, member.path))
        if earlier[0] < root_index:
            shadowed.setdefault(key, []).append(member.path)
        else:
            effective.append(member)
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
    for member in effective:
        source = member.program_id or member.details.get("name") or member.name
        index: dict[tuple[str, str], dict[str, str]] = {}
        for relation, targets in sorted(member.references.items()):
            for target in sorted(targets):
                edge = {"from": source, "to": target, "type": relation}
                edges.append(edge)
                index[(relation, target)] = edge
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
        for (kind, name), operations in sorted(member.access.items()):
            edge = index.get((kind, name))
            if edge is None:
                edge = {"from": source, "to": name, "type": kind}
                edges.append(edge)
            edge["access"] = _crud(operations)

    sections: dict[str, dict[str, Any]] = {"cics": {}, "vsam": {}, "mq": {}}
    cataloged: dict[str, Any] = {}
    db2: dict[str, Any] = {"binds": [], "remote_locations": []}
    listings: dict[str, Any] = {"compile": {}, "binder": []}
    schedule_jobs: set[str] = set()
    transfers: list[dict[str, str]] = []
    transactions: dict[str, str] = {}
    for member in effective:
        details = member.details
        for transaction, program in details.get("transactions", {}).items():
            transactions.setdefault(transaction, program)
        _merge(sections["cics"], details.get("cics", {}))
        if member.kind == "idcams-listcat":
            _merge(cataloged, details.get("idcams", {}))
        else:
            _merge(sections["vsam"], details.get("idcams", {}))
        _merge(sections["mq"], details.get("mqsc", {}))
        db2["binds"].extend(details.get("db2_binds", []))
        for location in details.get("db2_locations", []):
            if location not in db2["remote_locations"]:
                db2["remote_locations"].append(location)
        if "compile" in details:
            program = details["compile"].get("program") or member.name
            listings["compile"].setdefault(program, {}).update(details["compile"])
        if "binder" in details:
            listings["binder"].append({"member": member.name, **details["binder"]})
        schedule_jobs.update(details.get("schedule", {}).get("jobs", []))
        name = details.get("name") or member.name
        transfers.extend({"job": name, **transfer} for transfer in details.get("transfers", []))
        if "compile_options" in details:
            program = member.program_id or member.name
            listings["compile"].setdefault(program, {})["source_options"] = list(
                details["compile_options"]
            )
    db2["remote_locations"].sort()
    drift = _catalog_drift(sections["vsam"].get("clusters", {}), cataloged.get("clusters", {}))
    for key, entries in cataloged.items():
        if isinstance(entries, dict):
            sections["vsam"].setdefault(key, {}).update(entries)

    effective_members = effective
    kinds: Counter[str] = Counter()
    loc: Counter[str] = Counter()
    subsystems: Counter[str] = Counter()
    risk_totals: Counter[str] = Counter()
    for member in members:
        kinds[member.kind] += 1
        loc[member.kind] += member.code_lines
        subsystems.update(member.subsystems)
        risk_totals.update(member.risks)
    duplicates = Counter((member.kind, member.name) for member in members)
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
            "dbcs_members": sum(1 for member in members if member.details.get("dbcs_spans")),
            "duplicate_names": sorted(
                f"{kind}:{name}" for (kind, name), count in duplicates.items() if count > 1
            ),
            "unresolved": {key: sorted(value) for key, value in unresolved.items()},
            "external_or_system": sorted(external),
            "reused_from_previous": reused,
            "warnings": warnings,
        },
        "cics_transactions": dict(sorted(transactions.items())),
        "cics": sections["cics"],
        "vsam": sections["vsam"],
        "mq": sections["mq"],
        "db2": db2,
        "listings": listings,
        "schedules": {"jobs": sorted(schedule_jobs)},
        "transfers": transfers,
        "cross_checks": [
            *_cross_checks(effective_members, sections["vsam"].get("clusters", {})),
            *drift,
        ],
        "shared_updates": _shared_updates(effective_members, sections["cics"]),
        "cics_threadsafe": _threadsafe(effective_members, sections["cics"]),
        "dead_code": _dead_code(effective_members, edges, schedule_jobs, usage),
        "shadowed": [
            {
                "kind": kind,
                "name": name,
                "effective": first_root[(kind, name)][1],
                "shadowed": paths,
            }
            for (kind, name), paths in sorted(shadowed.items())
        ],
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
    if member.access:
        entry["access"] = [
            {"type": kind, "name": name, "ops": _crud(operations)}
            for (kind, name), operations in sorted(member.access.items())
        ]
    if member.risks:
        entry["risks"] = dict(sorted(member.risks.items()))
        entry["risk_score"] = _risk_score(member.risks)
    if member.details:
        entry["details"] = member.details
    if member.stat is not None:
        entry["stat"] = member.stat
    return entry


def _member_from_dict(entry: dict[str, Any]) -> Member:
    """Rebuild a member from its inventory entry, for incremental re-scans."""
    member = Member(
        entry["path"],
        entry["name"],
        entry["kind"],
        entry["lines"],
        entry["code_lines"],
        entry.get("encoding", "text"),
        entry.get("program_id"),
    )
    member.references = {key: set(value) for key, value in entry.get("references", {}).items()}
    member.subsystems = set(entry.get("subsystems", []))
    member.risks = Counter(entry.get("risks", {}))
    member.details = entry.get("details", {})
    member.access = {(a["type"], a["name"]): set(a["ops"]) for a in entry.get("access", [])}
    member.stat = entry.get("stat")
    return member


def load_previous(path: Path) -> dict[str, dict[str, Any]]:
    """Read member entries from an earlier JSON or JSON Lines inventory, keyed by path."""
    text = path.read_text(encoding="utf-8")
    try:
        entries = json.loads(text)["members"]
    except (json.JSONDecodeError, KeyError, TypeError):
        entries = [
            record
            for line in text.splitlines()
            if line.strip()
            for record in [json.loads(line)]
            if record.pop("record", None) == "member"
        ]
    return {entry["path"]: entry for entry in entries}


SECTION_KEYS = (
    "cics_transactions",
    "cics",
    "vsam",
    "mq",
    "db2",
    "listings",
    "schedules",
    "transfers",
    "cross_checks",
    "shared_updates",
    "cics_threadsafe",
    "dead_code",
    "shadowed",
)


def inventory_to_jsonl(inventory: dict[str, Any]) -> Iterator[str]:
    """Yield the inventory as JSON Lines: summary, sections, members, then edges.

    Each line's ``record`` key says which of the four it is.
    """
    yield json.dumps(
        {
            "record": "summary",
            "tool": inventory["tool"],
            "roots": inventory["roots"],
            **inventory["summary"],
        }
    )
    for key in SECTION_KEYS:
        yield json.dumps({"record": "section", "name": key, "data": inventory[key]})
    for member in inventory["members"]:
        yield json.dumps({"record": "member", **member})
    for edge in inventory["edges"]:
        yield json.dumps({"record": "edge", **edge})


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend(
        "| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows
    )
    return [*lines, ""]


def _markdown_definitions(inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    cics = inventory["cics"]
    remote = [
        (kind, name, attrs.get("remote_system"))
        for kind in ("transactions", "programs", "files")
        for name, attrs in cics.get(kind, {}).items()
        if attrs.get("remote_system")
    ]
    if remote:
        lines += ["## CICS routing to other regions", ""]
        lines += _table(["Resource", "Name", "Remote system"], remote)
    triggers = [
        (name, attrs.get("trigger_level"), attrs.get("transid"))
        for name, attrs in cics.get("tdqueues", {}).items()
        if attrs.get("transid")
    ]
    if triggers:
        lines += ["## Transient data triggers", ""]
        lines += _table(["Queue", "Trigger level", "Transaction"], triggers)
    web = cics.get("web", {}).get("urimaps", {})
    if web:
        lines += ["## CICS web endpoints", ""]
        lines += _table(
            ["URIMAP", "Usage", "Path", "Program or pipeline"],
            (
                (
                    name,
                    a.get("usage", ""),
                    a.get("path", ""),
                    a.get("program") or a.get("pipeline", ""),
                )
                for name, a in web.items()
            ),
        )
    if inventory["cics_threadsafe"]:
        lines += ["## CICS threadsafe readiness", ""]
        lines += _table(
            ["Program", "Concurrency", "Shared storage", "ENQ", "Assessment"],
            (
                (
                    t["program"],
                    t["concurrency"],
                    ", ".join(t["indicators"]),
                    "yes" if t["enq"] else "",
                    t["assessment"],
                )
                for t in inventory["cics_threadsafe"]
            ),
        )
    clusters = inventory["vsam"].get("clusters", {})
    if clusters:
        lines += ["## VSAM clusters", ""]
        lines += _table(
            ["Cluster", "Type", "Key (length, offset)", "Max record", "Share options"],
            (
                (
                    name,
                    c["type"],
                    f"{c['keys']['length']}, {c['keys']['offset']}" if "keys" in c else "",
                    c.get("recordsize", {}).get("maximum", ""),
                    " ".join(map(str, c.get("shareoptions", []))),
                )
                for name, c in clusters.items()
            ),
        )
    queues = inventory["mq"].get("queues", {})
    if queues:
        lines += ["## MQ queues", ""]
        lines += _table(
            ["Queue", "Type", "Target or remote", "Trigger process", "Backout queue"],
            (
                (
                    name,
                    q["type"],
                    q.get("target") or q.get("rname") or "",
                    q.get("process", "") if q.get("trigger") else "",
                    q.get("boqname", ""),
                )
                for name, q in queues.items()
            ),
        )
    db2 = inventory["db2"]
    if db2["binds"] or db2["remote_locations"]:
        lines += ["## Db2 binds and remote locations", ""]
        lines += _table(
            ["Type", "Name", "Options"],
            (
                (b["type"], b["name"], ", ".join(f"{k}({v})" for k, v in b["options"].items()))
                for b in db2["binds"]
            ),
        )
        if db2["remote_locations"]:
            lines += [f"Remote Db2 locations: {', '.join(db2['remote_locations'])}", ""]
    if inventory["transfers"]:
        lines += ["## File transfers", ""]
        lines += _table(
            ["Job", "Step", "Tool", "Direction", "Local", "Remote", "Host or node"],
            (
                (t["job"], t["step"], t["tool"], t["direction"], t["local"], t["remote"], t["host"])
                for t in inventory["transfers"]
            ),
        )
    return lines


def _markdown_findings(inventory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if inventory["cross_checks"]:
        lines += ["## Cross-check findings", ""]
        lines += _table(
            ["Check", "Program", "Where", "Detail"],
            (
                (f["check"], f["program"], f["where"], f["detail"])
                for f in inventory["cross_checks"]
            ),
        )
    if inventory["shared_updates"]:
        lines += ["## Data sets updated by both CICS and batch", ""]
        lines += _table(
            ["Data set", "CICS file", "Batch steps"],
            (
                (s["dataset"], s["cics_file"], ", ".join(s["batch"]))
                for s in inventory["shared_updates"]
            ),
        )
    dead = inventory["dead_code"]
    labels = {
        "unreferenced_programs": "Unreferenced programs",
        "unreferenced_copybooks": "Unreferenced copybooks",
        "unreferenced_procs": "Unreferenced procedures",
        "unreferenced_includes": "Unreferenced JCL includes",
        "unscheduled_jobs": "Jobs in no schedule",
        "unreferenced_and_unused": "Unreferenced and no recorded use",
        "used_but_unreferenced": "Used but unreferenced (find the caller or missing source)",
        "referenced_but_unused": "Referenced but no recorded use",
        "jobs_without_runs": "Jobs with no recorded runs",
    }
    found = [(label, dead[key]) for key, label in labels.items() if dead.get(key)]
    if found:
        lines += [f"## Dead-code candidates ({dead['evidence']})", ""]
        lines += [f"- **{label}:** {', '.join(names)}" for label, names in found]
        lines.append("")
    if inventory["shadowed"]:
        lines += ["## Shadowed members (an earlier root wins)", ""]
        lines += _table(
            ["Kind", "Name", "Effective", "Shadowed"],
            (
                (s["kind"], s["name"], s["effective"], ", ".join(s["shadowed"]))
                for s in inventory["shadowed"]
            ),
        )
    return lines


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
    lines += _markdown_definitions(inventory)
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
    lines += _markdown_findings(inventory)
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
        lines += [f"{summary['ebcdic_members']} members were decoded from EBCDIC.", ""]
    if summary["dbcs_members"]:
        lines += [
            f"{summary['dbcs_members']} members contain double-byte text, kept as <DBCS:hex>.",
            "",
        ]
    if summary["warnings"]:
        lines += ["## Warnings", "", *(f"- {warning}" for warning in summary["warnings"]), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, scan the roots, and print the inventory."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "roots", nargs="+", type=Path, help="Directories or files to scan, in search order."
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "markdown", "jsonl"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Skip files larger than this many bytes (default: {DEFAULT_MAX_BYTES}).",
    )
    parser.add_argument("--codepage", default="037", help="EBCDIC code page (default: 037).")
    parser.add_argument(
        "--recfm",
        type=str.upper,
        choices=["AUTO", "F", "FB", "V", "VB", "VBS", "NL"],
        default="AUTO",
        help="Record format of EBCDIC exports (default: auto-detect).",
    )
    parser.add_argument("--lrecl", type=int, help="Record length of fixed EBCDIC exports.")
    parser.add_argument(
        "--usage",
        action="append",
        default=[],
        type=Path,
        metavar="CSV",
        help="Usage evidence: a name column and an optional count column. Repeatable.",
    )
    parser.add_argument(
        "--previous", type=Path, help="Earlier JSON or JSONL inventory; unchanged files are reused."
    )
    parser.add_argument(
        "--reserved-words",
        type=Path,
        help="File of words the target compiler reserves, one per line, to flag as data names.",
    )
    args = parser.parse_args(argv)
    missing = [str(root) for root in args.roots if not root.exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    try:
        reserved = DEFAULT_RESERVED_WORDS
        if args.reserved_words:
            words = args.reserved_words.read_text(encoding="utf-8").split()
            reserved = frozenset(word.upper() for word in words)
        options = ScanOptions(
            args.max_bytes,
            zos_encoding.normalize_codepage(args.codepage),
            args.recfm,
            args.lrecl,
            reserved,
        )
        usage = load_usage(args.usage)
        previous = load_previous(args.previous) if args.previous else None
    except (OSError, ValueError, csv.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    inventory = build_inventory(args.roots, options, usage=usage, previous=previous)
    if args.output_format == "markdown":
        print(inventory_to_markdown(inventory))
    elif args.output_format == "jsonl":
        for line in inventory_to_jsonl(inventory):
            print(line)
    else:
        print(json.dumps(inventory, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
