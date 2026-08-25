-- lf_report_metrics.sql
-- All queries the weekly Lightfire report needs, parameterized by run window.
-- Target: LP MCP Supabase (lp_leads).
--
-- PARAMETERS (computed in n8n, passed as bind vars):
--   :cohort_set_start    date  -- activity_week_end - 40  (a Sunday)
--   :cohort_set_end      date  -- activity_week_end       (a Saturday)
--   :cohort_appt_cutoff  date  -- run_date - 1
--   :activity_week_start date  -- prior Sunday
--   :activity_week_end   date  -- prior Saturday
--   :prior_week_start    date  -- activity_week_start - 7
--   :prior_week_end      date  -- activity_week_end   - 7
--
-- ============================================================================
-- READ THIS BEFORE CHANGING ANY QUERY
-- ============================================================================
-- 1. TIMEZONE. set_date and appointment_date are timestamptz. EVERY date
--    comparison converts to America/New_York first. A naive ::date cast shifts
--    Sunday sets into Saturday and silently changes the cohort.
-- 2. MATURITY. Outcome metrics (sit, sold, gross) use the 6-week matured
--    cohort, NOT the activity week. An appointment set last Saturday may be
--    scheduled three weeks out. Computing sit % on the activity week reports a
--    number that is mostly "hasn't happened yet." This is the single most
--    important rule in the file.
-- 3. NAME MERGE. Lightfire agents appear under two forms ('Deer - LF, Craig'
--    and 'Deer, Craig'). trim(replace(set_by_name,' - LF','')) merges them.
--    Skip it and every Lightfire agent's numbers split in half.
-- 4. TEAM ASSIGNMENT IS DATA. Join lf_setter_roster. Never hardcode name lists
--    in the query or the workflow — a new hire silently vanishes from the report.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- Q1. BASE COHORT — reused by Q2/Q3/Q4/Q5 as a CTE in the app, or materialize
--     to a temp table. Shown standalone here for clarity.
-- ---------------------------------------------------------------------------
WITH base AS (
  SELECT
    trim(replace(l.set_by_name,' - LF','')) AS setter,
    l.ever_issued, l.ever_sat, l.closed_won,
    coalesce(l.job_value,0)          AS jv,
    l.disposition_code,
    l.confirmed_by_name,
    trim(replace(coalesce(l.confirmed_by_name,''),' - LF','')) AS confirmer
  FROM lp_leads l
  WHERE l.set_by_name IS NOT NULL
    AND (l.set_date AT TIME ZONE 'America/New_York')::date
        BETWEEN :cohort_set_start AND :cohort_set_end
    AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= :cohort_appt_cutoff
),
scoped AS (
  SELECT b.*, r.team, r.roster_flag
  FROM base b
  JOIN lf_setter_roster r ON r.setter_name = b.setter
  WHERE r.team <> 'exclude'
)

-- ---------------------------------------------------------------------------
-- Q2. TEAM TOTALS  -> lf_report_metrics
--     'Reece (W)' rolls into 'Reece' for team totals.
-- ---------------------------------------------------------------------------
SELECT
  CASE WHEN team LIKE 'Reece%' THEN 'Reece' ELSE 'Lightfire' END AS team,
  count(*)                                                          AS matured,
  count(*) FILTER (WHERE ever_issued)                               AS gross_issued,
  count(*) FILTER (WHERE ever_issued AND disposition_code='CXL')    AS cancels_in_issued,
  count(*) FILTER (WHERE ever_issued)
    - count(*) FILTER (WHERE ever_issued AND disposition_code='CXL') AS net_issued,
  count(*) FILTER (WHERE ever_sat)                                  AS sat,
  count(*) FILTER (WHERE closed_won)                                AS sold,
  (sum(jv) FILTER (WHERE closed_won) * 100)::bigint                 AS gross_cents,
  count(*) FILTER (WHERE disposition_code='CXL')                    AS cxl_all,
  count(*) FILTER (WHERE disposition_code='Set')                    AS stranded,
  count(*) FILTER (WHERE confirmed_by_name IS NULL)                 AS no_confirmer,
  count(*) FILTER (WHERE confirmed_by_name IS NOT NULL
                     AND confirmer NOT IN (SELECT setter_name FROM lf_setter_roster WHERE team='Lightfire')
                     AND confirmer NOT IN ('Agent, Revin','Integration, GoHighLevel')) AS confirmed_by_desk,
  count(*) FILTER (WHERE confirmer IN (SELECT setter_name FROM lf_setter_roster WHERE team='Lightfire')) AS self_confirmed,
  count(*) FILTER (WHERE confirmer IN ('Agent, Revin','Integration, GoHighLevel')) AS confirmed_ai_other
FROM scoped
GROUP BY 1;


-- ---------------------------------------------------------------------------
-- Q3. PER-AGENT  -> lf_report_agent_metrics
--     Drives BOTH page-1 (Issued Sit %) and page-3 (ranking, Matured Sit %).
--     Include every setter with matured >= 3. small_denominator = net_issued < 20.
-- ---------------------------------------------------------------------------
SELECT
  setter                                                        AS setter_name,
  max(team)                                                     AS team,
  max(roster_flag)                                              AS roster_flag,
  count(*)                                                      AS matured,
  count(*) FILTER (WHERE ever_issued)                           AS gross_issued,
  count(*) FILTER (WHERE ever_issued AND disposition_code='CXL') AS cancels,
  count(*) FILTER (WHERE ever_issued)
    - count(*) FILTER (WHERE ever_issued AND disposition_code='CXL') AS net_issued,
  count(*) FILTER (WHERE ever_sat)                              AS sat,
  count(*) FILTER (WHERE closed_won)                            AS sold,
  (coalesce(sum(jv) FILTER (WHERE closed_won),0) * 100)::bigint AS gross_cents
FROM scoped
GROUP BY setter
HAVING count(*) >= 3
ORDER BY coalesce(sum(jv) FILTER (WHERE closed_won),0) DESC;
-- App computes: issued_sit_pct = 100*sat/net_issued (NULL if net_issued=0)
--               matured_sit_pct = 100*sat/matured
--               sits_short = greatest(0, 0.80*net_issued - sat)
--               rank_by_gross = row_number() over gross desc


-- ---------------------------------------------------------------------------
-- Q4. CONFIRMATION OWNERSHIP  -> page-2 stacked chart
-- ---------------------------------------------------------------------------
SELECT
  CASE WHEN team LIKE 'Reece%' THEN 'Reece' ELSE 'Lightfire' END AS team,
  CASE
    WHEN confirmed_by_name IS NULL THEN 'no_confirmer'
    WHEN confirmer IN (SELECT setter_name FROM lf_setter_roster WHERE team='Lightfire') THEN 'lightfire_self'
    WHEN confirmer IN ('Agent, Revin','Integration, GoHighLevel') THEN 'ai_other'
    ELSE 'reece_desk'
  END AS who,
  count(*) AS n
FROM scoped GROUP BY 1,2;


-- ---------------------------------------------------------------------------
-- Q5. CONDITIONAL STRAND + OUTCOMES BY CONFIRMATION  -> page-2 table and prose
--     Feeds: strand-given-unconfirmed, and the "0 sales" claim.
-- ---------------------------------------------------------------------------
SELECT
  CASE WHEN team LIKE 'Reece%' THEN 'Reece' ELSE 'Lightfire' END AS team,
  (confirmed_by_name IS NOT NULL)                     AS confirmed,
  count(*)                                            AS n,
  count(*) FILTER (WHERE disposition_code='Set')      AS stranded,
  count(*) FILTER (WHERE ever_issued)                 AS issued,
  count(*) FILTER (WHERE ever_sat)                    AS sat,
  count(*) FILTER (WHERE closed_won)                  AS sold,
  (coalesce(sum(jv) FILTER (WHERE closed_won),0)*100)::bigint AS gross_cents
FROM scoped GROUP BY 1,2;


-- ---------------------------------------------------------------------------
-- Q6. ACTIVITY WEEK — appointments SET, this week vs prior week.
--     NOTE: no maturity filter and no appointment_date filter. This is the
--     only query in the file that measures the reporting week itself.
-- ---------------------------------------------------------------------------
SELECT
  trim(replace(l.set_by_name,' - LF','')) AS setter_name,
  count(*) FILTER (WHERE (l.set_date AT TIME ZONE 'America/New_York')::date
                   BETWEEN :activity_week_start AND :activity_week_end) AS sets_activity_wk,
  count(*) FILTER (WHERE (l.set_date AT TIME ZONE 'America/New_York')::date
                   BETWEEN :prior_week_start AND :prior_week_end)       AS sets_prior_wk
FROM lp_leads l
JOIN lf_setter_roster r ON r.setter_name = trim(replace(l.set_by_name,' - LF',''))
WHERE l.set_by_name IS NOT NULL
  AND r.team <> 'exclude'
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN :prior_week_start AND :activity_week_end
GROUP BY 1;


-- ---------------------------------------------------------------------------
-- Q7. SOURCE-MATCHED SIT (the "are we giving you harder leads" test).
--     Only sources with >= 10 matured on BOTH sides are reportable.
-- ---------------------------------------------------------------------------
SELECT
  l.lead_source_detail AS source,
  count(*) FILTER (WHERE r.team LIKE 'Reece%')                                     AS reece_n,
  round(100.0*count(*) FILTER (WHERE r.team LIKE 'Reece%' AND l.ever_sat)
        / NULLIF(count(*) FILTER (WHERE r.team LIKE 'Reece%'),0),1)                AS reece_sit,
  count(*) FILTER (WHERE r.team='Lightfire')                                       AS lf_n,
  round(100.0*count(*) FILTER (WHERE r.team='Lightfire' AND l.ever_sat)
        / NULLIF(count(*) FILTER (WHERE r.team='Lightfire'),0),1)                  AS lf_sit
FROM lp_leads l
JOIN lf_setter_roster r ON r.setter_name = trim(replace(l.set_by_name,' - LF',''))
WHERE l.set_by_name IS NOT NULL AND r.team <> 'exclude'
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN :cohort_set_start AND :cohort_set_end
  AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= :cohort_appt_cutoff
GROUP BY 1
HAVING count(*) FILTER (WHERE r.team='Lightfire') >= 10
   AND count(*) FILTER (WHERE r.team LIKE 'Reece%') >= 10
ORDER BY lf_n DESC;


-- ---------------------------------------------------------------------------
-- Q8. WEEK-OVER-WEEK DELTA — prior run's snapshot, for the trend line.
--     Returns zero rows on the first ever run; renderer must handle that.
-- ---------------------------------------------------------------------------
SELECT m.team, m.issued_sit_pct, m.matured_sit_pct, m.net_issued, m.sat,
       m.no_confirmer, m.matured, r.activity_week_start
FROM lf_report_metrics m
JOIN lf_report_runs r ON r.id = m.run_id
WHERE r.status IN ('approved','sent')
  AND r.activity_week_start < :activity_week_start
ORDER BY r.activity_week_start DESC
LIMIT 2;
