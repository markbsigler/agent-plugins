#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Parse z/OS runtime and build definitions for the mainframe inventory.

Reads CICS CSD extracts (DEFINE commands), IDCAMS control statements and LISTCAT ALL reports,
IBM MQ MQSC definitions, Db2 BIND statements, Enterprise COBOL compiler listings, binder
listings, and the job names in scheduler exports (Control-M XML, IBM Z Workload Scheduler
batch-loader statements, and predecessor/successor CSV). mainframe_inventory.py uses it for
every member it recognizes; run it directly to see one file as JSON. The script only reads
files.

Examples:
    uv run --script zos_definitions.py CICSPROD.CSD
    uv run --script zos_definitions.py VSAMDEFS.CNTL --kind idcams
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

import zos_encoding

DEFINE = re.compile(r"\bDEFINE\s+([A-Z0-9]+)\s*\(\s*'?([^)'\s]+)'?\s*\)", re.IGNORECASE)
ATTRIBUTE = re.compile(r"\b([A-Z][A-Z0-9]*)\s*\(\s*((?:[^()]|\([^()]*\))*?)\s*\)", re.IGNORECASE)
CSD_COMMAND = re.compile(
    r"(?:ADD|ALTER|APPEND|COPY|DEFINE|DELETE|EXTRACT|INITIALIZE|LIST|MIGRATE|PROCESS|REMOVE"
    r"|SCAN|SERVICE|UPGRADE|USERDEFINE|VERIFY)\s+(?!\()",
    re.IGNORECASE,
)
CSD_ALTER = re.compile(r"ALTER\s+([A-Z0-9]+)\s*\(\s*'?([^)'\s]+)'?\s*\)", re.IGNORECASE)
QUOTED_VALUE = re.compile(r"(?<=\()\s*'(?:[^']|'')*'\s*(?=\))")
CASE_SENSITIVE = frozenset(
    {
        "CERTIFICATE",
        "CHARACTERSET",
        "CONFIGFILE",
        "DESCRIPTION",
        "HOST",
        "LOCATION",
        "MEDIATYPE",
        "PATH",
        "QUERYSTRING",
        "SHELF",
        "WSBIND",
        "WSDLFILE",
    }
)
CSD_TYPES = {"TRANS": "TRANSACTION", "PROG": "PROGRAM", "TDQ": "TDQUEUE"}
IDCAMS_ALIASES = {
    "IXD": "INDEXED",
    "NIXD": "NONINDEXED",
    "NUMD": "NUMBERED",
    "LIN": "LINEAR",
    "RECSZ": "RECORDSIZE",
    "SHR": "SHAREOPTIONS",
    "FSPC": "FREESPACE",
    "CISZ": "CONTROLINTERVALSIZE",
    "UNQK": "UNIQUEKEY",
    "NUNQK": "NONUNIQUEKEY",
    "UPG": "UPGRADE",
    "NUPG": "NOUPGRADE",
    "REL": "RELATE",
    "PENT": "PATHENTRY",
    "LIM": "LIMIT",
    "SCR": "SCRATCH",
    "NSCR": "NOSCRATCH",
    "EMP": "EMPTY",
    "NEMP": "NOEMPTY",
    "AIX": "ALTERNATEINDEX",
    "GDG": "GENERATIONDATAGROUP",
    "CL": "CLUSTER",
}
VSAM_TYPES = {"INDEXED": "KSDS", "NONINDEXED": "ESDS", "NUMBERED": "RRDS", "LINEAR": "LDS"}
MQSC_TYPES = {
    "QL": "QLOCAL",
    "QR": "QREMOTE",
    "QA": "QALIAS",
    "QM": "QMODEL",
    "CHL": "CHANNEL",
    "PRO": "PROCESS",
    "NL": "NAMELIST",
}
MQSC_OBJECT = re.compile(
    r"\bDEFINE\s+(QLOCAL|QL|QREMOTE|QR|QALIAS|QA|QMODEL|QM|CHANNEL|CHL|PROCESS|PRO|NAMELIST|NL|"
    r"TOPIC|SUB|LISTENER|SERVICE)\s*\(\s*('[^']*'|[^)\s]+)\s*\)",
    re.IGNORECASE,
)
BIND = re.compile(r"\b(?:REBIND|BIND)\s+(PACKAGE|PLAN)\s*\(([^)]*)\)", re.IGNORECASE)
BIND_OPTION = re.compile(r"\b([A-Z]+)\s*\(([^)]*)\)", re.IGNORECASE)
LISTING_OPTIONS = re.compile(r"^\s+((?:NO)?[A-Z][A-Z0-9]*(?:\([^)]*\))?)\s*$")


def _card(line: str) -> str:
    """Drop a sequence field in columns 73-80; keep longer free-form lines whole."""
    if len(line) <= 80 and re.fullmatch(r"[\d ]*", line[72:]):
        return line[:72].rstrip()
    return line.rstrip()


def _flatten(text: str, comment: str = "*") -> str:
    """Join lines into one string, dropping comment lines and sequence fields."""
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith(comment) or line.startswith("//"):
            continue
        lines.append(_card(line))
    return " ".join(lines)


def _attributes(text: str) -> dict[str, str]:
    """Return attribute values, uppercased except where CICS keeps the case (PATH, HOST)."""
    attributes = {}
    for key, value in ATTRIBUTE.findall(text):
        cleaned = value.strip("' ")
        attributes[key.upper()] = cleaned if key.upper() in CASE_SENSITIVE else cleaned.upper()
    return attributes


def parse_csd(text: str) -> dict[str, dict[str, dict[str, str]]]:
    """Return CSD resources by type and name, with their attributes.

    Reads the DEFINE commands that DFHCSDUP EXTRACT (with a user program such as DFH0CBDC)
    produces, ALTER commands that change them, and ``ADD GROUP(g) LIST(l)`` statements.
    """
    resources: dict[str, dict[str, dict[str, str]]] = {}
    for command in _csd_commands(_flatten(text)):
        define = DEFINE.match(command)
        if define:
            kind = CSD_TYPES.get(define.group(1).upper(), define.group(1).upper())
            attributes = _attributes(command[define.end() :])
            resources.setdefault(kind, {})[define.group(2).upper()] = attributes
            continue
        alter = CSD_ALTER.match(command)
        if alter:
            kind = CSD_TYPES.get(alter.group(1).upper(), alter.group(1).upper())
            existing = resources.get(kind, {}).get(alter.group(2).upper())
            if existing is not None:
                existing.update(_attributes(command[alter.end() :]))
            continue
        added = re.match(
            r"ADD\s+GROUP\(\s*(\S+?)\s*\)\s+LIST\(\s*(\S+?)\s*\)", command, re.IGNORECASE
        )
        if added:
            group, group_list = added.group(1).upper(), added.group(2).upper()
            resources.setdefault("LIST", {}).setdefault(group_list, {})[group] = "member"
    return resources


def _csd_commands(flat: str) -> list[str]:
    """Split DFHCSDUP input into commands, ignoring command words inside attribute values."""
    masked = QUOTED_VALUE.sub(lambda match: "x" * len(match.group(0)), flat)
    starts = []
    depth = 0
    for index, char in enumerate(masked):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif (
            depth == 0
            and (index == 0 or masked[index - 1] == " ")
            and CSD_COMMAND.match(masked, index)
        ):
            starts.append(index)
    return [flat[start:end] for start, end in zip(starts, [*starts[1:], len(flat)], strict=True)]


def summarize_csd(resources: dict[str, dict[str, dict[str, str]]]) -> dict[str, Any]:
    """Pick out the CSD facts that matter for modernization."""
    tx = resources.get("TRANSACTION", {})
    programs = resources.get("PROGRAM", {})
    files = resources.get("FILE", {})
    tdqueues = resources.get("TDQUEUE", {})
    summary: dict[str, Any] = {
        "transactions": {
            name: {
                key: value
                for key, value in (
                    ("program", attrs.get("PROGRAM")),
                    ("group", attrs.get("GROUP")),
                    ("remote_system", attrs.get("REMOTESYSTEM")),
                    ("remote_name", attrs.get("REMOTENAME")),
                    ("tranclass", attrs.get("TRANCLASS")),
                )
                if value
            }
            for name, attrs in tx.items()
        },
        "programs": {
            name: {
                key: value
                for key, value in (
                    ("group", attrs.get("GROUP")),
                    ("language", attrs.get("LANGUAGE")),
                    ("concurrency", attrs.get("CONCURRENCY")),
                    ("api", attrs.get("API")),
                    ("remote_system", attrs.get("REMOTESYSTEM")),
                    ("remote_name", attrs.get("REMOTENAME")),
                    ("dynamic", attrs.get("DYNAMIC")),
                    ("jvm", attrs.get("JVM")),
                )
                if value
            }
            for name, attrs in programs.items()
        },
        "files": {
            name: {
                key: value
                for key, value in (
                    ("dsname", attrs.get("DSNAME")),
                    ("remote_system", attrs.get("REMOTESYSTEM")),
                    ("rls", attrs.get("RLSACCESS")),
                    ("operations", _file_operations(attrs)),
                    ("recovery", attrs.get("RECOVERY")),
                )
                if value
            }
            for name, attrs in files.items()
        },
        "tdqueues": {
            name: {
                key: value
                for key, value in (
                    ("type", attrs.get("TYPE")),
                    ("trigger_level", attrs.get("TRIGGERLEVEL")),
                    ("transid", attrs.get("TRANSID")),
                    ("dsname", attrs.get("DSNAME")),
                    ("ddname", attrs.get("DDNAME")),
                    ("indirect_name", attrs.get("INDIRECTNAME")),
                )
                if value
            }
            for name, attrs in tdqueues.items()
        },
    }
    db2_entries = resources.get("DB2ENTRY", {})
    summary["db2"] = {
        "entries": {
            name: {"plan": attrs.get("PLAN"), "transid": attrs.get("TRANSID")}
            for name, attrs in db2_entries.items()
        },
        "transactions": {
            attrs.get("TRANSID", ""): attrs.get("ENTRY")
            for attrs in resources.get("DB2TRAN", {}).values()
            if attrs.get("TRANSID")
        },
        "connection": {
            name: {"db2id": attrs.get("DB2ID"), "plan": attrs.get("PLAN")}
            for name, attrs in resources.get("DB2CONN", {}).items()
        },
    }
    summary["web"] = {
        "urimaps": {
            name: {
                key: value
                for key, value in (
                    ("usage", attrs.get("USAGE")),
                    ("path", attrs.get("PATH")),
                    ("host", attrs.get("HOST")),
                    ("program", attrs.get("PROGRAM")),
                    ("pipeline", attrs.get("PIPELINE")),
                    ("webservice", attrs.get("WEBSERVICE")),
                    ("transaction", attrs.get("TRANSACTION")),
                )
                if value
            }
            for name, attrs in resources.get("URIMAP", {}).items()
        },
        "pipelines": sorted(resources.get("PIPELINE", {})),
        "webservices": {
            name: attrs.get("PIPELINE") for name, attrs in resources.get("WEBSERVICE", {}).items()
        },
    }
    summary["connections"] = {
        name: {"type": kind, **({"applid": a["APPLID"]} if a.get("APPLID") else {})}
        for kind in ("CONNECTION", "IPCONN")
        for name, a in resources.get(kind, {}).items()
    }
    summary["lists"] = {name: sorted(groups) for name, groups in resources.get("LIST", {}).items()}
    summary["resource_counts"] = {kind: len(names) for kind, names in sorted(resources.items())}
    return summary


def _file_operations(attributes: dict[str, str]) -> str:
    """Return CRUD letters for the operations a CICS FILE definition allows."""
    allowed = {
        "C": attributes.get("ADD") == "YES",
        "R": attributes.get("READ", "YES") == "YES" or attributes.get("BROWSE") == "YES",
        "U": attributes.get("UPDATE") == "YES",
        "D": attributes.get("DELETE") == "YES",
    }
    return "".join(letter for letter, enabled in allowed.items() if enabled)


def _balanced(text: str, start: int) -> int:
    """Return the index just after the parenthesis group that opens at ``start``."""
    depth = 0
    for index in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        if depth == 0:
            return index + 1
    return len(text)


def _idcams_parameters(text: str) -> dict[str, str | None]:
    """Parse ``KEYWORD(value)`` and bare keywords at the top level of a parameter list."""
    parameters: dict[str, str | None] = {}
    index = 0
    while index < len(text):
        match = re.match(r"\s*([A-Z][A-Z0-9]*)", text[index:])
        if not match:
            index += 1
            continue
        keyword = IDCAMS_ALIASES.get(match.group(1), match.group(1))
        index += match.end()
        if index < len(text) and text[index] == "(":
            end = _balanced(text, index)
            parameters[keyword] = text[index + 1 : end - 1].strip()
            index = end
        else:
            parameters[keyword] = None
    return parameters


def _numbers(value: str | None) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", value or "")]


def parse_idcams(text: str) -> dict[str, Any]:
    """Return VSAM clusters, alternate indexes, paths, GDG bases, and deletes."""
    flat = re.sub(r"/\*.*?\*/", " ", text.upper(), flags=re.DOTALL)
    flat = re.sub(r"[-+]\s*\n", " ", flat).replace("\n", " ")
    result: dict[str, Any] = {"clusters": {}, "aix": {}, "paths": {}, "gdgs": {}, "deletes": []}
    for match in re.finditer(r"\bDEFINE\s+([A-Z]+)\s*\(", flat):
        kind = IDCAMS_ALIASES.get(match.group(1), match.group(1))
        end = _balanced(flat, match.end() - 1)
        parameters = _idcams_parameters(flat[match.end() : end - 1])
        tail = flat[end : end + 400]
        name = (parameters.get("NAME") or "").strip()
        if kind == "CLUSTER":
            for nested in ("DATA", "INDEX"):
                nested_match = re.match(rf"\s*{nested}\s*\(", tail)
                if nested_match:
                    close = _balanced(tail, nested_match.end() - 1)
                    nested_parameters = _idcams_parameters(tail[nested_match.end() : close - 1])
                    for key, value in nested_parameters.items():
                        parameters.setdefault(key, value)
                    tail = tail[close:]
            organization = next((VSAM_TYPES[k] for k in VSAM_TYPES if k in parameters), "KSDS")
            entry: dict[str, Any] = {"type": organization}
            if organization == "KSDS" and "KEYS" in parameters:
                length, offset = [*_numbers(parameters["KEYS"]), 0, 0][:2]
                entry["keys"] = {"length": length, "offset": offset}
            if "RECORDSIZE" in parameters:
                average, maximum = [*_numbers(parameters["RECORDSIZE"]), 0, 0][:2]
                entry["recordsize"] = {"average": average, "maximum": maximum}
            if "SHAREOPTIONS" in parameters:
                entry["shareoptions"] = _numbers(parameters["SHAREOPTIONS"])
            if "LOG" in parameters:
                entry["log"] = parameters["LOG"]
            result["clusters"][name] = entry
        elif kind == "ALTERNATEINDEX":
            length, offset = [*_numbers(parameters.get("KEYS")), 0, 0][:2]
            result["aix"][name] = {
                "relate": (parameters.get("RELATE") or "").strip(),
                "keys": {"length": length, "offset": offset},
                "unique": "UNIQUEKEY" in parameters,
                "upgrade": "NOUPGRADE" not in parameters,
            }
        elif kind == "PATH":
            result["paths"][name] = (parameters.get("PATHENTRY") or "").strip()
        elif kind == "GENERATIONDATAGROUP":
            result["gdgs"][name] = {
                "limit": (_numbers(parameters.get("LIMIT")) or [None])[0],
                "scratch": "SCRATCH" in parameters,
                "empty": "EMPTY" in parameters,
            }
    result["deletes"] = sorted(
        set(re.findall(r"\bDELETE\s+\(?\s*'?([A-Z0-9@#$.()+-]+?)'?\s*\)?(?:\s|$)", flat))
    )
    return {key: value for key, value in result.items() if value}


LISTCAT_ENTRY = re.compile(
    r"^[ 01+-]?(CLUSTER|DATA|INDEX|AIX|PATH|GDG BASE|NONVSAM|ALIAS|PAGESPACE) -{2,} (\S+)"
)
LISTCAT_ASSOCIATION = re.compile(r"^\s+(DATA|INDEX|CLUSTER|AIX|PATH|GDG)-{2,}(\S+)")
LISTCAT_ORGANIZATION = re.compile(r"\b(INDEXED|NONINDEXED|NUMBERED|LINEAR)\b")


def _listcat_number(label: str, block: str) -> int | None:
    match = re.search(rf"\b{label}\s*-+(\d+)\b", block)
    return int(match.group(1)) if match else None


def parse_listcat(text: str) -> dict[str, Any]:
    """Return VSAM clusters, alternate indexes, paths, and GDG bases from LISTCAT ALL output.

    Gives the same structure as parse_idcams, from the catalog rather than from DEFINE
    statements that may be out of date. Accepts reports with ASA carriage-control characters.
    Entries listed without their attributes (LISTCAT without ALL) are left out.
    """
    entries: list[tuple[str, str, list[str]]] = []
    for line in text.upper().splitlines():
        header = LISTCAT_ENTRY.match(line)
        if header:
            entries.append((header.group(1), header.group(2), []))
        elif entries:
            entries[-1][2].append(line)
    parent: dict[str, str] = {}
    for kind, name, lines in entries:
        for association in filter(None, map(LISTCAT_ASSOCIATION.match, lines)):
            if kind in {"DATA", "INDEX"} and association.group(1) in {"CLUSTER", "AIX"}:
                parent[name] = association.group(2)
    data = {
        parent[name]: "\n".join(lines)
        for kind, name, lines in entries
        if kind == "DATA" and name in parent
    }
    result: dict[str, Any] = {"clusters": {}, "aix": {}, "paths": {}, "gdgs": {}}
    for kind, name, lines in entries:
        block = "\n".join(lines)
        component = data.get(name, "")
        keys = {
            "length": _listcat_number("KEYLEN", component) or 0,
            "offset": _listcat_number("RKP", component) or 0,
        }
        if kind == "CLUSTER":
            if not component:
                continue
            organization = LISTCAT_ORGANIZATION.search(component)
            entry: dict[str, Any] = {
                "type": VSAM_TYPES[organization.group(1)] if organization else "KSDS"
            }
            if entry["type"] == "KSDS" and keys["length"]:
                entry["keys"] = keys
            maximum = _listcat_number("MAXLRECL", component)
            if maximum:
                average = _listcat_number("AVGLRECL", component) or maximum
                entry["recordsize"] = {"average": average, "maximum": maximum}
            shares = re.search(r"SHROPTNS\((\d+),(\d+)\)", component)
            if shares:
                entry["shareoptions"] = [int(shares.group(1)), int(shares.group(2))]
            log = re.search(r"\bLOG\s*-+([A-Z]+)\b", block)
            if log:
                entry["log"] = log.group(1)
            result["clusters"][name] = entry
        elif kind == "AIX":
            # The AIX data component's RKP counts from the start of the AIX record, after its
            # 5-byte header; AXRKP gives the key's position in the base cluster's records.
            keys["offset"] = _listcat_number("AXRKP", component) or keys["offset"]
            relate = next(
                (
                    m.group(2)
                    for m in map(LISTCAT_ASSOCIATION.match, lines)
                    if m and m.group(1) == "CLUSTER"
                ),
                "",
            )
            if not component:
                continue
            result["aix"][name] = {
                "relate": relate,
                "keys": keys,
                "unique": bool(re.search(r"\bUNIQKEY\b", component)),
                "upgrade": not re.search(r"\bNOUPGRADE\b", block),
            }
        elif kind == "PATH":
            target = next(
                (
                    m.group(2)
                    for m in map(LISTCAT_ASSOCIATION.match, lines)
                    if m and m.group(1) in {"AIX", "CLUSTER"}
                ),
                "",
            )
            if target:
                result["paths"][name] = target
        elif kind == "GDG BASE" and _listcat_number("LIMIT", block) is not None:
            result["gdgs"][name] = {
                "limit": _listcat_number("LIMIT", block),
                "scratch": not re.search(r"\bNOSCRATCH\b", block),
                "empty": not re.search(r"\bNOEMPTY\b", block),
            }
    return {key: value for key, value in result.items() if value}


def parse_mqsc(text: str) -> dict[str, Any]:
    """Return queues, processes, and channels from MQSC DEFINE commands."""
    joined = re.sub(r"[-+]\s*\n\s*", " ", text)
    lines = [line for line in joined.splitlines() if not line.lstrip().startswith("*")]
    flat = " ".join(lines)
    result: dict[str, Any] = {"queues": {}, "processes": {}, "channels": {}, "other": {}}
    matches = list(MQSC_OBJECT.finditer(flat))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(flat)
        kind = MQSC_TYPES.get(match.group(1).upper(), match.group(1).upper())
        name = match.group(2).strip("'")
        attributes = {
            key.upper(): value.strip("'")
            for key, value in re.findall(
                r"\b([A-Za-z]+)\s*\(\s*('[^']*'|[^)]*)\s*\)", flat[match.end() : end]
            )
        }
        flags = {
            word.upper()
            for word in re.findall(
                r"\b(TRIGGER|NOTRIGGER)\b", flat[match.end() : end], re.IGNORECASE
            )
        }
        if kind.startswith("Q"):
            entry = {"type": kind}
            for key in (
                "TARGET",
                "RNAME",
                "RQMNAME",
                "XMITQ",
                "INITQ",
                "PROCESS",
                "BOQNAME",
                "DEFPSIST",
                "USAGE",
                "TRIGTYPE",
            ):
                if key in attributes:
                    entry[key.lower()] = attributes[key]
            if "TRIGGER" in flags:
                entry["trigger"] = True
            result["queues"][name] = entry
        elif kind == "PROCESS":
            result["processes"][name] = {
                key.lower(): attributes[key]
                for key in ("APPLICID", "APPLTYPE", "USERDATA")
                if key in attributes
            }
        elif kind == "CHANNEL":
            result["channels"][name] = {
                key.lower(): attributes[key]
                for key in ("CHLTYPE", "CONNAME", "XMITQ", "TRPTYPE")
                if key in attributes
            }
        else:
            result["other"].setdefault(kind, []).append(name)
    return {key: value for key, value in result.items() if value}


def parse_binds(text: str) -> list[dict[str, Any]]:
    """Return Db2 BIND and REBIND PACKAGE or PLAN statements with their options."""
    flat = re.sub(r"[-+]\s*\n", " ", text.upper()).replace("\n", " ")
    statements = re.split(r"(?<!\S)(?=(?:REBIND|BIND|DSN|END|RUN)\b)", flat)
    binds = []
    for statement in statements:
        match = BIND.search(statement)
        if not match:
            continue
        options = {
            key.upper(): value.strip()
            for key, value in BIND_OPTION.findall(statement[match.end() :])
            if key.upper() not in {"PACKAGE", "PLAN"}
        }
        entry: dict[str, Any] = {"type": match.group(1).lower(), "name": match.group(2).strip()}
        if "MEMBER" in options:
            entry["name"] = f"{entry['name']}.{options.pop('MEMBER')}"
        entry["options"] = options
        binds.append(entry)
    return binds


def parse_compile_listing(text: str) -> dict[str, Any]:
    """Return the program name, compiler release, and options from a COBOL listing."""
    lines = text.splitlines()
    result: dict[str, Any] = {}
    release = re.search(r"IBM Enterprise COBOL for z/OS\s+(\d+\.\d+(?:\.\d+)?)", text)
    if release:
        result["compiler"] = f"Enterprise COBOL {release.group(1)}"
    program = re.search(r"PROGRAM-ID\.?\s+'?([A-Z0-9@#$-]+)", text.upper())
    if program:
        result["program"] = program.group(1)
    options: list[str] = []
    for index, line in enumerate(lines):
        if "OPTIONS IN EFFECT" in line.upper():
            for following in lines[index + 1 :]:
                match = LISTING_OPTIONS.match(following.upper())
                if match is None:
                    if options:
                        break
                    continue
                options.append(match.group(1))
            break
    if options:
        result["options"] = options
    return result


def parse_binder_listing(text: str) -> dict[str, Any]:
    """Return load module names, AMODE, and RMODE from a binder (IEWL) listing."""
    upper = text.upper()
    result: dict[str, Any] = {}
    names = re.findall(r"\bNAME\s+([A-Z0-9@#$]+)\s*\(R\)", upper)
    names += re.findall(r"MEMBER NAME\s*[:=]?\s+([A-Z0-9@#$]+)", upper)
    if names:
        result["modules"] = sorted(set(names))
    amode = re.findall(r"\bAMODE\s*[:=]?\s*(24|31|64|ANY)\b", upper)
    rmode = re.findall(r"\bRMODE\s*[:=]?\s*(24|31|ANY|SPLIT)\b", upper)
    if amode:
        result["amode"] = sorted(set(amode))
    if rmode:
        result["rmode"] = sorted(set(rmode))
    return result


def scheduled_jobs(text: str) -> dict[str, Any]:
    """Return job names (and their JCL members) from a scheduler export."""
    if "<JOB" in text.upper():
        jobs = sorted(
            {
                (attrs.get("MEMNAME") or attrs.get("JOBNAME") or "").upper()
                for element in re.findall(r"<JOB\s([^>]*)>", text, re.IGNORECASE)
                for attrs in [dict(re.findall(r'(\w+)="([^"]*)"', element))]
            }
            - {""}
        )
        return {"format": "control-m-xml", "jobs": jobs}
    if re.search(r"^ADSTART\b", text, re.MULTILINE | re.IGNORECASE):
        jobs = sorted(
            {job.upper() for job in re.findall(r"\bJOBN\(\s*([^)\s]+)\s*\)", text, re.IGNORECASE)}
        )
        return {"format": "iws-batch-loader", "jobs": jobs}
    try:
        rows = list(csv.DictReader(text.splitlines()))
    except csv.Error:
        rows = []
    if rows and {"predecessor", "successor"} <= {key.lower() for key in rows[0] if key}:
        names = set()
        for row in rows:
            lowered = {
                key.lower(): value.strip().upper()
                for key, value in row.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            names.update(filter(None, (lowered.get("predecessor"), lowered.get("successor"))))
        return {"format": "csv", "jobs": sorted(names)}
    return {"format": "unknown", "jobs": []}


PARSERS = {
    "cics-csd": lambda text: summarize_csd(parse_csd(text)),
    "idcams": parse_idcams,
    "listcat": parse_listcat,
    "mqsc": parse_mqsc,
    "db2-bind": parse_binds,
    "compile-listing": parse_compile_listing,
    "binder-listing": parse_binder_listing,
    "schedule": scheduled_jobs,
}


def detect_kind(text: str) -> str | None:
    """Guess which definition parser applies to ``text``."""
    upper = text.upper()
    if any(LISTCAT_ENTRY.match(line) for line in upper.splitlines()):
        return "listcat"
    if re.search(
        r"^\s*DEFINE\s+(?:TRANSACTION|TRANS|PROGRAM|FILE|TDQUEUE|URIMAP)\(", upper, re.MULTILINE
    ):
        return "cics-csd"
    if MQSC_OBJECT.search(upper):
        return "mqsc"
    if re.search(
        r"^\s*DEFINE\s+(?:CLUSTER|CL|GDG|GENERATIONDATAGROUP|AIX|ALTERNATEINDEX|PATH)\b",
        upper,
        re.MULTILINE,
    ):
        return "idcams"
    if "IBM ENTERPRISE COBOL FOR Z/OS" in upper and "OPTIONS IN EFFECT" in upper:
        return "compile-listing"
    if "MODULE MAP" in upper or "IEW2" in upper:
        return "binder-listing"
    if BIND.search(upper):
        return "db2-bind"
    if "<JOB" in upper or re.search(r"^ADSTART\b", upper, re.MULTILINE):
        return "schedule"
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse one definitions file and print the result as JSON."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", type=Path, help="Exported definitions, listing, or schedule.")
    parser.add_argument("--kind", choices=list(PARSERS), help="Override detection.")
    parser.add_argument("--codepage", default="037", help="EBCDIC code page (default: 037).")
    args = parser.parse_args(argv)
    try:
        codepage = zos_encoding.normalize_codepage(args.codepage)
        decoded = zos_encoding.decode_member(args.path.read_bytes(), codepage=codepage)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if decoded is None:
        print("error: binary content", file=sys.stderr)
        return 1
    kind = args.kind or detect_kind(decoded.text)
    if kind is None:
        print("error: unrecognized content; pass --kind", file=sys.stderr)
        return 1
    print(json.dumps({"kind": kind, "definitions": PARSERS[kind](decoded.text)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
