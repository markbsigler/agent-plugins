"""Tests for code-modernization-plugin: mainframe-program-docs scripts (cobol_flow, screen_map)."""

from __future__ import annotations

import json
from pathlib import Path

import cobol_flow
import pytest
import screen_map
import zos_encoding


def fixed(*lines: str) -> str:
    """Return fixed-format source: sequence numbers, indicator column, and code from col 8.

    A line starting with ``*``, ``-``, or ``/`` uses that character as its indicator, and
    ``D|`` marks a debugging line.
    """
    out = []
    for number, line in enumerate(lines, start=1):
        if line.startswith("D|"):
            indicator, code = "D", line[2:]
        elif line[:1] in {"*", "-", "/"}:
            indicator, code = line[0], line[1:]
        else:
            indicator, code = " ", line
        out.append(f"{number * 100:06d}{indicator}{code[:65]:<65}IDENT{number:03d}")
    return "\n".join(out) + "\n"


def line_of(lines: tuple[str, ...], text: str) -> int:
    """Return the 1-based line number of ``text`` in a member built by ``fixed``."""
    return lines.index(text) + 1


def macro(label: str, operation: str, *operands: str) -> list[str]:
    """Lay out an assembler macro: label in column 1, X in column 72 on continued lines."""
    out = []
    for index, text in enumerate(operands):
        prefix = f"{label:<8} {operation:<5} " if index == 0 else " " * 15
        mark = "X" if index < len(operands) - 1 else " "
        out.append(f"{prefix + text:<71}{mark}SEQ{index:05d}")
    return out


CUSTREC = (
    "*  CUSTOMER RECORD",
    "01  :PFX:-RECORD.",
    "    05  :PFX:-ID        PIC X(10).",
    "    05  :PFX:-STATUS    PIC X.",
    "        88  :PFX:-ACTIVE  VALUE 'A'.",
    "        88  :PFX:-CLOSED  VALUES ARE 'C' 'X'.",
    "    05  :PFX:-BALANCE   PIC S9(7)V99 COMP-3.",
)
ERRPARA = (
    "*  COMMON ERROR HANDLER",
    "9900-ERROR.",
    "    IF RETURN-CODE > 8",
    "       DISPLAY 'SEVERE ERROR'",
    "    END-IF.",
    "    GOBACK.",
)
BATCH = (
    "*****************************************************",
    "*  CUSTUPD: APPLY DAILY CUSTOMER UPDATES",
    "*****************************************************",
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. CUSTUPD.",
    "AUTHOR. J SMITH.",
    "INSTALLATION. ACME BANK.",
    "DATE-WRITTEN. 1989-01-15.",
    "REMARKS. NIGHTLY CUSTOMER UPDATE",
    "    WITH AUDIT TRAIL.",
    "ENVIRONMENT DIVISION.",
    "INPUT-OUTPUT SECTION.",
    "FILE-CONTROL.",
    "    SELECT CUST-FILE ASSIGN TO CUSTMAST",
    "        ORGANIZATION IS INDEXED ACCESS MODE IS DYNAMIC",
    "        RECORD KEY IS CUST-KEY",
    "        ALTERNATE RECORD KEY IS CUST-NAME WITH DUPLICATES",
    "        FILE STATUS IS WS-CUST-FS.",
    "    SELECT TRAN-FILE ASSIGN TO UT-S-TRANIN.",
    "    SELECT OPTIONAL RPT-FILE ASSIGN TO 'report.txt'",
    "        ORGANIZATION IS LINE SEQUENTIAL.",
    "    SELECT SORT-WORK ASSIGN TO SORTWK1.",
    "DATA DIVISION.",
    "FILE SECTION.",
    "FD  CUST-FILE.",
    "01  CUST-REC.",
    "    05  CUST-KEY   PIC X(10).",
    "    05  CUST-NAME  PIC X(30).",
    "FD  TRAN-FILE.",
    "01  TRAN-REC       PIC X(80).",
    "FD  RPT-FILE.",
    "01  RPT-LINE       PIC X(132).",
    "SD  SORT-WORK.",
    "01  SORT-REC       PIC X(80).",
    "WORKING-STORAGE SECTION.",
    "01  WS-CUST-FS     PIC XX.",
    "01  WS-UNNAMED.",
    "    05  PIC X(5) VALUE 'UNUSED'.",
    "01  WS-PGM         PIC X(8) VALUE 'AUDITLOG'.",
    "77  WS-SWITCH      PIC 9 VALUE 1.",
    "01  WS-EOF         PIC X VALUE 'N'.",
    "    88  END-OF-FILE VALUE 'Y'.",
    "COPY CUSTREC REPLACING ==:PFX:== BY ==WS-CUST==.",
    "COPY MISSING1.",
    "COPY DFHAID.",
    "LINKAGE SECTION.",
    "01  LK-PARM.",
    "    05  LK-LEN     PIC S9(4) COMP.",
    "PROCEDURE DIVISION USING LK-PARM.",
    "*  MAIN LINE",
    "0000-MAIN.",
    "    PERFORM 1000-INIT THRU 1000-EXIT.",
    "    PERFORM 2000-PROCESS UNTIL END-OF-FILE.",
    "    SORT SORT-WORK ON ASCENDING KEY SORT-REC",
    "        INPUT PROCEDURE IS 3000-SORT-IN THRU 3000-EXIT",
    "        GIVING TRAN-FILE.",
    "    GO TO 9000-END.",
    "*----------------------------------------------",
    "* 1000-INIT: OPEN FILES",
    "*----------------------------------------------",
    "1000-INIT.",
    "    OPEN I-O CUST-FILE INPUT TRAN-FILE OUTPUT RPT-FILE.",
    "    IF WS-CUST-FS NOT = '00'",
    "        GO TO 1000-EXIT",
    "    END-IF.",
    "    MOVE 'AUDITLG2' TO WS-PGM.",
    "    DISPLAY 'COPY FAKE.'.",
    "1000-EXIT.",
    "    EXIT.",
    "2000-PROCESS.",
    "    READ TRAN-FILE AT END SET END-OF-FILE TO TRUE",
    "    NOT AT END PERFORM 2100-APPLY",
    "    END-READ.",
    "2100-APPLY.",
    "    EVALUATE WS-CUST-STATUS",
    "       WHEN 'A' COMPUTE WS-CUST-BALANCE = WS-CUST-BALANCE * 1.05",
    "       WHEN 'C' GO TO 9900-ERROR",
    "       WHEN OTHER CONTINUE",
    "    END-EVALUATE.",
    "    IF WS-CUST-BALANCE > 10000 AND WS-CUST-ACTIVE",
    "       CALL WS-PGM USING WS-CUST-RECORD",
    "    END-IF.",
    "    MULTIPLY WS-RATE BY WS-CUST-BALANCE GIVING WS-INTEREST.",
    "    REWRITE CUST-REC.",
    "    WRITE RPT-LINE.",
    "    GO TO 2500-NEXT 2600-OTHER DEPENDING ON WS-SWITCH.",
    "2500-NEXT.",
    "    ALTER 2600-OTHER TO PROCEED TO 2700-LATE.",
    "2600-OTHER.",
    "    GO TO.",
    "2700-LATE.",
    "    GO TO 9000-END.",
    "3000-SORT-IN.",
    "    RELEASE SORT-REC.",
    "3000-EXIT.",
    "    EXIT.",
    "4000-DEAD.",
    "    DISPLAY 'NEVER'.",
    "9000-END.",
    "    CLOSE CUST-FILE TRAN-FILE RPT-FILE.",
    "    STOP RUN.",
    "COPY ERRPARA.",
)
ONLINE = (
    "ID DIVISION.",
    "PROGRAM-ID. CUSTINQ.",
    "*  ONLINE CUSTOMER INQUIRY",
    "ENVIRONMENT DIVISION.",
    "DATA DIVISION.",
    "WORKING-STORAGE SECTION.",
    "01  WS-NEXT     PIC X(8).",
    "01  GU-FUNC     PIC X(4) VALUE 'GU  '.",
    "    EXEC SQL INCLUDE SQLCA END-EXEC.",
    "PROCEDURE DIVISION.",
    "DECLARATIVES.",
    "IO-ERRORS SECTION.",
    "    USE AFTER ERROR PROCEDURE ON CUST-FILE.",
    "IO-ERR-1.",
    "    DISPLAY 'IO ERROR'.",
    "END DECLARATIVES.",
    "0000-MAIN SECTION.",
    "    EXEC CICS HANDLE CONDITION NOTFND(8000-NOTFND)",
    "         ERROR(9999-MISSING) RESP(WS-RESP) END-EXEC.",
    "    EXEC CICS HANDLE AID PF3(8100-EXIT) END-EXEC.",
    "    EXEC CICS HANDLE ABEND LABEL(8000-NOTFND) END-EXEC.",
    "    PERFORM 1000-WORK.",
    "    PERFORM 3 TIMES",
    "       EXEC CICS LINK PROGRAM('CUSTBAL') COMMAREA(WS-NEXT)",
    "       END-EXEC",
    "    END-PERFORM.",
    "    EXEC CICS RETURN TRANSID('CINQ') END-EXEC.",
    "0000-NEXT.",
    "    MOVE 'MENU01' TO WS-NEXT.",
    "    MOVE 'MENU01' TO WS-NEXT.",
    "    EXEC CICS XCTL PROGRAM(WS-NEXT) END-EXEC.",
    "1000-WORK SECTION.",
    "1000-A.",
    "    EXEC SQL DECLARE C1 CURSOR FOR SELECT NAME",
    "         FROM CUST.CUSTOMER WHERE ID = :WS-NEXT END-EXEC.",
    "    EXEC SQL FETCH C1 INTO :WS-NEXT END-EXEC.",
    "    EXEC DLI GU USING PCB(1) SEGMENT(CUSTSEG) END-EXEC.",
    "    CALL 'CBLTDLI' USING GU-FUNC DB-PCB IO-AREA.",
    "    CALL 'AIBTDLI' USING 'ISRT' AIB.",
    "    MOVE 'CUST.REPLY.QUEUE' TO MQOD-OBJECTNAME.",
    "    CALL 'MQOPEN' USING HCONN MQOD.",
    "    CALL 'DATEUTIL' USING BY CONTENT WS-NEXT",
    "        ON EXCEPTION CONTINUE END-CALL.",
    "    CALL WS-UNKNOWN USING WS-NEXT.",
    "    PERFORM 2000-LOOP.",
    "1000-B.",
    "    GO TO 3000-SEC.",
    "2000-LOOP SECTION.",
    "    PERFORM 1000-WORK.",
    "3000-SEC SECTION.",
    "3000-A.",
    "    ENTRY 'CUSTALT' USING WS-NEXT.",
    "    GOBACK.",
    "8000-NOTFND SECTION.",
    "    EXEC CICS RETURN END-EXEC.",
    "8100-EXIT SECTION 50.",
    "    EXEC CICS SEND MAP('CUSTM1') MAPSET('CUSTMAP') END-EXEC.",
    "    EXEC CICS READQ TS QUEUE('CUSTQ') INTO(WS-NEXT) END-EXEC.",
    "    EXEC CICS RETURN END-EXEC.",
    "9000-ORPHAN SECTION.",
    "9000-A.",
    "    DISPLAY 'ORPHAN'.",
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. INNER.",
    "PROCEDURE DIVISION.",
    "    GOBACK.",
    "END PROGRAM INNER.",
    "END PROGRAM CUSTINQ.",
    "IDENTIFICATION DIVISION.",
    "PROGRAM-ID. SIBLING.",
    "PROCEDURE DIVISION.",
    "    GOBACK.",
    "END PROGRAM SIBLING.",
)


@pytest.fixture
def batch(tmp_path: Path) -> Path:
    library = tmp_path / "copy"
    (library / "old").mkdir(parents=True)
    (library / "CUSTREC.cpy").write_text(fixed(*CUSTREC), encoding="utf-8")
    (library / "old" / "CUSTREC.txt").write_text(fixed(*CUSTREC), encoding="utf-8")
    (tmp_path / "ERRPARA.cpy").write_text(fixed(*ERRPARA), encoding="utf-8")
    program = tmp_path / "CUSTUPD.cbl"
    program.write_text(fixed(*BATCH), encoding="utf-8")
    return program


@pytest.fixture
def batch_result(batch: Path) -> dict:
    return cobol_flow.analyze_program(batch, copylibs=[batch.parent / "copy"])


@pytest.fixture
def online(tmp_path: Path) -> Path:
    program = tmp_path / "CUSTINQ.cbl"
    program.write_text(fixed(*ONLINE), encoding="utf-8")
    return program


def edges(result: dict) -> set[tuple[str, str, str]]:
    return {(edge["from"], edge["to"], edge["kind"]) for edge in result["edges"]}


def test_flow_graph_reachability_and_risks(batch_result: dict) -> None:
    assert edges(batch_result) == {
        ("0000-MAIN", "1000-INIT", "thru"),
        ("0000-MAIN", "2000-PROCESS", "perform"),
        ("0000-MAIN", "3000-SORT-IN", "sort-input"),
        ("0000-MAIN", "9000-END", "go-to"),
        ("1000-INIT", "1000-EXIT", "go-to"),
        ("1000-INIT", "1000-EXIT", "next"),
        ("1000-EXIT", "2000-PROCESS", "next"),
        ("2000-PROCESS", "2100-APPLY", "perform"),
        ("2000-PROCESS", "2100-APPLY", "next"),
        ("2100-APPLY", "9900-ERROR", "go-to"),
        ("2100-APPLY", "2500-NEXT", "go-to-depending"),
        ("2100-APPLY", "2600-OTHER", "go-to-depending"),
        ("2100-APPLY", "2500-NEXT", "next"),
        ("2500-NEXT", "2600-OTHER", "next"),
        ("2600-OTHER", "2700-LATE", "altered"),
        ("2700-LATE", "9000-END", "go-to"),
        ("3000-SORT-IN", "3000-EXIT", "next"),
        ("3000-EXIT", "4000-DEAD", "next"),
        ("4000-DEAD", "9000-END", "next"),
    }
    # 3000-EXIT ends the SORT input range, so it returns instead of falling into 4000-DEAD.
    assert batch_result["unreachable"] == ["4000-DEAD"]
    procedures = {p["name"]: p for p in batch_result["procedures"]}
    assert procedures["0000-MAIN"]["root"] is True
    assert procedures["0000-MAIN"]["description"] == "MAIN LINE"
    assert procedures["1000-INIT"]["description"] == "OPEN FILES"
    assert procedures["2600-OTHER"]["falls_through"] is False
    assert procedures["9900-ERROR"]["copybook"] == "ERRPARA"
    assert procedures["9900-ERROR"]["line"] == line_of(BATCH, "COPY ERRPARA.")
    assert procedures["0000-MAIN"]["performs"] == [
        "1000-INIT THRU 1000-EXIT",
        "2000-PROCESS",
        "3000-SORT-IN THRU 3000-EXIT",
    ]
    risks = batch_result["risks"]
    assert [
        (r["paragraph"], r["go_to"], r["range"]) for r in risks["go_to_leaves_perform_range"]
    ] == [
        ("2100-APPLY", "9900-ERROR", "2100-APPLY"),
        ("2100-APPLY", "2500-NEXT", "2100-APPLY"),
        ("2100-APPLY", "2600-OTHER", "2100-APPLY"),
    ]
    alter_line = line_of(BATCH, "    ALTER 2600-OTHER TO PROCEED TO 2700-LATE.")
    assert risks["alter"] == [
        {
            "paragraph": "2500-NEXT",
            "line": alter_line,
            "altered": "2600-OTHER",
            "proceeds_to": "2700-LATE",
        }
    ]
    assert risks["alterable_go_to"] == [
        {"paragraph": "2600-OTHER", "line": line_of(BATCH, "    GO TO.")}
    ]
    assert risks["go_to_depending"][0]["depending_on"] == "WS-SWITCH"
    assert risks["perform_cycles"] == []
    counts = batch_result["counts"]
    assert (counts["sections"], counts["paragraphs"], counts["performs"], counts["go_tos"]) == (
        0,
        13,
        3,
        6,
    )
    assert (counts["alters"], counts["unreachable"]) == (1, 1)


def test_copy_expansion_replacing_and_data_division(batch_result: dict) -> None:
    copybooks = [(c["member"], c["line"], c["status"]) for c in batch_result["copybooks"]]
    assert copybooks == [
        ("CUSTREC", line_of(BATCH, "COPY CUSTREC REPLACING ==:PFX:== BY ==WS-CUST==."), "resolved"),
        ("MISSING1", line_of(BATCH, "COPY MISSING1."), "unresolved"),
        ("DFHAID", line_of(BATCH, "COPY DFHAID."), "system"),
        ("ERRPARA", line_of(BATCH, "COPY ERRPARA."), "resolved"),
    ]
    assert batch_result["copybooks"][0]["path"].endswith("CUSTREC.cpy")
    assert any("COPY CUSTREC: 2 candidates" in warning for warning in batch_result["warnings"])
    working = batch_result["data"]["WORKING-STORAGE"]
    assert {
        "name": "WS-CUST-RECORD",
        "level": 1,
        "line": line_of(BATCH, "COPY CUSTREC REPLACING ==:PFX:== BY ==WS-CUST==."),
        "copybook": "CUSTREC",
    } in working["records"]
    assert [c["member"] for c in working["copybooks"]] == ["CUSTREC", "MISSING1", "DFHAID"]
    assert [(r["name"], r["level"]) for r in working["records"][:4]] == [
        ("WS-CUST-FS", 1),
        ("WS-UNNAMED", 1),
        ("WS-PGM", 1),
        ("WS-SWITCH", 77),
    ]
    files = [(r["name"], r.get("file")) for r in batch_result["data"]["FILE"]["records"]]
    assert files == [
        ("CUST-REC", "CUST-FILE"),
        ("TRAN-REC", "TRAN-FILE"),
        ("RPT-LINE", "RPT-FILE"),
        ("SORT-REC", "SORT-WORK"),
    ]
    assert batch_result["data"]["LINKAGE"]["records"][0]["name"] == "LK-PARM"
    assert batch_result["condition_names"] == {
        "END-OF-FILE": {"of": "WS-EOF", "values": "'Y'"},
        "WS-CUST-ACTIVE": {"of": "WS-CUST-STATUS", "values": "'A'"},
        "WS-CUST-CLOSED": {"of": "WS-CUST-STATUS", "values": "'C' 'X'"},
    }
    assert batch_result["identification"] == {
        "AUTHOR": "J SMITH",
        "INSTALLATION": "ACME BANK",
        "DATE-WRITTEN": "1989-01-15",
        "REMARKS": "NIGHTLY CUSTOMER UPDATE WITH AUDIT TRAIL",
    }
    assert batch_result["header_comments"] == ["CUSTUPD: APPLY DAILY CUSTOMER UPDATES"]
    assert batch_result["procedure_division"]["using"] == ["LK-PARM"]


def test_business_rule_candidates(batch_result: dict) -> None:
    rules = [
        (r["id"], r["paragraph"], r["kind"], r["text"], r["data_names"], r["signals"])
        for r in batch_result["rules"]
    ]
    assert rules == [
        (
            "BR-001",
            "0000-MAIN",
            "condition",
            "PERFORM 2000-PROCESS UNTIL END-OF-FILE",
            ["END-OF-FILE"],
            ["condition-name"],
        ),
        (
            "BR-002",
            "1000-INIT",
            "if",
            "IF WS-CUST-FS NOT = '00'",
            ["WS-CUST-FS"],
            ["literal-comparison", "technical"],
        ),
        (
            "BR-003",
            "2000-PROCESS",
            "set-condition",
            "SET END-OF-FILE TO TRUE",
            ["END-OF-FILE"],
            ["condition-name"],
        ),
        (
            "BR-004",
            "2100-APPLY",
            "evaluate",
            "EVALUATE WS-CUST-STATUS WHEN 'A' WHEN 'C' WHEN OTHER",
            ["WS-CUST-STATUS"],
            ["literal-comparison"],
        ),
        (
            "BR-005",
            "2100-APPLY",
            "compute",
            "COMPUTE WS-CUST-BALANCE = WS-CUST-BALANCE * 1.05",
            ["WS-CUST-BALANCE"],
            ["literal-constant"],
        ),
        (
            "BR-006",
            "2100-APPLY",
            "if",
            "IF WS-CUST-BALANCE > 10000 AND WS-CUST-ACTIVE",
            ["WS-CUST-BALANCE", "WS-CUST-ACTIVE"],
            ["condition-name", "literal-comparison"],
        ),
        (
            "BR-007",
            "2100-APPLY",
            "arithmetic",
            "MULTIPLY WS-RATE BY WS-CUST-BALANCE GIVING WS-INTEREST",
            ["WS-RATE", "WS-CUST-BALANCE", "WS-INTEREST"],
            [],
        ),
        (
            "BR-008",
            "9900-ERROR",
            "if",
            "IF RETURN-CODE > 8",
            ["RETURN-CODE"],
            ["literal-comparison", "technical"],
        ),
    ]
    assert batch_result["rules"][7]["copybook"] == "ERRPARA"
    assert batch_result["rules"][7]["line"] == line_of(BATCH, "COPY ERRPARA.")
    evaluate = batch_result["rules"][3]
    assert [when["text"] for when in evaluate["whens"]] == ["WHEN 'A'", "WHEN 'C'", "WHEN OTHER"]
    assert batch_result["rules"][5]["literals"] == ["10000"]
    assert batch_result["rules"][5]["line"] == line_of(
        BATCH, "    IF WS-CUST-BALANCE > 10000 AND WS-CUST-ACTIVE"
    )


def test_files_dynamic_calls_and_file_io(batch_result: dict) -> None:
    files = {entry["select"]: entry for entry in batch_result["files"]}
    assert files["CUST-FILE"] | {"line": 0} == {
        "select": "CUST-FILE",
        "assign": "CUSTMAST",
        "ddname": "CUSTMAST",
        "organization": "INDEXED",
        "access": "DYNAMIC",
        "record_key": "CUST-KEY",
        "alternate_keys": ["CUST-NAME"],
        "file_status": "WS-CUST-FS",
        "optional": False,
        "line": 0,
    }
    assert (files["TRAN-FILE"]["ddname"], files["TRAN-FILE"]["organization"]) == (
        "TRANIN",
        "SEQUENTIAL",
    )
    report = files["RPT-FILE"]
    assert (report["assign"], report["organization"], report["optional"]) == (
        "report.txt",
        "LINE SEQUENTIAL",
        True,
    )
    calls = batch_result["interfaces"]["calls"]
    assert calls == [
        {
            "target": "WS-PGM",
            "type": "dynamic",
            "resolved": ["AUDITLOG", "AUDITLG2"],
            "paragraph": "2100-APPLY",
            "line": line_of(BATCH, "       CALL WS-PGM USING WS-CUST-RECORD"),
            "using": ["WS-CUST-RECORD"],
        }
    ]
    file_io = {
        name: [use["verb"] for use in uses]
        for name, uses in batch_result["interfaces"]["file_io"].items()
    }
    assert file_io == {
        "SORT-WORK": ["SORT", "RELEASE"],
        "TRAN-FILE": ["SORT GIVING", "OPEN INPUT", "READ", "CLOSE"],
        "CUST-FILE": ["OPEN I-O", "REWRITE", "CLOSE"],
        "RPT-FILE": ["OPEN OUTPUT", "WRITE", "CLOSE"],
    }


def test_sections_declaratives_cics_handles_and_interfaces(online: Path) -> None:
    result = cobol_flow.analyze_program(online)
    procedures = {p["name"]: p for p in result["procedures"]}
    assert [name for name, p in procedures.items() if p["root"]] == [
        "IO-ERRORS",
        "0000-MAIN",
        "3000-A",
    ]
    assert procedures["IO-ERRORS"]["use"] == "USE AFTER ERROR PROCEDURE ON CUST-FILE"
    assert procedures["8100-EXIT"]["kind"] == "section"
    assert result["unreachable"] == ["9000-ORPHAN", "9000-A"]
    assert {
        ("0000-MAIN", "8000-NOTFND", "cics-handle"),
        ("0000-MAIN", "8100-EXIT", "cics-handle"),
        ("0000-MAIN", "1000-WORK", "perform"),
        ("0000-MAIN", "0000-NEXT", "next"),
        ("1000-B", "3000-SEC", "go-to"),
    } <= edges(result)
    # RETURN without TRANSID and XCTL end a paragraph; RETURN TRANSID may fall through.
    assert procedures["0000-MAIN"]["falls_through"] is True
    assert procedures["0000-NEXT"]["falls_through"] is False
    assert procedures["8000-NOTFND"]["falls_through"] is False
    risks = result["risks"]
    assert risks["perform_cycles"] == [["1000-A", "2000-LOOP"]]
    assert risks["go_to_leaves_perform_range"][0] | {"line": 0, "perform_line": 0} == {
        "paragraph": "1000-B",
        "line": 0,
        "go_to": "3000-SEC",
        "range": "1000-WORK",
        "performed_from": "0000-MAIN",
        "perform_line": 0,
    }
    assert [(h["command"], h["labels"]) for h in risks["cics_handle"]] == [
        ("HANDLE CONDITION", {"NOTFND": "8000-NOTFND", "ERROR": "9999-MISSING"}),
        ("HANDLE AID", {"PF3": "8100-EXIT"}),
        ("HANDLE ABEND", {"LABEL": "8000-NOTFND"}),
    ]
    assert [r["name"] for r in risks["unresolved_procedures"]] == ["9999-MISSING"]
    assert result["nested_programs"] == [
        {"name": "INNER", "line": line_of(ONLINE, "PROGRAM-ID. INNER."), "relation": "nested"},
        {
            "name": "SIBLING",
            "line": line_of(ONLINE, "PROGRAM-ID. SIBLING."),
            "relation": "following",
        },
    ]
    assert result["procedure_division"]["entry_points"] == [
        {
            "name": "CUSTALT",
            "paragraph": "3000-A",
            "line": line_of(ONLINE, "    ENTRY 'CUSTALT' USING WS-NEXT."),
        }
    ]
    assert result["copybooks"] == [
        {
            "member": "SQLCA",
            "line": line_of(ONLINE, "    EXEC SQL INCLUDE SQLCA END-EXEC."),
            "status": "system",
        }
    ]
    assert (result["counts"]["sections"], result["counts"]["inline_performs"]) == (8, 1)
    interfaces = result["interfaces"]
    cics = [
        (c["command"], [(r["option"], r["name"]) for r in c["resources"]])
        for c in interfaces["cics"]
    ]
    assert cics == [
        ("HANDLE CONDITION", []),
        ("HANDLE AID", []),
        ("HANDLE ABEND", []),
        ("LINK", [("PROGRAM", "CUSTBAL")]),
        ("RETURN", [("TRANSID", "CINQ")]),
        ("XCTL", [("PROGRAM", "WS-NEXT")]),
        ("RETURN", []),
        ("SEND MAP", [("MAP", "CUSTM1"), ("MAPSET", "CUSTMAP")]),
        ("READQ TS", [("QUEUE", "CUSTQ")]),
        ("RETURN", []),
    ]
    assert interfaces["cics"][5]["resources"][0] == {
        "option": "PROGRAM",
        "name": "WS-NEXT",
        "dynamic": True,
        "resolved": ["MENU01"],
    }
    assert [(s["statement"], s["tables"]) for s in interfaces["sql"]] == [
        ("DECLARE CURSOR", ["CUST.CUSTOMER"]),
        ("FETCH", []),
    ]
    assert [
        (d["via"], d["function"], d.get("pcb"), d.get("segments")) for d in interfaces["dli"]
    ] == [
        ("EXEC DLI", "GU", None, ["CUSTSEG"]),
        ("CALL CBLTDLI", "GU", "DB-PCB", None),
        ("CALL AIBTDLI", "ISRT", "AIB", None),
    ]
    assert [m["call"] for m in interfaces["mq"]] == ["MQOPEN"]
    assert interfaces["calls"][3]["using"] == ["WS-NEXT"]
    assert result["header_comments"] == ["ONLINE CUSTOMER INQUIRY"]
    assert interfaces["mq_queues"] == ["CUST.REPLY.QUEUE"]
    assert [
        (c["target"], c["type"], c.get("interface"), c.get("resolved")) for c in interfaces["calls"]
    ] == [
        ("CBLTDLI", "static", "ims", None),
        ("AIBTDLI", "static", "ims", None),
        ("MQOPEN", "static", "mq", None),
        ("DATEUTIL", "static", None, None),
        ("WS-UNKNOWN", "dynamic", None, []),
    ]
    markdown = cobol_flow.to_markdown(result)
    at = {text: line_of(ONLINE, text) for text in ONLINE}
    handle = at["    EXEC CICS HANDLE CONDITION NOTFND(8000-NOTFND)"]
    entry = at["    ENTRY 'CUSTALT' USING WS-NEXT."]
    dli = at["    CALL 'CBLTDLI' USING GU-FUNC DB-PCB IO-AREA."]
    mq = at["    CALL 'MQOPEN' USING HCONN MQOD."]
    for text in (
        (
            f"| Other programs in the source | INNER (line {at['PROGRAM-ID. INNER.']}, nested), "
            f"SIBLING (line {at['PROGRAM-ID. SIBLING.']}, following) |"
        ),
        f"| ENTRY points | CUSTALT (3000-A, line {entry}) |",
        f"| **0000-MAIN SECTION** | {at['0000-MAIN SECTION.']} | _To complete_ | 1000-WORK |",
        (
            f"| XCTL | PROGRAM(WS-NEXT) = MENU01 | 0000-NEXT | "
            f"{at['    EXEC CICS XCTL PROGRAM(WS-NEXT) END-EXEC.']} |"
        ),
        (
            f"| DECLARE CURSOR | CUST.CUSTOMER | 1000-A | "
            f"{at['    EXEC SQL DECLARE C1 CURSOR FOR SELECT NAME']} |"
        ),
        f"| CALL CBLTDLI | GU | DB-PCB | 1000-A | {dli} |",
        f"| MQOPEN | 1000-A | {mq} |",
        "Queue names moved to an object descriptor: CUST.REPLY.QUEUE",
        f"| WS-UNKNOWN | dynamic |  | 1000-A | {at['    CALL WS-UNKNOWN USING WS-NEXT.']} |",
        "- [ ] Find the run-time values of WS-UNKNOWN, the dynamic CALL targets",
        (
            f"- HANDLE CONDITION in 0000-MAIN (line {handle}): NOTFND -> 8000-NOTFND, "
            "ERROR -> 9999-MISSING; handlers act like GO TO"
        ),
        "- Recursive PERFORM cycle: 1000-A -> 2000-LOOP.",
        f"- Procedure 9999-MISSING referenced in 0000-MAIN (line {handle}) is not defined",
    ):
        assert text in markdown


def test_ebcdic_member_continuations_and_copy_edge_cases(tmp_path: Path) -> None:
    literal = "    IF WS-CODE = 'IT''S CONTINUED "
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. LEGACY.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "COPY LOOPCPY.",
        "01  WS-PRE PIC X. COPY TINYCPY. 01  WS-POST PIC X.",
        "COPY 'QUOTED' REPLACING LEADING ==WS== BY ==LK==",
        "    TRAILING ==QUOTED== BY ==RENAMED== PIC BY PICTURE.",
        "COPY BINCPY.",
        "PROCEDURE DIVISION.",
        "    PERFORM 1000-",
        "-    SAY.",
        "    STOP RUN.",
        "D|   DISPLAY 'DEBUG ONLY'.",
        "1000-SAY.",
        literal + "L" * (65 - len(literal)),
        "-    'ITERAL'",
        "       DISPLAY 'MATCH'",
        "    END-IF.",
    )
    data = b"".join(
        zos_encoding.encode(line.ljust(80), "037") for line in fixed(*lines).splitlines()
    )
    program = tmp_path / "LEGACY"
    program.write_bytes(data)
    (tmp_path / "LOOPCPY.cpy").write_text(
        fixed("01  WS-LOOP PIC X.", "COPY LOOPCPY."), encoding="utf-8"
    )
    (tmp_path / "QUOTED.cpy").write_text(fixed("01  WS-QUOTED PIC X."), encoding="utf-8")
    (tmp_path / "TINYCPY.cpy").write_text(fixed("01  WS-TINY PIC X."), encoding="utf-8")
    (tmp_path / "BINCPY.cpy").write_bytes(b"\x00\x01\x02")
    result = cobol_flow.analyze_program(program, copylibs=[tmp_path / "absent"])
    assert (result["encoding"], result["format"], result["program_id"]) == (
        "ebcdic-cp037",
        "fixed",
        "LEGACY",
    )
    assert [(c["member"], c["status"], c.get("in")) for c in result["copybooks"]] == [
        ("LOOPCPY", "resolved", None),
        ("LOOPCPY", "skipped", "LOOPCPY"),
        ("TINYCPY", "resolved", None),
        ("QUOTED", "resolved", None),
        ("BINCPY", "skipped", None),
    ]
    records = [r["name"] for r in result["data"]["WORKING-STORAGE"]["records"]]
    assert records == ["WS-LOOP", "WS-PRE", "WS-TINY", "WS-POST", "LK-RENAMED"]
    warnings = " ".join(result["warnings"])
    assert "copy library not found" in warnings
    assert "COPY LOOPCPY: recursive" in warnings
    assert "BINCPY.cpy is binary" in warnings
    start = result["procedures"][0]
    assert (start["name"], start["kind"], start["root"], start["statements"]) == (
        "(start)",
        "start",
        True,
        2,
    )
    expected = "IF WS-CODE = 'IT''S CONTINUED " + "L" * (65 - len(literal)) + "ITERAL'"
    assert [rule["text"] for rule in result["rules"]] == [expected]
    assert result["unreachable"] == []
    assert edges(result) == {("(start)", "1000-SAY", "perform")}


def test_free_format_source(tmp_path: Path) -> None:
    program = tmp_path / "FREEPGM.cbl"
    program.write_text(
        "       >>SOURCE FORMAT FREE\n"
        ">>CALLINTERFACE STATIC\n"
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. FREEPGM.\n"
        "PROCEDURE DIVISION.\n"
        "*> Main control.\n"
        "MAIN-PARA.\n"
        "    PERFORM SUB-PARA *> floating comment\n"
        "    DISPLAY 'NOT A HEADER'\n"
        "        WS-NAME.\n"
        "    MOVE X'FF' TO WS-HEX\n"
        "    DISPLAY 'IT''S' 'OPEN\n"
        "EJECT\n"
        "    STOP RUN.\n"
        "SUB-PARA. DISPLAY 'HI'.\n"
        "UNUSED-PARA.\n"
        "    DISPLAY 'NO'.\n",
        encoding="utf-8",
    )
    result = cobol_flow.analyze_program(program)
    assert result["format"] == "free"
    assert [(p["name"], p["description"]) for p in result["procedures"]] == [
        ("MAIN-PARA", "Main control."),
        ("SUB-PARA", ""),
        ("UNUSED-PARA", ""),
    ]
    # SUB-PARA is performed, so it returns rather than falling into UNUSED-PARA.
    assert result["unreachable"] == ["UNUSED-PARA"]


def test_statement_nesting_and_qualified_names(tmp_path: Path) -> None:
    lines = (
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. NESTING.",
        "PROCEDURE DIVISION USING LK-A RETURNING LK-RC.",
        "A000 SECTION.",
        "A100.",
        "    PERFORM B100 OF B000.",
        "    PERFORM A300 THRU A100.",
        "    PERFORM 7777-NOWHERE.",
        "    IF WS-A = 1",
        "       IF WS-B = 2 NEXT SENTENCE",
        "       ELSE MOVE 1 TO WS-C",
        "       ELSE MOVE 2 TO WS-C.",
        "    SEARCH WS-TABLE AT END MOVE 0 TO WS-C",
        "       WHEN WS-KEY(WS-IX) = 'K1' MOVE 1 TO WS-C",
        "       WHEN WS-ACTIVE(WS-IX) CONTINUE",
        "    END-SEARCH.",
        "    ADD WS-A TO WS-B GIVING WS-C ON SIZE ERROR MOVE 0 TO WS-C",
        "    NOT ON SIZE ERROR MOVE 1 TO WS-D END-ADD.",
        "    SET WS-DONE TO FALSE.",
        "    PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3",
        "       DISPLAY WS-I",
        "    END-PERFORM.",
        "    COMPUTE WS-AGE = FUNCTION INTEGER(WS-DAYS) / 365.",
        "    OPEN INPUT IN-FILE WITH NO REWIND.",
        "    READ IN-FILE END-READ.",
        "    CLOSE IN-FILE WITH LOCK.",
        "    IF WS-B = 3 GO TO 8888-NOWHERE.",
        "    IF WS-A = 1 GO TO A300.",
        "A300.",
        "    EXIT PROGRAM.",
        "B000 SECTION.",
        "B100.",
        "    SORT SD-FILE ASCENDING KEY K",
        "       INPUT PROCEDURE A100 OUTPUT PROCEDURE IS B200.",
        "B200.",
        "    DISPLAY FUNCTION UPPER-CASE(WS-NAME).",
    )
    program = tmp_path / "NESTING.cbl"
    program.write_text(fixed(*lines), encoding="utf-8")
    result = cobol_flow.analyze_program(program)
    assert {
        ("A100", "B100", "perform"),
        ("A100", "A300", "thru"),
        ("A100", "A300", "go-to"),
        ("B100", "A100", "sort-input"),
        ("B100", "B200", "sort-output"),
    } <= edges(result)
    assert "line 7: THRU A100 precedes A300" in result["warnings"]
    unresolved = [r["name"] for r in result["risks"]["unresolved_procedures"]]
    assert unresolved == ["7777-NOWHERE", "8888-NOWHERE"]
    procedures = {p["name"]: p for p in result["procedures"]}
    # The last statement of A100 is a GO TO inside an IF, so A100 can still fall through.
    assert procedures["A100"]["falls_through"] is True
    assert procedures["A300"]["falls_through"] is False
    assert result["procedure_division"] | {"line": 0} == {
        "line": 0,
        "using": ["LK-A"],
        "returning": "LK-RC",
        "entry_points": [],
    }
    assert result["counts"]["inline_performs"] == 1
    rules = [(r["kind"], r["text"], r["signals"]) for r in result["rules"]]
    assert rules == [
        ("if", "IF WS-A = 1", ["literal-comparison"]),
        ("if", "IF WS-B = 2", ["literal-comparison"]),
        ("condition", "WHEN WS-KEY(WS-IX) = 'K1'", ["literal-comparison"]),
        ("arithmetic", "ADD WS-A TO WS-B GIVING WS-C ON SIZE ERROR", []),
        ("set-condition", "SET WS-DONE TO FALSE", []),
        (
            "condition",
            "PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 3",
            ["literal-comparison"],
        ),
        ("compute", "COMPUTE WS-AGE = FUNCTION INTEGER(WS-DAYS) / 365", ["literal-constant"]),
        ("if", "IF WS-B = 3", ["literal-comparison"]),
        ("if", "IF WS-A = 1", ["literal-comparison"]),
    ]
    assert result["rules"][2]["data_names"] == ["WS-KEY", "WS-IX"]
    assert result["rules"][6]["data_names"] == ["WS-AGE", "WS-DAYS"]
    file_io = {
        name: [use["verb"] for use in uses]
        for name, uses in result["interfaces"]["file_io"].items()
    }
    assert file_io == {"IN-FILE": ["OPEN INPUT", "READ", "CLOSE"], "SD-FILE": ["SORT"]}


def test_mermaid_styles_and_truncation(batch_result: dict, online: Path) -> None:
    mermaid = cobol_flow.to_mermaid(batch_result)
    assert mermaid.startswith("flowchart TD\n")
    for line in (
        '  n0_0000_MAIN["0000-MAIN"]',
        "  n0_0000_MAIN -->|thru 1000-EXIT| n1_1000_INIT",
        "  n0_0000_MAIN -->|perform| n3_2000_PROCESS",
        "  n0_0000_MAIN -->|sort input thru 3000-EXIT| n8_3000_SORT_IN",
        "  n1_1000_INIT -.->|go to| n2_1000_EXIT",
        "  n4_2100_APPLY -.->|go to depending| n5_2500_NEXT",
        "  n1_1000_INIT -.->|next| n2_1000_EXIT",
        "  n6_2600_OTHER ==>|altered| n7_2700_LATE",
        "  class n0_0000_MAIN entry",
        "  class n10_4000_DEAD unreachable",
    ):
        assert line in mermaid.splitlines()
    short = cobol_flow.to_mermaid(batch_result, max_nodes=2)
    assert (
        "  %% truncated: showing 2 of 13 procedures; use --format json for the full graph" in short
    )
    assert short.count('["') == 2
    assert "n3_2000_PROCESS" not in short
    online_mermaid = cobol_flow.to_mermaid(cobol_flow.analyze_program(online))
    assert '  n2_0000_MAIN["0000-MAIN SECTION"]' in online_mermaid
    assert "  n2_0000_MAIN -.->|handle NOTFND| n10_8000_NOTFND" in online_mermaid
    assert "  n2_0000_MAIN -->|perform| n4_1000_WORK" in online_mermaid


def test_markdown_skeleton(batch_result: dict) -> None:
    markdown = cobol_flow.to_markdown(batch_result)
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Overview",
        "## Files",
        "## Data",
        "## Interfaces",
        "## Procedure structure",
        "## Flow",
        "## Unreachable candidates",
        "## Structure risks",
        "## Business-rule candidates",
        "## To complete",
    ]
    assert "| Author | J SMITH |" in markdown
    files_row = "| CUST-FILE | CUSTMAST | INDEXED | DYNAMIC | CUST-KEY | WS-CUST-FS |"
    assert f"{files_row} OPEN I-O, REWRITE, CLOSE |" in markdown
    line = line_of(BATCH, "1000-INIT.")
    assert f"| 1000-INIT | {line} | OPEN FILES |  | 1000-EXIT |  |" in markdown
    assert "| 4000-DEAD | paragraph | " in markdown
    main = line_of(BATCH, "0000-MAIN.")
    performs = "1000-INIT THRU 1000-EXIT, 2000-PROCESS, 3000-SORT-IN THRU 3000-EXIT"
    assert f"| 0000-MAIN | {main} | MAIN LINE | {performs} | 9000-END | entry point |" in markdown
    assert (
        f"| 4000-DEAD | {line_of(BATCH, '4000-DEAD.')} | _To complete_ |  |  | unreachable? |"
        in (markdown)
    )
    assert "```mermaid\nflowchart TD" in markdown
    assert "| BR-007 | 2100-APPLY |" in markdown
    assert "- [ ] Obtain the copybooks MISSING1 and rerun with --copylib." in markdown
    assert "ALTER in 2500-NEXT" in markdown


def test_markdown_for_a_minimal_program(tmp_path: Path) -> None:
    long_comment = "*  " + "DESCRIBES THE PARAGRAPH AT GREAT LENGTH " * 2
    program = tmp_path / "TINY.cbl"
    program.write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. TINY.",
            "PROCEDURE DIVISION.",
            long_comment[:60],
            "*  AND THEN SOME MORE TEXT TO PASS ONE HUNDRED AND TWENTY CHARS",
            "*  IN TOTAL.",
            "MAIN-PARA.",
            "    GOBACK.",
        ),
        encoding="utf-8",
    )
    markdown = cobol_flow.to_markdown(cobol_flow.analyze_program(program))
    for text in (
        "No FILE-CONTROL entries.",
        "No CALL, CICS, SQL, DL/I, or MQ interfaces found.",
        "Every procedure is reachable from an entry point.",
        "No structure risks found.",
        "No candidates found.",
    ):
        assert text in markdown
    assert "...|" in markdown.replace(" |", "|")


def test_cobol_flow_cli(batch: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copylib = str(batch.parent / "copy")
    assert cobol_flow.main([str(batch), "--copylib", copylib]) == 0
    assert capsys.readouterr().out.startswith("# CUSTUPD: program documentation")
    assert cobol_flow.main([str(batch), "--copylib", copylib, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["program_id"] == "CUSTUPD"
    assert cobol_flow.main([str(batch), "--format", "mermaid", "--max-nodes", "3"]) == 0
    assert "%% truncated" in capsys.readouterr().out
    (tmp_path / "binary.cbl").write_bytes(b"\x00\x01\x02")
    (tmp_path / "data.cpy").write_text(fixed("01  JUST-DATA PIC X."), encoding="utf-8")
    for args, message in (
        ([str(tmp_path / "absent.cbl")], "not found"),
        ([str(tmp_path / "binary.cbl")], "binary content"),
        ([str(tmp_path / "data.cpy")], "no PROCEDURE DIVISION"),
        ([str(batch), "--codepage", "9999"], "unsupported code page"),
        ([str(batch), "--max-nodes", "0"], "--max-nodes"),
    ):
        assert cobol_flow.main(args) == 1
        assert message in capsys.readouterr().err


def bms_lines() -> list[str]:
    return [
        "* CUSTOMER INQUIRY MAPSET",
        *macro(
            "CUSTMAP",
            "DFHMSD",
            "TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL,",
            "STORAGE=AUTO,TIOAPFX=YES,CTRL=(FREEKB,FRSET),",
            "DSATTS=(COLOR,HILIGHT),MAPATTS=(COLOR,HILIGHT)",
        ),
        *macro("CUSTM1", "DFHMDI", "SIZE=(24,80),LINE=1,COLUMN=1"),
        *macro(
            "", "DFHMDF", "POS=(1,30),LENGTH=16,ATTRB=(ASKIP,BRT),", "INITIAL='CUSTOMER INQUIRY'"
        ),
        *macro("", "DFHMDF", "POS=(3,2),LENGTH=12,ATTRB=ASKIP,INITIAL='CUSTOMER ID:'"),
        *macro("CUSTID", "DFHMDF", "POS=(3,15),LENGTH=8,ATTRB=(NUM,IC),COLOR=GREEN"),
        *macro("", "DFHMDF", "POS=(3,24),LENGTH=1"),
        *macro("NAME", "DFHMDF", "POS=402,LENGTH=30,ATTRB=(ASKIP,NORM)"),
        *macro("PASSWD", "DFHMDF", "POS=(7,2),LENGTH=8,ATTRB=(UNPROT,DRK)"),
        *macro("LINE", "DFHMDF", "POS=(9,2),LENGTH=10,ATTRB=PROT,OCCURS=3"),
        *macro("MO", "DFHMDF", "POS=(11,1),LENGTH=2,ATTRB=NUM,GRPNAME=DATE"),
        *macro("SEP", "DFHMDF", "POS=(11,3),LENGTH=1,GRPNAME=DATE,INITIAL='-'"),
        *macro("DAY", "DFHMDF", "POS=(11,4),LENGTH=2,GRPNAME=DATE"),
        *macro("AMOUNT", "DFHMDF", "POS=(13,2),ATTRB=ASKIP,PICOUT='Z,ZZ9.99'"),
        *macro("NOLEN", "DFHMDF", "POS=(15,2),ATTRB=UNPROT"),
        *macro("OVER", "DFHMDF", "POS=(3,20),LENGTH=3,ATTRB=ASKIP"),
        *macro(
            "TITLE2",
            "DFHMDF",
            "POS=(20,2),LENGTH=60,INITIAL='CONTINUED STRING SPANNING",
            " TWO LINES'",
        ),
        *macro(
            "MSG",
            "DFHMDF",
            "POS=(24,2),LENGTH=79,ATTRB=(ASKIP,BRT),",
            "INITIAL='IT''S A, LONG MESSAGE'",
        ),
        *macro("", "DFHMSD", "TYPE=FINAL"),
        "         END",
    ]


@pytest.fixture
def bms(tmp_path: Path) -> Path:
    path = tmp_path / "CUSTMAP.bms"
    path.write_text("\n".join(bms_lines()) + "\n", encoding="utf-8")
    return path


def test_bms_field_model(bms: Path) -> None:
    result = screen_map.parse_screens(bms)
    assert result["kind"] == "bms"
    mapset = result["mapsets"][0]
    assert mapset | {"line": 0} == {
        "name": "CUSTMAP",
        "line": 0,
        "type": "&SYSPARM",
        "mode": "INOUT",
        "lang": "COBOL",
        "storage": "AUTO",
        "ctrl": ["FREEKB", "FRSET"],
        "tioapfx": True,
        "dsatts": ["COLOR", "HILIGHT"],
        "mapatts": ["COLOR", "HILIGHT"],
        "maps": ["CUSTM1"],
    }
    screen = result["screens"][0]
    assert (screen["name"], screen["size"], screen["tioapfx"]) == ("CUSTM1", [24, 80], True)
    fields = [
        (
            f["name"],
            f["row"],
            f["col"],
            f["data_row"],
            f["data_col"],
            f["length"],
            f["initial"],
            f["classification"],
        )
        for f in screen["fields"]
    ]
    assert fields == [
        (None, 1, 30, 1, 31, 16, "CUSTOMER INQUIRY", ["constant"]),
        (None, 3, 2, 3, 3, 12, "CUSTOMER ID:", ["constant"]),
        ("CUSTID", 3, 15, 3, 16, 8, None, ["input", "numeric", "initial-cursor"]),
        (None, 3, 24, 3, 25, 1, None, ["constant"]),
        ("NAME", 6, 3, 6, 4, 30, None, ["output"]),
        ("PASSWD", 7, 2, 7, 3, 8, None, ["input", "hidden"]),
        ("LINE(1)", 9, 2, 9, 3, 10, None, ["output"]),
        ("LINE(2)", 9, 13, 9, 14, 10, None, ["output"]),
        ("LINE(3)", 9, 24, 9, 25, 10, None, ["output"]),
        ("MO", 11, 1, 11, 2, 2, None, ["input", "numeric"]),
        ("SEP", 11, 3, 11, 4, 1, "-", ["input", "numeric"]),
        ("DAY", 11, 4, 11, 5, 2, None, ["input", "numeric"]),
        ("AMOUNT", 13, 2, 13, 3, 8, None, ["output"]),
        ("NOLEN", 15, 2, 15, 3, 0, None, ["input"]),
        ("OVER", 3, 20, 3, 21, 3, None, ["output"]),
        ("TITLE2", 20, 2, 20, 3, 60, "CONTINUED STRING SPANNING TWO LINES", ["constant"]),
        ("MSG", 24, 2, 24, 3, 79, "IT'S A, LONG MESSAGE", ["constant"]),
    ]
    custid = screen["fields"][2]
    assert (custid["attributes"], custid["color"]) == (["NUM", "IC"], "GREEN")
    assert screen["fields"][10]["group"] == "DATE"
    assert screen["fields"][10]["attribute_byte"] is False
    assert screen["fields"][12]["picout"] == "Z,ZZ9.99"
    assert result["warnings"] == [
        "CUSTM1: NOLEN: input field has no LENGTH",
        "CUSTM1: MSG: runs past column 80 and wraps to the next row",
        "CUSTM1: MSG: extends beyond the 24x80 screen",
        "CUSTM1: CUSTID overlaps OVER",
    ]


def test_bms_mockup_and_contract(bms: Path) -> None:
    screen = screen_map.parse_screens(bms)["screens"][0]
    mockup = screen["mockup"]
    assert len(mockup) == 25
    assert (
        mockup[0] == "   "
        "----+----1----+----2----+----3----+----4----+----5----+----6----+----7----+----8"
    )
    assert mockup[1] == "01 " + " " * 30 + "CUSTOMER INQUIRY"
    assert mockup[3] == "03   CUSTOMER ID: 9999 XXX"
    assert mockup[6] == "06    " + "X" * 30
    assert mockup[7] == "07   ________"
    assert mockup[9] == "09   " + " ".join(["X" * 10] * 3)
    assert mockup[11] == "11  99999"
    assert mockup[13] == "13   XXXXXXXX"
    assert mockup[20] == "20   CONTINUED STRING SPANNING TWO LINES"
    assert mockup[24] == "24   IT'S A, LONG MESSAGE"
    contract = {
        c["field"]: (c["row"], c["col"], c["length"], c["role"]) for c in screen["contract"]
    }
    assert contract["CUSTID"] == (3, 16, 8, "input")
    assert contract["LINE(3)"] == (9, 25, 10, "output")
    assert contract["MSG"] == (24, 3, 79, "constant")
    assert None not in contract
    markdown = screen_map.to_markdown(screen_map.parse_screens(bms))
    assert "## Map CUSTM1 (mapset CUSTMAP, 24x80)" in markdown
    assert "| CUSTID | 3 | 16 | 8 | input |" in markdown
    assert "Mapset **CUSTMAP** (line 2): TYPE=&SYSPARM, MODE=INOUT" in markdown


def mfs_lines() -> list[str]:
    return [
        "* CUSTOMER INQUIRY FORMAT",
        *macro("CUSTFMT", "FMT", ""),
        *macro("", "DEV", "TYPE=(3270,2),FEAT=IGNORE,DSCA=X'00C0'"),
        *macro("", "DIV", "TYPE=INOUT"),
        *macro("PAGE1", "DPAGE", "CURSOR=((5,20))"),
        *macro("TITLE", "DFLD", "'CUSTOMER INQUIRY',POS=(1,30)"),
        *macro("", "DFLD", "'CUSTOMER ID:',POS=(5,5)"),
        *macro("CUSTID", "DFLD", "POS=(5,20),LTH=8,ATTR=(NOPROT,NUM)"),
        *macro("CUSTNM", "DFLD", "POS=(7,20),LTH=30,ATTR=(PROT)"),
        *macro("SECRET", "DFLD", "POS=(9,20),LTH=4,ATTR=(PROT,NODISP)"),
        *macro("NOPOS", "DFLD", "LTH=2"),
        *macro("", "FMTEND", ""),
        *macro("CUSTIN", "MSG", "TYPE=INPUT,SOR=(CUSTFMT,IGNORE),NXT=CUSTOUT"),
        *macro("", "SEG", ""),
        *macro("", "MFLD", "'CINQ    ',LTH=8"),
        *macro("", "MFLD", "CUSTID,LTH=8"),
        *macro("", "MSGEND", ""),
        *macro("CUSTOUT", "MSG", "TYPE=OUTPUT,SOR=(CUSTFMT,IGNORE),NXT=CUSTIN"),
        *macro("OUTPAGE", "LPAGE", "SOR=(PAGE1)"),
        *macro("", "SEG", ""),
        *macro("", "MFLD", "(CUSTNM,'UNKNOWN'),LTH=30,ATTR=YES"),
        *macro("", "MFLD", "MISSING,LTH=5"),
        *macro("", "MSGEND", ""),
        "         END",
    ]


def test_mfs_formats_messages_and_links(tmp_path: Path) -> None:
    path = tmp_path / "CUSTFMT.mfs"
    path.write_text("\n".join(mfs_lines()) + "\n", encoding="utf-8")
    result = screen_map.parse_screens(path)
    assert result["kind"] == "mfs"
    assert result["formats"] == [{"name": "CUSTFMT", "line": 2, "devices": ["3270,2"]}]
    screen = result["screens"][0]
    assert (screen["kind"], screen["size"], screen["division"], screen["features"]) == (
        "mfs-device",
        [24, 80],
        "INOUT",
        ["IGNORE"],
    )
    fields = [
        (
            f["name"],
            f["row"],
            f["col"],
            f["data_row"],
            f["data_col"],
            f["length"],
            f["classification"],
        )
        for f in screen["fields"]
    ]
    assert fields == [
        ("TITLE", 1, 29, 1, 30, 16, ["constant"]),
        (None, 5, 4, 5, 5, 12, ["constant"]),
        ("CUSTID", 5, 19, 5, 20, 8, ["input", "numeric", "initial-cursor"]),
        ("CUSTNM", 7, 19, 7, 20, 30, ["output"]),
        ("SECRET", 9, 19, 9, 20, 4, ["output", "hidden"]),
        ("NOPOS", 9, 24, 9, 25, 2, ["input"]),
    ]
    assert screen["fields"][0]["page"] == "PAGE1"
    assert screen["mockup"][5] == "05     CUSTOMER ID:   99999999"
    assert screen["mockup"][9] == "09 " + " " * 24 + "__"
    messages = {m["name"]: m for m in result["messages"]}
    assert (messages["CUSTIN"]["type"], messages["CUSTIN"]["format"]) == ("INPUT", "CUSTFMT")
    assert [
        (f["dfld"], f["literal"], f.get("device_field")) for f in messages["CUSTIN"]["fields"]
    ] == [
        (None, "CINQ    ", None),
        ("CUSTID", None, {"row": 5, "col": 20, "length": 8}),
    ]
    output = messages["CUSTOUT"]
    assert output["pages"] == [{"name": "OUTPAGE", "dpage": ["PAGE1"]}]
    assert (output["fields"][0]["dfld"], output["fields"][0]["literal"]) == ("CUSTNM", "UNKNOWN")
    assert output["fields"][0]["device_field"] == {"row": 7, "col": 20, "length": 30}
    assert result["warnings"] == [
        "CUSTFMT: NOPOS: no POS; placed after the previous field",
        "MSG CUSTOUT: MFLD MISSING has no DFLD in format CUSTFMT",
    ]
    markdown = screen_map.to_markdown(result)
    assert "## MFS format CUSTFMT (DEV TYPE=(3270,2), 24x80)" in markdown
    assert "| CUSTIN | INPUT | CUSTFMT | 'CINQ    ' | 8 |  |  |" in markdown
    assert "| CUSTOUT | OUTPUT | CUSTFMT | CUSTNM | 30 | 7 | 20 |" in markdown


def test_stray_statements_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "STRAY.bms"
    path.write_text(
        "\n".join(
            [
                *macro("", "DFHMDF", "POS=(1,1),LENGTH=1"),
                *macro("STRAY", "DFHMDI", "SIZE=(12,40)"),
                *macro("F1", "DFHMDF", "LENGTH=3,ATTRB=UNPROT"),
                *macro("F2", "DFHMDF", "POS=(&ROW,5),LENGTH=2,ATTRB=ASKIP"),
                *macro("", "DEV", "TYPE=(3270,2)"),
                *macro("", "DIV", "TYPE=INOUT"),
                *macro("", "DFLD", "POS=(1,2),LTH=1"),
                *macro("", "MFLD", "F1,LTH=1"),
                *macro("", "LPAGE", "SOR=(P1)"),
                *macro("", "SEG", ""),
                *macro("", "PRINT", "NOGEN"),
                *macro("PRTFMT", "FMT", ""),
                *macro("", "DEV", "TYPE=SCS1"),
                *macro("", "DPAGE", ""),
                *macro("ITEM", "DFLD", "POS=(2,2)"),
                *macro("", "FMTEND", ""),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = screen_map.parse_screens(path)
    assert result["kind"] == "bms+mfs"
    stray, printer = result["screens"]
    assert [(f["name"], f["data_row"], f["data_col"]) for f in stray["fields"]] == [
        ("F1", 1, 2),
        ("F2", 1, 6),
    ]
    assert stray["mockup"][0] == "   ----+----1----+----2----+----3----+----4"
    assert (printer["device"], printer["size"]) == ("SCS1", [24, 80])
    assert "page" not in printer["fields"][0]
    assert result["warnings"] == [
        "line 1: DFHMDF outside a DFHMDI map; ignored",
        "line 2: DFHMDI STRAY has no DFHMSD",
        "line 5: DEV outside an FMT; ignored",
        "line 7: DFLD outside a DEV; ignored",
        "line 8: MFLD outside a MSG; ignored",
        "STRAY: F1: no POS; placed after the previous field",
        "STRAY: F2: no POS; placed after the previous field",
        "PRTFMT: ITEM: input field has no LTH",
    ]


SYMBOLIC = (
    "01  SYMMAPI.",
    "    02  FILLER PIC X(12).",
    "    02  CUSTIDL    COMP  PIC  S9(4).",
    "    02  CUSTIDF    PICTURE X.",
    "    02  FILLER REDEFINES CUSTIDF.",
    "      03 CUSTIDA    PICTURE X.",
    "    02  FILLER   PICTURE X(1).",
    "    02  CUSTIDI  PIC X(8).",
    "    02  CUSTNML    PIC X(2).",
    "    02  CUSTNMF    PICTURE X.",
    "    02  CUSTNMA    PICTURE X.",
    "    02  CUSTNMI  PIC X(25).",
    "    02  MOI  PIC X(2).",
    "    02  MOO  PIC X(2).",
    "    02  DAYI PIC X(2).",
    "*   OUTPUT STRUCTURE",
    "01  SYMMAPO REDEFINES SYMMAPI.",
    "    02  FILLER PIC X(12).",
    "    02  FILLER  PICTURE X(3).",
    "    02  CUSTIDC    PICTURE X.",
    "    02  CUSTIDO  PIC X(8).",
    "    02  FILLER  PICTURE X(3).",
    "    02  CUSTNMO  PIC X(30).",
    "01  SYM2O.",
    "    02  F1L    COMP  PIC  S9(4).",
    "    02  F1F    PICTURE X.",
    "    02  FILLER REDEFINES F1F.",
    "      03 F1A    PICTURE X.",
    "    02  F1I  PIC X(5).",
    "    02  F1O  PIC X(5).",
)


def test_symbolic_map_check(tmp_path: Path) -> None:
    source = tmp_path / "SYMSET.bms"
    source.write_text(
        "\n".join(
            [
                *macro(
                    "SYMSET",
                    "DFHMSD",
                    "TYPE=MAP,LANG=COBOL,TIOAPFX=YES,",
                    "DSATTS=(COLOR),MAPATTS=(COLOR,HILIGHT)",
                ),
                *macro("SYMMAP", "DFHMDI", "SIZE=(24,80)"),
                *macro("CUSTID", "DFHMDF", "POS=(3,15),LENGTH=8,ATTRB=(UNPROT,NUM)"),
                *macro("CUSTNM", "DFHMDF", "POS=(5,15),LENGTH=30,ATTRB=ASKIP"),
                *macro("MO", "DFHMDF", "POS=(7,1),LENGTH=2,ATTRB=NUM,GRPNAME=DATE"),
                *macro("DAY", "DFHMDF", "POS=(7,3),LENGTH=2,GRPNAME=DATE"),
                *macro("SYM2", "DFHMDI", "SIZE=(12,40),TIOAPFX=NO,DSATTS=(),MAPATTS=()"),
                *macro("F1", "DFHMDF", "POS=(1,2),LENGTH=5,ATTRB=UNPROT"),
                *macro("", "DFHMSD", "TYPE=FINAL"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    copybook = tmp_path / "SYMSET.cpy"
    copybook.write_text(fixed(*SYMBOLIC), encoding="utf-8")
    result = screen_map.parse_screens(source)
    assert screen_map.check_symbolic_map(result, copybook) == [
        "note: SYMMAP: TIOAPFX=YES adds a 12-byte FILLER prefix to SYMMAPI",
        (
            "note: SYMMAP: MAPATTS lists HILIGHT but DSATTS does not, so the symbolic map has no "
            "subfields for them"
        ),
        "SYMMAP: CUSTNML should be PIC S9(4) COMP, a 2-byte binary length",
        "SYMMAP: CUSTNMA does not redefine CUSTNMF",
        "SYMMAP: missing CUSTNMC (COLOR attribute)",
        "SYMMAP: CUSTNMI is 25 bytes but the map field is 30",
        "SYMMAP: MOO is not in SYMMAPO",
        "SYMMAP: missing DAYO (output field)",
        "SYM2: missing 01 SYM2I (input structure)",
        "SYM2: 01 SYM2O does not REDEFINES SYM2I",
    ]
    assert "## Warnings" not in screen_map.to_markdown(result)
    mfs = tmp_path / "CUSTFMT.mfs"
    mfs.write_text("\n".join(mfs_lines()) + "\n", encoding="utf-8")
    assert screen_map.check_symbolic_map(screen_map.parse_screens(mfs), copybook) == [
        "note: no BMS maps to check; MFS formats have no symbolic map"
    ]
    no_prefix = tmp_path / "NOPFX.cpy"
    no_prefix.write_text(
        "01 SYMMAPI.\n*> FREE FORMAT\n   02 CUSTIDL COMP PIC S9(4).\n", encoding="utf-8"
    )
    findings = screen_map.check_symbolic_map(result, no_prefix)
    assert "SYMMAP: TIOAPFX=YES, but SYMMAPI does not start with a 12-byte FILLER" in findings
    assert "SYMMAP: missing 01 SYMMAPO (output structure)" in findings


def test_screen_map_cli(bms: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copybook = tmp_path / "CUSTMAP.cpy"
    copybook.write_text(fixed("01  CUSTM1I.", "    02  FILLER PIC X(12)."), encoding="utf-8")
    assert screen_map.main([str(bms), "--symbolic", str(copybook)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("# Screens: CUSTMAP.bms")
    assert f"## Symbolic map check: {copybook}" in output
    assert "- CUSTM1: missing CUSTIDL (2-byte binary length)" in output
    assert "## Warnings" in output
    assert screen_map.main([str(bms), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["screens"][0]["name"] == "CUSTM1"
    (tmp_path / "binary.bms").write_bytes(b"\x00\x01\x02")
    (tmp_path / "notes.txt").write_text("nothing to see\n", encoding="utf-8")
    for args, message in (
        ([str(tmp_path / "absent.bms")], "not found"),
        ([str(tmp_path / "binary.bms")], "binary content"),
        ([str(tmp_path / "notes.txt")], "no BMS"),
        ([str(bms), "--symbolic", str(tmp_path / "absent.cpy")], "absent.cpy"),
        ([str(bms), "--symbolic", str(tmp_path / "binary.bms")], "binary content"),
        ([str(bms), "--codepage", "9999"], "unsupported code page"),
    ):
        assert screen_map.main(args) == 1
        assert message in capsys.readouterr().err
