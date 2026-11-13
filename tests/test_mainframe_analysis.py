"""Tests for code-modernization-plugin: mainframe-analysis scripts and stack-profile contract."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import mainframe_inventory
import pytest
import seam_report
from discovery import REPO_ROOT
from mainframe_fixtures import ebcdic, ebcdic_member, fixed, rdw, write_rich_estate

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


def _access(inventory: dict) -> dict[tuple[str, str, str], str]:
    return {
        (e["from"], e["type"], e["to"]): e["access"] for e in inventory["edges"] if "access" in e
    }


def test_inventory_tags_create_read_update_delete_for_each_resource(tmp_path: Path) -> None:
    write_rich_estate(tmp_path)
    access = _access(mainframe_inventory.build_inventory([tmp_path]))
    assert access[("ACCTUPD", "cics-file", "ACCTFIL")] == "RU"
    assert access[("ACCTUPD", "cics-queue", "ACCTQ")] == "C"
    assert access[("ACCTUPD", "db2-table", "ACCT.BALANCE")] == "U"
    assert access[("ACCTUPD", "db2-table", "ACCT.HISTORY")] == "C"
    assert access[("ACCTUPD", "db2-table", "DB2B.ACCT.REMOTE")] == "R"
    assert access[("ACCTUPD", "mq-queue", "ACCT.EVENTS")] == "C"
    assert access[("ACCTBAT", "ddname", "ACCTDD")] == "RU"
    assert access[("ACCTBAT", "ddname", "RPTOUT")] == "C"
    assert access[("ACCTBAT", "ims-segment", "CUSTOMER")] == "R"
    assert access[("ACCTBAT", "ims-segment", "ACCOUNT")] == "C"
    assert access[("ACCTPLI", "ddname", "ACCTDD")] == "R"
    assert access[("ACCTPLI", "ddname", "OUTF")] == "C"
    assert access[("ACCTNAT", "adabas-file", "ACCOUNTS")] == "CR"
    assert access[("ACCTREXX", "ddname", "IN")] == "R"
    assert access[("ACCTJOB", "dataset", "PROD.ACCT.KSDS")] == "RU"
    assert access[("ACCTJOB", "dataset", "PROD.ACCT.EXTRACT")] == "C"
    assert access[("OLDJOB", "dataset", "PROD.OLD.FILE")] == "CD"


def test_inventory_reads_languages_and_resolves_dynamic_targets(tmp_path: Path) -> None:
    write_rich_estate(tmp_path)
    inventory = mainframe_inventory.build_inventory([tmp_path])
    members = {member["name"]: member for member in inventory["members"]}
    kinds = {name: member["kind"] for name, member in members.items()}
    assert kinds["ACCTINC"] == "pli-include"
    assert kinds["ACCTDS"] == "assembler-macro"
    assert kinds["ACCTSKEL"] == "ispf-skeleton"
    assert kinds["ACCTQ"] == "mqsc"
    assert kinds["ACCTSCHED"] == "schedule"
    assert kinds["ACCTBIND"] == "tso-db2-control"
    assert kinds["ACCTCMP"] == "compile-listing"
    assert kinds["ACCTLNK"] == "binder-listing"
    assert kinds["ACCTNAT"] == "natural"

    online = members["ACCTUPD"]
    assert online["references"]["cics-link"] == ["ACCTVAL"]
    assert online["details"]["dynamic_targets"] == {"WS-PGM": ["ACCTVAL"]}
    assert online["references"]["cics-return-transid"] == ["AUPD"]
    assert online["references"]["cics-start-transid"] == ["APRT"]
    assert online["details"]["syncpoints"] == 1
    assert online["details"]["db2_locations"] == ["DB2B"]
    assert online["details"]["shared_storage"] == ["cwa"]
    assert online["references"]["mq-queue"] == ["ACCT.EVENTS"]

    pli = members["ACCTPLI"]
    assert pli["references"]["call"] == ["DYNMOD", "PLIDATE"]
    assert pli["references"]["copy"] == ["ACCTINC"]
    assert pli["risks"] == {"dynamic_call": 1}
    assembler = members["ACCTASM"]
    assert assembler["references"]["load-link"] == ["ACCTSUB"]
    assert assembler["details"]["purpose"] == [
        "program-control",
        "messages",
        "serialization",
        "dynamic-allocation",
    ]
    rexx = members["ACCTREXX"]["references"]
    assert rexx["submits"] == ["ACCTJOB"]
    assert rexx["ispf-skeleton"] == ["ACCTSKEL"]
    assert rexx["exec"] == ["ACCTUTIL"]
    assert members["ACCTSKEL"]["references"]["jcl-exec"] == ["ACCTBAT"]
    assert members["ACCTNAT"]["references"]["call"] == ["ACCTSUBN"]
    assert members["ACCTBAT"]["details"]["compile_options"] == ["ARITH(EXTEND)"]
    assert members["ACCTAPI"]["references"]["ims-psb"] == ["ACCTPSB"]
    assert members["ACCTBAT"]["references"]["ims-psb"] == ["ACCTBPSB"]
    assert inventory["summary"]["unresolved"]["programs"] == [
        "ACCTSUB",
        "ACCTSUBN",
        "ACCTVAL",
        "DYNMOD",
        "PLIDATE",
    ]


def test_inventory_reads_definitions_and_cross_checks_them(tmp_path: Path) -> None:
    write_rich_estate(tmp_path)
    inventory = mainframe_inventory.build_inventory([tmp_path])
    cics = inventory["cics"]
    assert inventory["cics_transactions"] == {"AUPD": "ACCTUPD", "REMT": "REMPGM"}
    assert cics["files"]["ACCTFIL"] == {"dsname": "PROD.ACCT.KSDS", "operations": "CRU"}
    assert cics["web"]["urimaps"]["ACCTURI"]["path"] == "/acct/*"
    assert cics["transactions"]["REMT"]["remote_system"] == "CICB"
    assert cics["tdqueues"]["ATRG"] == {"type": "INTRA", "trigger_level": "1", "transid": "APRT"}
    assert cics["lists"] == {"PRODLIST": ["ACCT"]}
    assert inventory["vsam"]["clusters"]["PROD.ACCT.KSDS"] == {
        "type": "KSDS",
        "keys": {"length": 10, "offset": 0},
        "recordsize": {"average": 150, "maximum": 150},
        "shareoptions": [2, 3],
    }
    assert inventory["mq"]["queues"]["ACCT.EVENTS"]["trigger"] is True
    assert inventory["mq"]["processes"]["ACCT.PROC"]["applicid"] == "ACCTMQ"
    assert [bind["name"] for bind in inventory["db2"]["binds"]] == ["ACCTPLN", "ACCTCOLL.ACCTUPD"]
    assert inventory["db2"]["binds"][1]["options"] == {"VALIDATE": "BIND", "ISOLATION": "CS"}
    assert inventory["db2"]["remote_locations"] == ["DB2B"]
    assert inventory["listings"]["compile"]["ACCTUPD"]["options"] == [
        "NOADATA",
        "ARCH(12)",
        "NODYNAM",
        "RENT",
        "TRUNC(STD)",
    ]
    assert inventory["listings"]["binder"] == [
        {"member": "ACCTLNK", "modules": ["ACCTUPD"], "amode": ["31"], "rmode": ["ANY"]}
    ]
    assert inventory["schedules"] == {"jobs": ["ACCTJOB"]}
    assert inventory["transfers"] == [
        {
            "job": "ACCTJOB",
            "step": "STEP030",
            "tool": "ftp",
            "direction": "send",
            "local": "PROD.ACCT.EXTRACT",
            "remote": "acct.csv",
            "host": "FTP.EXAMPLE.COM",
        }
    ]
    assert inventory["cross_checks"] == [
        {
            "check": "record-length",
            "program": "ACCTBAT",
            "where": "ACCTJOB.STEP010 ACCTDD",
            "detail": (
                "ACCT-FILE records are 200 bytes but PROD.ACCT.KSDS RECORDSIZE maximum is 150"
            ),
        }
    ]
    assert inventory["shared_updates"] == [
        {"dataset": "PROD.ACCT.KSDS", "cics_file": "ACCTFIL", "batch": ["ACCTJOB.STEP010"]}
    ]
    threadsafe = {entry["program"]: entry["assessment"] for entry in inventory["cics_threadsafe"]}
    assert threadsafe == {
        "ACCTAPI": "defined threadsafe; confirm serialization",
        "ACCTUPD": "serialize shared storage before defining it threadsafe",
    }
    assert inventory["summary"]["warnings"] == []
    dead = inventory["dead_code"]
    assert dead["unreferenced_programs"] == ["ACCTASM", "ACCTNAT"]
    assert dead["unscheduled_jobs"] == ["OLDJOB"]
    members = {member["name"]: member for member in inventory["members"]}
    assert members["ACCTJOB"]["details"]["reports"] == [
        {"step": "STEP010", "dd": "RPTOUT", "class": "A", "dest": "RMT1"}
    ]


def test_inventory_cross_checks_against_a_listcat_report(tmp_path: Path) -> None:
    write_rich_estate(tmp_path)
    jcl = tmp_path / "jcl" / "ACCTJOB.jcl"
    text = jcl.read_text(encoding="utf-8")
    jcl.write_text(text.replace("RECORDSIZE(150 150)", "RECORDSIZE(200 200)"), encoding="utf-8")
    (tmp_path / "LISTCAT.txt").write_text(
        "1IDCAMS  SYSTEM SERVICES\n"
        " CLUSTER ------- PROD.ACCT.KSDS\n"
        " DATA ---------- PROD.ACCT.KSDS.DATA\n"
        "      ASSOCIATIONS\n"
        "        CLUSTER--PROD.ACCT.KSDS\n"
        "      ATTRIBUTES\n"
        "        KEYLEN----------------10     AVGLRECL-------------200\n"
        "        MAXLRECL-------------200\n"
        "        SHROPTNS(2,3)   RECOVERY     UNIQUE           NOERASE     NONINDEXED\n",
        encoding="utf-8",
    )
    inventory = mainframe_inventory.build_inventory([tmp_path])
    kinds = {member["name"]: member["kind"] for member in inventory["members"]}
    assert kinds["LISTCAT"] == "idcams-listcat"
    assert inventory["vsam"]["clusters"]["PROD.ACCT.KSDS"]["type"] == "ESDS"
    assert inventory["cross_checks"] == [
        {
            "check": "organization",
            "program": "ACCTBAT",
            "where": "ACCTJOB.STEP010 ACCTDD",
            "detail": "ACCT-FILE is INDEXED but PROD.ACCT.KSDS is defined as ESDS",
        },
        {
            "check": "catalog-drift",
            "program": "",
            "where": "PROD.ACCT.KSDS",
            "detail": (
                "type KSDS in DEFINE statements, ESDS in the catalog; key 10 bytes at offset 0"
                " in DEFINE statements, none in the catalog"
            ),
        },
    ]


def test_inventory_reads_sql_scripts_duplicates_and_updates_through_open_modes(
    tmp_path: Path,
) -> None:
    for app in ("app1", "app2"):
        (tmp_path / app).mkdir()
        (tmp_path / app / "REPRO.ctl").write_text("  REPRO INFILE(IN) OUTFILE(OUT)\n")
    (tmp_path / "LOADCAT.ctl").write_text(
        "/* LOAD CATEGORIES */\n"
        "INSERT INTO CARD.CATEGORY (CODE)\n"
        " WITH DMY AS (SELECT * FROM SYSIBM.SYSDUMMY1)\n"
        " SELECT '01' FROM DMY;\n"
        "DELETE FROM CARD.OLDCAT WHERE CODE = '99'; -- retire\n"
    )
    (tmp_path / "XCAT.ddl").write_text(
        "CREATE UNIQUE INDEX CARD.XCAT\n    ON CARD.CATEGORY (CODE);\n"
    )
    (tmp_path / "POSTPGM.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. POSTPGM.",
            "FILE-CONTROL.",
            "    SELECT ACCT-FILE ASSIGN TO ACCTFILE",
            "        ORGANIZATION IS INDEXED.",
            "PROCEDURE DIVISION.",
            "    OPEN I-O ACCT-FILE.",
        )
    )
    (tmp_path / "POSTJOB.jcl").write_text(
        "//POSTJOB  JOB (ACCT),'POST',CLASS=A\n"
        "//STEP1    EXEC PGM=POSTPGM\n"
        "//ACCTFILE DD DSN=PROD.ACCT.KSDS,DISP=SHR\n"
        "//STEP2    EXEC PGM=SDSF\n"
    )
    (tmp_path / "ACCT.csd").write_text(
        "DEFINE FILE(ACCTFIL) GROUP(ACCT) DSNAME(PROD.ACCT.KSDS) UPDATE(YES)\n"
    )

    inventory = mainframe_inventory.build_inventory([tmp_path])
    kinds = {member["name"]: member["kind"] for member in inventory["members"]}
    assert (kinds["LOADCAT"], kinds["XCAT"]) == ("sql-dml", "sql-ddl")
    access = _access(inventory)
    assert access[("LOADCAT", "db2-table", "CARD.CATEGORY")] == "C"
    assert access[("LOADCAT", "db2-table", "CARD.OLDCAT")] == "D"
    assert {e["to"] for e in inventory["edges"] if e["from"] == "LOADCAT"} == {
        "CARD.CATEGORY",
        "CARD.OLDCAT",
    }
    assert inventory["shadowed"] == []
    assert inventory["summary"]["duplicate_names"] == ["idcams-control:REPRO"]
    assert inventory["shared_updates"] == [
        {"dataset": "PROD.ACCT.KSDS", "cics_file": "ACCTFIL", "batch": ["POSTJOB.STEP1"]}
    ]
    assert "SDSF" in inventory["summary"]["external_or_system"]
    assert inventory["summary"]["unresolved"]["programs"] == []


def test_inventory_attributes_dli_paths_open_modes_and_natural_updates(tmp_path: Path) -> None:
    common = (
        "WORKING-STORAGE SECTION.",
        "01  ISRT-FUNC PIC X(4) VALUE 'ISRT'.",
        "01  SSA-CUST  PIC X(9) VALUE 'CUSTOMER '.",
        "01  SSA-CUSTD PIC X(10) VALUE 'CUSTOMER*D'.",
        "01  SSA-ORDER.",
        "    05 SSA-ORD-SEG PIC X(8) VALUE 'ORDER   '.",
        "    05 FILLER PIC X VALUE ' '.",
        "01  WS-PGM-NAME.",
        "    05 FILLER PIC X(4) VALUE 'ACCT'.",
        "    05 FILLER PIC X(4) VALUE '0100'.",
        "PROCEDURE DIVISION.",
    )
    (tmp_path / "DLIPOS.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. DLIPOS.",
            "FILE-CONTROL.",
            "    SELECT IN-FILE ASSIGN TO INDD.",
            "    SELECT OUT-FILE ASSIGN TO OUTDD.",
            *common,
            "    OPEN INPUT IN-FILE",
            "         OUTPUT OUT-FILE",
            "    READ IN-FILE",
            "        AT END SET WS-EOF TO TRUE",
            "    END-READ.",
            "    CALL 'CBLTDLI' USING ISRT-FUNC DB-PCB IO-AREA",
            "         SSA-CUST SSA-ORDER.",
            "    CALL WS-PGM-NAME.",
            "    EXEC CICS LINK PROGRAM(WS-PGM-NAME) END-EXEC.",
            "    EXEC DLI ISRT USING PCB(1) SEGMENT(ACCOUNT)",
            "         WHERE(ACCTNO = WS-ID) SEGMENT(TXN) FROM(WS-TXN)",
            "         END-EXEC.",
        )
    )
    (tmp_path / "DLIPATH.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. DLIPATH.",
            *common,
            "    CALL 'CBLTDLI' USING ISRT-FUNC DB-PCB IO-AREA",
            "         SSA-CUSTD SSA-ORDER.",
            "    EXEC DLI ISRT USING PCB(1) SEGMENT(ACCOUNT) FROM(WS-ACCT)",
            "         SEGMENT(TXN) FROM(WS-TXN) END-EXEC.",
        )
    )
    (tmp_path / "NATUPD.nsp").write_text(
        "DEFINE DATA LOCAL\n"
        "1 ACCT-V VIEW OF ACCOUNTS\n"
        "  2 ACCT-ID\n"
        "1 HIST-V VIEW OF HISTORY\n"
        "  2 ACCT-ID\n"
        "END-DEFINE\n"
        "RD. READ ACCT-V BY ACCT-ID\n"
        "  FIND HIST-V WITH ACCT-ID = ACCT-V.ACCT-ID\n"
        "* UPDATE IS NOT DONE HERE\n"
        "    DELETE /* UPDATE NOTHING\n"
        "  END-FIND\n"
        "  UPDATE (RD.)\n"
        "END-READ\n"
        "WRITE 'UPDATE DONE'\n"
        "END\n"
    )

    inventory = mainframe_inventory.build_inventory([tmp_path])
    access = _access(inventory)
    assert access[("DLIPOS", "ims-segment", "CUSTOMER")] == "R"
    assert access[("DLIPOS", "ims-segment", "ORDER")] == "C"
    assert access[("DLIPOS", "ims-segment", "ACCOUNT")] == "R"
    assert access[("DLIPOS", "ims-segment", "TXN")] == "C"
    assert access[("DLIPATH", "ims-segment", "CUSTOMER")] == "C"
    assert access[("DLIPATH", "ims-segment", "ACCOUNT")] == "C"
    assert access[("DLIPOS", "ddname", "INDD")] == "R"
    assert access[("DLIPOS", "ddname", "OUTDD")] == "C"
    assert access[("NATUPD", "adabas-file", "ACCOUNTS")] == "RU"
    assert access[("NATUPD", "adabas-file", "HISTORY")] == "RD"
    online = next(m for m in inventory["members"] if m["name"] == "DLIPOS")
    assert "call" not in online["references"]
    assert "cics-link" not in online["references"]
    assert "dynamic_targets" not in online["details"]
    assert online["risks"]["dynamic_call"] == 2


def test_inventory_merges_definitions_and_survives_bad_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for first, second in (("cobol", "listings"), ("listings", "zcobol")):
        root = tmp_path / first
        (root / first).mkdir(parents=True)
        (root / second).mkdir()
        source = second if first == "listings" else first
        listing = first if first == "listings" else second
        (root / source / "ACCTUPD.cbl").write_text(
            fixed("CBL ARITH(EXTEND)", "IDENTIFICATION DIVISION.", "PROGRAM-ID. ACCTUPD.")
        )
        (root / listing / "ACCTUPD.lst").write_text(
            "PP 5655-EC6 IBM Enterprise COBOL for z/OS  6.4.0\n"
            "Options in effect:\n    RENT\n\n 000002  PROGRAM-ID. ACCTUPD.\n"
        )
        inventory = mainframe_inventory.build_inventory([root])
        entry = inventory["listings"]["compile"]["ACCTUPD"]
        assert entry["source_options"] == ["ARITH(EXTEND)"]
        assert entry["options"] == ["RENT"]
        listed = next(m for m in inventory["members"] if m["kind"] == "compile-listing")
        assert "source_options" not in listed["details"]["compile"]

    csd = tmp_path / "csd"
    csd.mkdir()
    (csd / "A.csd").write_text("DEFINE TRANSACTION(AAAA) GROUP(G) PROGRAM(PGMA)\n")
    (csd / "B.csd").write_text(
        "DEFINE TRANSACTION(AAAA) GROUP(H) PROGRAM(PGMB)\n"
        "DEFINE TRANSACTION(BBBB) GROUP(H) PROGRAM(PGMB)\n"
    )
    (csd / "VSAM.ctl").write_text(
        "  DEFINE CLUSTER (NAME(PROD.X.KSDS) INDEXED KEYS(8 0) SHAREOPTIONS(3 3))\n"
    )
    (csd / "usage.csv").write_text("program,count,last_run\nPGMA,12,2025-01-01,extra\n")
    inventory = mainframe_inventory.build_inventory([csd])
    assert inventory["cics_transactions"] == {"AAAA": "PGMA", "BBBB": "PGMB"}
    assert inventory["cics"]["resource_counts"] == {"TRANSACTION": 3}
    assert inventory["vsam"]["clusters"]["PROD.X.KSDS"]["shareoptions"] == [3, 3]
    assert mainframe_inventory.load_usage([csd / "usage.csv"]) == {"PGMA": 12}

    estate = tmp_path / "estate"
    write_rich_estate(estate)

    def broken(text: str) -> dict:
        raise KeyError(text[:5])

    monkeypatch.setitem(mainframe_inventory.zos_definitions.PARSERS, "mqsc", broken)
    assert mainframe_inventory.main([str(estate)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["summary"]["warnings"]) == 1
    assert "ACCTQ.mqsc: could not be analyzed (KeyError" in result["summary"]["warnings"][0]
    assert result["cics_transactions"]["AUPD"] == "ACCTUPD"
    bad = tmp_path / "bad.csv"
    bad.write_text("program\n" + "x" * 140_000 + "\n")
    assert mainframe_inventory.main([str(estate), "--usage", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err


def test_inventory_finds_updates_by_programs_run_under_tso(tmp_path: Path) -> None:
    (tmp_path / "BATUPD.cbl").write_text(
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. BATUPD.",
            "FILE-CONTROL.",
            "    SELECT ACCT-FILE ASSIGN TO ACCTDD.",
            "PROCEDURE DIVISION.",
            "    OPEN I-O ACCT-FILE.",
        )
    )
    (tmp_path / "DB2JOB.jcl").write_text(
        "//DB2JOB   JOB (ACCT),'DB2',CLASS=A\n"
        "//STEP1    EXEC PGM=IKJEFT01\n"
        "//ACCTDD   DD DSN=PROD.ACCT.KSDS,DISP=SHR\n"
        "//SYSTSIN  DD *\n"
        "  DSN SYSTEM(DB2P)\n"
        "  RUN PROGRAM(BATUPD) PLAN(BATPLN)\n"
        "  END\n"
        "/*\n"
    )
    (tmp_path / "ACCT.csd").write_text(
        "DEFINE FILE(ACCTFIL) GROUP(ACCT) DSNAME(PROD.ACCT.KSDS) UPDATE(YES)\n"
    )
    inventory = mainframe_inventory.build_inventory([tmp_path])
    assert inventory["shared_updates"] == [
        {"dataset": "PROD.ACCT.KSDS", "cics_file": "ACCTFIL", "batch": ["DB2JOB.STEP1"]}
    ]


def test_inventory_uses_evidence_reserved_words_and_search_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, hotfix = tmp_path / "main", tmp_path / "hotfix"
    write_rich_estate(root)
    hotfix.mkdir()
    (hotfix / "ACCTREC.cpy").write_text(fixed("01  ACCT-REC.", "    05  ACCT-ID PIC X(12)."))
    usage = tmp_path / "usage.csv"
    usage.write_text("Program,Count\nACCTASM,12\nACCTUPD,40\nACCTJOB,3\n,9\n")
    words = tmp_path / "words.txt"
    words.write_text("acctno\n")
    arguments = [str(hotfix), str(root), "--usage", str(usage), "--reserved-words", str(words)]
    assert mainframe_inventory.main(arguments) == 0
    inventory = json.loads(capsys.readouterr().out)
    dead = inventory["dead_code"]
    assert dead["evidence"] == "static references and usage"
    assert dead["unreferenced_and_unused"] == ["ACCTNAT"]
    assert dead["used_but_unreferenced"] == ["ACCTASM"]
    assert dead["referenced_but_unused"] == ["ACCTAPI", "ACCTBAT", "ACCTPLI"]
    assert dead["jobs_without_runs"] == ["OLDJOB"]
    assert inventory["shadowed"] == [
        {
            "kind": "cobol-copybook",
            "name": "ACCTREC",
            "effective": str(hotfix / "ACCTREC.cpy"),
            "shadowed": [str(root / "copy" / "ACCTREC.cpy")],
        }
    ]
    assert inventory["summary"]["duplicate_names"] == ["cobol-copybook:ACCTREC"]
    online = next(m for m in inventory["members"] if m["name"] == "ACCTUPD")
    assert online["details"]["reserved_words"] == ["ACCTNO"]
    assert online["risks"]["reserved_word"] == 1


def test_inventory_decodes_code_pages_record_formats_and_double_byte_text(tmp_path: Path) -> None:
    (tmp_path / "ACCTEBC").write_bytes(
        ebcdic_member(
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. ACCTEBC.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       COPY ACCT@REC.",
            codepage="1141",
        )
    )
    (tmp_path / "ACCT@REC.cpy").write_text(fixed("01  ACCT-REC.", "    05 ACCT-ID PIC X(10)."))
    records = ["       01  ACCT-VREC.", "       05  ACCT-V PIC X(4)."]
    (tmp_path / "ACCTVREC").write_bytes(b"".join(rdw(ebcdic(line, "1141")) for line in records))
    double_byte = ebcdic("      *", "1141") + b"\x0e\x42\xc1\x42\xc2\x0f" + ebcdic(" " * 67, "1141")
    (tmp_path / "ACCTJREC").write_bytes(ebcdic_member("       01  ACCT-JREC.") + double_byte)

    options = mainframe_inventory.ScanOptions(codepage="cp1141")
    inventory = mainframe_inventory.build_inventory([tmp_path], options)
    members = {member["name"]: member for member in inventory["members"]}
    assert members["ACCTEBC"]["encoding"] == "ebcdic-cp1141"
    assert members["ACCTEBC"]["references"]["copy"] == ["ACCT@REC"]
    assert inventory["summary"]["unresolved"]["copybooks"] == []
    assert members["ACCTVREC"]["encoding"] == "ebcdic-cp1141-v"
    assert inventory["summary"]["dbcs_members"] == 1

    strict = mainframe_inventory.ScanOptions(codepage="cp1141", recfm="V")
    inventory = mainframe_inventory.build_inventory([tmp_path], strict)
    members = {member["name"]: member for member in inventory["members"]}
    assert "encoding" not in members["ACCT@REC"]
    assert "ACCTEBC" not in members
    assert any("ACCTEBC" in warning for warning in inventory["summary"]["warnings"])


def test_inventory_cli_formats_and_incremental_rescan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "estate"
    write_rich_estate(root)
    assert mainframe_inventory.main([str(root), "--format", "markdown"]) == 0
    report = capsys.readouterr().out
    for heading in (
        "## CICS routing to other regions",
        "## Transient data triggers",
        "## CICS web endpoints",
        "## CICS threadsafe readiness",
        "## VSAM clusters",
        "## MQ queues",
        "## Db2 binds and remote locations",
        "## File transfers",
        "## Cross-check findings",
        "## Data sets updated by both CICS and batch",
        "## Dead-code candidates (static references)",
    ):
        assert heading in report
    assert "| ACCTURI | SERVER | /acct/* | ACCTAPI |" in report
    assert "| PROD.ACCT.KSDS | KSDS | 10, 0 | 150 | 2 3 |" in report

    assert mainframe_inventory.main([str(root), "--format", "jsonl"]) == 0
    lines = capsys.readouterr().out.splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["record"] == "summary"
    assert {record["record"] for record in records[-3:]} == {"edge"}
    sections = [record["name"] for record in records if record["record"] == "section"]
    assert sections == list(mainframe_inventory.SECTION_KEYS)
    previous = tmp_path / "inventory.jsonl"
    previous.write_text("\n".join(lines), encoding="utf-8")

    with (root / "cobol" / "ACCTAPI.cbl").open("a", encoding="utf-8") as handle:
        handle.write(fixed("    GOBACK."))
    assert mainframe_inventory.main([str(root), "--previous", str(previous)]) == 0
    rescanned = json.loads(capsys.readouterr().out)
    summary = rescanned["summary"]
    assert summary["reused_from_previous"] == summary["members"] - 1
    assert _access(rescanned) == _access(mainframe_inventory.build_inventory([root]))

    assert mainframe_inventory.main([str(root), "--codepage", "999"]) == 1
    assert "code page" in capsys.readouterr().err


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("CARDDEMO_DIR"),
    reason="set CARDDEMO_DIR to a clone of aws-samples/aws-mainframe-modernization-carddemo",
)
def test_inventory_and_seams_on_carddemo() -> None:
    app = Path(os.environ["CARDDEMO_DIR"]) / "app"
    inventory = mainframe_inventory.build_inventory([app])
    assert inventory["summary"]["unresolved"] == {"copybooks": [], "programs": [], "jcl": []}
    assert inventory["summary"]["warnings"] == []
    assert len(inventory["cics_transactions"]) >= 20
    shared = {entry["dataset"] for entry in inventory["shared_updates"]}
    assert "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS" in shared
    alternate = inventory["vsam"]["aix"]["AWS.M2.CARDDEMO.CARDDATA.VSAM.AIX"]
    assert alternate["keys"] == {"length": 11, "offset": 16}
    psbs = {(e["from"], e["to"]) for e in inventory["edges"] if e["type"] == "ims-psb"}
    assert ("COPAUA0C", "PSBPAUTB") in psbs
    report = seam_report.build_report(inventory)
    assert "dataset:AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS" in report["multiple_writers"]
