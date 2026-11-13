//*-------------------------------------------------------------------
//* MQSC-EXPORT.JCL - Dumps the object definitions of a running queue
//* manager as MQSC commands with CSQUTIL COMMAND MAKEDEF: DEFINE
//* NOREPLACE for objects, ALTER for the queue manager, and SET for
//* channel authentication records. The DISPLAY commands only read.
//* No definitions are produced for dynamic queues or for channels
//* that were defined automatically.
//*
//* The MQ administrators review, edit, and submit this job. The agent
//* never submits it. Add the shop's JOB statement above this block.
//*
//* Placeholders:
//*   <QMGR>    Queue manager (subsystem) name.
//*   <MQ.HLQ>  MQ installation high-level qualifier.
//*   <HLQ>     High-level qualifier for the output data set.
//*
//* Remove the QSGDISP(GROUP), QSGDISP(SHARED), and CFSTRUCT lines if
//* the queue manager is not in a queue-sharing group. The user ID
//* needs access to the command server queues (SYSTEM.COMMAND.INPUT,
//* SYSTEM.COMMAND.REPLY.MODEL, SYSTEM.CSQUTIL.*) and to the DISPLAY
//* commands.
//*
//* Output: <HLQ>.<QMGR>.MQSC (RECFM=FB, LRECL=80). Download it as
//* text. The mainframe-analysis skill's mainframe_inventory.py reads
//* the MQSC definitions.
//*-------------------------------------------------------------------
//MAKEDEF  EXEC PGM=CSQUTIL,PARM='<QMGR>'
//STEPLIB  DD DISP=SHR,DSN=<MQ.HLQ>.SCSQANLE
//         DD DISP=SHR,DSN=<MQ.HLQ>.SCSQAUTH
//OUTPUT1  DD DSN=<HLQ>.<QMGR>.MQSC,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(1,1),RLSE),
//            RECFM=FB,LRECL=80
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
COMMAND DDNAME(CMDINP) MAKEDEF(OUTPUT1)
/*
//CMDINP   DD *
DISPLAY STGCLASS(*) ALL QSGDISP(QMGR)
DISPLAY STGCLASS(*) ALL QSGDISP(GROUP)
DISPLAY CFSTRUCT(*) ALL
DISPLAY QUEUE(*) ALL QSGDISP(QMGR)
DISPLAY QUEUE(*) ALL QSGDISP(GROUP)
DISPLAY QUEUE(*) ALL QSGDISP(SHARED)
DISPLAY TOPIC(*) ALL QSGDISP(QMGR)
DISPLAY TOPIC(*) ALL QSGDISP(GROUP)
DISPLAY NAMELIST(*) ALL QSGDISP(QMGR)
DISPLAY NAMELIST(*) ALL QSGDISP(GROUP)
DISPLAY PROCESS(*) ALL QSGDISP(QMGR)
DISPLAY PROCESS(*) ALL QSGDISP(GROUP)
DISPLAY CHANNEL(*) ALL QSGDISP(QMGR)
DISPLAY CHANNEL(*) ALL QSGDISP(GROUP)
DISPLAY AUTHINFO(*) ALL QSGDISP(QMGR)
DISPLAY AUTHINFO(*) ALL QSGDISP(GROUP)
DISPLAY CHLAUTH('*') ALL
DISPLAY SUB(*) SUBTYPE(ADMIN) ALL DISTYPE(DEFINED)
DISPLAY QMGR ALL
/*
