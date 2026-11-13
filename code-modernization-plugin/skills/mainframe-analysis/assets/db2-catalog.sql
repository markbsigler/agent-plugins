-- DB2-CATALOG.SQL - Read-only Db2 for z/OS catalog queries for the
-- packages, plans, tables, columns, and indexes in scope. Each query
-- returns one comma-separated text column, so DSNTIAUL writes plain
-- fixed-length text records (CSV without a header row).
--
-- The platform team (a DBA) reviews and runs these queries, for
-- example with db2-catalog-unload.jcl. The agent never runs them.
--
-- Placeholders:
--   <COLLID>  Collection name or LIKE pattern, such as PAY%.
--   <SCHEMA>  Table creator (schema) or LIKE pattern.
--
-- Format: keep every line within columns 1-72 (DSNTEP2 and DSNTIAUL
-- read only the first 72 bytes) and start comment lines with -- in
-- column 1, so that the unload job can drop them.
--
-- Output: one CSV file per query, in the order below; the columns
-- are listed above each query. The agent reads them: query 1 is
-- usage evidence for the mainframe-analysis skill's
-- mainframe_inventory.py --usage, and queries 2-6 feed the Db2
-- sections of the estate brief, the data ownership matrix, and the
-- code page decisions for the copybook-data skill.
--
-- 1. Packages: COLLID,NAME,VERSION,LASTUSED,BINDTIME,ISOLATION,
--    OWNER,QUALIFIER,VALID,OPERATIVE. LASTUSED 0001-01-01 means no
--    recorded use since the package was created; updates can lag by
--    a day or more. ISOLATION R=RR, S=CS, T=RS, U=UR, blank=plan.
SELECT CAST(RTRIM(COLLID) CONCAT ',' CONCAT RTRIM(NAME)
       CONCAT ',' CONCAT RTRIM(VERSION)
       CONCAT ',' CONCAT CHAR(LASTUSED, ISO)
       CONCAT ',' CONCAT CHAR(BINDTIME)
       CONCAT ',' CONCAT ISOLATION
       CONCAT ',' CONCAT RTRIM(OWNER)
       CONCAT ',' CONCAT RTRIM(QUALIFIER)
       CONCAT ',' CONCAT VALID CONCAT ',' CONCAT OPERATIVE
       AS CHAR(255))
  FROM SYSIBM.SYSPACKAGE
 WHERE COLLID LIKE '<COLLID>'
 ORDER BY COLLID, NAME, VERSION
  WITH UR;

-- 2. Package dependencies on tables, views, aliases, and synonyms:
--    DCOLLID,DNAME,BQUALIFIER,BNAME,BTYPE. BTYPE T=table, V=view,
--    M=materialized query table, A=alias, S=synonym. DTYPE O and P
--    rows belong to original and previous package copies.
SELECT DISTINCT
       CAST(RTRIM(DCOLLID) CONCAT ',' CONCAT RTRIM(DNAME)
       CONCAT ',' CONCAT RTRIM(BQUALIFIER)
       CONCAT ',' CONCAT RTRIM(BNAME)
       CONCAT ',' CONCAT BTYPE
       AS CHAR(255))
  FROM SYSIBM.SYSPACKDEP
 WHERE DCOLLID LIKE '<COLLID>'
   AND BTYPE IN ('T', 'V', 'M', 'A', 'S')
   AND DTYPE NOT IN ('O', 'P')
 ORDER BY 1
  WITH UR;

-- 3. Plan package lists: PLANNAME,SEQNO,COLLID,NAME. NAME * means
--    every package in the collection.
SELECT CAST(RTRIM(PLANNAME) CONCAT ',' CONCAT RTRIM(CHAR(SEQNO))
       CONCAT ',' CONCAT RTRIM(COLLID)
       CONCAT ',' CONCAT RTRIM(NAME)
       AS CHAR(255))
  FROM SYSIBM.SYSPACKLIST
 WHERE COLLID LIKE '<COLLID>'
 ORDER BY PLANNAME, SEQNO
  WITH UR;

-- 4. Tables, views, and aliases: CREATOR,NAME,TYPE,DBNAME,TSNAME,
--    ENCODING_SCHEME,CARDF,TBCREATOR,TBNAME. TYPE T=table, V=view,
--    M=materialized query table, A=alias (TBCREATOR and TBNAME name
--    its target). ENCODING_SCHEME E=EBCDIC, A=ASCII, U=Unicode.
--    CARDF is the row count from statistics; -1 means none.
SELECT CAST(RTRIM(CREATOR) CONCAT ',' CONCAT RTRIM(NAME)
       CONCAT ',' CONCAT TYPE
       CONCAT ',' CONCAT RTRIM(DBNAME)
       CONCAT ',' CONCAT RTRIM(TSNAME)
       CONCAT ',' CONCAT ENCODING_SCHEME
       CONCAT ',' CONCAT RTRIM(CHAR(BIGINT(CARDF)))
       CONCAT ',' CONCAT RTRIM(TBCREATOR)
       CONCAT ',' CONCAT RTRIM(TBNAME)
       AS CHAR(255))
  FROM SYSIBM.SYSTABLES
 WHERE CREATOR LIKE '<SCHEMA>'
   AND TYPE IN ('T', 'V', 'M', 'A')
 ORDER BY CREATOR, NAME
  WITH UR;

-- 5. Columns: TBCREATOR,TBNAME,COLNO,NAME,COLTYPE,LENGTH,SCALE,
--    NULLS,CCSID,FOREIGNKEY. For DECIMAL, LENGTH is the precision.
--    CCSID 0 means a non-string column or one created before DB2
--    Version 8. FOREIGNKEY on character columns: B=bit data,
--    S=single-byte, M=mixed single- and double-byte data.
SELECT CAST(RTRIM(C.TBCREATOR) CONCAT ',' CONCAT RTRIM(C.TBNAME)
       CONCAT ',' CONCAT RTRIM(CHAR(C.COLNO))
       CONCAT ',' CONCAT RTRIM(C.NAME)
       CONCAT ',' CONCAT RTRIM(C.COLTYPE)
       CONCAT ',' CONCAT RTRIM(CHAR(C.LENGTH))
       CONCAT ',' CONCAT RTRIM(CHAR(C.SCALE))
       CONCAT ',' CONCAT C.NULLS
       CONCAT ',' CONCAT RTRIM(CHAR(C.CCSID))
       CONCAT ',' CONCAT C.FOREIGNKEY
       AS CHAR(255))
  FROM SYSIBM.SYSCOLUMNS C
 WHERE C.TBCREATOR LIKE '<SCHEMA>'
 ORDER BY C.TBCREATOR, C.TBNAME, C.COLNO
  WITH UR;

-- 6. Index keys: TBCREATOR,TBNAME,CREATOR,NAME,UNIQUERULE,
--    CLUSTERING,COLSEQ,COLNAME,ORDERING. UNIQUERULE D=duplicates
--    allowed, P=primary key, other values=unique. ORDERING
--    A=ascending, D=descending, R=random.
SELECT CAST(RTRIM(I.TBCREATOR) CONCAT ',' CONCAT RTRIM(I.TBNAME)
       CONCAT ',' CONCAT RTRIM(I.CREATOR)
       CONCAT ',' CONCAT RTRIM(I.NAME)
       CONCAT ',' CONCAT I.UNIQUERULE
       CONCAT ',' CONCAT I.CLUSTERING
       CONCAT ',' CONCAT RTRIM(CHAR(K.COLSEQ))
       CONCAT ',' CONCAT RTRIM(K.COLNAME)
       CONCAT ',' CONCAT K.ORDERING
       AS CHAR(255))
  FROM SYSIBM.SYSINDEXES I
  JOIN SYSIBM.SYSKEYS K
    ON K.IXCREATOR = I.CREATOR
   AND K.IXNAME = I.NAME
 WHERE I.TBCREATOR LIKE '<SCHEMA>'
 ORDER BY I.TBCREATOR, I.TBNAME, I.NAME, K.COLSEQ
  WITH UR;
