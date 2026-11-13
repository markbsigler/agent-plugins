"""Tests for code-modernization-plugin: the mainframe-batch-flow skill's batch_flow.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import batch_flow
import pytest
import zos_encoding


def write(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def steps_of(flow: dict[str, Any], job: str) -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in flow["jobs"][job]["steps"]}


def dd(step: dict[str, Any], name: str, concat: int = 0) -> dict[str, Any]:
    return next(d for d in step["dds"] if d["ddname"] == name and d["concat"] == concat)


def test_parse_jcl_joins_continuations_and_keeps_instream_data() -> None:
    prefix = "//STEP1    EXEC PGM=MYPGM,PARM='ABC"
    filler = "X" * (71 - len(prefix))
    text = "\n".join(
        [
            "//PARSE    JOB (ACCT),'O''BRIEN',CLASS=A      COMMENT",
            "/*JOBPARM LINES=99",
            "",
            prefix + filler,
            "//" + " " * 13 + "DEF',REGION=0M",
            f"{'//STEP2    EXEC PGM=OTHER':<72}00010000",
            "//DD1      DD DSN=A.B.C,              FIRST LINE COMMENT",
            "//* A COMMENT BETWEEN CONTINUATION LINES",
            "//            DISP=SHR",
            "//SYSIN    DD *",
            "  DATA LINE",
            "//DD3      DD DATA,DLM=$$",
            "//NOT A STATEMENT",
            "$$",
            "//DD4      DD *",
            " CARD",
            "/*",
            "// IF (STEP1.RC = 0 &",
            "//     STEP2.RC <= 4 &",
            "//     STEP3.RC < 8) THEN",
            "//         DISP=SHR",
            "// ENDIF",
            "//STEP3    EXEC PGM=X",
            "DATA WITHOUT A DD STATEMENT",
            "//Q        DD DSN='ABC",
            "//R        DD DSN=Z,",
            "//S        DD DUMMY",
            "// IF RC = 0",
            "//T        DD DUMMY",
            "//",
            "//DATA1    DD *,",
            " CARD AFTER A COMMA",
            "//LAST     DD DSN=END,",
        ]
    )
    statements, warnings = batch_flow.parse_jcl(text)
    assert [(s.name, s.operation, s.operands) for s in statements] == [
        ("PARSE", "JOB", "(ACCT),'O''BRIEN',CLASS=A"),
        ("STEP1", "EXEC", f"PGM=MYPGM,PARM='ABC{filler}DEF',REGION=0M"),
        ("STEP2", "EXEC", "PGM=OTHER"),
        ("DD1", "DD", "DSN=A.B.C,DISP=SHR"),
        ("SYSIN", "DD", "*"),
        ("DD3", "DD", "DATA,DLM=$$"),
        ("DD4", "DD", "*"),
        ("", "IF", "(STEP1.RC = 0 & STEP2.RC <= 4 & STEP3.RC < 8)"),
        ("", "DISP=SHR", ""),
        ("", "ENDIF", ""),
        ("STEP3", "EXEC", "PGM=X"),
        ("SYSIN", "DD", "*"),
        ("Q", "DD", "DSN='ABC"),
        ("R", "DD", "DSN=Z"),
        ("S", "DD", "DUMMY"),
        ("", "IF", "RC = 0"),
        ("T", "DD", "DUMMY"),
        ("", "NULL", ""),
        ("DATA1", "DD", "*"),
        ("LAST", "DD", "DSN=END"),
    ]
    assert {s.line: s.instream for s in statements if s.instream is not None} == {
        10: ["  DATA LINE"],
        12: ["//NOT A STATEMENT"],
        15: [" CARD"],
        24: ["DATA WITHOUT A DD STATEMENT"],
        31: [" CARD AFTER A COMMA"],
    }
    assert warnings == [
        "line 21: unrecognized statement 'DISP=SHR'",
        "line 24: data without a DD statement read as //SYSIN DD *",
        "line 25: apostrophe string is not closed",
        "line 26: statement ends with a comma but is not continued",
        "line 28: IF statement has no THEN",
        "line 31: statement ends with a comma but is not continued",
        "line 33: statement ends with a comma but is not continued",
    ]


def write_payroll(root: Path) -> tuple[Path, list[Path]]:
    """Write a payroll job with cataloged, nested, recursive, and in-stream procedures."""
    jcl, site, procs = root / "jcl", root / "site", root / "proclib"
    write(
        procs / "PAYPROC.prc",
        "//PAYPROC  PROC ENV=PROD,PGMNAME=PAYCALC",
        "//CALC     EXEC PGM=&PGMNAME,PARM='OLD',COND=(0,NE)",
        "//STEPLIB  DD DSN=&HLQ..LOADLIB,DISP=SHR",
        "//INPUT    DD DSN=&HLQ..PAY.MASTER,DISP=SHR",
        "//OUTPUT   DD DSN=&HLQ..PAY.&ENV..EXTRACT(+1),",
        "//            DISP=(NEW,CATLG,DELETE),",
        "//            DCB=(RECFM=FB,LRECL=200)",
        "//LIBS     DD DSN=&HLQ..LIB1,DISP=SHR",
        "//         DD DSN=&HLQ..LIB2,DISP=SHR",
        "//REPORT   EXEC PGM=PAYRPT,PARM='DETAIL'",
        "//IN       DD DSN=*.CALC.OUTPUT,DISP=SHR",
        "//RPT      DD SYSOUT=(A,,STD),DEST=RMT1",
        "//         PEND",
    )
    write(procs / "INNERP.prc", "//INSTEP   EXEC PGM=INNERPGM,PARM='&LEVEL'")
    write(site / "INNERP", "//INSTEP   EXEC PGM=SITEPGM,PARM='&LEVEL'")
    write(site / "PAYPROC.txt", "A CONTROL MEMBER THAT SHARES THE PROCEDURE NAME")
    write(procs / "SELFCALL.prc", "//SELFCALL    PROC", "//AGAIN    EXEC SELFCALL")
    write(jcl / "OUTER.prc", "//OUTER    PROC", "//INNER    EXEC INNERP,LEVEL=&LVL")
    write(jcl / "STDSETS", "//* STANDARD SYMBOLS", "// SET REGION=EAST")
    write(
        jcl / "PAYD010.jcl",
        "//PAYD010  JOB (ACCT),'PAYROLL',CLASS=A,MSGCLASS=X,NOTIFY=&SYSUID,",
        "//             PASSWORD=SECRET",
        "//LOCAL    PROC MSG=HELLO",
        "//LSTEP1   EXEC PGM=LOCAL1,PARM='&MSG'",
        "//LSTEP2   EXEC PGM=LOCAL2,PARM='KEEP'",
        "//OUT      DD DSN=&DEPT..REPORT,DISP=SHR",
        "//         PEND",
        "//         JCLLIB ORDER=(PROD.PROCLIB,'SYS1.PROCLIB')",
        "//         SET HLQ=PROD",
        "//         INCLUDE MEMBER=STDSETS",
        "//STEP010  EXEC PAYPROC,ENV=TEST,PARM.CALC='NEW,RUN',",
        "//             COND.REPORT=(4,LT)",
        "//CALC.INPUT DD DSN=&HLQ..PAY.MASTER.&REGION",
        "//CALC.EXTRA DD DSN=&HLQ..PAY.EXTRA,DISP=SHR",
        "//CALC.LIBS DD",
        "//         DD DSN=&HLQ..LIB2.NEW,DISP=SHR",
        "//         DD DSN=&HLQ..LIB3,DISP=SHR",
        "//NOSTEP.X DD DUMMY",
        "//STEP020  EXEC OUTER,LVL=&SYSUID",
        "//STEP030  EXEC MISSING",
        "//STEP040  EXEC LOCAL,PARM=ALL",
        "//         INCLUDE MEMBER=STDSETS",
        "//STEP050  EXEC SELFCALL",
        "//         INCLUDE MEMBER=NOSUCH",
        "//         INCLUDE",
    )
    return jcl, [site, procs]


def test_procedures_symbols_includes_and_overrides(tmp_path: Path) -> None:
    jcl, proclibs = write_payroll(tmp_path)
    flow = batch_flow.build_flow(
        [jcl], proclibs=proclibs, symbols={"SYSUID": "BATCH1", "&REGION": "WEST"}
    )
    job = flow["jobs"]["PAYD010"]
    steps = steps_of(flow, "PAYD010")
    assert list(steps) == [
        "STEP010.CALC",
        "STEP010.REPORT",
        "STEP020.INNER.INSTEP",
        "STEP030",
        "STEP040.LSTEP1",
        "STEP040.LSTEP2",
        "STEP050.AGAIN",
    ]

    calc = steps["STEP010.CALC"]
    assert (calc["proc"], calc["procstep"], calc["program"], calc["parm"]) == (
        "PAYPROC",
        "CALC",
        "PAYCALC",
        "NEW,RUN",
    )
    assert calc["cond"]["raw"] == "(0,NE)"
    assert [(d["ddname"], d["concat"], d.get("dsn"), d.get("override")) for d in calc["dds"]] == [
        ("STEPLIB", 0, "PROD.LOADLIB", None),
        ("INPUT", 0, "PROD.PAY.MASTER.WEST", "overridden"),
        ("OUTPUT", 0, "PROD.PAY.TEST.EXTRACT(+1)", None),
        ("LIBS", 0, "PROD.LIB1", None),
        ("LIBS", 1, "PROD.LIB2.NEW", "overridden"),
        ("LIBS", 2, "PROD.LIB3", "added"),
        ("EXTRA", 0, "PROD.PAY.EXTRA", "added"),
    ]
    assert dd(calc, "INPUT")["disp"]["status"] == "SHR"
    output = dd(calc, "OUTPUT")
    assert (output["dataset"], output["generation"]) == ("PROD.PAY.TEST.EXTRACT", "+1")
    assert output["dcb"] == {"RECFM": "FB", "LRECL": "200"}
    assert output["disp"] == {
        "raw": "(NEW,CATLG,DELETE)",
        "status": "NEW",
        "normal": "CATLG",
        "abnormal": "DELETE",
    }
    assert dd(calc, "STEPLIB")["library"] is True

    report = steps["STEP010.REPORT"]
    assert (report["parm"], report["cond"]["raw"]) == ("DETAIL", "(4,LT)")
    assert dd(report, "IN")["backref"] == "*.CALC.OUTPUT"
    assert dd(report, "IN")["dsn"] == "PROD.PAY.TEST.EXTRACT(+1)"
    assert dd(report, "RPT")["sysout"] == {"class": "A", "form": "STD"}

    inner = steps["STEP020.INNER.INSTEP"]
    assert (inner["proc"], inner["program"], inner["parm"]) == ("INNERP", "SITEPGM", "BATCH1")
    assert steps["STEP040.LSTEP1"]["parm"] == "ALL"
    assert steps["STEP040.LSTEP2"]["parm"] is None
    missing = steps["STEP030"]
    assert (missing["proc"], missing["program"]) == ("MISSING", None)
    assert missing["flags"] == ["procedure MISSING not found"]
    assert steps["STEP050.AGAIN"]["flags"] == ["procedure SELFCALL calls itself"]

    assert job["jcllib"] == ["PROD.PROCLIB", "SYS1.PROCLIB"]
    assert job["procs"] == ["PAYPROC", "OUTER", "INNERP", "LOCAL", "SELFCALL"]
    assert job["includes"] == ["STDSETS"]
    assert job["parameters"] == {"CLASS": "A", "MSGCLASS": "X", "NOTIFY": "BATCH1"}
    assert job["symbols"] == {
        "DEPT": [],
        "ENV": ["TEST"],
        "HLQ": ["PROD"],
        "LEVEL": ["BATCH1"],
        "LVL": ["BATCH1"],
        "MSG": ["HELLO"],
        "PGMNAME": ["PAYCALC"],
        "REGION": ["WEST"],
        "SYSUID": ["BATCH1"],
    }
    assert job["unresolved_symbols"] == ["DEPT"]
    assert flow["unresolved"] == {"procs": ["MISSING"], "includes": ["NOSUCH"], "symbols": ["DEPT"]}
    assert flow["warnings"] == [
        "PAYD010 STEP010: override NOSTEP.X matches no step in PAYPROC",
        "PAYD010 STEP030: procedure MISSING not found",
        "PAYD010: INCLUDE member NOSUCH not found",
        "PAYD010: INCLUDE statement names no member",
        "PAYD010 STEP050.AGAIN: procedure SELFCALL calls itself",
    ]
    assert "SECRET" not in json.dumps(flow)
    report = batch_flow.flow_to_markdown(flow)
    for line in (
        "| PAYD010 | STEP030 | MISSING | (not found) |  | procedure MISSING not found |",
        "- **Procedures:** MISSING",
        "- **INCLUDE members:** NOSUCH",
        "- **Symbols:** &DEPT",
        "| PAYD010 | STEP010.REPORT | RPT | A | RMT1 |",
    ):
        assert line in report
    assert "SYSOUT DDs that carry messages" not in report


def test_dd_overrides_follow_the_jcl_merge_rules(tmp_path: Path) -> None:
    jcl = write(
        tmp_path / "MERGEJOB.jcl",
        "//MERGEJOB JOB (ACCT)",
        "//MERGEP   PROC",
        "//MSTEP    EXEC PGM=MPGM",
        "//A        DD DSN=PROD.A,DISP=SHR,UNIT=SYSDA",
        "//B        DD DSN=PROD.B,DISP=(NEW,CATLG),",
        "//            DCB=(RECFM=FB,LRECL=80,BLKSIZE=0)",
        "//C        DD SYSOUT=A",
        "//D        DD DSN=PROD.D,DISP=SHR",
        "//E        DD DUMMY",
        "//F        DD *",
        "  ORIGINAL CARD",
        "//G        DD DSN=PROD.G,DISP=SHR",
        "//H        DD DSN=PROD.H,DISP=SHR",
        "//I        DD *",
        "  KEEP THIS CARD",
        "//J        DD DSN=PROD.J,DISP=OLD,DCB=(PROD.MODEL,RECFM=FB),LRECL=100",
        "//MSTEP2   EXEC PGM=MPGM2,PARM='KEEP'",
        "//         PEND",
        "//CALL     EXEC MERGEP,PARM.MSTEP2=NEW,COND=(4,LT),REGION=0M",
        "//MSTEP.A  DD UNIT=",
        "//MSTEP.B  DD DCB=(LRECL=120)",
        "//MSTEP.C  DD DSN=PROD.C.FILE,DISP=(NEW,CATLG)",
        "//MSTEP.D  DD SYSOUT=B",
        "//MSTEP.E  DD DSN=PROD.E,DISP=SHR",
        "//MSTEP.F  DD PATH='/u/f.txt'",
        "//MSTEP.H  DD DUMMY",
        "//MSTEP.I  DD DCB=(LRECL=80)",
        "//MSTEP.G  DD *",
        "  NEW CARD",
        "//CALL2    EXEC MERGEP",
        "//LATER    EXEC PGM=LATER",
        "//R        DD DSN=*.CALL.MSTEP.NODD,DISP=SHR",
    )
    flow = batch_flow.build_flow([jcl])
    steps = steps_of(flow, "MERGEJOB")
    first, second = steps["CALL.MSTEP"], steps["CALL.MSTEP2"]
    assert "unit" not in dd(first, "A")
    assert dd(first, "B")["dcb"] == {"RECFM": "FB", "LRECL": "120", "BLKSIZE": "0"}
    assert (dd(first, "C")["dsn"], "sysout" in dd(first, "C")) == ("PROD.C.FILE", False)
    assert dd(first, "D") == {
        "ddname": "D",
        "concat": 0,
        "override": "overridden",
        "sysout": {"class": "B"},
    }
    assert ("dummy" in dd(first, "E"), dd(first, "E")["dsn"]) == (False, "PROD.E")
    assert (dd(first, "F")["path"], "instream" in dd(first, "F")) == ("/u/f.txt", False)
    assert ("dsn" in dd(first, "G"), dd(first, "G")["instream"]) == (False, ["  NEW CARD"])
    assert [step["cond"]["raw"] for step in (first, second)] == ["(4,LT)", "(4,LT)"]
    assert (first["parm"], second["parm"]) == (None, "NEW")
    assert (dd(first, "H")["dummy"], dd(first, "H")["dsn"]) == (True, "PROD.H")
    assert (dd(first, "I")["instream"], dd(first, "I")["dcb"]) == (
        ["  KEEP THIS CARD"],
        {"LRECL": "80"},
    )
    assert dd(first, "J")["dcb"] == {"MODEL": "PROD.MODEL", "RECFM": "FB", "LRECL": "100"}
    assert steps["CALL2.MSTEP2"]["parm"] == "KEEP"
    assert flow["jobs"]["MERGEJOB"]["procs"] == ["MERGEP"]
    assert flow["warnings"] == ["MERGEJOB LATER: *.CALL.MSTEP.NODD does not resolve"]


def test_conditions_record_if_context_and_explain_cond(tmp_path: Path) -> None:
    jcl = write(
        tmp_path / "CONDJOB.jcl",
        "//CONDJOB  JOB (ACCT),'COND',COND=((16,GE),(8,LT))",
        "//IFPROC   PROC",
        "// ENDIF",
        "// IF (RC = 0) THEN",
        "//PSTEP    EXEC PGM=PPGM",
        "//         PEND",
        "//STEP1    EXEC PGM=PGM1",
        "//STEP2    EXEC PGM=PGM2,COND=(4,LT)",
        "// IF (STEP1.RC = 0) THEN",
        "//STEP3    EXEC PGM=PGM3,COND=((8,LE),(4,EQ,STEP1))",
        "//STEPP    EXEC IFPROC",
        "// IF (STEP2.RC > 0) THEN",
        "//STEP4    EXEC PGM=PGM4,COND=EVEN",
        "// ENDIF",
        "// ELSE",
        "//STEP5    EXEC PGM=PGM5,COND=((4,LT,STEP1),ONLY)",
        "// ENDIF",
        "// ELSE",
        "// ENDIF",
        "//STEP6    EXEC PGM=PGM6,COND=(4,XX)",
        "// IF RC = 0 THEN",
        "//STEP7    EXEC PGM=PGM7",
    )
    flow = batch_flow.build_flow([jcl])
    steps = steps_of(flow, "CONDJOB")
    assert {name: step["if_context"] for name, step in steps.items()} == {
        "STEP1": [],
        "STEP2": [],
        "STEP3": ["IF (STEP1.RC = 0) THEN"],
        "STEPP.PSTEP": ["IF (STEP1.RC = 0) THEN", "IF (RC = 0) THEN"],
        "STEP4": ["IF (STEP1.RC = 0) THEN", "IF (STEP2.RC > 0) THEN"],
        "STEP5": ["IF (STEP1.RC = 0) ELSE"],
        "STEP6": [],
        "STEP7": ["IF RC = 0 THEN"],
    }
    explanations = {
        name: step["cond"]["explanation"] for name, step in steps.items() if step["cond"]
    }
    assert explanations == {
        "STEP2": "Bypass this step if 4 is less than the return code of any earlier step "
        "(any RC > 4).",
        "STEP3": "Bypass this step if any of these is true: 8 is less than or equal to the "
        "return code of any earlier step (any RC >= 8); 4 is equal to the return code of "
        "STEP1 (STEP1 RC = 4).",
        "STEP4": "Run this step even if an earlier step abended.",
        "STEP5": "Run this step only if an earlier step abended; bypass it if 4 is less than "
        "the return code of STEP1 (STEP1 RC > 4).",
        "STEP6": batch_flow.UNRECOGNIZED_COND,
    }
    assert flow["jobs"]["CONDJOB"]["cond"] == {
        "raw": "((16,GE),(8,LT))",
        "explanation": "Bypass all remaining steps if any of these is true: 16 is greater than "
        "or equal to the return code of any step (any RC <= 16); 8 is less than the return "
        "code of any step (any RC > 8).",
    }
    assert flow["warnings"] == [
        "CONDJOB STEPP: ENDIF at line 3 has no IF",
        "CONDJOB STEPP: procedure IFPROC leaves an IF without ENDIF",
        "CONDJOB: ELSE at line 18 has no IF",
        "CONDJOB: ENDIF at line 19 has no IF",
        "CONDJOB: IF statement without ENDIF",
    ]
    report = batch_flow.flow_to_markdown(flow)
    assert "| CONDJOB | (job) |  |  | COND=((16,GE),(8,LT)): Bypass all remaining" in report
    assert "| CONDJOB | STEP2 |  | PGM2 | COND=(4,LT): Bypass this step if 4 is" in report
    assert "## Data set lineage" not in report


@pytest.mark.parametrize(
    ("cond", "job", "explanation"),
    [
        (
            "(0,NE)",
            False,
            (
                "Bypass this step if 0 is not equal to the return code of any earlier "
                "step (any RC != 0)."
            ),
        ),
        (
            "(4,GT)",
            True,
            (
                "Bypass all remaining steps if 4 is greater than the return code of "
                "any step (any RC < 4)."
            ),
        ),
        (
            "(4,LT),(8,GT)",
            False,
            (
                "Bypass this step if any of these is true: 4 is less than the return code of "
                "any earlier step (any RC > 4); 8 is greater than the return code of any earlier "
                "step (any RC < 8)."
            ),
        ),
        ("(4,LT,STEP1)", True, batch_flow.UNRECOGNIZED_COND),
        ("((4,LT),BOGUS)", False, batch_flow.UNRECOGNIZED_COND),
        ("EVEN", True, batch_flow.UNRECOGNIZED_COND),
        ("()", False, batch_flow.UNRECOGNIZED_COND),
        ("()", True, batch_flow.UNRECOGNIZED_COND),
    ],
)
def test_explain_cond_edge_cases(cond: str, job: bool, explanation: str) -> None:
    assert batch_flow.explain_cond(cond, job=job) == explanation


CUSTOMER_JOBS = {
    "EXTRACT.jcl": (
        "//EXTRACT  JOB (ACCT),'EXTRACT'",
        "//STEP1    EXEC PGM=EXTPGM",
        "//IN       DD DSN=PROD.CUST.MASTER,DISP=SHR",
        "//LOOKUP   DD DSN=PROD.RATES,DISP=OLD",
        "//OUT      DD DSN=PROD.CUST.DAILY(+1),DISP=(NEW,CATLG,DELETE)",
        "//WORK     DD DSN=&&WORK,DISP=(,PASS),UNIT=SYSDA,SPACE=(TRK,1)",
        "//SCRATCH  DD DSN=PROD.SCRATCH,DISP=(NEW,DELETE)",
        "//STEP2    EXEC PGM=EXTPGM2",
        "//IN       DD DSN=*.STEP1.WORK,DISP=(OLD,DELETE)",
        "//SAME     DD DSN=*.IN,DISP=SHR",
        "//BAD      DD DSN=*.NOPE.DD,DISP=SHR",
        "//SHARED   DD DSN=PROD.SHARED(MEMB),DISP=SHR",
        "//CTL      DD DSN=PROD.CNTL(EXTRACT),DISP=SHR",
        "//LOG      DD PATH='/u/logs/extract.log',PATHOPTS=(OWRONLY,OCREAT)",
        "//CFG      DD PATH='/u/cfg/extract.cfg'",
        "//NULL     DD DSN=NULLFILE",
        "//OPT      DD DUMMY,DSN=PROD.OPTIONAL",
    ),
    "LOADJCL.jcl": (
        "//LOAD     JOB (ACCT),'LOAD'",
        "//STEP1    EXEC PGM=LOADPGM",
        "//IN       DD DSN=PROD.CUST.DAILY(0),DISP=SHR",
        "//ABS      DD DSN=PROD.CUST.DAILY.G0005V00,DISP=SHR",
        "//OUT      DD DSN=PROD.CUST.HISTORY,DISP=MOD",
        "//CTL      DD DSN=PROD.CNTL(LOAD),DISP=SHR",
        "//COPY     EXEC PGM=IEBGENER",
        "//SYSPRINT DD SYSOUT=*",
        "//SYSUT1   DD DSN=PROD.CUST.MASTER,DISP=SHR",
        "//SYSUT2   DD DSN=PROD.SHARED(MEMA),DISP=SHR",
        "//SYSIN    DD DUMMY",
        "//CLEAN    EXEC PGM=IEFBR14",
        "//OLD      DD DSN=PROD.CUST.OLD,DISP=(MOD,DELETE,DELETE)",
        "//NEW      DD DSN=PROD.CUST.NEW,DISP=(NEW,CATLG)",
    ),
    "AUDIT.jcl": (
        "//AUDIT    JOB (ACCT),'AUDIT',MSGCLASS=X",
        "//STEP1    EXEC PGM=AUDPGM",
        "//IN       DD DSN=PROD.SHARED(MEMA),DISP=SHR",
        "//DAILY    DD DSN=PROD.CUST.DAILY(0),DISP=SHR",
        "//REPORT   DD SYSOUT=*",
        "// IF (STEP1.RC = 0 | STEP1.RC = 4) THEN",
        "//STEP2    EXEC PGM=AUDPGM2",
        "// ENDIF",
    ),
}


@pytest.fixture
def customer(tmp_path: Path) -> Path:
    """Write three jobs that share data sets; the LOAD job lives in member LOADJCL."""
    jcl = tmp_path / "jcl"
    for name, lines in CUSTOMER_JOBS.items():
        write(jcl / name, *lines)
    return jcl


def test_lineage_across_jobs(customer: Path) -> None:
    flow = batch_flow.build_flow([customer])
    datasets = flow["datasets"]
    summary = {
        name: (info["producers"], info["consumers"], info["deleted_by"])
        for name, info in datasets.items()
    }
    assert summary == {
        "/u/cfg/extract.cfg": ([], ["EXTRACT"], []),
        "/u/logs/extract.log": (["EXTRACT"], [], []),
        "PROD.CNTL": ([], ["EXTRACT", "LOAD"], []),
        "PROD.CUST.DAILY": (["EXTRACT"], ["AUDIT", "LOAD"], []),
        "PROD.CUST.HISTORY": (["LOAD"], [], []),
        "PROD.CUST.MASTER": ([], ["EXTRACT", "LOAD"], []),
        "PROD.CUST.NEW": (["LOAD"], [], []),
        "PROD.CUST.OLD": ([], [], ["LOAD"]),
        "PROD.RATES": ([], ["EXTRACT"], []),
        "PROD.SCRATCH": (["EXTRACT"], [], ["EXTRACT"]),
        "PROD.SHARED": (["LOAD"], ["AUDIT", "EXTRACT"], []),
    }
    assert datasets["PROD.CUST.DAILY"]["generations"] == ["+1", "0", "G0005V00"]
    assert datasets["PROD.SHARED"]["members"] == ["MEMA", "MEMB"]
    assert datasets["PROD.RATES"]["accesses"] == [
        {"job": "EXTRACT", "step": "STEP1", "action": "read", "dd": "LOOKUP", "disp": "OLD"}
    ]
    assert flow["external_inputs"] == [
        "/u/cfg/extract.cfg",
        "PROD.CNTL",
        "PROD.CUST.MASTER",
        "PROD.RATES",
    ]
    assert flow["final_outputs"] == ["/u/logs/extract.log", "PROD.CUST.HISTORY", "PROD.CUST.NEW"]
    assert flow["job_dependencies"] == [
        {
            "from": "EXTRACT",
            "to": "AUDIT",
            "type": "data",
            "datasets": ["PROD.CUST.DAILY"],
            "scheduled": None,
        },
        {
            "from": "EXTRACT",
            "to": "LOAD",
            "type": "data",
            "datasets": ["PROD.CUST.DAILY"],
            "scheduled": None,
        },
        {
            "from": "LOAD",
            "to": "AUDIT",
            "type": "data",
            "datasets": ["PROD.SHARED"],
            "scheduled": None,
        },
    ]
    assert {"from": "LOAD", "to": "PROD.CUST.OLD", "type": "deletes"} in flow["edges"]
    assert {"from": "PROD.CUST.DAILY", "to": "LOAD", "type": "reads"} in flow["edges"]

    extract = flow["jobs"]["EXTRACT"]
    assert extract["temporary_datasets"] == {
        "&&WORK": {"written_by": ["STEP1"], "read_by": ["STEP2"], "deleted_by": ["STEP2"]}
    }
    step2 = steps_of(flow, "EXTRACT")["STEP2"]
    assert (dd(step2, "IN")["dsn"], dd(step2, "SAME")["dsn"]) == ("&&WORK", "&&WORK")
    assert dd(step2, "IN")["temporary"] is True
    assert dd(steps_of(flow, "EXTRACT")["STEP1"], "WORK")["disp"]["abnormal"] == "DELETE"
    assert dd(step2, "NULL")["dummy"] is True
    assert flow["warnings"] == ["EXTRACT STEP2: *.NOPE.DD does not resolve"]
    assert [(r["job"], r["dd"], r["kind"], r.get("msgclass")) for r in flow["reports"]] == [
        ("AUDIT", "REPORT", "report", "X"),
        ("LOAD", "SYSPRINT", "messages", None),
    ]


UTILITY_JOB = (
    "//UTIL     JOB (ACCT),'UTILITIES',MSGCLASS=H",
    "//RPTOUT   OUTPUT CLASS=R,DEST=PRT01",
    "//DEFINE   EXEC PGM=IDCAMS",
    "//SYSPRINT DD SYSOUT=*",
    "//INPUT    DD DSN=PROD.SEQ.IN,DISP=SHR",
    "//BACKUP   DD DSN=PROD.CUST.BACKUP(+1),DISP=(NEW,CATLG)",
    "//SYSIN    DD *",
    "  /* REBUILD THE KSDS */",
    "  /* A COMMENT THAT",
    "     CONTINUES */",
    "  DELETE (PROD.CUST.KSDS, PROD.CUST.AIX) CLUSTER PURGE",
    "  IF LASTCC <= 8 THEN SET MAXCC = 0",
    "  DEFINE CLUSTER (NAME(PROD.CUST.KSDS) -",
    "         INDEXED KEYS(10 0) RECORDSIZE(200 200)) -",
    "         DATA (NAME(PROD.CUST.KSDS.DATA))",
    "  DEF GDG (NAME(PROD.CUST.BACKUP) LIMIT(7) SCRATCH)",
    "  DEFINE ALIAS (NAME(CUST) RELATE(UCAT.PROD))",
    "  REPRO INFILE(INPUT) OUTDATASET(PROD.CUST.KSDS)",
    "  REPRO INDATASET(PROD.CUST.KSDS) OFILE(BACKUP)",
    "  LISTCAT ENTRIES(PROD.CUST.KSDS) ALL",
    "  LISTCAT ALL",
    "  DEFINE PAGESPACE",
    "  IF MAXCC > 4 THEN DO",
    "  DELETE PROD.CUST.FLAG",
    "  END",
    "/*",
    "//NOCMDS   EXEC PGM=IDCAMS",
    "//SYSIN    DD DUMMY",
    "//MERGE    EXEC PGM=SORT",
    "//SYSOUT   DD SYSOUT=*",
    "//SORTIN01 DD DSN=PROD.SALES.EAST,DISP=SHR",
    "//SORTIN02 DD DSN=PROD.SALES.WEST,DISP=SHR",
    "//SORTOUT  DD DSN=PROD.SALES.ALL,DISP=(NEW,CATLG)",
    "//BIGONES  DD DSN=PROD.SALES.BIG,DISP=(NEW,CATLG)",
    "//SORTOF1  DD DSN=PROD.SALES.ONE,DISP=OLD",
    "//SYSIN    DD *",
    "* MERGE THE REGIONS",
    "  MERGE FIELDS=(1,10,CH,A)",
    "  OUTFIL FNAMES=BIGONES,INCLUDE=(20,5,ZD,GT,+1000),",
    "         OUTREC=(1,80)",
    "  OUTFIL FILES=1",
    "  OUTFIL SAVE",
    "  SUM FIELDS=NONE",
    "/*",
    "//JOIN     EXEC PGM=SORT",
    "//SORTJNF1 DD DSN=PROD.JOIN.LEFT,DISP=SHR",
    "//RIGHT    DD DSN=PROD.JOIN.RIGHT,DISP=SHR",
    "//SORTOUT  DD DSN=PROD.JOIN.OUT,DISP=(NEW,CATLG)",
    "//SYSIN    DD *",
    "  JOINKEYS FILE=F1,FIELDS=(1,10,A)",
    "  JOINKEYS F2=RIGHT,FIELDS=(1,10,A)",
    "LABEL1   REFORMAT FIELDS=(F1:1,80,F2:11,20)",
    "  SORT FIELDS=COPY",
    "/*",
    "//TOOL     EXEC PGM=ICETOOL",
    "//TOOLMSG  DD SYSOUT=*",
    "//IN       DD DSN=PROD.SALES.ALL,DISP=SHR",
    "//OUT1     DD DSN=PROD.SALES.TOP,DISP=(NEW,CATLG)",
    "//LISTING  DD SYSOUT=A",
    "//TOOLIN   DD *",
    "* TOP CUSTOMERS",
    "  SELECT FROM(IN) TO(OUT1) ON(1,10,CH) FIRST USING(CTL1)",
    "  COUNT FROM(IN)",
    "  DISPLAY FROM(IN) LIST(LISTING) -",
    "          ON(1,10,CH)",
    "  MISSING OPERATOR",
    "/*",
    "//CTL1CNTL DD *",
    "  OMIT COND=(30,1,CH,EQ,C'X')",
    "/*",
    "//SORTCTL  EXEC PGM=SORT",
    "//SORTIN   DD DSN=PROD.SALES.ALL,DISP=SHR",
    "//SORTOUT  DD DSN=PROD.SALES.SORTED,DISP=(NEW,CATLG)",
    "//SYSIN    DD DSN=PROD.CNTL(SORTCARD),DISP=SHR",
    "//SORTMISS EXEC PGM=SORT",
    "//SYSIN    DD DSN=PROD.CNTL(NOCARD),DISP=SHR",
    "//SORTPATH EXEC PGM=SORT",
    "//SYSIN    DD PATH='/u/cards/sort.txt'",
    "//GENER    EXEC PGM=IEBGENER",
    "//SYSUT1   DD DSN=PROD.SALES.TOP,DISP=SHR",
    "//SYSUT2   DD DSN=PROD.SALES.COPY,DISP=OLD",
    "//SYSIN    DD *",
    "  GENERATE MAXFLDS=1",
    "  RECORD FIELD=(80)",
    "/*",
    "//COPYPDS  EXEC PGM=IEBCOPY",
    "//IN1      DD DSN=PROD.SRC.LIB,DISP=SHR",
    "//IN2      DD DSN=PROD.FIX.LIB,DISP=SHR",
    "//OUT      DD DSN=PROD.MERGED.LIB,DISP=OLD",
    "//SYSIN    DD *",
    "  COPY OUTDD=OUT,INDD=(IN1,(IN2,R))",
    "  SELECT MEMBER=(PGMA,PGMB)",
    "/*",
    "//COPYDEF  EXEC PGM=IEBCOPY",
    "//SYSUT1   DD DSN=PROD.SRC.LIB,DISP=SHR",
    "//SYSUT2   DD DSN=PROD.SRC.BACKUP,DISP=OLD",
    "//SYSIN    DD DUMMY",
    "//DB2RUN   EXEC PGM=IKJEFT01,DYNAMNBR=20",
    "//SYSTSPRT DD SYSOUT=*",
    "//SYSTSIN  DD *",
    "  DSN SYSTEM(DB2P)",
    "  RUN PROGRAM(CUSTRPT) PLAN(CUSTPLN) -",
    "      LIB('PROD.LOADLIB')",
    "  BIND PACKAGE(COLL1) MEMBER(CUSTRPT) ACTION(REPLACE)",
    "  END",
    "%AUDITX",
    "/*",
    "//IMSBMP   EXEC PGM=DFSRRC00,PARM='BMP,CUSTBMP'",
    "//IMSDLI   EXEC PGM=DFSRRC00,PARM=(DLI,CUSTDLI,CUSTPSB,7)",
    "//IMSBAD   EXEC PGM=DFSRRC00,PARM=ULU",
    "//FTPPUT   EXEC PGM=FTP,PARM='ftp.partner.example (EXIT'",
    "//OUTPUT   DD SYSOUT=*",
    "//OUTFILE  DD DSN=PROD.SALES.ALL,DISP=SHR",
    "//INPUT    DD *",
    "batchuser",
    "secretpw",
    "cd /inbound",
    "put //DD:OUTFILE sales.dat",
    "lcd 'PROD.FTP.'",
    "put DAILY daily.dat",
    "get report.csv 'PROD.FTP.REPORT' (REPLACE",
    "get summary.csv SUMMARY",
    "mput 'PROD.FTP.*'",
    "put /u/data/x.txt",
    "quit",
    "/*",
    "//FTPGET   EXEC PGM=FTP",
    "//LANDING  DD DSN=PROD.LANDING,DISP=(NEW,CATLG)",
    "//SYSIN    DD *",
    "mft.example.com",
    "user2",
    "pw2",
    "get in.dat //DD:LANDING",
    "get other.dat",
    "/*",
    "//CDXFER   EXEC PGM=DMBATCH,PARM=(YYSLYNN)",
    "//SYSIN    DD *",
    "  SIGNON USERID=(CDUSER,CDPASS) ESF=YES",
    "  SUBMIT PROC=PAYXFER SNODE=PARTNER.NODE",
    "PAYXFER  PROCESS SNODE=PARTNER.NODE",
    "STEP01   COPY FROM (DSN=PROD.SALES.ALL DISP=SHR PNODE) -",
    "              TO (DSN='/data/sales.dat' SNODE DISP=RPL)",
    "STEP02   COPY FROM (DSN=REMOTE.ORDERS SNODE) -",
    "              TO (DSN=PROD.ORDERS.IN DISP=(NEW,CATLG))",
    "STEP03   COPY FROM (DSN='/u/out/file.txt' PNODE) -",
    "              TO (DSN=REMOTE.FILE)",
    "  SIGNOFF",
    "/*",
    "//CDSUB    EXEC PGM=DMBATCH",
    "//SYSIN    DD *",
    "  SUBMIT PROC=NIGHTLY -",
    "         SNODE=DR.SITE -",
    "/*",
    "//USS      EXEC PGM=BPXBATCH,PARM='SH /u/scripts/load.sh daily'",
    "//STDOUT   DD PATH='/u/logs/load.out',PATHOPTS=(OWRONLY,OCREAT,OTRUNC)",
    "//STDERR   DD SYSOUT=*",
    "//USS2     EXEC PGM=BPXBATCH",
    "//STDPARM  DD *",
    "PGM /u/bin/report",
    "  --verbose",
    "/*",
    "//STDIN    DD PATH='/u/data/in.txt',PATHOPTS=ORDONLY",
    "//USS3     EXEC PGM=BPXBATCH,PARM='SH'",
    "//USS4     EXEC PGM=BPXBATCH",
    "//REPORTS  EXEC PGM=RPTPGM",
    "//STEPOUT  OUTPUT DEST=PRT02",
    "//RPT1     DD SYSOUT=(,),OUTPUT=*.RPTOUT",
    "//RPT2     DD SYSOUT=B,OUTPUT=*.REPORTS.STEPOUT",
    "//RPT3     DD SYSOUT=(A,INTRDR),DEST=RMT9",
)


def test_utilities_read_their_control_statements(tmp_path: Path) -> None:
    jcl = write(tmp_path / "jcl" / "UTIL.jcl", *UTILITY_JOB)
    write(
        tmp_path / "cntl" / "SORTCARD",
        "* SORT CARD KEPT IN A CONTROL LIBRARY",
        "  SORT FIELDS=(1,10,CH,A)",
    )
    flow = batch_flow.build_flow([jcl, tmp_path / "cntl"])
    steps = steps_of(flow, "UTIL")
    datasets = flow["datasets"]

    define = steps["DEFINE"]
    assert define["utility"] == "idcams"
    assert define["control"] == {
        "conditional": True,
        "commands": [
            {"command": "DELETE", "datasets": ["PROD.CUST.KSDS", "PROD.CUST.AIX"]},
            {"command": "SET"},
            {"command": "DEFINE CLUSTER", "dataset": "PROD.CUST.KSDS"},
            {"command": "DEFINE GDG", "dataset": "PROD.CUST.BACKUP"},
            {"command": "DEFINE ALIAS", "dataset": "CUST"},
            {"command": "REPRO", "to": "PROD.CUST.KSDS", "infile": "INPUT"},
            {"command": "REPRO", "from": "PROD.CUST.KSDS", "outfile": "BACKUP"},
            {"command": "LISTCAT", "entries": ["PROD.CUST.KSDS"]},
            {"command": "LISTCAT"},
            {"command": "DEFINE PAGESPACE"},
            {"command": "DELETE", "datasets": ["PROD.CUST.FLAG"]},
        ],
    }
    assert [(a["action"], a.get("via")) for a in datasets["PROD.CUST.KSDS"]["accesses"]] == [
        ("delete", "IDCAMS DELETE"),
        ("write", "IDCAMS DEFINE CLUSTER"),
        ("write", "IDCAMS REPRO"),
        ("read", "IDCAMS REPRO"),
    ]
    assert datasets["PROD.SEQ.IN"]["consumers"] == ["UTIL"]
    assert datasets["PROD.CUST.FLAG"]["deleted_by"] == ["UTIL"]
    assert "CUST" not in datasets
    assert steps["NOCMDS"]["control"] == {}

    merge = steps["MERGE"]
    assert merge["control"] == {"statements": ["MERGE", "OUTFIL", "SUM"]}
    assert merge["flags"] == ["business logic in sort control cards"]
    for name in ("PROD.SALES.ALL", "PROD.SALES.BIG", "PROD.SALES.ONE"):
        assert [a["action"] for a in datasets[name]["accesses"] if a["step"] == "MERGE"] == [
            "write"
        ]
    assert datasets["PROD.SALES.EAST"]["consumers"] == ["UTIL"]
    assert steps["JOIN"]["control"] == {"statements": ["JOINKEYS", "REFORMAT", "SORT"]}
    assert datasets["PROD.JOIN.RIGHT"]["consumers"] == ["UTIL"]

    tool = steps["TOOL"]
    assert tool["control"] == {"statements": ["OMIT"], "operators": ["COUNT", "DISPLAY", "SELECT"]}
    assert tool["flags"] == ["business logic in sort control cards"]
    assert datasets["PROD.SALES.TOP"]["producers"] == ["UTIL"]

    sortctl = steps["SORTCTL"]
    assert sortctl["control"] == {"statements": ["SORT"]}
    assert dd(sortctl, "SYSIN")["control_member"] == str(tmp_path / "cntl" / "SORTCARD")
    assert steps["SORTMISS"]["flags"] == ["control statements in PROD.CNTL(NOCARD) were not found"]
    assert steps["SORTPATH"]["flags"] == ["control statements in /u/cards/sort.txt were not found"]
    assert steps["GENER"]["control"] == {"statements": ["GENERATE", "RECORD"]}
    assert steps["COPYPDS"]["control"] == {"statements": ["COPY", "SELECT"]}
    assert datasets["PROD.FIX.LIB"]["consumers"] == ["UTIL"]
    assert datasets["PROD.MERGED.LIB"]["producers"] == ["UTIL"]
    assert datasets["PROD.SRC.BACKUP"]["producers"] == ["UTIL"]

    db2 = steps["DB2RUN"]
    assert (db2["program"], db2["runs"]) == ("IKJEFT01", ["CUSTRPT", "AUDITX"])
    assert db2["control"] == {
        "db2_system": "DB2P",
        "run": [{"program": "CUSTRPT", "plan": "CUSTPLN"}],
        "binds": ["BIND PACKAGE(COLL1) MEMBER(CUSTRPT) ACTION(REPLACE)"],
        "execs": ["AUDITX"],
    }
    assert steps["IMSBMP"]["control"] == {"region": "BMP", "program": "CUSTBMP", "psb": "CUSTBMP"}
    assert steps["IMSDLI"]["control"] == {"region": "DLI", "program": "CUSTDLI", "psb": "CUSTPSB"}
    assert steps["IMSDLI"]["runs"] == ["CUSTDLI"]
    assert (steps["IMSBAD"]["control"], steps["IMSBAD"]["runs"]) == ({}, [])

    transfers = [
        {key: value for key, value in t.items() if key not in {"job", "protocol"}}
        for t in flow["transfers"]
    ]
    ftp_host = "ftp.partner.example"
    assert transfers == [
        {
            "step": "FTPPUT",
            "command": "PUT",
            "direction": "outbound",
            "host": ftp_host,
            "local": "//DD:OUTFILE",
            "remote": "/inbound/sales.dat",
            "dataset": "PROD.SALES.ALL",
        },
        {
            "step": "FTPPUT",
            "command": "PUT",
            "direction": "outbound",
            "host": ftp_host,
            "local": "DAILY",
            "remote": "/inbound/daily.dat",
            "dataset": "PROD.FTP.DAILY",
        },
        {
            "step": "FTPPUT",
            "command": "GET",
            "direction": "inbound",
            "host": ftp_host,
            "local": "'PROD.FTP.REPORT'",
            "remote": "/inbound/report.csv",
            "dataset": "PROD.FTP.REPORT",
        },
        {
            "step": "FTPPUT",
            "command": "GET",
            "direction": "inbound",
            "host": ftp_host,
            "local": "SUMMARY",
            "remote": "/inbound/summary.csv",
            "dataset": "PROD.FTP.SUMMARY",
        },
        {
            "step": "FTPPUT",
            "command": "MPUT",
            "direction": "outbound",
            "host": ftp_host,
            "local": "'PROD.FTP.*'",
            "remote": None,
        },
        {
            "step": "FTPPUT",
            "command": "PUT",
            "direction": "outbound",
            "host": ftp_host,
            "local": "/u/data/x.txt",
            "remote": None,
        },
        {
            "step": "FTPGET",
            "command": "GET",
            "direction": "inbound",
            "host": "mft.example.com",
            "local": "//DD:LANDING",
            "remote": "in.dat",
            "dataset": "PROD.LANDING",
        },
        {
            "step": "FTPGET",
            "command": "GET",
            "direction": "inbound",
            "host": "mft.example.com",
            "local": None,
            "remote": "other.dat",
        },
        {
            "step": "CDXFER",
            "command": "COPY",
            "direction": "outbound",
            "host": "PARTNER.NODE",
            "process": "PAYXFER",
            "local": "PROD.SALES.ALL",
            "remote": "/data/sales.dat",
            "dataset": "PROD.SALES.ALL",
        },
        {
            "step": "CDXFER",
            "command": "COPY",
            "direction": "inbound",
            "host": "PARTNER.NODE",
            "process": "PAYXFER",
            "local": "PROD.ORDERS.IN",
            "remote": "REMOTE.ORDERS",
            "dataset": "PROD.ORDERS.IN",
        },
        {
            "step": "CDXFER",
            "command": "COPY",
            "direction": "outbound",
            "host": "PARTNER.NODE",
            "process": "PAYXFER",
            "local": "/u/out/file.txt",
            "remote": "REMOTE.FILE",
        },
        {
            "step": "CDSUB",
            "command": "SUBMIT",
            "direction": "unknown",
            "process": "NIGHTLY",
            "host": "DR.SITE",
        },
    ]
    for name, producer in (
        ("PROD.FTP.REPORT", True),
        ("PROD.FTP.SUMMARY", True),
        ("PROD.LANDING", True),
        ("PROD.ORDERS.IN", True),
        ("PROD.FTP.DAILY", False),
    ):
        assert (datasets[name]["producers"] == ["UTIL"]) is producer
    rendered = json.dumps(flow)
    for secret in ("secretpw", "pw2", "CDPASS"):
        assert secret not in rendered
    assert dd(steps["FTPPUT"], "INPUT")["instream_lines"] == 11

    assert steps["USS"]["control"] == {"mode": "SH", "command": "/u/scripts/load.sh daily"}
    assert steps["USS"]["runs"] == ["/u/scripts/load.sh"]
    assert steps["USS2"]["control"] == {"mode": "PGM", "command": "/u/bin/report --verbose"}
    assert (steps["USS3"]["control"], steps["USS3"]["runs"]) == ({"mode": "SH", "command": ""}, [])
    assert datasets["/u/logs/load.out"]["producers"] == ["UTIL"]
    assert datasets["/u/data/in.txt"]["consumers"] == ["UTIL"]
    assert (steps["USS4"]["control"], steps["USS4"]["runs"]) == ({}, [])

    reports = [
        (r["step"], r["dd"], r.get("class"), r.get("dest"), r.get("writer"))
        for r in flow["reports"]
        if r["kind"] == "report"
    ]
    assert reports == [
        ("TOOL", "LISTING", "A", None, None),
        ("REPORTS", "RPT1", "R", "PRT01", None),
        ("REPORTS", "RPT2", "B", "PRT02", None),
        ("REPORTS", "RPT3", "A", "RMT9", "INTRDR"),
    ]
    messages = [r for r in flow["reports"] if r["kind"] == "messages"]
    assert {r["msgclass"] for r in messages} == {"H"}
    assert len(messages) == 6
    report = batch_flow.flow_to_markdown(flow)
    for line in (
        "| UTIL | DB2RUN |  | IKJEFT01 -> CUSTRPT, AUDITX |  | tso-batch |",
        (
            "| UTIL | FTPPUT | ftp | outbound | ftp.partner.example | //DD:OUTFILE | "
            "/inbound/sales.dat |"
        ),
        "| UTIL | CDSUB | connect-direct | unknown | DR.SITE |  |  |",
        "| UTIL | REPORTS | RPT3 | A | RMT9 |",
        "6 SYSOUT DDs that carry messages or dumps are not listed.",
    ):
        assert line in report


CONTROL_M = (
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<DEFTABLE xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    '  <FOLDER DATACENTER="DC1" FOLDER_NAME="CUSTOMER">',
    '    <RULE_BASED_CALENDARS NAME="WORKDAYS"/>',
    '    <JOB JOBNAME="EXTRACT" MEMNAME="EXTRACT" MEMLIB="PROD.JCL" APPLICATION="CUST"',
    '         SUB_APPLICATION="DAILY" NODEID="MVSA" TASKTYPE="Job" DAYS="ALL" TIMEFROM="0100">',
    '      <OUTCOND NAME="EXTRACT-OK" ODATE="ODAT" SIGN="+"/>',
    "    </JOB>",
    '    <SUB_FOLDER JOBNAME="LOADS">',
    '      <JOB JOBNAME="LOAD-DAILY" MEMNAME="LOADJCL" APPLICATION="CUST">',
    '        <INCOND NAME="EXTRACT-OK" ODATE="ODAT" AND_OR="A"/>',
    '        <OUTCOND NAME="EXTRACT-OK" ODATE="ODAT" SIGN="DEL"/>',
    "      </JOB>",
    "    </SUB_FOLDER>",
    '    <JOB JOBNAME="AUDIT" MEMNAME="AUDIT" WEEKDAYS="1,2,3,4,5" CYCLIC="0">',
    '      <INCOND NAME="MANUAL-GO" ODATE="ODAT" AND_OR="A"/>',
    '      <OUTCOND NAME="AUDIT-OK" ODATE="ODAT" SIGN="ADD"/>',
    "    </JOB>",
    '    <JOB JOBNAME="ARCHIVE" MEMNAME="ARCHIVE">',
    '      <INCOND NAME="AUDIT-OK" ODATE="ODAT"/>',
    "    </JOB>",
    "  </FOLDER>",
    "</DEFTABLE>",
)


def data_dependencies(flow: dict[str, Any]) -> dict[tuple[str, str], bool | None]:
    return {
        (item["from"], item["to"]): item["scheduled"]
        for item in flow["job_dependencies"]
        if item["type"] == "data"
    }


def test_control_m_schedule_and_missing_dependencies(customer: Path, tmp_path: Path) -> None:
    xml = write(tmp_path / "ctm.xml", *CONTROL_M)
    flow = batch_flow.build_flow([customer], schedules=[xml])
    schedule = flow["schedule"]
    assert schedule["sources"] == [{"path": str(xml), "format": "control-m"}]
    assert list(schedule["jobs"]) == ["ARCHIVE", "AUDIT", "EXTRACT", "LOAD"]
    assert schedule["jobs"]["EXTRACT"] == {
        "source": "control-m",
        "folder": "CUSTOMER",
        "jobname": "EXTRACT",
        "memname": "EXTRACT",
        "memlib": "PROD.JCL",
        "application": "CUST",
        "sub_application": "DAILY",
        "nodeid": "MVSA",
        "tasktype": "Job",
        "days": "ALL",
        "timefrom": "0100",
        "inconds": [],
        "outconds": [{"NAME": "EXTRACT-OK", "ODATE": "ODAT", "SIGN": "+"}],
    }
    assert schedule["jobs"]["LOAD"]["folder"] == "LOADS"
    assert sorted((e["from"], e["to"], e["via"]) for e in schedule["edges"]) == [
        ("AUDIT", "ARCHIVE", "AUDIT-OK"),
        ("EXTRACT", "LOAD", "EXTRACT-OK"),
    ]
    assert schedule["unmatched_conditions"] == ["MANUAL-GO"]
    assert (schedule["jobs_without_jcl"], schedule["unscheduled_jobs"]) == (["ARCHIVE"], [])
    assert data_dependencies(flow) == {
        ("EXTRACT", "AUDIT"): False,
        ("EXTRACT", "LOAD"): True,
        ("LOAD", "AUDIT"): False,
    }
    assert [w for w in flow["warnings"] if w.startswith("missing scheduler dependency")] == [
        (
            "missing scheduler dependency: EXTRACT writes PROD.CUST.DAILY, which AUDIT reads, "
            "but the schedule has no path from EXTRACT to AUDIT"
        ),
        (
            "missing scheduler dependency: LOAD writes PROD.SHARED, which AUDIT reads, "
            "but the schedule has no path from LOAD to AUDIT"
        ),
    ]
    assert {"from": "EXTRACT", "to": "LOAD", "type": "schedule"} in flow["edges"]


def test_workload_scheduler_batch_loader(customer: Path, tmp_path: Path) -> None:
    loader = write(
        tmp_path / "custapp.txt",
        "/* CUSTOMER BATCH, LOADED WITH THE BATCH LOADER */",
        "ADSTART ACTION(SETDEFAULT) OWNER(BATCH)",
        "ADOP    WSID(CPU1) OPNO(001) JOBN(STRAY)",
        "ADSTART ADID(CUSTAPP) DESCR('Customer batch')",
        "        OWNER(CUSTTEAM)",
        "ADRUN   PERIOD(WORKDAYS) RULE(D)",
        "ADOP    WSID(CPU1) OPNO(010) JOBN(EXTRACT) DESC('Extract (daily)')",
        "ADOP    WSID(CPU1) OPNO(020) JOBN(LOAD)",
        "ADDEP   PREWSID(CPU1) PREOP(10)",
        "ADOP    WSID(CPU1) OPNO(030) JOBN(AUDIT) PREOP(020)",
        "ADDEP   PREWSID(CPU1) PREOP(050) PREADID(GLAPP)",
        "ADOP    WSID(PRT1) OPNO(040) DESC('Print') PREOP(030)",
        "ADSTART ADID(OTHERAPP)",
        "ADOP    WSID(CPU1) OPNO(005) JOBN(ARCHIVE)",
        "ADDEP   PREOP(030) PREAD(CUSTAPP)",
    )
    flow = batch_flow.build_flow([customer], schedules=[loader])
    schedule = flow["schedule"]
    assert schedule["sources"] == [{"path": str(loader), "format": "iws-batch-loader"}]
    assert [(e["from"], e["to"], e["via"]) for e in schedule["edges"]] == [
        ("EXTRACT", "LOAD", "CUSTAPP 010 -> CUSTAPP 020"),
        ("LOAD", "AUDIT", "CUSTAPP 020 -> CUSTAPP 030"),
        ("AUDIT", "ARCHIVE", "CUSTAPP 030 -> OTHERAPP 005"),
    ]
    operations = {(op["adid"], op["opno"]): op for op in schedule["operations"]}
    assert operations["CUSTAPP", "010"]["desc"] == "Extract (daily)"
    assert operations["CUSTAPP", "040"] == {
        "adid": "CUSTAPP",
        "opno": "040",
        "wsid": "PRT1",
        "jobn": None,
        "desc": "Print",
        "predecessors": [{"adid": "CUSTAPP", "opno": "030"}],
    }
    assert schedule["jobs"]["LOAD"] == {
        "source": "iws-batch-loader",
        "application": "CUSTAPP",
        "operations": ["020"],
    }
    assert schedule["run_cycles"] == {
        "CUSTAPP": [{"statement": "ADRUN", "PERIOD": "WORKDAYS", "RULE": "D"}]
    }
    assert data_dependencies(flow) == {
        ("EXTRACT", "AUDIT"): True,
        ("EXTRACT", "LOAD"): True,
        ("LOAD", "AUDIT"): True,
    }
    assert flow["warnings"] == [
        "EXTRACT STEP2: *.NOPE.DD does not resolve",
        f"{loader}: ADOP outside an application is ignored",
        (
            "schedule: predecessor GLAPP operation 050 of CUSTAPP operation 030 is not in the "
            "loaded schedules"
        ),
    ]


def test_csv_schedule_and_unreadable_exports(customer: Path, tmp_path: Path) -> None:
    exported = write(
        tmp_path / "ca7.csv",
        "Predecessor;Successor;Condition",
        "EXTRACT;LOAD;EXTRACT-OK",
        "LOADJCL;EXTRACT;",
        "ARCHIVE;AUDIT;",
        "AUDIT;AUDIT;",
        ";AUDIT;",
    )
    flow = batch_flow.build_flow([customer], schedules=[exported])
    schedule = flow["schedule"]
    assert [(e["from"], e["to"], e["via"]) for e in schedule["edges"]] == [
        ("EXTRACT", "LOAD", "EXTRACT-OK"),
        ("LOAD", "EXTRACT", None),
        ("ARCHIVE", "AUDIT", None),
    ]
    assert schedule["jobs"]["ARCHIVE"] == {"source": "csv"}
    assert data_dependencies(flow) == {
        ("EXTRACT", "AUDIT"): False,
        ("EXTRACT", "LOAD"): True,
        ("LOAD", "AUDIT"): False,
    }

    lone = write(tmp_path / "lone.xml", '<DEFTABLE><JOB JOBNAME="LONE" MEMNAME="LONE"/></DEFTABLE>')
    assert batch_flow.build_flow([customer], schedules=[lone])["schedule"]["jobs"]["LONE"] == {
        "source": "control-m",
        "jobname": "LONE",
        "memname": "LONE",
        "inconds": [],
        "outconds": [],
    }
    empty = write(tmp_path / "empty.xml", "<DEFTABLE/>")
    assert batch_flow.build_flow([customer], schedules=[empty])["warnings"][-1] == (
        f"{empty}: no Control-M JOB elements"
    )
    unreadable = [
        (write(tmp_path / "bad.xml", "<DEFTABLE><JOB></DEFTABLE>"), "not well-formed XML"),
        (write(tmp_path / "cols.csv", "predecessor_job,successor_job"), "CSV needs"),
        (write(tmp_path / "notes.txt", "nothing to see"), "not a Control-M XML"),
    ]
    for path, message in unreadable:
        with pytest.raises(batch_flow.FlowError, match=message):
            batch_flow.build_flow([customer], schedules=[path])


def test_members_are_found_by_content_and_decoded(tmp_path: Path) -> None:
    jcl = tmp_path / "jcl"
    jcl.mkdir()
    records = [
        "//EBCJOB   JOB (ACCT),'EBCDIC'",
        "//JOBLIB   DD DSN=PROD.LOADLIB,DISP=SHR",
        "//STEP1    EXEC PGM=IEFBR14",
        "//NEW      DD DSN=PROD.EBC.NEW,DISP=(NEW,CATLG)",
    ]
    ebcdic = b"".join(zos_encoding.encode(record.ljust(80), "037") for record in records)
    (jcl / "EBCJOB").write_bytes(ebcdic)
    (jcl / "LOADMOD").write_bytes(b"\x00\x01\x02binary")
    write(jcl / ".hidden" / "HIDDEN.jcl", "//HIDDEN   JOB (ACCT)")
    write(jcl / "NOTES.md", "//NOTJCL   JOB (ACCT)")
    write(jcl / "BIG.jcl", "//BIG      JOB (ACCT)", *["//* PADDING" + " " * 60] * 40)
    write(jcl / "DUPA.jcl", "//DUPJOB   JOB (ACCT)")
    write(jcl / "DUPB.jcl", "//DUPJOB   JOB (ACCT)")
    multi = write(
        jcl / "MULTI.jcl",
        "//FIRST    JOB (ACCT)",
        "//OPENP    PROC",
        "//PS       EXEC PGM=X",
        "//SECOND   JOB (ACCT)",
        "//JOBCTL   CNTL",
        "//JPRT     PRINTDEV FONTDD=*.FONTS",
        "//         ENDCNTL",
        "// SET TODAY=2024",
        "//S1       EXEC PGM=SORT",
        "//CTLGRP   CNTL *",
        "//PRT      PRINTDEV BUFNO=20",
        "//IGNORED  DD DSN=SHOULD.NOT.APPEAR,DISP=SHR",
        "//         ENDCNTL",
        "//SYSIN    DD *,SYMBOLS=JCLONLY",
        "  INCLUDE COND=(1,4,CH,EQ,C'&TODAY')",
        "/*",
        "//S2       EXEC REGION=0M",
        "//         DD DSN=PROD.ORPHAN,DISP=SHR",
        "// IF (S1.RC = 0) THEN",
        "//LOOSE    DD DSN=PROD.LOOSE,DISP=SHR",
        "// ENDIF",
        "//         XMIT DEST=NODE2",
        "//",
        "//AFTER    EXEC PGM=IGNORED",
        "//THIRD    JOB (ACCT)",
        "//OPENQ    PROC",
        "//QS       EXEC PGM=Y",
    )
    flow = batch_flow.build_flow([jcl], max_bytes=2000)
    assert list(flow["jobs"]) == ["DUPJOB", "DUPJOB#2", "EBCJOB", "FIRST", "SECOND", "THIRD"]
    ebc = flow["jobs"]["EBCJOB"]
    assert ebc["encoding"] == "ebcdic-cp037"
    assert [(d["ddname"], d["dsn"], d["library"]) for d in ebc["dds"]] == [
        ("JOBLIB", "PROD.LOADLIB", True)
    ]
    assert flow["final_outputs"] == ["PROD.EBC.NEW"]
    assert "PROD.LOADLIB" not in flow["datasets"]
    second = steps_of(flow, "SECOND")
    assert list(second) == ["S1"]
    assert dd(second["S1"], "SYSIN")["instream"] == ["  INCLUDE COND=(1,4,CH,EQ,C'2024')"]
    assert [flow["jobs"][name]["steps"] for name in ("FIRST", "THIRD")] == [[], []]
    assert "SHOULD.NOT.APPEAR" not in json.dumps(flow)
    assert flow["warnings"] == [
        f"{jcl / 'BIG.jcl'}: skipped, larger than 2000 bytes",
        f"{jcl / 'DUPB.jcl'}: job DUPJOB is repeated; shown as DUPJOB#2",
        f"{multi}: in-stream procedure OPENP has no PEND",
        f"{multi}: in-stream procedure OPENQ has no PEND",
        "SECOND: unnamed DD at line 18 follows no DD",
        "SECOND S2: EXEC names no program or procedure",
        "SECOND: DD at line 20 does not follow an EXEC",
    ]
    only = batch_flow.build_flow([jcl / "DUPA.jcl"])
    assert list(only["jobs"]) == ["DUPJOB"]


def test_nesting_limits_and_include_loops(tmp_path: Path) -> None:
    procs = tmp_path / "procs"
    for level in range(1, 18):
        write(
            procs / f"P{level:02d}.prc",
            f"//P{level:02d}      PROC",
            f"//S{level:02d}      EXEC P{level + 1:02d}",
        )
        write(procs / f"I{level:02d}", f"//         INCLUDE MEMBER=I{level + 1:02d}")
    write(procs / "LOOPI", "//         INCLUDE MEMBER=LOOPI")
    jcl = write(
        tmp_path / "jcl" / "DEEP.jcl",
        "//DEEP     JOB (ACCT)",
        "//         INCLUDE MEMBER=I01",
        "//         INCLUDE MEMBER=LOOPI",
        "//TOP      EXEC P01",
    )
    flow = batch_flow.build_flow([jcl], proclibs=[procs])
    job = flow["jobs"]["DEEP"]
    assert job["procs"] == [f"P{level:02d}" for level in range(1, 16)]
    (step,) = job["steps"]
    assert step["name"] == "TOP." + ".".join(f"S{level:02d}" for level in range(1, 16))
    assert step["flags"] == ["procedure P16 is nested more than 15 levels deep"]
    assert job["includes"] == [*(f"I{level:02d}" for level in range(1, 16)), "LOOPI"]
    assert flow["warnings"] == [
        "DEEP: INCLUDE members nest deeper than 15",
        "DEEP: INCLUDE member LOOPI includes itself",
        f"DEEP {step['name']}: procedure P16 is nested more than 15 levels deep",
    ]


def test_cli_renders_json_markdown_and_mermaid(
    customer: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    xml = str(write(tmp_path / "ctm.xml", *CONTROL_M))
    assert batch_flow.main([str(customer), "--schedule", xml, "--set", "SYSUID=BATCH1"]) == 0
    flow = json.loads(capsys.readouterr().out)
    assert (flow["tool"], flow["roots"], flow["proclibs"]) == ("batch_flow", [str(customer)], [])

    assert batch_flow.main([str(customer), "--schedule", xml, "--format", "markdown"]) == 0
    report = capsys.readouterr().out
    for line in (
        "| AUDIT | STEP2 |  | AUDPGM2 | IF (STEP1.RC = 0 \\| STEP1.RC = 4) THEN |  |",
        "| LOAD | COPY |  | IEBGENER |  | copy |",
        "| PROD.CUST.DAILY | EXTRACT (STEP1) | AUDIT (STEP1); LOAD (STEP1) |",
        "| PROD.CUST.MASTER | EXTRACT (STEP1); LOAD (COPY) |",
        "| EXTRACT | AUDIT | data | PROD.CUST.DAILY (no path in the schedule) |",
        "| EXTRACT | LOAD | schedule | control-m: EXTRACT-OK |",
        "| AUDIT | STEP1 | REPORT | * |  |",
        "1 SYSOUT DDs that carry messages or dumps are not listed.",
        "- EXTRACT STEP2: *.NOPE.DD does not resolve",
    ):
        assert line in report

    assert batch_flow.main([str(customer), "--schedule", xml, "--format", "mermaid"]) == 0
    chart = capsys.readouterr().out.splitlines()
    assert chart[0] == "flowchart LR"
    for line in (
        '    job_ARCHIVE("ARCHIVE")',
        '    dataset_PROD_CUST_DAILY[("PROD.CUST.DAILY")]',
        '    dataset__u_cfg_extract_cfg[("/u/cfg/extract.cfg")]',
        "    job_EXTRACT --> dataset_PROD_CUST_DAILY",
        "    dataset_PROD_CUST_DAILY --> job_LOAD",
        "    job_EXTRACT -.-> job_LOAD",
    ):
        assert line in chart
    assert all("PROD_CUST_OLD" not in line for line in chart)

    assert batch_flow.main([str(customer), "--format", "mermaid", "--job", "load"]) == 0
    focused = capsys.readouterr().out
    assert "job_LOAD" in focused
    assert "job_EXTRACT" not in focused
    assert batch_flow.main([str(customer), "--job", "LOAD", "--max-bytes", "100000"]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert list(selected["jobs"]) == ["LOAD"]
    assert "/u/cfg/extract.cfg" not in selected["datasets"]
    assert selected["final_outputs"] == ["PROD.CUST.HISTORY", "PROD.CUST.NEW"]
    assert {(d["from"], d["to"]) for d in selected["job_dependencies"]} == {
        ("EXTRACT", "LOAD"),
        ("LOAD", "AUDIT"),
    }
    assert batch_flow.main([str(customer), "--job", "LOAD", "--format", "markdown"]) == 0
    assert "## Final outputs" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--set", "BAD"], "error: --set expects NAME=VALUE, got 'BAD'"),
        (["--job", "NOPE"], "error: no such job: NOPE"),
        (["--codepage", "9999"], "error: unsupported code page '9999'"),
        (["--proclib", "missing-proclib"], "error: not found: missing-proclib"),
    ],
)
def test_cli_errors(
    customer: Path, extra: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert batch_flow.main([str(customer), *extra]) == 1
    assert capsys.readouterr().err.startswith(message)


def test_cli_rejects_a_missing_root_and_a_bad_size(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert batch_flow.main([str(tmp_path / "missing")]) == 1
    assert capsys.readouterr().err == f"error: not found: {tmp_path / 'missing'}\n"
    with pytest.raises(SystemExit):
        batch_flow.main([str(tmp_path), "--max-bytes", "0"])
    assert "must be a positive number of bytes" in capsys.readouterr().err


def test_mermaid_caps_nodes_and_sanitizes_ids(tmp_path: Path) -> None:
    lines: list[str] = []
    for number in range(160):
        lines += [
            f"//J{number:04d}    JOB (ACCT)",
            "//S1       EXEC PGM=IEFBR14",
            f"//D1       DD DSN=PROD.DS{number:04d},DISP=(NEW,CATLG)",
            "//",
        ]
    chart = batch_flow.flow_to_mermaid(batch_flow.build_flow([write(tmp_path / "MANY", *lines)]))
    chart_lines = chart.splitlines()
    assert chart_lines[1] == (
        "    %% truncated: 300 of 320 nodes shown; use --job to focus on fewer jobs"
    )
    assert sum('("' in line for line in chart_lines) == 300
    assert sum("-->" in line for line in chart_lines) == 140

    flow = {
        "jobs": {"A": {}},
        "datasets": {
            "/u/a.b": {"producers": ["A"], "consumers": []},
            "/u/a_b": {"producers": [], "consumers": ["A"]},
            'X"Y': {"producers": ["A"], "consumers": []},
            "GONE": {"producers": [], "consumers": []},
        },
        "edges": [
            {"from": "A", "to": "/u/a.b", "type": "writes"},
            {"from": "/u/a_b", "to": "A", "type": "reads"},
            {"from": "A", "to": 'X"Y', "type": "writes"},
            {"from": "A", "to": "GONE", "type": "deletes"},
            {"from": "A", "to": "GONE", "type": "writes"},
            {"from": "A", "to": "B", "type": "schedule"},
        ],
    }
    assert batch_flow.flow_to_mermaid(flow).splitlines() == (
        [
            "flowchart LR",
            '    job_A("A")',
            '    job_B("B")',
            '    dataset__u_a_b[("/u/a.b")]',
            '    dataset__u_a_b_2[("/u/a_b")]',
            '    dataset_X_Y[("X#quot;Y")]',
            "    job_A --> dataset__u_a_b",
            "    dataset__u_a_b_2 --> job_A",
            "    job_A --> dataset_X_Y",
            "    job_A -.-> job_B",
        ]
    )
