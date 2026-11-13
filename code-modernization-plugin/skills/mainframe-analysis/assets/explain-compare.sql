-- EXPLAIN-COMPARE.SQL - Access paths of one package before and after
-- a rebind (or a recompile and bind), compared step by step by
-- QUERYNO from PLAN_TABLE rows written by EXPLAIN(YES) or
-- EXPLAIN(ONLY) binds. The queries only read PLAN_TABLE.
--
-- The platform team (a DBA) reviews and runs these queries, with
-- DSNTEP2 or any SQL tool. The agent never runs them.
--
-- Placeholders:
--   <OWNER>      Owner of the PLAN_TABLE (the package owner).
--   <COLLID>     Collection of the package.
--   <PROGRAM>    Package name (PROGNAME in PLAN_TABLE).
--   <BEFORE_TS>  EXPLAIN_TIME of the old access paths (query 1).
--   <AFTER_TS>   EXPLAIN_TIME of the new access paths (query 1),
--                in the form 2026-11-13-10.55.00.123456.
--
-- Rebind options: REBIND PACKAGE with EXPLAIN(YES) and APCOMPARE(WARN)
-- or APCOMPARE(ERROR) reports statements whose access paths differ
-- (message DSNT285I, details in PLAN_TABLE.REMARKS). APREUSE(WARN)
-- or APREUSE(ERROR) reuses the previous access paths where possible
-- (HINT_USED is APREUSE). EXPLAIN(ONLY) writes PLAN_TABLE rows
-- without replacing the package. With package copies kept,
-- REBIND ... SWITCH(PREVIOUS) restores the old access paths.
--
-- QUERYNO comes from the statement number in the source. It is
-- stable across a rebind, but a recompiled program can renumber its
-- statements, and numbers above 32767 show as 0; match those
-- statements by text instead.
--
-- Output: the agent reads the result as Refactor Stage 3 and 4
-- evidence (mainframe-analysis references/performance-cost.md).
--
-- 1. EXPLAIN runs on record for the package.
SELECT EXPLAIN_TIME, VERSION, COUNT(*) AS PLAN_ROWS
  FROM <OWNER>.PLAN_TABLE
 WHERE COLLID = '<COLLID>'
   AND PROGNAME = '<PROGRAM>'
 GROUP BY EXPLAIN_TIME, VERSION
 ORDER BY EXPLAIN_TIME DESC
  WITH UR;

-- 2. Steps whose join method, table, access type, index, matching
--    columns, index-only access, or prefetch changed, appeared, or
--    disappeared. METHOD 0=first table, 1=nested loop, 2=merge
--    scan, 3=sort, 4=hybrid join. ACCESSTYPE I=index, I1=one-fetch
--    index, N=index with IN list, R=table space scan, M=multiple
--    index. PREFETCH S=sequential, L=list, D=dynamic.
WITH OLDPATH AS (
  SELECT QUERYNO, QBLOCKNO, PLANNO, MIXOPSEQ, METHOD, TNAME,
         ACCESSTYPE, ACCESSNAME, MATCHCOLS, INDEXONLY, PREFETCH
    FROM <OWNER>.PLAN_TABLE
   WHERE COLLID = '<COLLID>' AND PROGNAME = '<PROGRAM>'
     AND EXPLAIN_TIME = '<BEFORE_TS>'),
NEWPATH AS (
  SELECT QUERYNO, QBLOCKNO, PLANNO, MIXOPSEQ, METHOD, TNAME,
         ACCESSTYPE, ACCESSNAME, MATCHCOLS, INDEXONLY, PREFETCH
    FROM <OWNER>.PLAN_TABLE
   WHERE COLLID = '<COLLID>' AND PROGNAME = '<PROGRAM>'
     AND EXPLAIN_TIME = '<AFTER_TS>')
SELECT COALESCE(O.QUERYNO, N.QUERYNO) AS QUERYNO,
       COALESCE(O.QBLOCKNO, N.QBLOCKNO) AS QBLOCKNO,
       COALESCE(O.PLANNO, N.PLANNO) AS PLANNO,
       COALESCE(O.MIXOPSEQ, N.MIXOPSEQ) AS MIXOPSEQ,
       O.METHOD AS OLD_METHOD, N.METHOD AS NEW_METHOD,
       O.TNAME AS OLD_TABLE, N.TNAME AS NEW_TABLE,
       O.ACCESSTYPE AS OLD_TYPE, N.ACCESSTYPE AS NEW_TYPE,
       O.ACCESSNAME AS OLD_INDEX, N.ACCESSNAME AS NEW_INDEX,
       O.MATCHCOLS AS OLD_MATCH, N.MATCHCOLS AS NEW_MATCH,
       O.INDEXONLY AS OLD_IXONLY, N.INDEXONLY AS NEW_IXONLY,
       O.PREFETCH AS OLD_PREFETCH, N.PREFETCH AS NEW_PREFETCH
  FROM OLDPATH O
  FULL OUTER JOIN NEWPATH N
    ON O.QUERYNO = N.QUERYNO
   AND O.QBLOCKNO = N.QBLOCKNO
   AND O.PLANNO = N.PLANNO
   AND O.MIXOPSEQ = N.MIXOPSEQ
 WHERE O.QUERYNO IS NULL OR N.QUERYNO IS NULL
    OR O.METHOD <> N.METHOD OR O.TNAME <> N.TNAME
    OR O.ACCESSTYPE <> N.ACCESSTYPE
    OR O.ACCESSNAME <> N.ACCESSNAME
    OR O.MATCHCOLS <> N.MATCHCOLS
    OR O.INDEXONLY <> N.INDEXONLY
    OR O.PREFETCH <> N.PREFETCH
 ORDER BY 1, 2, 3, 4
  WITH UR;
