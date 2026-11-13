//*-------------------------------------------------------------------
//* CSD-EXTRACT.JCL - CICS resource definitions from the CSD, written
//* as DEFINE commands. DFHCSDUP EXTRACT calls the supplied COBOL
//* program DFH0CBDC (executable in SDFHLOAD), which writes DEFINE
//* commands to the CBDOUT DD. The CSD is opened read-only.
//*
//* The platform team reviews, edits, and submits this job. The agent
//* never submits it. Add the shop's JOB statement above this block.
//*
//* Placeholders:
//*   <CICS.HLQ>  CICS installation high-level qualifier.
//*   <CSD.DSN>   CSD data set that the regions use.
//*   <HLQ>       High-level qualifier for the output data set.
//*   <LIST>      One group list from the region's GRPLIST system
//*               initialization parameter. With OBJECTS the list
//*               name cannot be generic: code one EXTRACT per list,
//*               or GROUP(<GROUP>) per group (generic names allowed).
//*
//* Output: <HLQ>.CSD.DEFINES, the DEFINE commands of every EXTRACT
//* (DISP=MOD appends; DFH0CBDC supplies the record format). Download
//* it as text. The mainframe-analysis skill's mainframe_inventory.py
//* reads the DEFINE statements. Groups later in a list override
//* duplicate definitions in earlier groups. Delete the data set
//* before a rerun. For a printed report instead, replace EXTRACT
//* with LIST LIST(<LIST>) OBJECTS (output in SYSPRINT).
//*-------------------------------------------------------------------
//EXTRACT  EXEC PGM=DFHCSDUP,REGION=0M,
//             PARM='CSD(READONLY),PAGESIZE(60),NOCOMPAT'
//STEPLIB  DD DISP=SHR,DSN=<CICS.HLQ>.SDFHLOAD
//DFHCSD   DD DISP=SHR,DSN=<CSD.DSN>
//CBDOUT   DD DSN=<HLQ>.CSD.DEFINES,DISP=(MOD,CATLG,DELETE),
//            UNIT=SYSDA,SPACE=(CYL,(2,2),RLSE)
//SYSABOUT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  EXTRACT LIST(<LIST>) USERPROGRAM(DFH0CBDC) OBJECTS
/*
