//*-------------------------------------------------------------------
//* COMPARE-OUTPUTS.JCL - Compares a golden-master data set (OLDDD)
//* with the output of a new run (NEWDD) record by record with SuperC
//* (ISRSUPC). Return code 0: no differences; 1: differences found
//* (see the listing); 4 or higher: warning or error.
//*
//* The platform team reviews, edits, and submits this job. The agent
//* never submits it. Add the shop's JOB statement above this block.
//*
//* Placeholders:
//*   <ISPF.LOAD>   ISPF load library that holds ISRSUPC. Remove the
//*                 STEPLIB if ISRSUPC is in the link list.
//*   <NEW.DSN>     Output of the candidate run.
//*   <GOLDEN.DSN>  Baseline output from the legacy run.
//*
//* Mask volatile fields (run dates, times, job numbers) by enabling
//* the CMPCOLM or DPLINE process statements in SYSIN; lines that
//* start with .* are comments. NOSEQ compares columns 73-80 of
//* 80-byte records as data.
//*
//* Output: the delta listing in OUTDD (job output). Download it as
//* text for the agent. SuperC compares bytes: it shows that a record
//* with packed-decimal fields differs, not which field or value. For
//* field-level results, download both data sets in binary and run
//* the copybook-data skill's record_compare.py with the copybook
//* layout.
//*-------------------------------------------------------------------
//SUPERC   EXEC PGM=ISRSUPC,PARM=('LINECMP,DELTAL,NOSEQ')
//STEPLIB  DD DISP=SHR,DSN=<ISPF.LOAD>
//NEWDD    DD DISP=SHR,DSN=<NEW.DSN>
//OLDDD    DD DISP=SHR,DSN=<GOLDEN.DSN>
//OUTDD    DD SYSOUT=*
//SYSIN    DD *
.* CMPCOLM 1:120
.* DPLINE 'RUN DATE'
/*
