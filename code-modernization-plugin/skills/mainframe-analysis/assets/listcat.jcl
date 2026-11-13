//*-------------------------------------------------------------------
//* LISTCAT.JCL - Catalog entries, with all attributes, for the data
//* sets in scope: VSAM clusters, alternate indexes, paths, GDG bases,
//* and non-VSAM data sets.
//*
//* The platform team reviews, edits, and submits this job. The agent
//* never submits it. Add the shop's JOB statement above this block.
//*
//* Placeholders:
//*   <HLQ>     High-level qualifier for the output data set.
//*   <PREFIX>  Leading qualifiers of the entries to list. An asterisk
//*             replaces one whole qualifier (A.* or A.*.C). List
//*             several names in ENTRIES, or use LEVEL(<PREFIX>) to
//*             list every entry under the prefix.
//*
//* Output: <HLQ>.LISTCAT.REPORT (RECFM=VBA, LRECL=125). Download it
//* as text. The mainframe-analysis skill's mainframe_inventory.py
//* reads it with the other exports. Delete the data set before a
//* rerun. For several LISTCAT commands in one step, code DISP=MOD.
//*-------------------------------------------------------------------
//LISTCAT  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//LISTOUT  DD DSN=<HLQ>.LISTCAT.REPORT,DISP=(NEW,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(5,5),RLSE),
//            RECFM=VBA,LRECL=125,BLKSIZE=629
//SYSIN    DD *
  LISTCAT ENTRIES(<PREFIX>.*) -
          ALL -
          OUTFILE(LISTOUT)
/*
