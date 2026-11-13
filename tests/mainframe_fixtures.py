"""Helpers that build mainframe-shaped test data for the code-modernization-plugin tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import zos_encoding

if TYPE_CHECKING:
    from pathlib import Path


def fixed(*lines: str) -> str:
    """Return fixed-format source: sequence numbers, indicator column, and code from col 8."""
    out = []
    for number, line in enumerate(lines, start=1):
        indicator, code = (line[0], line[1:]) if line[:1] in {"*", "-"} else (" ", line)
        out.append(f"{number * 100:06d}{indicator}{code[:65]:<65}IDENT{number:03d}")
    return "\n".join(out) + "\n"


def ebcdic(text: str, codepage: str = "037") -> bytes:
    """Encode text in an EBCDIC code page."""
    return zos_encoding.encode(text, codepage)


def ebcdic_member(*lines: str, codepage: str = "037") -> bytes:
    """Return a member as exported in binary: 80-byte EBCDIC records, no line ends."""
    return b"".join(zos_encoding.encode(line.ljust(80), codepage) for line in lines)


def packed(number: int, digits: int, sign: str | None = None) -> bytes:
    """Encode a packed-decimal value; ``sign`` overrides the sign nibble (C, D, or F)."""
    nibble = sign or ("D" if number < 0 else "C")
    text = f"{abs(number):0{digits}d}{nibble}"
    return bytes.fromhex(text if len(text) % 2 == 0 else f"0{text}")


def zoned(number: int, digits: int, *, signed: bool = True) -> bytes:
    """Encode a zoned-decimal value with a trailing overpunched sign."""
    body = bytearray(0xF0 | int(char) for char in f"{abs(number):0{digits}d}")
    if signed:
        body[-1] = ((0xD if number < 0 else 0xC) << 4) | (body[-1] & 0x0F)
    return bytes(body)


def rdw(record: bytes) -> bytes:
    """Prefix a record with its record descriptor word."""
    return (len(record) + 4).to_bytes(2, "big") + b"\x00\x00" + record


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_rich_estate(root: Path) -> None:
    """Write an estate that touches every subsystem the inventory reads.

    CICS (CSD, files, queues, URIMAP, remote routing, threadsafe), Db2 (tables, remote
    location, binds), IMS DL/I calls, MQ (calls and MQSC), VSAM (IDCAMS), batch JCL with
    utilities, file transfer, and reports, PL/I, Assembler, REXX, Natural, an ISPF skeleton,
    a Control-M schedule, and compiler and binder listings.
    """
    _write(
        root / "cobol" / "ACCTUPD.cbl",
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. ACCTUPD.",
            "DATA DIVISION.",
            "WORKING-STORAGE SECTION.",
            "COPY ACCTREC.",
            "01  WS-PGM      PIC X(8) VALUE 'ACCTVAL'.",
            "01  WS-QNAME    PIC X(48) VALUE 'ACCT.EVENTS'.",
            "01  WS-QUEUE-STS PIC X VALUE 'N'.",
            "01  ACCTNO      PIC X(10).",
            "PROCEDURE DIVISION.",
            "    EXEC CICS ADDRESS CWA(WS-PTR) END-EXEC.",
            "    EXEC CICS READ FILE('ACCTFIL') INTO(WS-REC) RIDFLD(ACCTNO)",
            "         UPDATE END-EXEC.",
            "    EXEC CICS REWRITE FILE('ACCTFIL') FROM(WS-REC) END-EXEC.",
            "    EXEC CICS WRITEQ TS QUEUE('ACCTQ') FROM(WS-REC) END-EXEC.",
            "    EXEC CICS LINK PROGRAM(WS-PGM) COMMAREA(WS-REC) END-EXEC.",
            "    EXEC SQL UPDATE ACCT.BALANCE SET AMT = :WS-AMT",
            "         WHERE ID = :ACCTNO END-EXEC.",
            "    EXEC SQL INSERT INTO ACCT.HISTORY (ID) VALUES (:ACCTNO)",
            "         END-EXEC.",
            "    EXEC SQL SELECT NAME INTO :WS-NAME FROM DB2B.ACCT.REMOTE",
            "         END-EXEC.",
            "    CALL 'MQPUT' USING HCONN HOBJ MD PMO LEN BUFFER CC RC.",
            "    EXEC CICS SYNCPOINT END-EXEC.",
            "    EXEC CICS SEND MAP('ACCTM1') MAPSET('ACCTSET') END-EXEC.",
            "    EXEC CICS START TRANSID('APRT') END-EXEC.",
            "    EXEC CICS RETURN TRANSID('AUPD') END-EXEC.",
        ),
    )
    _write(
        root / "cobol" / "ACCTAPI.cbl",
        fixed(
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. ACCTAPI.",
            "WORKING-STORAGE SECTION.",
            "01  PSB-NAME PIC X(8) VALUE 'ACCTPSB'.",
            "PROCEDURE DIVISION.",
            "    EXEC DLI SCHD PSB((PSB-NAME)) NODHABEND END-EXEC.",
            "    EXEC CICS GET CONTAINER('REQ') CHANNEL('API') INTO(WS-REQ)",
            "         END-EXEC.",
            "    EXEC SQL SELECT AMT INTO :WS-AMT FROM ACCT.BALANCE",
            "         WHERE ID = :WS-ID END-EXEC.",
        ),
    )
    _write(
        root / "cobol" / "ACCTBAT.cbl",
        fixed(
            "CBL ARITH(EXTEND)",
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. ACCTBAT.",
            "ENVIRONMENT DIVISION.",
            "INPUT-OUTPUT SECTION.",
            "FILE-CONTROL.",
            "    SELECT ACCT-FILE ASSIGN TO ACCTDD",
            "        ORGANIZATION IS INDEXED RECORD KEY IS ACCT-KEY.",
            "    SELECT RPT-FILE ASSIGN TO RPTOUT.",
            "DATA DIVISION.",
            "FILE SECTION.",
            "FD  ACCT-FILE RECORD CONTAINS 200 CHARACTERS.",
            "01  ACCT-REC PIC X(200).",
            "FD  RPT-FILE.",
            "01  RPT-LINE PIC X(133).",
            "WORKING-STORAGE SECTION.",
            "01  GU-FUNC   PIC X(4) VALUE 'GU  '.",
            "01  ISRT-FUNC PIC X(4) VALUE 'ISRT'.",
            "01  SSA-CUST  PIC X(9) VALUE 'CUSTOMER '.",
            "01  SSA-ACCT  PIC X(9) VALUE 'ACCOUNT  '.",
            "01  PCB-FUNC  PIC X(4) VALUE 'PCB '.",
            "01  BAT-PSB   PIC X(8) VALUE 'ACCTBPSB'.",
            "PROCEDURE DIVISION.",
            "    OPEN I-O ACCT-FILE OUTPUT RPT-FILE.",
            "    CALL 'CBLTDLI' USING PCB-FUNC BAT-PSB UIB-PTR.",
            "    CALL 'CBLTDLI' USING GU-FUNC DB-PCB IO-AREA SSA-CUST.",
            "    CALL 'CBLTDLI' USING ISRT-FUNC DB-PCB IO-AREA",
            "         SSA-CUST SSA-ACCT.",
            "    STOP RUN.",
        ),
    )
    _write(root / "copy" / "ACCTREC.cpy", fixed("01  ACCT-REC.", "    05  ACCT-ID PIC X(10)."))
    _write(
        root / "pli" / "ACCTPLI.pli",
        " ACCTPLI: PROC OPTIONS(MAIN);\n"
        "   DCL ACCTIN FILE RECORD INPUT TITLE('ACCTDD');\n"
        "   DCL OUTF FILE RECORD OUTPUT;\n"
        "   %INCLUDE ACCTINC;\n"
        "   READ FILE(ACCTIN) INTO(REC);\n"
        "   WRITE FILE(OUTF) FROM(REC);\n"
        "   CALL PLIDATE(D);\n"
        "   FETCH DYNMOD;\n"
        " END ACCTPLI;\n",
    )
    _write(root / "pli" / "ACCTINC.inc", " DCL 1 ACCT_REC,\n     2 ID CHAR(10);\n")
    _write(
        root / "asm" / "ACCTASM.asm",
        "ACCTASM  CSECT\n"
        "         USING *,12\n"
        "         LINK  EP=ACCTSUB\n"
        "         WTO   'ACCOUNT RUN'\n"
        "         ENQ   (QN,RN,E,8,SYSTEM)\n"
        "         SVC   99\n"
        "         COPY  ACCTDS\n"
        "         END\n",
    )
    _write(root / "asm" / "ACCTDS.mac", "ACCTDS   DSECT\nACCTID   DS    CL10\n")
    _write(
        root / "rexx" / "ACCTREXX",
        "/* REXX */\n"
        "\"ALLOC DD(IN) DA('PROD.ACCT.EXTRACT') SHR REUSE\"\n"
        '"EXECIO * DISKR IN (STEM L. FINIS"\n'
        'ADDRESS ISPEXEC "FTINCL ACCTSKEL"\n'
        "\"SUBMIT 'PROD.JCL(ACCTJOB)'\"\n"
        'ADDRESS ISPEXEC "SELECT PGM(ACCTUTIL)"\n',
    )
    _write(
        root / "natural" / "ACCTNAT.nsp",
        "DEFINE DATA LOCAL\n"
        "1 ACCT-V VIEW OF ACCOUNTS\n"
        "  2 ACCT-ID\n"
        "END-DEFINE\n"
        "READ ACCT-V BY ACCT-ID\n"
        "END-READ\n"
        "STORE ACCT-V\n"
        "CALLNAT 'ACCTSUBN' ACCT-ID\n"
        "END\n",
    )
    _write(
        root / "skel" / "ACCTSKEL.skel",
        ")CM ACCOUNT EXTRACT SKELETON\n"
        "//&ZUSER.A JOB (ACCT),'SKEL',CLASS=A\n"
        "//STEP1    EXEC PGM=ACCTBAT\n"
        ")IM ACCTJCLS\n",
    )
    _write(
        root / "jcl" / "ACCTJOB.jcl",
        "//ACCTJOB  JOB (ACCT),'ACCOUNTS',CLASS=A\n"
        "//STEP005  EXEC PGM=IDCAMS\n"
        "//SYSPRINT DD SYSOUT=*\n"
        "//SYSIN    DD *\n"
        "  DEFINE CLUSTER (NAME(PROD.ACCT.KSDS) -\n"
        "         INDEXED KEYS(10 0) -\n"
        "         RECORDSIZE(150 150) -\n"
        "         SHAREOPTIONS(2 3))\n"
        "/*\n"
        "//STEP010  EXEC PGM=ACCTBAT\n"
        "//ACCTDD   DD DSN=PROD.ACCT.KSDS,DISP=OLD\n"
        "//RATES    DD DSN=PROD.RATES.TABLE,DISP=SHR\n"
        "//RPTOUT   DD SYSOUT=A,DEST=RMT1\n"
        "//STEP015  EXEC PGM=ACCTPLI\n"
        "//ACCTDD   DD DSN=PROD.ACCT.KSDS,DISP=SHR\n"
        "//OUTF     DD DSN=PROD.ACCT.PLIOUT,DISP=(NEW,CATLG,DELETE)\n"
        "//STEP020  EXEC PGM=SORT\n"
        "//SORTIN   DD DSN=PROD.ACCT.KSDS,DISP=SHR\n"
        "//SORTOUT  DD DSN=PROD.ACCT.EXTRACT,DISP=(NEW,CATLG,DELETE)\n"
        "//SYSIN    DD *\n"
        "  SORT FIELDS=(1,10,CH,A)\n"
        "/*\n"
        "//STEP030  EXEC PGM=FTP,PARM='FTP.EXAMPLE.COM (EXIT'\n"
        "//INPUT    DD *\n"
        "put 'PROD.ACCT.EXTRACT' acct.csv\n"
        "quit\n"
        "/*\n"
        "//STEP040  EXEC PGM=IKJEFT01\n"
        "//SYSTSIN  DD *\n"
        "  DSN SYSTEM(DB2P)\n"
        "  BIND PACKAGE(ACCTCOLL) MEMBER(ACCTUPD) VALIDATE(BIND) -\n"
        "       ISOLATION(CS)\n"
        "  END\n"
        "/*\n",
    )
    _write(
        root / "jcl" / "OLDJOB.jcl",
        "//OLDJOB   JOB (ACCT),'OLD',CLASS=A\n"
        "//   SET HLQ=PROD\n"
        "//STEP010  EXEC PGM=IEFBR14\n"
        "//DD1      DD DSN=&HLQ..OLD.FILE,DISP=(MOD,DELETE,DELETE)\n"
        "//DD2      DD DSN=&&TEMP,DISP=(NEW,PASS)\n",
    )
    _write(
        root / "csd" / "ACCTCSD.csd",
        "* CSD EXTRACT FOR GROUP ACCT\n"
        "DEFINE TRANSACTION(AUPD) GROUP(ACCT)\n"
        "       PROGRAM(ACCTUPD)\n"
        "DEFINE URIMAP(ACCTURI) GROUP(ACCT) USAGE(SERVER) PATH(/acct/*)\n"
        "       PROGRAM(ACCTAPI)\n"
        "DEFINE PROGRAM(ACCTUPD) GROUP(ACCT) LANGUAGE(COBOL)\n"
        "DEFINE PROGRAM(ACCTAPI) GROUP(ACCT) LANGUAGE(COBOL)\n"
        "       CONCURRENCY(THREADSAFE)\n"
        "DEFINE FILE(ACCTFIL) GROUP(ACCT) DESCRIPTION(Accounts - add and update)\n"
        "       DSNAME(PROD.ACCT.KSDS) ADD(YES) UPDATE(YES) DELETE(NO)\n"
        "DEFINE TRANSACTION(REMT) GROUP(ACCT) PROGRAM(REMPGM)\n"
        "       REMOTESYSTEM(CICB)\n"
        "DEFINE TDQUEUE(ATRG) GROUP(ACCT) TYPE(INTRA) TRIGGERLEVEL(1)\n"
        "       TRANSID(APRT)\n"
        "ADD GROUP(ACCT) LIST(PRODLIST)\n",
    )
    _write(
        root / "mq" / "ACCTQ.mqsc",
        "* QUEUE DEFINITIONS\n"
        "DEFINE QLOCAL('ACCT.EVENTS') +\n"
        "       TRIGGER PROCESS('ACCT.PROC') +\n"
        "       INITQ('SYSTEM.CICS.INITIATION.QUEUE') +\n"
        "       BOQNAME('ACCT.BACKOUT')\n"
        "DEFINE PROCESS('ACCT.PROC') APPLICID('ACCTMQ') APPLTYPE(CICS)\n"
        "DEFINE QREMOTE('ACCT.TO.DIST') RNAME('DIST.IN') RQMNAME('QMDIST')\n",
    )
    _write(
        root / "sched" / "ACCTSCHED.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<DEFTABLE>\n"
        '  <FOLDER FOLDER_NAME="ACCT">\n'
        '    <JOB JOBNAME="ACCTJOB" MEMNAME="ACCTJOB" APPLICATION="ACCT"/>\n'
        "  </FOLDER>\n"
        "</DEFTABLE>\n",
    )
    _write(
        root / "db2" / "ACCTBIND.ctl",
        "DSN SYSTEM(DB2P)\nBIND PLAN(ACCTPLN) PKLIST(ACCTCOLL.*) ACTION(REPLACE)\nEND\n",
    )
    _write(
        root / "listings" / "ACCTCMP.lst",
        "PP 5655-EC6 IBM Enterprise COBOL for z/OS  6.4.0 P230418       ACCTUPD   Date 05/01/2025\n"
        "Invocation parameters:\n"
        " RENT,LIST\n"
        "Options in effect:\n"
        "    NOADATA\n"
        "    ARCH(12)\n"
        "    NODYNAM\n"
        "    RENT\n"
        "    TRUNC(STD)\n"
        "\n"
        " LineID  PL SL  ----+-*A-1-B--+----2----+----3\n"
        " 000001                IDENTIFICATION DIVISION.\n"
        " 000002                PROGRAM-ID. ACCTUPD.\n",
    )
    _write(
        root / "listings" / "ACCTLNK.lst",
        "z/OS V2 R5 BINDER     10:00:00 THURSDAY MAY 1, 2025\n"
        "IEW2278I B352 INVOCATION PARAMETERS - LIST,MAP,XREF\n"
        "IEW2322I 1220  1    NAME ACCTUPD(R)\n"
        "                         *** M O D U L E  M A P ***\n"
        "                         SAVE MODULE ATTRIBUTES:\n"
        "                                   AMODE                 31\n"
        "                                   RMODE                ANY\n",
    )
