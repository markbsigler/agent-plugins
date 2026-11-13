"""Tests for code-modernization-plugin: mainframe-analysis scripts and stack-profile contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

import copybook_layout
import mainframe_inventory
import pytest
from discovery import REPO_ROOT

PLUGIN_SKILLS = REPO_ROOT / "code-modernization-plugin" / "skills"
STAGE_SECTION = r"(?:Refactor|Rearchitect) Stage \d"
ALL_STAGES = {f"{track} Stage {n}" for track in ("Refactor", "Rearchitect") for n in range(1, 5)}


def test_every_stack_profile_provides_the_stage_sections_the_playbooks_call() -> None:
    """Each playbook stage names a section that every registered stack profile must provide."""
    called = set()
    for playbook in ("playbook-refactor", "playbook-rearchitect"):
        text = (PLUGIN_SKILLS / playbook / "SKILL.md").read_text(encoding="utf-8")
        called.update(re.findall(rf"`({STAGE_SECTION})`", text))
    assert called == ALL_STAGES

    triage = (PLUGIN_SKILLS / "modernization-triage" / "SKILL.md").read_text(encoding="utf-8")
    registry = triage.split("## Stack profiles", 1)[1].split("\n## ", 1)[0]
    profiles = re.findall(r"^\| `([a-z0-9-]+)` \|", registry, re.MULTILINE)
    assert profiles, "the triage skill lists no stack profiles"
    for profile in profiles:
        stages = PLUGIN_SKILLS / profile / "references" / "playbook-stages.md"
        assert stages.is_file(), f"{profile} has no references/playbook-stages.md"
        headings = rf"^### ({STAGE_SECTION})\b"
        provided = set(re.findall(headings, stages.read_text(encoding="utf-8"), re.MULTILINE))
        assert provided == called, f"{profile} is missing {sorted(called - provided)}"


def fixed(*lines: str) -> str:
    """Return fixed-format source: sequence numbers, indicator column, and code from col 8."""
    out = []
    for number, line in enumerate(lines, start=1):
        indicator, code = (line[0], line[1:]) if line[:1] in {"*", "-"} else (" ", line)
        out.append(f"{number * 100:06d}{indicator}{code[:65]:<65}IDENT{number:03d}")
    return "\n".join(out) + "\n"


def fields_by_name(layout: copybook_layout.Layout) -> dict[str, dict]:
    record = copybook_layout.layout_to_dict(layout)["records"][0]
    return {entry["name"]: entry for entry in record["fields"]}


@pytest.fixture
def account_copybook(tmp_path: Path) -> Path:
    path = tmp_path / "ACCOUNT.cpy"
    path.write_text(
        fixed(
            "*  ACCOUNT MASTER RECORD",
            "01  ACCOUNT-RECORD.",
            "    05  ACCT-ID           PIC X(10).",
            "    05  ACCT-STATUS       PIC X.",
            "        88  ACCT-OPEN     VALUE 'O'.",
            "        88  ACCT-CLOSED   VALUES 'C' 'X'.",
            "    05  ACCT-BALANCE      PIC S9(7)V99 COMP-3.",
            "    05  ACCT-COUNT        PIC S9(4) COMP.",
            "    05  ACCT-LIMIT        PIC S9(9) BINARY.",
            "    05  ACCT-SEQ          PIC 9(18) COMP-5.",
            "    05  ACCT-RATE         COMP-2.",
            "    05  ACCT-DELTA        PIC S9(5) SIGN LEADING SEPARATE.",
            "    05  ACCT-NAME-N       PIC N(5).",
            "    05  ACCT-EDIT         PIC ZZ,ZZ9.99-.",
            "    05  ACCT-THOUSANDS    PIC 99PPP.",
            "    05  ACCT-OPENED       PIC 9(8).",
            "    05  ACCT-OPENED-X REDEFINES ACCT-OPENED.",
            "        10  OPEN-YEAR     PIC 9(4).",
            "        10  FILLER        PIC X(4).",
            "    05  ACCT-HISTORY OCCURS 3 TIMES.",
            "        10  HIST-DATE     PIC X(8).",
            "        10  HIST-AMOUNT   PIC S9(5)V99 COMP-3.",
        ),
        encoding="utf-8",
    )
    return path


def test_layout_applies_ibm_storage_rules(account_copybook: Path) -> None:
    layout = copybook_layout.parse_copybook(account_copybook)
    fields = fields_by_name(layout)
    expected = {
        "ACCT-ID": (1, 10, "CH"),
        "ACCT-STATUS": (11, 1, "CH"),
        "ACCT-BALANCE": (12, 5, "PD"),
        "ACCT-COUNT": (17, 2, "FI"),
        "ACCT-LIMIT": (19, 4, "FI"),
        "ACCT-SEQ": (23, 8, "BI"),
        "ACCT-RATE": (31, 8, "FL"),
        "ACCT-DELTA": (39, 6, "CSL"),
        "ACCT-NAME-N": (45, 10, None),
        "ACCT-EDIT": (55, 10, "CH"),
        "ACCT-THOUSANDS": (65, 2, "ZD"),
        "ACCT-OPENED": (67, 8, "ZD"),
        "ACCT-OPENED-X": (67, 8, None),
        "OPEN-YEAR": (67, 4, "ZD"),
        "ACCT-HISTORY": (75, 12, None),
        "HIST-AMOUNT": (83, 4, "PD"),
    }
    actual = {
        name: (fields[name]["position"], fields[name]["length"], fields[name].get("dfsort"))
        for name in expected
    }
    assert actual == expected
    assert fields["ACCT-THOUSANDS"]["scale"] == -3
    assert fields["ACCT-BALANCE"]["scale"] == 2
    assert fields["ACCT-HISTORY"]["total_length"] == 36
    assert fields["HIST-AMOUNT"]["occurs_in"] == [{"name": "ACCT-HISTORY", "max": 3, "stride": 12}]
    assert fields["ACCT-STATUS"]["conditions"] == [
        {"name": "ACCT-OPEN", "values": ["'O'"]},
        {"name": "ACCT-CLOSED", "values": ["'C'", "'X'"]},
    ]
    assert copybook_layout.layout_to_dict(layout)["records"][0]["length"] == 110
    assert layout.warnings == []


def test_fixed_format_ignores_sequence_and_identification_areas(tmp_path: Path) -> None:
    literal_start = "    05  NOTE PIC X(41) VALUE 'CONTINUED "
    path = tmp_path / "NOTE.cpy"
    path.write_text(
        fixed(
            "01  NOTE-RECORD.",
            literal_start + "L" * (65 - len(literal_start)),
            "-       'ITERAL'.",
            "*    05  COMMENTED-OUT PIC X(99).",
            "    05  TRAILER PIC X(2).",
        ),
        encoding="utf-8",
    )
    fields = fields_by_name(copybook_layout.parse_copybook(path))
    assert list(fields) == ["NOTE", "TRAILER"]
    expected_value = "'CONTINUED " + "L" * (65 - len(literal_start)) + "ITERAL'"
    assert fields["NOTE"]["value"] == expected_value
    assert fields["TRAILER"]["position"] == 42


def test_occurs_depending_on_marks_variable_layout(tmp_path: Path) -> None:
    path = tmp_path / "ORDERS.cpy"
    path.write_text(
        "01 ORDER-MSG.\n"
        "   05 LINE-COUNT PIC S9(4) COMP.\n"
        "   05 ORDER-LINE OCCURS 1 TO 50 TIMES DEPENDING ON LINE-COUNT INDEXED BY LX.\n"
        "      10 ITEM-ID PIC X(6).\n"
        "   05 MSG-END PIC X.\n",
        encoding="utf-8",
    )
    record = copybook_layout.layout_to_dict(copybook_layout.parse_copybook(path))["records"][0]
    fields = {entry["name"]: entry for entry in record["fields"]}
    assert record["variable_length"] is True
    assert record["length"] == 2 + 50 * 6 + 1
    assert fields["ORDER-LINE"]["occurs"] == {"min": 1, "max": 50, "depending_on": "LINE-COUNT"}
    assert fields["MSG-END"]["variable_offset"] is True
    assert "variable_offset" not in fields["ITEM-ID"]


def test_nested_copy_replacing_and_synthetic_record(tmp_path: Path) -> None:
    library = tmp_path / "copylib"
    library.mkdir()
    (library / "ADDR.cpy").write_text(
        "05 :TAG:-ADDRESS.\n   10 :TAG:-CITY PIC X(20).\n   10 :TAG:-ZIP PIC 9(5).\n",
        encoding="utf-8",
    )
    top = tmp_path / "CUSTPART.cpy"
    top.write_text(
        "05 :PFX:-TYPE PIC X(2).\nCOPY ADDR REPLACING ==:TAG:== BY ==HOME==.\nCOPY MISSING.\n",
        encoding="utf-8",
    )
    layout = copybook_layout.parse_copybook(top, copylibs=[library], replacements=[(":PFX:", "WS")])
    record = copybook_layout.layout_to_dict(layout)["records"][0]
    assert record["name"] == "CUSTPART"
    assert record["synthetic"] is True
    assert [(f["name"], f["position"]) for f in record["fields"]] == [
        ("WS-TYPE", 1),
        ("HOME-ADDRESS", 3),
        ("HOME-CITY", 3),
        ("HOME-ZIP", 23),
    ]
    assert any("COPY MISSING" in warning for warning in layout.warnings)
    assert any("synthetic record" in warning for warning in layout.warnings)


def test_json_schema_keeps_decimals_exact(account_copybook: Path) -> None:
    layout = copybook_layout.parse_copybook(account_copybook)
    schema = copybook_layout.layout_to_json_schema(layout)
    properties = schema["properties"]
    assert schema["title"] == "ACCOUNT-RECORD"
    assert properties["acctBalance"]["type"] == "string"
    assert properties["acctBalance"]["pattern"] == r"^-?[0-9]{1,7}(\.[0-9]{1,2})?$"
    assert properties["acctCount"] == {
        "type": "integer",
        "minimum": -9999,
        "maximum": 9999,
        "description": properties["acctCount"]["description"],
        "x-cobol": properties["acctCount"]["x-cobol"],
    }
    assert properties["acctThousands"]["multipleOf"] == 1000
    assert properties["acctSeq"]["type"] == "string"
    assert properties["acctHistory"]["maxItems"] == 3
    assert properties["acctOpenedX"]["x-cobol"]["redefines"] == "ACCT-OPENED"
    assert "filler" not in json.dumps(properties["acctOpenedX"]).lower()
    cobol_names = copybook_layout.layout_to_json_schema(layout, names="cobol")["properties"]
    assert "ACCT-BALANCE" in cobol_names


def test_layout_cli_formats_and_errors(
    account_copybook: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert copybook_layout.main([str(account_copybook), "--format", "markdown"]) == 0
    assert "| 12 | 5 | 05 | ACCT-BALANCE | S9(7)V99 | PACKED-DECIMAL |" in capsys.readouterr().out
    assert copybook_layout.main([str(account_copybook), "--format", "json-schema"]) == 0
    assert json.loads(capsys.readouterr().out)["$schema"].endswith("2020-12/schema")
    assert copybook_layout.main([str(account_copybook), "--record", "NOPE"]) == 1
    assert copybook_layout.main([str(tmp_path / "absent.cpy")]) == 1
    assert "error:" in capsys.readouterr().err


def write_estate(root: Path) -> None:
    """Write a small exported mainframe estate: CICS, batch, JCL, CSD, BMS, EBCDIC."""
    (root / "cobol").mkdir(parents=True)
    (root / "copy").mkdir()
    (root / "jcl").mkdir()
    (root / "cobol" / "CUSTINQ.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. CUSTINQ.",
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "COPY CUSTREC.",
            "COPY DFHAID.",
            "PROCEDURE DIVISION.",
            "    EXEC CICS HANDLE CONDITION NOTFND(9000-NF) END-EXEC.",
            "    EXEC CICS RECEIVE MAP('CUSTM1') MAPSET('CUSTMAP')",
            "         END-EXEC.",
            "    EXEC SQL SELECT C.NAME INTO :WS-NAME",
            "         FROM CUST.CUSTOMER C, CUST.ACCOUNT A",
            "         WHERE C.ID = A.ID END-EXEC.",
            "    EXEC CICS LINK PROGRAM('CUSTBAL') END-EXEC.",
            "    EXEC CICS XCTL PROGRAM(WS-NEXT) END-EXEC.",
            "    GO TO 8000-EXIT.",
        ),
        encoding="utf-8",
    )
    (root / "cobol" / "CUSTBAT.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. CUSTBAT.",
            "FILE-CONTROL.",
            "    SELECT CUST-IN ASSIGN TO UT-S-CUSTIN",
            "        ORGANIZATION IS INDEXED RECORD KEY IS CUST-ID.",
            "WORKING-STORAGE SECTION.",
            "01  GU-FUNC PIC X(4) VALUE 'GU  '.",
            "*   CALL 'OLDPGM' IS COMMENTED OUT",
            "PROCEDURE DIVISION.",
            "    ALTER 1000-SW TO PROCEED TO 2000-NEXT.",
            "    PERFORM 1000-INIT THRU 1000-EXIT.",
            "    CALL 'DATEUTIL' USING WS-DATE.",
            "    CALL WS-PGM USING WS-AMT.",
            "    CALL 'CBLTDLI' USING GU-FUNC DB-PCB SEG-IO.",
        ),
        encoding="utf-8",
    )
    (root / "copy" / "CUSTREC.cpy").write_text(
        fixed("01  CUSTOMER-RECORD.", "    05  CUST-ID  PIC X(10)."), encoding="utf-8"
    )
    ebcdic = "".join(f"{line:<80}" for line in ["       01  ACCT-REC.", "       05 X PIC X."])
    (root / "copy" / "ACCTREC").write_bytes(ebcdic.encode("cp037"))
    (root / "copy" / "LOADMOD").write_bytes(b"\x00\x01binary")
    (root / "jcl" / "NIGHTLY.jcl").write_text(
        "//NIGHTLY  JOB (ACCT),'NIGHTLY',CLASS=A\n"
        "//* CUSTOMER CYCLE\n"
        "//STEP010  EXEC PGM=CUSTBAT\n"
        "//CUSTIN   DD DSN=PROD.CUST.MASTER,DISP=SHR\n"
        "//CUSTOUT  DD DSN=PROD.CUST.EXTRACT(+1),\n"
        "//            DISP=(NEW,CATLG,DELETE)\n"
        "//STEP020  EXEC PGM=IKJEFT01\n"
        "//SYSTSIN  DD *\n"
        "  DSN SYSTEM(DB2P)\n"
        "  RUN PROGRAM(CUSTRPT) PLAN(CUSTPLN)\n"
        "/*\n"
        "//STEP030  EXEC PGM=DFSRRC00,PARM='DLI,CUSTIMS,CUSTPSB'\n"
        "//STEP040  EXEC PGM=SORT\n"
        "//SYSIN    DD DATA,DLM=@@\n"
        "  SORT FIELDS=(1,10,CH,A)\n"
        "//NOTJCL  THIS LINE IS DATA BECAUSE OF DLM\n"
        "  INCLUDE COND=(11,1,CH,EQ,C'A')\n"
        "@@\n"
        "//STEP050  EXEC DLIBATCH,MBR=CUSTUPD,PSB=CUSTPSB\n",
        encoding="utf-8",
    )
    (root / "CUSTCSD.csd").write_text(
        "DEFINE TRANSACTION(CINQ) GROUP(CUST)\n  PROGRAM(CUSTINQ)\n"
        "DEFINE FILE(CUSTFILE) GROUP(CUST) DSNAME(PROD.CUST.KSDS)\n",
        encoding="utf-8",
    )
    (root / "CUSTMAP.bms").write_text(
        "CUSTMAP  DFHMSD TYPE=MAP,LANG=COBOL\nCUSTM1   DFHMDI SIZE=(24,80)\n", encoding="utf-8"
    )


def test_inventory_maps_dependencies_and_risks(tmp_path: Path) -> None:
    write_estate(tmp_path)
    inventory = mainframe_inventory.build_inventory([tmp_path])
    members = {member["name"]: member for member in inventory["members"]}
    summary = inventory["summary"]

    assert "LOADMOD" not in members
    assert members["ACCTREC"]["encoding"] == "ebcdic-cp037"
    assert members["ACCTREC"]["kind"] == "cobol-copybook"
    assert inventory["cics_transactions"] == {"CINQ": "CUSTINQ"}

    online = members["CUSTINQ"]
    assert online["references"]["db2-table"] == ["CUST.ACCOUNT", "CUST.CUSTOMER"]
    assert online["references"]["cics-link"] == ["CUSTBAL"]
    assert online["references"]["bms-mapset"] == ["CUSTMAP"]
    assert "RECEIVE MAP" in online["details"]["cics_commands"]
    assert online["risks"] == {"cics_handle": 1, "dynamic_call": 1, "go_to": 1}

    batch = members["CUSTBAT"]
    assert batch["references"]["call"] == ["DATEUTIL"]
    assert batch["details"]["dli_functions"] == ["GU"]
    assert batch["details"]["files"][0] == {
        "select": "CUST-IN",
        "ddname": "CUSTIN",
        "organization": "INDEXED",
    }
    assert {"alter", "perform_thru", "dynamic_call"} <= set(batch["risks"])

    steps = members["NIGHTLY"]["details"]["steps"]
    assert steps[1]["db2_programs"] == ["CUSTRPT"]
    assert (steps[2]["ims_program"], steps[2]["psb"]) == ("CUSTIMS", "CUSTPSB")
    assert steps[3]["sort_statements"] == ["INCLUDE", "SORT"]
    assert steps[4]["proc_program"] == "CUSTUPD"
    assert len(steps) == 5
    assert members["NIGHTLY"]["risks"] == {
        "business_logic_in_sort": 1,
        "gdg_relative_reference": 1,
    }

    assert summary["unresolved"]["programs"] == [
        "CUSTBAL",
        "CUSTIMS",
        "CUSTRPT",
        "CUSTUPD",
        "DATEUTIL",
    ]
    assert summary["unresolved"]["copybooks"] == []
    assert "DFHAID" in summary["external_or_system"]
    assert "OLDPGM" not in json.dumps(inventory)


def test_inventory_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_estate(tmp_path)
    assert mainframe_inventory.main([str(tmp_path), "--format", "markdown"]) == 0
    report = capsys.readouterr().out
    assert "| CINQ | CUSTINQ |" in report
    assert "| NIGHTLY | STEP050 | PROC DLIBATCH |  | CUSTUPD |" in report
    assert mainframe_inventory.main([str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["members"] == 7
    assert mainframe_inventory.main([str(tmp_path / "missing")]) == 1
    assert "not found" in capsys.readouterr().err
