"""Tests for code-modernization-plugin: mainframe-analysis zos_definitions.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import zos_definitions
from mainframe_fixtures import ebcdic_member

CSD = """\
* DFHCSDUP EXTRACT OUTPUT
DEFINE TRANSACTION(AUPD) GROUP(ACCT) PROGRAM(ACCTUPD) TRANCLASS(TCL1)
DEFINE TRANS(REMT) GROUP(ACCT) PROGRAM(REMPGM) REMOTESYSTEM(CICB)
       REMOTENAME(RMT1)
DEFINE PROGRAM(ACCTUPD) GROUP(ACCT) LANGUAGE(COBOL)
       CONCURRENCY(THREADSAFE) API(CICSAPI) DYNAMIC(NO)
DEFINE FILE(ACCTFIL) GROUP(ACCT) DSNAME(PROD.ACCT.KSDS) RLSACCESS(YES)
       READ(NO) BROWSE(YES) ADD(YES) UPDATE(YES) DELETE(YES)
       RECOVERY(BACKOUTONLY)
DEFINE TDQUEUE(ATRG) GROUP(ACCT) TYPE(INTRA) TRIGGERLEVEL(1) TRANSID(APRT)
DEFINE DB2ENTRY(ACCTENT) GROUP(ACCT) PLAN(ACCTPLN) TRANSID(AUPD)
DEFINE DB2TRAN(ACCTTRN) GROUP(ACCT) ENTRY(ACCTENT) TRANSID(AINQ)
DEFINE DB2CONN(DB2C) GROUP(ACCT) DB2ID(DB2P)
DEFINE URIMAP(ACCTURI) GROUP(ACCT) USAGE(PIPELINE) HOST(api.example.com)
       PATH(/acct/v1/*) PIPELINE(ACCTPIP) WEBSERVICE(ACCTWS)
DEFINE PIPELINE(ACCTPIP) GROUP(ACCT) CONFIGFILE(/u/cics/acct.xml)
DEFINE WEBSERVICE(ACCTWS) GROUP(ACCT) PIPELINE(ACCTPIP)
DEFINE CONNECTION(CICB) GROUP(ACCT) NETNAME(CICSB)
DEFINE IPCONN(CICC) GROUP(ACCT) APPLID(CICSC)
ADD GROUP(ACCT) LIST(PRODLIST)
ADD GROUP(BASE) LIST(PRODLIST)                                          00012300
"""
IDCAMS = """\
  /* VSAM DEFINITIONS */
  DELETE PROD.ACCT.KSDS CLUSTER PURGE
  DEFINE CL (NAME(PROD.ACCT.KSDS) IXD KEYS(10 0) RECSZ(150 200) -
         SHR(2 3) LOG(UNDO)) -
    DATA (NAME(PROD.ACCT.KSDS.DATA) CISZ(4096)) -
    INDEX (NAME(PROD.ACCT.KSDS.INDEX))
  DEFINE CLUSTER (NAME(PROD.ACCT.ESDS) NONINDEXED RECORDSIZE(80 80))
  DEFINE AIX (NAME(PROD.ACCT.AIX) RELATE(PROD.ACCT.KSDS) KEYS(20 10) UNQK NUPG)
  DEFINE PATH (NAME(PROD.ACCT.PATH) PENT(PROD.ACCT.AIX))
  DEFINE GDG (NAME(PROD.ACCT.HIST) LIMIT(7) SCRATCH NOEMPTY)
"""
MQSC = """\
* QUEUE MANAGER QM1
DEFINE QLOCAL('ACCT.EVENTS') +
       TRIGGER TRIGTYPE(FIRST) PROCESS('ACCT.PROC') +
       INITQ('SYSTEM.CICS.INITIATION.QUEUE') BOQNAME('ACCT.BACKOUT') +
       DEFPSIST(YES)
DEFINE QL('ACCT.WORK') NOTRIGGER
DEFINE QREMOTE('ACCT.TO.DIST') RNAME('DIST.IN') RQMNAME('QMDIST') XMITQ('QMDIST')
DEFINE QALIAS('ACCT.ALIAS') TARGET('ACCT.EVENTS')
DEFINE PROCESS('ACCT.PROC') APPLICID('ACCTMQ') APPLTYPE(CICS)
DEFINE CHANNEL('QM1.TO.QMDIST') CHLTYPE(SDR) TRPTYPE(TCP) +
       CONNAME('dist.example.com(1414)') XMITQ('QMDIST')
DEFINE NAMELIST('ACCT.NL') NAMES('A','B')
"""
LISTCAT = """\
1IDCAMS  SYSTEM SERVICES                                           TIME: 10:00:00
0  LISTCAT ENTRIES(PROD.ACCT.*) ALL
 CLUSTER ------- PROD.ACCT.KSDS
      HISTORY
        DATASET-OWNER-----(NULL)     CREATION--------2024.123
      RLSDATA
        LOG ----------------UNDO     RECOVERY REQUIRED --(NO)
      ASSOCIATIONS
        DATA-----PROD.ACCT.KSDS.DATA
        INDEX----PROD.ACCT.KSDS.INDEX
 DATA ---------- PROD.ACCT.KSDS.DATA
      ASSOCIATIONS
        CLUSTER--PROD.ACCT.KSDS
      ATTRIBUTES
        KEYLEN----------------10     AVGLRECL-------------150     BUFSPACE------------8192
        RKP--------------------0     MAXLRECL-------------200     EXCPEXIT----------(NULL)
        SHROPTNS(2,3)   RECOVERY     UNIQUE           NOERASE     INDEXED       NOWRITECHK
 INDEX --------- PROD.ACCT.KSDS.INDEX
      ASSOCIATIONS
        CLUSTER--PROD.ACCT.KSDS
      ATTRIBUTES
        KEYLEN----------------10     AVGLRECL---------------0     MAXLRECL------------4089
        SHROPTNS(2,3)   RECOVERY     UNIQUE           NOERASE     NOWRITECHK       UNORDERED
 CLUSTER ------- PROD.ACCT.ESDS
      ASSOCIATIONS
        DATA-----PROD.ACCT.ESDS.DATA
 DATA ---------- PROD.ACCT.ESDS.DATA
      ASSOCIATIONS
        CLUSTER--PROD.ACCT.ESDS
      ATTRIBUTES
        KEYLEN-----------------0     AVGLRECL--------------80     BUFSPACE------------8192
        RKP--------------------0     MAXLRECL--------------80     EXCPEXIT----------(NULL)
        SHROPTNS(1,3)   RECOVERY     UNIQUE           NOERASE     NONINDEXED    NOWRITECHK
 AIX ----------- PROD.ACCT.AIX
      ASSOCIATIONS
        DATA-----PROD.ACCT.AIX.DATA
        CLUSTER--PROD.ACCT.KSDS
        PATH-----PROD.ACCT.PATH
      ATTRIBUTES
        NOUPGRADE
 DATA ---------- PROD.ACCT.AIX.DATA
      ASSOCIATIONS
        AIX------PROD.ACCT.AIX
      ATTRIBUTES
        KEYLEN----------------20     AVGLRECL------------4086     BUFSPACE-----------29184
        RKP--------------------5     MAXLRECL-----------32600     EXCPEXIT----------(NULL)
        AXRKP-----------------10
        UNORDERED        NOREUSE     NONSPANNED      UNIQKEY
 PATH ---------- PROD.ACCT.PATH
      ASSOCIATIONS
        AIX------PROD.ACCT.AIX
 GDG BASE ------ PROD.ACCT.HIST
      ATTRIBUTES
        LIMIT------------------7     SCRATCH          NOEMPTY
 NONVSAM ------- PROD.ACCT.HIST.G0001V00
      ASSOCIATIONS
        GDG------PROD.ACCT.HIST
"""
LISTING = """\
PP 5655-EC6 IBM Enterprise COBOL for z/OS  6.4.0 P230418       ACCTUPD   Date 05/01/2025
Options in effect:
    NOADATA
    ARCH(12)
    TRUNC(STD)

 000002                PROGRAM-ID. ACCTUPD.
"""
BINDER = """\
IEW2278I B352 INVOCATION PARAMETERS - LIST,MAP,XREF
IEW2322I 1220  1    NAME ACCTUPD(R)
                         *** M O D U L E  M A P ***
                                   AMODE                 31
                                   RMODE                ANY
"""


def test_csd_summary_covers_routing_files_queues_db2_web_and_lists() -> None:
    summary = zos_definitions.summarize_csd(zos_definitions.parse_csd(CSD))
    assert summary["transactions"]["REMT"] == {
        "program": "REMPGM",
        "group": "ACCT",
        "remote_system": "CICB",
        "remote_name": "RMT1",
    }
    assert summary["transactions"]["AUPD"]["tranclass"] == "TCL1"
    assert summary["programs"]["ACCTUPD"]["concurrency"] == "THREADSAFE"
    assert summary["files"]["ACCTFIL"] == {
        "dsname": "PROD.ACCT.KSDS",
        "rls": "YES",
        "operations": "CRUD",
        "recovery": "BACKOUTONLY",
    }
    assert summary["tdqueues"]["ATRG"] == {"type": "INTRA", "trigger_level": "1", "transid": "APRT"}
    assert summary["db2"] == {
        "entries": {"ACCTENT": {"plan": "ACCTPLN", "transid": "AUPD"}},
        "transactions": {"AINQ": "ACCTENT"},
        "connection": {"DB2C": {"db2id": "DB2P", "plan": None}},
    }
    assert summary["web"] == {
        "urimaps": {
            "ACCTURI": {
                "usage": "PIPELINE",
                "path": "/acct/v1/*",
                "host": "api.example.com",
                "pipeline": "ACCTPIP",
                "webservice": "ACCTWS",
            }
        },
        "pipelines": ["ACCTPIP"],
        "webservices": {"ACCTWS": "ACCTPIP"},
    }
    assert summary["connections"] == {
        "CICB": {"type": "CONNECTION"},
        "CICC": {"type": "IPCONN", "applid": "CICSC"},
    }
    assert summary["lists"] == {"PRODLIST": ["ACCT", "BASE"]}
    assert summary["resource_counts"]["URIMAP"] == 1


def test_csd_ignores_command_words_inside_values_and_applies_alter() -> None:
    summary = zos_definitions.summarize_csd(
        zos_definitions.parse_csd(
            "DEFINE FILE(ACCTFIL) GROUP(ACCT) DESCRIPTION(Account master - add and update)\n"
            "       DSNAME(PROD.ACCT.KSDS) ADD(YES) UPDATE(YES)\n"
            "DEFINE PROGRAM(ACCTADD) GROUP(ACCT) DESCRIPTION('Define (new'' account')\n"
            "       CONCURRENCY(THREADSAFE)\n"
            "DEFINE TRANSACTION(AINQ) GROUP(ACCT) PROGRAM(ACCTINQ) TRANCLASS(TCL1)\n"
            "ALTER TRANSACTION(AINQ) GROUP(ACCT) PROGRAM(ACCTINQ2)\n"
            "ALTER TRANSACTION(NONE) GROUP(ACCT) PROGRAM(IGNORED)\n"
            "LIST GROUP(ACCT) OBJECTS\n"
        )
    )
    assert summary["files"]["ACCTFIL"] == {"dsname": "PROD.ACCT.KSDS", "operations": "CRU"}
    assert summary["programs"]["ACCTADD"]["concurrency"] == "THREADSAFE"
    assert summary["transactions"] == {
        "AINQ": {"program": "ACCTINQ2", "group": "ACCT", "tranclass": "TCL1"}
    }


def test_idcams_reads_clusters_indexes_paths_generations_and_deletes() -> None:
    assert zos_definitions.parse_idcams(IDCAMS) == {
        "clusters": {
            "PROD.ACCT.KSDS": {
                "type": "KSDS",
                "keys": {"length": 10, "offset": 0},
                "recordsize": {"average": 150, "maximum": 200},
                "shareoptions": [2, 3],
                "log": "UNDO",
            },
            "PROD.ACCT.ESDS": {"type": "ESDS", "recordsize": {"average": 80, "maximum": 80}},
        },
        "aix": {
            "PROD.ACCT.AIX": {
                "relate": "PROD.ACCT.KSDS",
                "keys": {"length": 20, "offset": 10},
                "unique": True,
                "upgrade": False,
            }
        },
        "paths": {"PROD.ACCT.PATH": "PROD.ACCT.AIX"},
        "gdgs": {"PROD.ACCT.HIST": {"limit": 7, "scratch": True, "empty": False}},
        "deletes": ["PROD.ACCT.KSDS"],
    }


def test_listcat_report_gives_the_same_structure_as_define_statements() -> None:
    assert zos_definitions.parse_listcat(LISTCAT) == {
        "clusters": {
            "PROD.ACCT.KSDS": {
                "type": "KSDS",
                "keys": {"length": 10, "offset": 0},
                "recordsize": {"average": 150, "maximum": 200},
                "shareoptions": [2, 3],
                "log": "UNDO",
            },
            "PROD.ACCT.ESDS": {
                "type": "ESDS",
                "recordsize": {"average": 80, "maximum": 80},
                "shareoptions": [1, 3],
            },
        },
        "aix": {
            "PROD.ACCT.AIX": {
                "relate": "PROD.ACCT.KSDS",
                "keys": {"length": 20, "offset": 10},
                "unique": True,
                "upgrade": False,
            }
        },
        "paths": {"PROD.ACCT.PATH": "PROD.ACCT.AIX"},
        "gdgs": {"PROD.ACCT.HIST": {"limit": 7, "scratch": True, "empty": False}},
    }


def test_listcat_without_attributes_lists_nothing() -> None:
    names_only = (
        "CLUSTER ------- USER.DUMMY\n"
        "DATA ---------- USER.DUMMY.CLDATA\n"
        "INDEX --------- USER.DUMMY.CLINDEX\n"
        "AIX ----------- USER.DUMMY.AIX\n"
        "PATH ---------- USER.DUMMY.PATH\n"
        "GDG BASE ------ USER.GDGBASE\n"
    )
    assert zos_definitions.parse_listcat(names_only) == {}


def test_mqsc_reads_queues_triggers_processes_and_channels() -> None:
    parsed = zos_definitions.parse_mqsc(MQSC)
    assert parsed["queues"]["ACCT.EVENTS"] == {
        "type": "QLOCAL",
        "initq": "SYSTEM.CICS.INITIATION.QUEUE",
        "process": "ACCT.PROC",
        "boqname": "ACCT.BACKOUT",
        "defpsist": "YES",
        "trigtype": "FIRST",
        "trigger": True,
    }
    assert parsed["queues"]["ACCT.WORK"] == {"type": "QLOCAL"}
    assert parsed["queues"]["ACCT.TO.DIST"]["rqmname"] == "QMDIST"
    assert parsed["queues"]["ACCT.ALIAS"] == {"type": "QALIAS", "target": "ACCT.EVENTS"}
    assert parsed["processes"] == {"ACCT.PROC": {"applicid": "ACCTMQ", "appltype": "CICS"}}
    assert parsed["channels"]["QM1.TO.QMDIST"]["conname"] == "dist.example.com(1414)"
    assert parsed["other"] == {"NAMELIST": ["ACCT.NL"]}


def test_binds_listings_and_schedules() -> None:
    binds = zos_definitions.parse_binds(
        "DSN SYSTEM(DB2P)\n"
        "BIND PACKAGE(COLL) MEMBER(PGM1) VALIDATE(BIND) DYNAMICRULES(RUN) -\n"
        "     ISOLATION(CS)\n"
        "REBIND PLAN(PLAN1) PKLIST(COLL.*)\n"
        "END\n"
    )
    assert binds == [
        {
            "type": "package",
            "name": "COLL.PGM1",
            "options": {"VALIDATE": "BIND", "DYNAMICRULES": "RUN", "ISOLATION": "CS"},
        },
        {"type": "plan", "name": "PLAN1", "options": {"PKLIST": "COLL.*"}},
    ]
    assert zos_definitions.parse_compile_listing(LISTING) == {
        "compiler": "Enterprise COBOL 6.4.0",
        "program": "ACCTUPD",
        "options": ["NOADATA", "ARCH(12)", "TRUNC(STD)"],
    }
    assert zos_definitions.parse_binder_listing(BINDER) == {
        "modules": ["ACCTUPD"],
        "amode": ["31"],
        "rmode": ["ANY"],
    }
    control_m = '<JOB JOBNAME="ACCTJOB" MEMNAME="ACCTJCL"/>\n<JOB JOBNAME="ACCTRPT"/>'
    assert zos_definitions.scheduled_jobs(control_m) == {
        "format": "control-m-xml",
        "jobs": ["ACCTJCL", "ACCTRPT"],
    }
    loader = "ADSTART ADID(ACCTAPP)\nADOP WSID(CPU1) OPNO(010) JOBN(acctjob)\n"
    assert zos_definitions.scheduled_jobs(loader) == {
        "format": "iws-batch-loader",
        "jobs": ["ACCTJOB"],
    }
    links = "Predecessor,Successor\nACCTJOB,ACCTRPT\nACCTRPT,\n"
    assert zos_definitions.scheduled_jobs(links) == {
        "format": "csv",
        "jobs": ["ACCTJOB", "ACCTRPT"],
    }
    assert zos_definitions.scheduled_jobs("hello") == {"format": "unknown", "jobs": []}
    extra = "Predecessor,Successor\nACCTJOB,ACCTRPT,EXTRA\n,\n"
    assert zos_definitions.scheduled_jobs(extra)["jobs"] == ["ACCTJOB", "ACCTRPT"]
    oversized = "x" * 140_000
    assert zos_definitions.scheduled_jobs(oversized) == {"format": "unknown", "jobs": []}


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (CSD, "cics-csd"),
        (MQSC, "mqsc"),
        (IDCAMS, "idcams"),
        (LISTCAT, "listcat"),
        (LISTING, "compile-listing"),
        (BINDER, "binder-listing"),
        ("BIND PACKAGE(COLL) MEMBER(PGM1)", "db2-bind"),
        ("ADSTART ADID(X)", "schedule"),
        ("hello", None),
    ],
)
def test_detect_kind(text: str, kind: str | None) -> None:
    assert zos_definitions.detect_kind(text) == kind


def test_definitions_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csd = tmp_path / "CICSPROD.CSD"
    csd.write_bytes(ebcdic_member(*CSD.splitlines()))
    assert zos_definitions.main([str(csd)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "cics-csd"
    assert result["definitions"]["files"]["ACCTFIL"]["operations"] == "CRUD"

    cards = tmp_path / "VSAMDEFS.CNTL"
    cards.write_text("REPRO INFILE(IN) OUTFILE(OUT)\n", encoding="utf-8")
    assert zos_definitions.main([str(cards)]) == 1
    assert "pass --kind" in capsys.readouterr().err
    assert zos_definitions.main([str(cards), "--kind", "idcams"]) == 0
    assert json.loads(capsys.readouterr().out) == {"kind": "idcams", "definitions": {}}

    binary = tmp_path / "LOADMOD"
    binary.write_bytes(b"\x00\x01\x02binary")
    assert zos_definitions.main([str(binary)]) == 1
    assert "binary" in capsys.readouterr().err
    assert zos_definitions.main([str(tmp_path / "missing")]) == 1
    assert zos_definitions.main([str(csd), "--codepage", "999"]) == 1
    assert "error:" in capsys.readouterr().err
