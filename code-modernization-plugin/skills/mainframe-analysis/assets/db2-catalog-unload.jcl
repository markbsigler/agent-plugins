//*-------------------------------------------------------------------
//* DB2-CATALOG-UNLOAD.JCL - Runs the read-only catalog queries in
//* db2-catalog.sql and writes one comma-separated text data set per
//* query. Step STRIP copies the SQL member without its comment lines,
//* because DSNTIAUL documents only bracketed comments; step UNLOAD
//* runs DSNTIAUL with PARMS('SQL') under the TSO terminal monitor.
//*
//* The platform team (a DBA) reviews, edits, and submits this job.
//* The agent never submits it. Add the shop's JOB statement above
//* this block.
//*
//* Placeholders:
//*   <SQL.PDS>        PDS (RECFM=FB, LRECL=80) that holds
//*                    db2-catalog.sql as member DB2CAT.
//*   <SSID>           Db2 subsystem or group attachment name.
//*   <DB2.SDSNEXIT>   Db2 exit library.
//*   <DB2.SDSNLOAD>   Db2 load library. Remove the STEPLIB if both
//*                    libraries are in the link list.
//*   <DSNTIAUL.PLAN>  Plan bound for DSNTIAUL at installation.
//*   <RUNLIB.LOAD>    Library that holds the DSNTIAUL load module.
//*   <HLQ>            High-level qualifier for the output data sets.
//*
//* Output: SYSREC00 to SYSREC05 receive queries 1 to 6 in order;
//* keep exactly one SYSRECnn DD per SELECT. Download them as text:
//* trailing blanks are dropped, leaving CSV lines. The agent reads
//* them; DB2CAT.PACKAGES is usage evidence for the mainframe-analysis
//* skill's mainframe_inventory.py --usage. SYSPUNCH lists the LOAD
//* statements that describe each record. Delete the output data sets
//* before a rerun.
//*-------------------------------------------------------------------
//STRIP    EXEC PGM=SORT
//SYSOUT   DD SYSOUT=*
//SORTIN   DD DISP=SHR,DSN=<SQL.PDS>(DB2CAT)
//SORTOUT  DD DSN=&&SQL,DISP=(NEW,PASS),UNIT=SYSDA,
//            SPACE=(TRK,(1,1))
//SYSIN    DD *
  OPTION COPY
  OMIT COND=(1,2,CH,EQ,C'--')
/*
//UNLOAD   EXEC PGM=IKJEFT01,DYNAMNBR=20,COND=(4,LT)
//STEPLIB  DD DISP=SHR,DSN=<DB2.SDSNEXIT>
//         DD DISP=SHR,DSN=<DB2.SDSNLOAD>
//SYSTSPRT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSUDUMP DD SYSOUT=*
//SYSPUNCH DD SYSOUT=*
//SYSIN    DD DSN=&&SQL,DISP=(OLD,DELETE)
//SYSREC00 DD DSN=<HLQ>.DB2CAT.PACKAGES,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(5,5),RLSE)
//SYSREC01 DD DSN=<HLQ>.DB2CAT.PKGDEPS,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(5,5),RLSE)
//SYSREC02 DD DSN=<HLQ>.DB2CAT.PLANPKGS,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(1,1),RLSE)
//SYSREC03 DD DSN=<HLQ>.DB2CAT.TABLES,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(1,1),RLSE)
//SYSREC04 DD DSN=<HLQ>.DB2CAT.COLUMNS,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(10,10),RLSE)
//SYSREC05 DD DSN=<HLQ>.DB2CAT.INDEXES,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(5,5),RLSE)
//SYSTSIN  DD *
 DSN SYSTEM(<SSID>)
 RUN PROGRAM(DSNTIAUL) PLAN(<DSNTIAUL.PLAN>) PARMS('SQL') -
     LIB('<RUNLIB.LOAD>')
 END
/*
