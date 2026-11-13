"""Tests for code-modernization-plugin: the copybook-data skill's layout and record tools."""

from __future__ import annotations

import hashlib
import json
import string
from decimal import Decimal
from pathlib import Path

import copybook_layout
import pli_hlasm_layout
import pytest
import record_compare
import record_decode
import record_mask
import zos_encoding
from mainframe_fixtures import ebcdic, fixed, packed, rdw, zoned


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


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def field_map(layout: copybook_layout.Layout, index: int = 0) -> dict[str, dict]:
    record = copybook_layout.layout_to_dict(layout)["records"][index]
    return {entry["name"]: entry for entry in record["fields"]}


def test_synchronized_items_get_ibm_slack_bytes(tmp_path: Path) -> None:
    """The first two records are IBM's documented slack-byte examples."""
    path = write(
        tmp_path,
        "SYNC.cpy",
        "01 FIELD-A.\n"
        "   05 FIELD-B PIC X(5).\n"
        "   05 FIELD-C.\n"
        "      10 FIELD-D PIC XX.\n"
        "      10 FIELD-E COMP PIC S9(6) SYNC.\n"
        "01 WORK-RECORD.\n"
        "   05 WORK-CODE PIC X.\n"
        "   05 COMP-TABLE OCCURS 10 TIMES.\n"
        "      10 COMP-TYPE PIC X.\n"
        "      10 COMP-PAY PIC S9(4)V99 COMP SYNC.\n"
        "      10 COMP-HOURS PIC S9(3) COMP SYNC.\n"
        "      10 COMP-NAME PIC X(5).\n"
        "01 NESTED SYNC.\n"
        "   05 G1.\n"
        "      10 A PIC X(3).\n"
        "   05 G2.\n"
        "      10 B PIC S9(9) COMP.\n"
        "      10 R COMP-2.\n"
        "01 OTHER.\n"
        "   05 X PIC X.\n"
        "   05 G4 SYNC.\n"
        "      10 C PIC S9(4) COMP.\n",
    )
    layout = copybook_layout.parse_copybook(path)
    lengths = [r["length"] for r in copybook_layout.layout_to_dict(layout)["records"]]
    assert lengths == [12, 161, 16, 4]
    first = field_map(layout, 0)
    assert (first["FIELD-C"]["length"], first["FIELD-E"]["position"]) == (7, 9)
    assert first["FIELD-E"]["slack_before"] == 1
    table = field_map(layout, 1)
    assert (table["COMP-PAY"]["position"], table["COMP-PAY"]["slack_before"]) == (5, 2)
    assert table["COMP-HOURS"]["position"] == 9
    assert (table["COMP-TABLE"]["length"], table["COMP-TABLE"]["slack_after"]) == (16, 2)
    assert table["COMP-NAME"]["occurs_in"] == [{"name": "COMP-TABLE", "max": 10, "stride": 16}]
    nested = field_map(layout, 2)
    assert nested["G1"]["length"] == 4, "slack after A belongs to G1, as IBM places it"
    assert (nested["G2"]["position"], nested["R"]["position"]) == (5, 9)
    other = field_map(layout, 3)
    assert (other["G4"]["position"], other["C"]["position"]) == (3, 3)
    assert any("below level 01" in warning for warning in layout.warnings)
    markdown = copybook_layout.layout_to_markdown(layout)
    assert "2 slack bytes after each occurrence" in markdown
    assert "1 slack bytes before" in markdown


def test_redefines_must_be_aligned_for_synchronized_items(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "R.cpy",
        "01 R.\n   05 P PIC X.\n   05 A PIC X(4).\n   05 B REDEFINES A PIC S9(9) COMP SYNC.\n",
    )
    layout = copybook_layout.parse_copybook(path)
    assert any("4-byte boundary" in warning for warning in layout.warnings)


def test_diff_classifies_breaking_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = write(
        tmp_path,
        "OLD.cpy",
        "01 CUST-REC.\n 05 CUST-ID PIC X(10).\n 05 CUST-STATUS PIC X.\n  88 ACTIVE VALUE 'A'.\n"
        " 05 CUST-BAL PIC S9(7)V99 COMP-3.\n 05 FILLER PIC X(5).\n",
    )
    new = write(
        tmp_path,
        "NEW.cpy",
        "01 CUSTOMER-REC.\n 05 CUST-ID PIC X(10).\n 05 CUST-STATUS PIC X.\n"
        "  88 ACTIVE VALUES 'A' 'R'.\n 05 CUST-BAL PIC S9(7)V99 COMP-3.\n 05 CUST-NEW PIC X(5).\n",
    )
    resized = write(
        tmp_path,
        "RESIZED.cpy",
        "01 CUST-REC.\n 05 CUST-ID PIC X(12).\n 05 CUST-BAL PIC S9(9)V99 COMP-3.\n",
    )
    parse = copybook_layout.parse_copybook
    compatible = copybook_layout.diff_layouts(parse(old), parse(new))
    assert compatible["breaking"] is False
    assert [(c["field"], c["kinds"]) for c in compatible["changes"]] == [
        ("CUST-STATUS", ["conditions"]),
        ("CUST-NEW", ["added"]),
    ]
    breaking = copybook_layout.diff_layouts(parse(old), parse(resized))
    assert breaking["breaking"] is True
    assert {c["field"]: c["kinds"] for c in breaking["changes"]} == {
        "CUST-REC": ["record-length"],
        "CUST-ID": ["resized"],
        "CUST-STATUS": ["removed"],
        "CUST-BAL": ["moved", "resized", "retyped"],
    }
    assert copybook_layout.main([str(old), "--diff", str(new)]) == 0
    assert json.loads(capsys.readouterr().out)["match"] == "name"
    assert copybook_layout.main([str(old), "--diff", str(resized), "--format", "markdown"]) == 1
    report = capsys.readouterr().out
    assert "| CUST-ID | resized | yes | pos 1, len 10, X(10) | pos 1, len 12, X(12) |" in report
    assert "| CUST-REC | record-length | yes | 21 bytes | 18 bytes |" in report
    assert copybook_layout.main([str(old), "--diff", str(tmp_path / "absent.cpy")]) == 2
    assert copybook_layout.main([str(old), "--diff", str(new), "--record", "NOPE"]) == 2


def test_diff_with_several_records_matches_them_by_name(tmp_path: Path) -> None:
    old = write(tmp_path, "A.cpy", "01 HDR.\n 05 H PIC X.\n01 DTL.\n 05 D PIC X.\n")
    new = write(tmp_path, "B.cpy", "01 HDR.\n 05 H PIC X(2).\n01 TRL.\n 05 T PIC X.\n")
    diff = copybook_layout.diff_layouts(
        copybook_layout.parse_copybook(old), copybook_layout.parse_copybook(new)
    )
    assert {c["field"]: c["kinds"] for c in diff["changes"]} == {
        "HDR": ["record-length"],
        "DTL": ["record-removed"],
        "TRL": ["record-added"],
        "HDR.H": ["resized"],
        "DTL.D": ["removed"],
        "TRL.T": ["added"],
    }


PLI_RECORD = (
    " /* CUSTOMER RECORD */\n"
    " DCL 1 CUST_REC UNALIGNED,\n"
    "       2 CUST_ID    CHAR(10),\n"
    "       2 CUST_BAL   FIXED DEC(9,2),\n"
    "       2 CUST_COUNT FIXED BIN(15),\n"
    "       2 CUST_NAME  CHAR(20) VARYING,\n"
    "       2 CUST_AMT   PIC 'S999V99',\n"
    "       2 HIST(3),\n"
    "         3 H_AMT    FIXED DEC(7,2);\n"
    " DCL COUNTER FIXED BIN(31);\n"
)
COBOL_RECORD = (
    "01 CUST-REC.\n"
    "   05 CUST-ID PIC X(10).\n"
    "   05 CUST-BAL PIC S9(7)V99 COMP-3.\n"
    "   05 CUST-COUNT PIC S9(4) COMP.\n"
    "   05 CUST-NAME.\n"
    "      49 CUST-NAME-LEN PIC S9(4) COMP.\n"
    "      49 CUST-NAME-TEXT PIC X(20).\n"
    "   05 CUST-AMT PIC S999V99 SIGN LEADING SEPARATE.\n"
    "   05 HIST OCCURS 3.\n"
    "      10 H-AMT PIC S9(5)V99 COMP-3.\n"
)


def test_pli_structure_matches_the_equivalent_copybook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pli = write(tmp_path, "CUSTREC.pli", PLI_RECORD)
    cobol = write(tmp_path, "CUSTREC.cpy", COBOL_RECORD)
    layout = pli_hlasm_layout.parse_source(pli)
    fields = field_map(layout)
    assert [r.name for r in layout.records] == ["CUST_REC"]
    assert {name: (f["position"], f["total_length"]) for name, f in fields.items()} == {
        "CUST_ID": (1, 10),
        "CUST_BAL": (11, 5),
        "CUST_COUNT": (16, 2),
        "CUST_NAME": (18, 22),
        "CUST_NAME_LENGTH": (18, 2),
        "CUST_NAME_TEXT": (20, 20),
        "CUST_AMT": (40, 6),
        "HIST": (46, 12),
        "H_AMT": (46, 4),
    }
    assert fields["CUST_AMT"]["sign"] == {"position": "leading", "separate": True}
    assert fields["CUST_BAL"]["picture"] == "FIXED DEC(9,2)"
    diff = copybook_layout.diff_layouts(
        copybook_layout.parse_copybook(cobol), layout, match="position"
    )
    assert diff["breaking"] is False
    assert {kind for change in diff["changes"] for kind in change["kinds"]} == {"renamed"}
    assert copybook_layout.main([str(cobol), "--diff", str(pli), "--match", "position"]) == 0
    capsys.readouterr()
    assert copybook_layout.main([str(pli), "--language", "pli", "--format", "markdown"]) == 0
    assert "| 18 | 2 | 03 | CUST_NAME_LENGTH |" in capsys.readouterr().out


def test_pli_bits_alignment_unions_and_warnings(tmp_path: Path) -> None:
    source = write(
        tmp_path,
        "MSG.inc",
        " DCL 1 FLAGS_REC UNALIGNED,\n"
        "       2 FLAG_A  BIT(1),\n"
        "       2 FLAG_B  BIT(7),\n"
        "       2 FLAG_C  BIT(4),\n"
        "       2 NEXT    CHAR(1);\n"
        " DECLARE 1 MSG,\n"
        "       2 MSG_CODE  CHAR(3),\n"
        "       2 MSG_LEN   FIXED BIN(31),\n"
        "       2 MSG_RATE  FLOAT DEC(16),\n"
        "       2 MSG_PTR   POINTER,\n"
        "       2 MSG_BODY  UNION,\n"
        "         3 AS_TEXT CHAR(8),\n"
        "         3 AS_NUM  FIXED DEC(15),\n"
        "       2 ITEMS(N REFER(MSG_LEN)) CHAR(2),\n"
        "       2 COPYOF    LIKE MSG_BODY,\n"
        "       2 ODD       FANCY,\n"
        "       2 TABLE(0:4) FIXED BIN(7) UNSIGNED,\n"
        "       2 WIDE      WIDECHAR(2),\n"
        "       2 GRAPH     GRAPHIC(2) INIT(''),\n"
        "       2 VARZ      CHAR(4) VARYINGZ,\n"
        "       2 EDITED    PIC 'ZZ9.99',\n"
        "       2 TEXTPIC   PIC '(3)X',\n"
        "       2 STORE     AREA(100);\n",
    )
    layout = pli_hlasm_layout.parse_source(source)
    flags, msg = (field_map(layout, index) for index in (0, 1))
    assert [(f["position"], f["bit_offset"], f["bits"]) for f in list(flags.values())[:3]] == [
        (1, 0, 1),
        (1, 1, 7),
        (2, 0, 4),
    ]
    assert flags["NEXT"]["position"] == 3
    assert msg["MSG_LEN"]["slack_before"] == 1
    assert (msg["MSG_LEN"]["position"], msg["MSG_RATE"]["position"]) == (5, 9)
    assert msg["MSG_RATE"]["usage"] == "COMP-2"
    assert msg["MSG_PTR"]["category"] == "pointer"
    assert msg["AS_NUM"]["redefines"] == "AS_TEXT"
    assert msg["AS_NUM"]["position"] == msg["AS_TEXT"]["position"]
    assert msg["ITEMS"]["occurs"] == {"min": 1, "max": 1, "depending_on": "MSG_LEN"}
    assert (msg["TABLE"]["occurs"]["max"], msg["TABLE"]["length"]) == (5, 1)
    assert msg["WIDE"]["category"] == "national"
    assert msg["GRAPH"]["category"] == "dbcs"
    assert msg["VARZ"]["length"] == 5
    assert msg["EDITED"]["category"] == "numeric-edited"
    assert msg["TEXTPIC"]["category"] == "alphanumeric"
    assert msg["STORE"]["length"] == 116
    joined = "\n".join(layout.warnings)
    for expected in (
        "non-numeric bound",
        "LIKE, which is not expanded",
        "ignored FANCY",
        "ODD has no data attributes",
        "AGGREGATE listing",
    ):
        assert expected in joined


def test_hlasm_dsect_layout(tmp_path: Path) -> None:
    source = write(
        tmp_path,
        "CUSTDS.mac",
        "* CUSTOMER RECORD\n"
        "CUSTREC  DSECT\n"
        "CUSTID   DS    CL10               CUSTOMER ID\n"
        "CUSTBAL  DS    PL5\n"
        "CUSTCNT  DS    H\n"
        "CUSTFLG  DS    X\n"
        "CUSTALT  DS    0CL6\n"
        "CUSTA1   DS    CL3\n"
        "CUSTA2   DS    CL3\n"
        "         ORG   CUSTALT\n"
        "CUSTKEY  DS    XL6\n"
        "         ORG\n"
        "CUSTLIM  DS    F\n"
        "CUSTHIST DS    3CL8\n"
        "CUSTLIT  DC    C'AB''C'\n"
        "CUSTPK   DC    P'-12345'\n"
        "CUSTZD   DC    Z'123'\n"
        "CUSTHX   DC    X'0102030'\n"
        "CUSTBT   DC    B'101'\n"
        "CUSTMULT DS    CL2,PL3\n"
        "CUSTBAD  DS    3Q'X\n"
        "         ORG   NOWHERE+5\n"
        "CUSTDB   DS    DB\n"
        "OTHER    CSECT\n"
        "NOTMAPPED DS   CL80\n"
        "         END\n",
    )
    parsed = pli_hlasm_layout.parse_source(source)
    fields = field_map(parsed)
    positions = {name: (f["position"], f["length"]) for name, f in fields.items()}
    assert positions == {
        "CUSTID": (1, 10),
        "CUSTBAL": (11, 5),
        "CUSTCNT": (17, 2),
        "CUSTFLG": (19, 1),
        "CUSTALT": (20, 6),
        "CUSTA1": (20, 3),
        "CUSTA2": (23, 3),
        "CUSTKEY": (20, 6),
        "CUSTLIM": (29, 4),
        "CUSTHIST": (33, 8),
        "CUSTLIT": (57, 4),
        "CUSTPK": (61, 3),
        "CUSTZD": (64, 3),
        "CUSTHX": (67, 4),
        "CUSTBT": (71, 1),
        "CUSTMULT": (72, 2),
        "FILLER": (74, 3),
        "CUSTDB": (81, 8),
    }
    assert fields["CUSTKEY"]["redefines"] == "CUSTALT"
    assert fields["CUSTCNT"]["slack_before"] == 1
    assert fields["CUSTHIST"]["occurs"]["max"] == 3
    assert fields["CUSTPK"]["digits"] == 5
    assert copybook_layout.layout_to_dict(parsed)["records"][0]["length"] == 88
    joined = "\n".join(parsed.warnings)
    assert "cannot size operand" in joined
    assert "cannot evaluate ORG NOWHERE+5" in joined
    assert "binary float" in joined


def test_hlasm_continuation_and_detection(tmp_path: Path) -> None:
    prefix = "MSGTEXT  DC    C'"
    first = (prefix + "THIS LITERAL CONTINUES ON THE NEXT LINE").ljust(71)
    lines = [
        "MSGREC   DSECT",
        first + "X",
        "               HERE'",
        "MSGLIST  DC    C'A',                                                   X",
        "               C'BC'",
        "MSGEND   DS    0H",
    ]
    source = write(tmp_path, "MSGREC", "\n".join(lines) + "\n")
    assert pli_hlasm_layout.detect_language(source, source.read_text()) == "hlasm"
    fields = field_map(pli_hlasm_layout.parse_source(source))
    assert fields["MSGTEXT"]["length"] == len(first) - len(prefix) + len("HERE")
    assert [(f["name"], f["length"]) for f in list(fields.values())[1:]] == [
        ("MSGLIST", 1),
        ("FILLER", 2),
    ]
    assert pli_hlasm_layout.main([str(source), "--format", "markdown"]) == 0


def test_dfsort_symbols_expand_tables(account_copybook: Path, tmp_path: Path) -> None:
    layout = copybook_layout.parse_copybook(account_copybook)
    symbols = copybook_layout.layout_to_dfsort_symbols(layout)
    assert "ACCT-BALANCE,12,5,PD" in symbols
    assert "ACCT-DELTA,39,6,CSL" in symbols
    assert "* ACCT-NAME-N: no DFSORT format for national data" in symbols
    assert "ACCT-HISTORY_3,99,12,CH" in symbols
    assert "HIST-AMOUNT_2,95,4,PD" in symbols
    with_rdw = copybook_layout.layout_to_dfsort_symbols(layout, rdw=True, limit=2)
    assert "ACCT-ID,5,10,CH" in with_rdw
    assert "HIST-AMOUNT_3" not in with_rdw
    assert "only the first 2 of 3 occurrences of ACCT-HISTORY" in with_rdw
    duplicates = write(
        tmp_path,
        "DUP.cpy",
        "01 R.\n 05 HOME.\n  10 CITY PIC X(5).\n 05 WORK.\n  10 CITY PIC X(5).\n 05 1ST PIC X.\n",
    )
    text = copybook_layout.layout_to_dfsort_symbols(copybook_layout.parse_copybook(duplicates))
    assert "CITY,1,5,CH" in text
    assert "WORK_CITY,6,5,CH" in text
    assert "F1ST,11,1,CH" in text


def test_avro_and_asyncapi_drafts(account_copybook: Path, tmp_path: Path) -> None:
    layout = copybook_layout.parse_copybook(account_copybook)
    avro = copybook_layout.layout_to_avro(layout)
    fields = {f["name"]: f for f in avro["schema"]["fields"]}
    assert avro["schema"]["name"] == "ACCOUNT_RECORD"
    assert fields["acctBalance"]["type"] == {
        "type": "bytes",
        "logicalType": "decimal",
        "precision": 9,
        "scale": 2,
    }
    assert fields["acctCount"]["type"] == "int"
    assert fields["acctSeq"]["type"] == "long"
    assert fields["acctRate"]["type"] == "double"
    assert fields["acctThousands"]["type"] == "int"
    assert fields["acctHistory"]["type"]["type"] == "array"
    assert "acctOpenedX" not in fields
    assert any("REDEFINES ACCT-OPENED" in w for w in avro["warnings"])
    assert "88 ACCT-OPEN = 'O'" in fields["acctStatus"]["doc"]
    multi = write(
        tmp_path,
        "MULTI.cpy",
        "01 HDR.\n 05 H-PTR POINTER.\n 05 H-BIG PIC 9(20).\n 05 H-TINY PIC VPP9.\n"
        "01 HDR-2.\n 05 F PIC X.\n",
    )
    union = copybook_layout.layout_to_avro(copybook_layout.parse_copybook(multi), names="cobol")
    assert [schema["name"] for schema in union["schema"]] == ["HDR", "HDR_2"]
    big, tiny = union["schema"][0]["fields"]
    assert big["type"]["precision"] == 20
    assert tiny["type"] == {"type": "bytes", "logicalType": "decimal", "precision": 3, "scale": 3}
    assert any("pointer items have no Avro form" in w for w in union["warnings"])
    document = copybook_layout.layout_to_asyncapi(layout, channel="ACCT.EVENTS")
    assert document["asyncapi"] == "3.0.0"
    assert document["channels"]["acctEvents"]["address"] == "ACCT.EVENTS"
    message = document["components"]["messages"]["accountRecord"]
    assert message["payload"]["schemaFormat"].endswith("draft-2020-12")
    assert message["payload"]["schema"]["properties"]["acctBalance"]["type"] == "string"
    several = copybook_layout.layout_to_asyncapi(copybook_layout.parse_copybook(multi))
    assert set(several["components"]["messages"]) == {"hdr", "hdr2"}
    assert several["x-cobol-warnings"]


def test_layout_cli_new_formats(account_copybook: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for output_format, marker in (
        ("avro", '"logicalType": "decimal"'),
        ("asyncapi", '"asyncapi": "3.0.0"'),
        ("dfsort-symbols", "ACCT-ID,1,10,CH"),
    ):
        assert copybook_layout.main([str(account_copybook), "--format", output_format]) == 0
        assert marker in capsys.readouterr().out
    assert copybook_layout.main([str(account_copybook), "--language", "cobol"]) == 0
    assert json.loads(capsys.readouterr().out)["records"][0]["name"] == "ACCOUNT-RECORD"


ALL_TYPES = (
    "01 ALL-TYPES.\n"
    "   05 T-TEXT   PIC X(4).\n"
    "   05 T-ZONED  PIC S9(3).\n"
    "   05 T-LEAD   PIC S9(3) SIGN LEADING.\n"
    "   05 T-SEP    PIC S9(3) SIGN TRAILING SEPARATE.\n"
    "   05 T-UNS    PIC 9(3).\n"
    "   05 T-PACKED PIC S9(5)V99 COMP-3.\n"
    "   05 T-BIN    PIC S9(4) COMP.\n"
    "   05 T-UBIN   PIC 9(4) COMP.\n"
    "   05 T-SCALED PIC S9(3)V9 COMP.\n"
    "   05 T-FLOAT  COMP-1.\n"
    "   05 T-NAT    PIC N(2).\n"
    "   05 T-NATNUM PIC 9(3) USAGE NATIONAL.\n"
    "   05 T-DBCS   PIC G(2).\n"
    "   05 T-PTR    POINTER.\n"
    "   05 T-EDIT   PIC ZZ9.\n"
)
ALL_TYPES_DATA = (
    ebcdic("AB  ")
    + zoned(-123, 3)
    + bytes([0xD1, 0xF2, 0xF3])
    + ebcdic("123")
    + b"\x60"
    + ebcdic("042")
    + packed(1234567, 7)
    + (-5).to_bytes(2, "big", signed=True)
    + (65535).to_bytes(2, "big")
    + (-125).to_bytes(2, "big", signed=True)
    + bytes.fromhex("41180000")
    + "Hi".encode("utf-16-be")
    + "042".encode("utf-16-be")
    + b"\x42\x81\x42\x82"
    + b"\x00\x00\x10\x00"
    + ebcdic(" 42")
)


def test_decode_record_handles_every_storage_format(tmp_path: Path) -> None:
    layout = record_decode.load_layout(write(tmp_path, "ALL.cpy", ALL_TYPES))
    values = {
        v.label: v.value for v in record_decode.decode_record(layout.records[0], ALL_TYPES_DATA)
    }
    assert values == {
        "T-TEXT": "AB",
        "T-ZONED": -123,
        "T-LEAD": -123,
        "T-SEP": -123,
        "T-UNS": 42,
        "T-PACKED": Decimal("12345.67"),
        "T-BIN": -5,
        "T-UBIN": 65535,
        "T-SCALED": Decimal("-12.5"),
        "T-FLOAT": 1.5,
        "T-NAT": "Hi",
        "T-NATNUM": 42,
        "T-DBCS": "<DBCS:42814282>",
        "T-PTR": "00001000",
        "T-EDIT": " 42",
    }


@pytest.mark.parametrize(
    ("picture", "raw", "issue"),
    [
        ("PIC S9(3)", b"\xf1\xfa\xc3", "invalid digit X'FA'"),
        ("PIC S9(3)", b"\xf1\xf2\x43", "invalid sign zone X'43'"),
        ("PIC S9(3) SIGN LEADING SEPARATE", b"\x40\xf1\xf2\xf3", "invalid separate sign X'40'"),
        ("PIC 9(3)", b"\xf1\xf2\xc3", "zone X'C' in a digit position"),
        ("PIC S9(3) COMP-3", b"\x40\x40", "spaces"),
        ("PIC S9(3) COMP-3", b"\x00\x00", "low-values"),
        ("PIC S9(3) COMP-3", b"\xff\xff", "high-values"),
        ("PIC S9(3) COMP-3", b"\x1a\x2c", "invalid packed digit"),
        ("PIC S9(3) COMP-3", b"\x12\x35", "invalid packed sign X'5'"),
        ("PIC 9(3) COMP-3", b"\x12\x3d", "unsigned field has a negative sign"),
        ("PIC S9(3) COMP-3", b"\x12", "record too short"),
    ],
)
def test_decode_reports_invalid_numeric_data(
    tmp_path: Path, picture: str, raw: bytes, issue: str
) -> None:
    layout = record_decode.load_layout(write(tmp_path, "F.cpy", f"01 R.\n 05 F {picture}.\n"))
    item = layout.records[0].children[0]
    assert record_decode.decode_value(item, raw)[1] == issue


def test_decode_other_categories() -> None:
    assert record_decode.hfp_to_float(bytes.fromhex("C2640000")) == -100.0
    assert record_decode.hfp_to_float(b"\x80\x00\x00\x00") == 0.0


def test_decode_variable_tables_selector_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout_path = write(
        tmp_path,
        "TRAN.cpy",
        "01 TRAN-HEADER.\n"
        "   05 TH-TYPE PIC XX.\n"
        "   05 TH-DATE PIC 9(8).\n"
        "01 TRAN-DETAIL.\n"
        "   05 TD-TYPE PIC XX.\n"
        "   05 TD-COUNT PIC 9.\n"
        "   05 TD-LINE OCCURS 0 TO 3 DEPENDING ON TD-COUNT.\n"
        "      10 TD-AMT PIC S9(3) COMP-3.\n"
        "   05 TD-END PIC X.\n",
    )
    header = ebcdic("HD20240131")
    detail = ebcdic("DT2") + packed(5, 3) + packed(-7, 3) + ebcdic("*")
    unknown = ebcdic("ZZ")
    data = tmp_path / "TRAN.VB"
    data.write_bytes(rdw(header) + rdw(detail) + rdw(unknown))
    layout = record_decode.load_layout(layout_path)
    record = layout.records[1]
    values = record_decode.decode_record(record, detail)
    assert [(v.label, v.value) for v in values] == [
        ("TD-TYPE", "DT"),
        ("TD-COUNT", 2),
        ("TD-AMT(1)", 5),
        ("TD-AMT(2)", -7),
        ("TD-END", "*"),
    ]
    assert record_decode.record_length(record, detail) == len(detail)
    args = [
        str(layout_path),
        str(data),
        "--type-field",
        "1:2",
        "--type",
        "HD=TRAN-HEADER",
        "--type",
        "DT=TRAN-DETAIL",
    ]
    assert record_decode.main([*args, "--hex"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["fields"] == {"TH-TYPE": "HD", "TH-DATE": 20240131}
    assert lines[1]["hex"]["TD-AMT(2)"] == "007D"
    assert lines[2]["issues"] == {"record": "no layout matches the record type"}
    assert record_decode.main([*args, "--format", "markdown", "--max-records", "2"]) == 0
    assert "| TD-AMT(2) | 6 | 2 | -7 | 007D |  |" in capsys.readouterr().out
    assert record_decode.main([*args[:2], "--record", "NOPE"]) == 1
    assert record_decode.main([*args[:2], "--type", "HD=X"]) == 1
    assert record_decode.main([*args[:2], "--type-field", "0:2"]) == 1
    assert record_decode.main([*args[:2], "--type-field", "1:2", "--type", "HD"]) == 1
    assert record_decode.main([*args[:2], "--recfm", "U"]) == 1
    assert "error:" in capsys.readouterr().err


def test_decode_fixed_records_and_elementary_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout_path = write(tmp_path, "AMT.cpy", "01 AMOUNT PIC S9(5) COMP-3.\n")
    data = tmp_path / "AMT.DATA"
    data.write_bytes(packed(12, 5) + packed(-3, 5) + b"\x00")
    assert record_decode.main([str(layout_path), str(data)]) == 0
    captured = capsys.readouterr()
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert [row["fields"] for row in rows] == [{"AMOUNT": 12}, {"AMOUNT": -3}, {"AMOUNT": None}]
    assert rows[2]["issues"] == {"AMOUNT": "record too short"}
    assert "last record is short" in captured.err


CUST_LAYOUT = (
    "01 CUST.\n"
    "   05 CUST-ID   PIC X(4).\n"
    "   05 CUST-BAL  PIC S9(5)V99 COMP-3.\n"
    "   05 CUST-CNT  PIC S9(3).\n"
    "   05 RUN-DATE  PIC X(8).\n"
)


def cust(cust_id: str, balance: int, count: int, date: str = "20240101", sign: str = "") -> bytes:
    return ebcdic(cust_id) + packed(balance, 7, sign or None) + zoned(count, 3) + ebcdic(date)


def test_compare_reports_differences_totals_and_keys(tmp_path: Path) -> None:
    layout = record_decode.load_layout(write(tmp_path, "CUST.cpy", CUST_LAYOUT))
    old = [cust("A001", 10000, 1), cust("A002", 5000, 2), cust("A003", 700, 3)]
    new = [
        cust("A001", 10000, 1, "20250101", sign="F"),
        cust("A002", 6000, 2),
        cust("A004", 700, 3),
    ]
    options = record_compare.Options(totals=["CUST-BAL"])
    result = record_compare.compare_files(old, new, layout, options)
    assert result["match"] is False
    assert result["summary"]["differing_records"] == 3
    assert result["field_differences"] == {"RUN-DATE": 1, "CUST-BAL": 1, "CUST-ID": 1}
    assert result["format_only_differences"] == {"CUST-BAL": 1}
    assert result["totals"]["CUST-BAL"] == {"old": "157.00", "new": "167.00", "equal": False}
    first = result["differences"][0]
    assert (first["record"], first["field"], first["kind"]) == (
        "record 1",
        "CUST-BAL",
        "format-only",
    )
    assert (first["old_hex"], first["new_hex"]) == ("0010000C", "0010000F")

    ignored = record_compare.Options(ignore=["RUN-DATE"], numeric_equal=True)
    result = record_compare.compare_files(old[:1], new[:1], layout, ignored)
    assert result["match"] is True

    keyed = record_compare.Options(keys=["CUST-ID"], max_diffs=1)
    result = record_compare.compare_files(old, [*new, new[1]], layout, keyed)
    assert result["only_in_old"] == ["A003"]
    assert result["only_in_new"] == ["A004"]
    assert result["summary"]["duplicate_keys"] == {"new": 1}
    assert len(result["differences"]) == 1


def test_compare_lengths_layouts_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout_path = write(tmp_path, "CUST.cpy", CUST_LAYOUT)
    golden, same, changed = (tmp_path / name for name in ("GOLDEN", "SAME", "CHANGED"))
    golden.write_bytes(rdw(cust("A001", 100, 1)) + rdw(cust("A002", 200, 2)))
    same.write_bytes(golden.read_bytes())
    changed.write_bytes(
        rdw(cust("A001", 100, 1) + b"X") + rdw(ebcdic("ZZ")) + rdw(cust("A9", 1, 1))
    )
    base = [str(layout_path), str(golden)]
    assert record_compare.main([*base, str(same), "--recfm", "V"]) == 0
    assert json.loads(capsys.readouterr().out)["match"] is True
    selector = ["--type-field", "1:1", "--type", "A=CUST"]
    assert record_compare.main([*base, str(changed), "--recfm", "V", *selector]) == 1
    result = json.loads(capsys.readouterr().out)
    kinds = [d["kind"] for d in result["differences"]]
    assert kinds == ["length", "layout"]
    assert result["summary"]["only_in_new"] == 1
    assert (
        record_compare.main([*base, str(changed), "--format", "markdown", "--total", "CUST-BAL"])
        == 1
    )
    report = capsys.readouterr().out
    assert "# Record comparison" in report
    assert "## Control totals" in report
    assert "## Invalid numeric data" in report
    assert record_compare.main([*base, str(tmp_path / "absent")]) == 2


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char) * (2 if index % 2 else 1)
        total += number - 9 if number > 9 else number
    return total % 10 == 0


MASK_LAYOUT = (
    "01 CUST.\n"
    "   05 CUST-ID      PIC X(6).\n"
    "   05 CUST-NAME    PIC X(10).\n"
    "   05 CARD-NO      PIC 9(16).\n"
    "   05 CUST-BAL     PIC S9(5)V99 COMP-3.\n"
    "   05 CUST-PIN     PIC X(4).\n"
    "   05 CUST-NAME-N  PIC N(3).\n"
    "   05 CUST-PHOTO   PIC G(1).\n"
    "   05 CUST-RATE    COMP-1.\n"
    "   05 CUST-CNT     PIC S9(3).\n"
    "   05 CUST-LIMIT   PIC S9(3) COMP.\n"
)


def mask_record(name: str, card: str, balance: int, count_bytes: bytes) -> bytes:
    return (
        ebcdic("C00001")
        + ebcdic(name.ljust(10))
        + ebcdic(card)
        + packed(balance, 7)
        + ebcdic("1234")
        + "Ann".encode("utf-16-be")
        + b"\x42\x81"
        + bytes.fromhex("41180000")
        + count_bytes
        + (250).to_bytes(2, "big", signed=True)
    )


def test_mask_suggestions_and_rules(tmp_path: Path) -> None:
    layout = record_decode.load_layout(write(tmp_path, "CUST.cpy", MASK_LAYOUT))
    suggested = {s["field"]: s["rule"] for s in record_mask.suggest(layout)}
    assert suggested == {
        "CUST-NAME": "hash",
        "CARD-NO": "luhn",
        "CUST-PIN": "blank",
        "CUST-NAME-N": "hash",
    }
    with pytest.raises(ValueError, match="FIELD=RULE"):
        record_mask.parse_rules(["CUST-NAME"])
    with pytest.raises(ValueError, match="FIELD=RULE"):
        record_mask.parse_rules(["CUST-NAME=scramble"])
    rules = record_mask.parse_rules(
        [
            "CUST-ID=fixed:XX",
            "CUST-NAME=hash",
            "CARD-NO=luhn",
            "CUST-BAL=hash",
            "CUST-PIN=blank",
            "CUST-NAME-N=hash",
            "CUST-PHOTO=blank",
            "CUST-RATE=hash",
            "CUST-CNT=hash",
            "CUST-LIMIT=fixed:9",
            "MISSING=hash",
        ]
    )
    records = [
        mask_record("JOHN SMITH", "4111111111111111", -12345, zoned(42, 3)),
        mask_record("JOHN SMITH", "4111111111111111", 0, b"\x40\x40\x40"),
    ]
    masker = record_mask.Masker(b"secret", "cp037")
    masked, summary = record_mask.mask_records(records, layout, rules, masker)
    again, _ = record_mask.mask_records(records, layout, rules, masker)
    other, _ = record_mask.mask_records(records, layout, rules, record_mask.Masker(b"x", "cp037"))
    assert masked == again
    assert masked != other
    assert [len(r) for r in masked] == [len(r) for r in records]
    first = {v.label: v.value for v in record_decode.decode_record(layout.records[0], masked[0])}
    second = {v.label: v.value for v in record_decode.decode_record(layout.records[0], masked[1])}
    assert first["CUST-ID"] == "XX"
    assert first["CUST-NAME"] == second["CUST-NAME"] != "JOHN SMITH"
    assert first["CUST-NAME"][4] == " "
    assert first["CUST-NAME"].replace(" ", "").isalpha()
    card = f"{first['CARD-NO']:016d}"
    assert card != "4111111111111111"
    assert luhn_valid(card)
    assert first["CUST-BAL"] < 0
    assert first["CUST-BAL"] != Decimal("-123.45")
    assert second["CUST-BAL"] == 0
    assert first["CUST-PIN"] == ""
    assert first["CUST-NAME-N"] != "Ann"
    assert len(first["CUST-NAME-N"]) == 3
    assert first["CUST-PHOTO"] == ""
    assert first["CUST-RATE"] == 1.5
    assert first["CUST-LIMIT"] == 9
    assert summary["unknown_fields"] == ["MISSING"]
    assert "CUST-CNT: invalid numeric data (spaces); left unchanged" in summary["skipped"]
    assert any(key.startswith("CUST-RATE: float") for key in summary["skipped"])
    zero = record_mask.parse_rules(["CUST-BAL=zero", "CUST-NAME=zero", "CUST-CNT=fixed:abc"])
    zeroed, report = record_mask.mask_records(records[:1], layout, zero, masker)
    values = {v.label: v.value for v in record_decode.decode_record(layout.records[0], zeroed[0])}
    assert (values["CUST-BAL"], values["CUST-NAME"]) == (0, "0000000000")
    assert any("is not a number" in key for key in report["skipped"])


def test_mask_hash_is_one_to_one_and_keeps_the_format(tmp_path: Path) -> None:
    masker = record_mask.Masker(b"secret", "cp037")
    numbers = [masker.number(value) for value in range(1, 3000)]
    assert len(set(numbers)) == len(numbers)
    assert all(len(str(a)) == len(str(b)) for a, b in zip(range(1, 3000), numbers, strict=True))
    assert sorted(masker.number(value) for value in range(1, 10)) == list(range(1, 10))
    codes = [
        first + second for first in string.ascii_uppercase for second in string.ascii_uppercase
    ]
    assert len({masker.text(code) for code in codes}) == len(codes)
    shaped = masker.text("Ab-12 \u00dc")
    assert shaped[0] in string.ascii_uppercase
    assert shaped[1] in string.ascii_lowercase
    assert shaped[2] == "-"
    assert shaped[3:5].isdigit()
    assert shaped[6] in string.ascii_uppercase

    layout = record_decode.load_layout(
        write(
            tmp_path,
            "CARD.cpy",
            "01 CARD-REC.\n   05 CARD-NO PIC 9(16).\n   05 CNT PIC S9(4) COMP.\n",
        )
    )
    cards = [record_mask.luhn_fix(f"411111111111{n:03d}0") for n in range(300)]
    records = [
        ebcdic(card) + (32000 + n).to_bytes(2, "big", signed=True) for n, card in enumerate(cards)
    ]
    rules = record_mask.parse_rules(["CARD-NO=luhn", "CNT=hash"])
    masked, summary = record_mask.mask_records(records, layout, rules, masker)
    assert summary["skipped"] == {}
    decoded = [
        {v.label: v.value for v in record_decode.decode_record(layout.records[0], record)}
        for record in masked
    ]
    new_cards = [f"{values['CARD-NO']:016d}" for values in decoded]
    assert len(set(new_cards)) == len(cards)
    assert all(luhn_valid(card) for card in new_cards)
    counts = [values["CNT"] for values in decoded]
    assert len(set(counts)) == len(counts)
    assert all(10_000 <= count <= 32_767 for count in counts)


def test_mask_text_changes_every_part_of_long_and_card_fields(tmp_path: Path) -> None:
    masker = record_mask.Masker(b"secret", "cp037")
    digests = [hashlib.sha256(str(seed).encode()).digest() * 4 for seed in range(20)]
    texts = ["".join(string.ascii_uppercase[byte % 26] for byte in d[:100]) for d in digests]
    unchanged = sum(a == b for text in texts for a, b in zip(text, masker.text(text), strict=True))
    assert unchanged < 20 * 100 / 26 * 1.6  # about 1 letter in 26 by chance

    layout = record_decode.load_layout(
        write(tmp_path, "CARDT.cpy", "01 REC.\n   05 CARD PIC X(19).\n")
    )
    cards = [record_mask.luhn_fix(f"411111111111{n:03d}0") for n in range(200)]
    records = [ebcdic(f"{c[:4]}-{c[4:8]}-{c[8:12]}-{c[12:]}") for c in cards]
    masked, _ = record_mask.mask_records(
        records, layout, record_mask.parse_rules(["CARD=luhn"]), masker
    )
    texts = [zos_encoding.decode(record, "cp037") for record in masked]
    assert len(set(texts)) == len(cards)
    assert all(text[4] == text[9] == text[14] == "-" for text in texts)
    assert all(luhn_valid(text.replace("-", "")) for text in texts)


def test_mask_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    layout_path = write(tmp_path, "CUST.cpy", MASK_LAYOUT)
    data = tmp_path / "CUST.VB"
    data.write_bytes(rdw(mask_record("JANE DOE", "5500000000000004", 99, zoned(1, 3))))
    output = tmp_path / "MASKED.VB"
    base = [str(layout_path), str(data)]
    assert record_mask.main([*base, "--suggest"]) == 0
    assert '"CARD-NO"' in capsys.readouterr().out
    assert record_mask.main(base) == 1
    assert record_mask.main([*base, "--rule", "CUST-NAME=hash", "--output", str(data)]) == 1
    assert record_mask.main([*base, "--rule", "CUST-NAME=hash", "--secret-env", "NO_SUCH_VAR"]) == 1
    assert "NO_SUCH_VAR is not set" in capsys.readouterr().err
    monkeypatch.setenv("MASK_TEST_SECRET", "s3cret")
    args = [*base, "--rule", "CUST-NAME=hash", "--secret-env", "MASK_TEST_SECRET", "--recfm", "V"]
    assert record_mask.main([*args, "--output", str(output)]) == 0
    assert '"masked": {"CUST-NAME": 1}' in capsys.readouterr().err
    masked = output.read_bytes()
    assert len(masked) == len(data.read_bytes())
    assert zos_encoding.split_records(masked, recfm="V").records[0][:6] == ebcdic("C00001")


def test_mask_writes_binary_to_standard_output(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    layout_path = write(tmp_path, "CUST.cpy", MASK_LAYOUT)
    data = tmp_path / "CUST.DATA"
    data.write_bytes(mask_record("JANE DOE", "5500000000000004", 99, zoned(1, 3)))
    assert record_mask.main([str(layout_path), str(data), "--rule", "CUST-NAME=keep"]) == 0
    captured = capsysbinary.readouterr()
    assert captured.out == data.read_bytes()
    assert b"differ on every run" in captured.err
