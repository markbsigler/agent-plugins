"""Tests for code-modernization-plugin: mainframe-analysis ims_model.py."""

from __future__ import annotations

import json
from pathlib import Path

import ims_model
import pytest
from mainframe_fixtures import ebcdic_member


def card(text: str, *, continued: bool = False) -> str:
    """Return one 72-column macro statement line, with a continuation mark if asked."""
    assert len(text) <= 71, text
    return text.ljust(71) + ("X" if continued else " ")


CUSTDB = [
    "* CUSTOMER DATABASE",
    card("         DBD   NAME=CUSTDB,ACCESS=(HIDAM,VSAM),", continued=True),
    card("               RMNAME=(DFSHDC40,1,10)"),
    card("         DATASET DD1=CUSTDD,DEVICE=3390"),
    card("         SEGM  NAME=CUSTOMER,PARENT=0,BYTES=120"),
    card("         FIELD NAME=(CUSTNO,SEQ,U),BYTES=8,START=1,TYPE=C"),
    card("         FIELD NAME=CUSTNAME,BYTES=30,START=9,TYPE=C"),
    card("         FIELD NAME=BALANCE,BYTES=5,START=39,TYPE=P"),
    card("         FIELD NAME=CUSTKEY2,BYTES=4,START=5,TYPE=C"),
    card("         LCHILD NAME=(CUSTIDX,CUSTXDB),POINTER=INDX"),
    card("         LCHILD NAME=(NAMEIDX,CUSTNDB),POINTER=INDX"),
    card("         XDFLD NAME=XNAME,SRCH=CUSTNAME"),
    card("         SEGM  NAME=ACCOUNT,PARENT=CUSTOMER,BYTES=(80,20)"),
    card("         FIELD NAME=(ACCTNO,SEQ,U),BYTES=10,START=3,TYPE=C"),
    card("         SEGM  NAME=TRANS,PARENT=((ACCOUNT,SNGL)),BYTES=40"),
    card("         FIELD NAME=(TRDATE,SEQ,M),BYTES=8,START=1,TYPE=C"),
    card("         FIELD NAME=AMOUNT,BYTES=6,START=9,DATATYPE=DECIMAL(11,2)"),
    card("         SEGM  NAME=ORDLINE,BYTES=30,", continued=True),
    card("               PARENT=((CUSTOMER,DBLE),(PRODUCT,PHYSICAL,PRODDB))"),
    card("         FIELD NAME=(PRODNO,SEQ,U),BYTES=6,START=1"),
    card("         DBDGEN"),
    card("         END"),
]
CUSTXDB = [
    "         DBD   NAME=CUSTXDB,ACCESS=(INDEX,VSAM)",
    "         SEGM  NAME=CUSTIDX,BYTES=8",
    "         FIELD NAME=(CUSTNO,SEQ,U),BYTES=8,START=1",
    "         LCHILD NAME=(CUSTOMER,CUSTDB),INDEX=CUSTNO",
    "         DBDGEN",
]
PRODDB = [
    "         DBD   NAME=PRODDB,ACCESS=HDAM",
    "         SEGM  NAME=PRODUCT,PARENT=0,BYTES=50",
    "         FIELD NAME=(PRODNO,SEQ,U),BYTES=6,START=1,TYPE=C",
    "         FIELD NAME=(PRICE),BYTES=4,START=7,TYPE=F",
    "         LCHILD NAME=(ORDLINE,CUSTDB),POINTER=SNGL,PAIR=VORDLN",
    "         SEGM  NAME=VORDLN,PARENT=PRODUCT,POINTER=PAIRED,",
    "               SOURCE=((ORDLINE,DATA,CUSTDB))",
    "         DBDGEN",
]
CUSTPGM = [
    card("IOPCB    PCB   TYPE=TP,LTERM=OUTPUT,MODIFY=YES"),
    card("CUSTPCB  PCB   TYPE=DB,DBDNAME=CUSTDB,PROCOPT=G,KEYLEN=20"),
    card("         SENSEG NAME=CUSTOMER,PARENT=0"),
    card("         SENSEG NAME=ACCOUNT,PARENT=CUSTOMER,PROCOPT=GR"),
    card("         SENSEG NAME=TRANS,PARENT=ACCOUNT,PROCOPT=A"),
    card("         SENSEG NAME=GHOST,PARENT=0"),
    card("         PSBGEN LANG=COBOL,PSBNAME=CUSTPGM"),
    card("         END"),
]


def write_sources(root: Path) -> None:
    root.mkdir(exist_ok=True)
    (root / "CUSTDB.dbd").write_text("\n".join(CUSTDB) + "\n", encoding="utf-8")
    (root / "PRODDB.dbd").write_text("\n".join(PRODDB) + "\n", encoding="utf-8")
    (root / "CUSTXDB").write_bytes(ebcdic_member(*CUSTXDB))
    (root / "CUSTPGM.psb").write_text("\n".join(CUSTPGM) + "\n", encoding="utf-8")
    (root / "notes.txt").write_text("not a DBD\n", encoding="utf-8")


def test_ims_model_reads_hierarchy_sensitivity_and_checks_programs(tmp_path: Path) -> None:
    write_sources(tmp_path)
    model = ims_model.load([tmp_path])
    inventory = {
        "members": [{"details": {"steps": [{"ims_program": "BATCHPGM", "psb": "CUSTPGM"}]}}],
        "edges": [
            {"from": "BATCHPGM", "to": "ACCOUNT", "type": "ims-segment", "access": "CD"},
            {"from": "CUSTPGM", "to": "CUSTOMER", "type": "ims-segment", "access": "R"},
            {"from": "CUSTPGM", "to": "ORDLINE", "type": "ims-segment", "access": "R"},
            {"from": "CUSTPGM", "to": "CUSTDD", "type": "ddname", "access": "R"},
            {"from": "ONLINE", "to": "CUSTPGM", "type": "ims-psb"},
            {"from": "ONLINE", "to": "TRANS", "type": "ims-segment", "access": "CRUD"},
            {"from": "ONLINE", "to": "CUSTOMER", "type": "ims-segment", "access": "U"},
        ],
    }
    report = ims_model.build_report(model, inventory)

    assert sorted(report["databases"]) == ["CUSTDB", "CUSTXDB", "PRODDB"]
    custdb = report["databases"]["CUSTDB"]
    assert custdb["access"] == ["HIDAM", "VSAM"]
    assert custdb["datasets"] == ["CUSTDD"]
    segments = {segment["name"]: segment for segment in custdb["segments"]}
    assert segments["CUSTOMER"]["children"] == ["ACCOUNT", "ORDLINE"]
    assert (segments["ACCOUNT"]["bytes"], segments["ACCOUNT"]["min_bytes"]) == (80, 20)
    assert segments["TRANS"]["parent"] == "ACCOUNT"
    assert segments["TRANS"]["twins"] == "non-unique"
    assert segments["TRANS"]["concatenated_key"] == 26
    assert segments["ORDLINE"]["parent"] == "CUSTOMER"
    assert segments["ORDLINE"]["logical_parent"] == {
        "segment": "PRODUCT",
        "storage": "PHYSICAL",
        "dbd": "PRODDB",
    }
    secondary = segments["CUSTOMER"]["indexes"][1]
    assert (secondary["xdfld"], secondary["search"]) == ("XNAME", ["CUSTNAME"])
    virtual = report["databases"]["PRODDB"]["segments"][1]
    assert (virtual["name"], virtual["source"]) == ("VORDLN", ["ORDLINE"])

    psb = report["psbs"]["CUSTPGM"]
    assert psb["language"] == "COBOL"
    assert (psb["pcbs"][0]["type"], psb["pcbs"][0]["destination"]) == ("TP", "OUTPUT")
    assert psb["pcbs"][1]["name"] == "CUSTPCB"
    assert [s["ops"] for s in psb["pcbs"][1]["sensitive"]] == ["R", "RU", "CRUD", "R"]

    assert report["segment_access"] == {
        "ACCOUNT": {"BATCHPGM": "CD"},
        "CUSTOMER": {"CUSTPGM": "R", "ONLINE": "U"},
        "ORDLINE": {"CUSTPGM": "R"},
        "TRANS": {"ONLINE": "CRUD"},
    }
    findings = {(finding["check"], finding["detail"]) for finding in report["findings"]}
    assert findings == {
        ("unknown-segment", "PCB 2 names GHOST, which CUSTDB does not define"),
        (
            "keylen",
            (
                "PCB 2 KEYLEN=20 is shorter than the longest concatenated key (26) of its "
                "sensitive segments"
            ),
        ),
        ("procopt", "BATCHPGM with PSB CUSTPGM does CD on ACCOUNT; PROCOPT allows RU"),
        ("not-sensitive", "CUSTPGM with PSB CUSTPGM uses ORDLINE, which no PCB is sensitive to"),
        ("procopt", "ONLINE with PSB CUSTPGM does U on CUSTOMER; PROCOPT allows R"),
    }
    assert ims_model.procopt_crud("LS") == "C"
    assert ims_model.procopt_crud("GOT") == "R"


def test_ims_model_drafts_ddl_with_keys_types_and_indexes(tmp_path: Path) -> None:
    write_sources(tmp_path)
    ddl = ims_model.to_ddl(ims_model.load([tmp_path]))
    assert "PRIMARY KEY (CUSTOMER_CUSTNO, ACCOUNT_ACCTNO, TRDATE, SEQ_NO)" in ddl
    assert (
        "FOREIGN KEY (CUSTOMER_CUSTNO, ACCOUNT_ACCTNO) REFERENCES ACCOUNT (CUSTOMER_CUSTNO, ACCTNO)"
        in ddl
    )
    assert "    AMOUNT DECIMAL(11,2)," in ddl
    assert "    BALANCE DECIMAL(9,0),  -- packed: take the scale from the copybook" in ddl
    assert "    -- CUSTKEY2 overlaps another field; map it from the copybook" in ddl
    assert "-- 68 of 80 bytes are not described by FIELD statements" in ddl
    assert "CREATE INDEX CUSTOMER_XNAME ON CUSTOMER (CUSTNAME);" in ddl
    assert "-- logical parent PRODDB.PRODUCT" in ddl
    assert "    PRICE INTEGER," in ddl
    assert "-- VORDLN is a virtual segment over ORDLINE" in ddl
    assert "-- CUSTXDB (INDEX): no tables" in ddl
    sql = [line.split("--")[0].rstrip() for line in ddl.splitlines()]
    statements = "\n".join(line for line in sql if line.strip())
    assert ",\n)" not in statements


def test_ims_model_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_sources(tmp_path)
    inventory = tmp_path / "inventory.jsonl"
    edge = {"record": "edge", "from": "CUSTPGM", "to": "CUSTOMER", "type": "ims-segment"}
    lines = [{"record": "summary", "tool": "mainframe_inventory"}, {**edge, "access": "D"}]
    inventory.write_text("\n".join(json.dumps(line) for line in lines) + "\n\n", "utf-8")
    arguments = [str(tmp_path), "--format", "markdown", "--inventory", str(inventory)]
    assert ims_model.main(arguments) == 0
    markdown = capsys.readouterr().out
    assert "| ACCOUNT | CUSTOMER | 20-80 | ACCTNO | unique |  |  |" in markdown
    assert "| CUSTOMER | (root) | 120 | CUSTNO | unique |  | CUSTIDX (INDX), XNAME |" in markdown
    assert "| CUSTPGM | 1 | TP | OUTPUT |  |  |  |" in markdown
    assert (
        "| procopt | CUSTPGM | CUSTPGM with PSB CUSTPGM does D on CUSTOMER; PROCOPT allows R |"
        in (markdown)
    )
    assert "| CUSTOMER | CUSTPGM D |" in markdown

    assert ims_model.main([str(tmp_path / "CUSTDB.dbd"), "--format", "mermaid"]) == 0
    mermaid = capsys.readouterr().out
    assert "CUSTDB_CUSTOMER --> CUSTDB_ACCOUNT" in mermaid
    assert "CUSTDB_ORDLINE -.->|logical parent| PRODDB_PRODUCT" in mermaid

    assert ims_model.main([str(tmp_path), "--format", "ddl", "--dbd", "custdb"]) == 0
    ddl = capsys.readouterr().out
    assert "CREATE TABLE CUSTOMER" in ddl
    assert "PRODUCT" not in ddl.split("ORDLINE", 1)[0]
    assert "CUSTXDB" not in ddl

    assert ims_model.main([str(tmp_path / "CUSTPGM.psb")]) == 0
    assert list(json.loads(capsys.readouterr().out)["psbs"]) == ["CUSTPGM"]

    assert ims_model.main([str(tmp_path / "missing")]) == 1
    assert "not found" in capsys.readouterr().err
    assert ims_model.main([str(tmp_path / "notes.txt")]) == 1
    assert "no DBD or PSB" in capsys.readouterr().err
    assert ims_model.main([str(tmp_path), "--codepage", "999"]) == 1
    assert "error:" in capsys.readouterr().err
