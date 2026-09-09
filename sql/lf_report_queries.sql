-- sql/lf_report_queries.sql
-- Production queries for the weekly Lightfire report. Under the Phase-E
-- adaptation these run from the RENDER SERVICE (services/lf-report-render/db.py),
-- not from n8n Postgres nodes — the service owns all LP I/O over the IPv4
-- pooler as lf_report_svc. This file is the canonical, reviewable copy; db.py
-- mirrors it verbatim except that (a) it composes the Q1 base CTE into each of
-- Q2/Q3/Q5/Q5b because a WITH clause binds to a single statement, and (b) it
-- doubles percent literals (LIKE 'Reece%%') since those statements also carry
-- %(name)s parameters. Keep the two in sync.
--
-- Derived from the handoff's lf_report_metrics.sql with corrections, all
-- documented in docs/REPORT_SPEC.md:
--
--   1. Q3's HAVING count(*) >= 3 is now >= 1 (Mark, 2026-08-18): snapshots
--      store every agent with activity; display filtering happens in the
--      render service from lf_report_config.min_matured_for_table.
--   2. Q3 also emits per-agent no_confirmer and stranded — the headline
--      selector and the Lightfire accountability box need them.
--   3. Q8 as shipped referenced columns that do not exist in the V2 schema
--      (lf_report_metrics.issued_sit_pct, lf_report_runs.activity_week_start,
--      lowercase statuses). Rewritten against lf_weekly_team_metrics +
--      lf_report_runs per §9's trend-source rule.
--
-- PARAMETERS (computed by Workflow 01's window Code node, ET calendar dates):
--   :cohort_set_start :cohort_set_end :cohort_appt_cutoff
--   :activity_week_start :activity_week_end :prior_week_start :prior_week_end
--
-- RULES (from the shipped file — unchanged and load-bearing):
--   TIMEZONE: every date comparison converts first:
--     (l.set_date AT TIME ZONE 'America/New_York')::date
--   MATURITY: outcome metrics use the cohort, never the activity week.
--   NAME MERGE: trim(replace(set_by_name,' - LF','')) — skip it and every
--     Lightfire agent's numbers split in half.
--   TEAM ASSIGNMENT IS DATA: join lf_setter_roster; never hardcode names.

-- ---------------------------------------------------------------------------
-- Q1. BASE COHORT (CTE reused by Q2/Q3/Q4/Q5/Q7)
-- ---------------------------------------------------------------------------
WITH base AS (
  SELECT
    trim(replace(l.set_by_name,' - LF','')) AS setter,
    l.ever_issued, l.ever_sat, l.closed_won,
    coalesce(l.job_value,0)          AS jv,
    l.disposition_code,
    l.confirmed_by_name,
    l.lead_source_detail,
    trim(replace(coalesce(l.confirmed_by_name,''),' - LF','')) AS confirmer
  FROM lp_leads l
  WHERE l.set_by_name IS NOT NULL
    AND (l.set_date AT TIME ZONE 'America/New_York')::date
        BETWEEN :cohort_set_start AND :cohort_set_end
    AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= :cohort_appt_cutoff
),
scoped AS (
  SELECT b.*, r.team, r.roster_flag, r.display_name
  FROM base b
  JOIN lf_setter_roster r ON r.setter_name = b.setter
  WHERE r.team <> 'exclude'
)

-- ---------------------------------------------------------------------------
-- Q2. TEAM TOTALS ('Reece (W)' rolls into 'Reece')
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
-- Q3. PER-AGENT (HAVING >= 1; adds no_confirmer + stranded)
-- ---------------------------------------------------------------------------
SELECT
  setter                                                        AS setter_name,
  max(display_name)                                             AS display_name,
  max(team)                                                     AS team,
  max(roster_flag)                                              AS roster_flag,
  count(*)                                                      AS matured,
  count(*) FILTER (WHERE ever_issued)                           AS gross_issued,
  count(*) FILTER (WHERE ever_issued AND disposition_code='CXL') AS cancels,
  count(*) FILTER (WHERE ever_issued)
    - count(*) FILTER (WHERE ever_issued AND disposition_code='CXL') AS net_issued,
  count(*) FILTER (WHERE ever_sat)                              AS sat,
  count(*) FILTER (WHERE closed_won)                            AS sold,
  (coalesce(sum(jv) FILTER (WHERE closed_won),0) * 100)::bigint AS gross_cents,
  count(*) FILTER (WHERE confirmed_by_name IS NULL)             AS no_confirmer,
  count(*) FILTER (WHERE disposition_code='Set')                AS stranded
FROM scoped
GROUP BY setter
HAVING count(*) >= 1
ORDER BY coalesce(sum(jv) FILTER (WHERE closed_won),0) DESC;

-- ---------------------------------------------------------------------------
-- Q4. CONFIRMATION OWNERSHIP (page-2 chart)
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
-- Q5. OUTCOMES BY CONFIRMATION (confirmed/unconfirmed splits per team)
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
-- Q5b. SELF-GENERATED SLICE + STRANDED-ON-REECE-LEADS (page-2 boxes)
-- ---------------------------------------------------------------------------
SELECT
  count(*) FILTER (WHERE lead_source_detail = 'Self Generated')                          AS selfgen_matured,
  count(*) FILTER (WHERE lead_source_detail = 'Self Generated'
                     AND confirmed_by_name IS NULL)                                      AS selfgen_no_confirmer,
  count(*) FILTER (WHERE lead_source_detail = 'Self Generated'
                     AND disposition_code = 'Set')                                       AS selfgen_stranded,
  count(*) FILTER (WHERE disposition_code = 'Set'
                     AND coalesce(lead_source_detail,'') <> 'Self Generated')            AS stranded_on_reece_leads
FROM scoped
WHERE team = 'Lightfire';

-- ---------------------------------------------------------------------------
-- Q6. ACTIVITY WEEK — sets this week vs prior week (the only reporting-week
--     query; no maturity filter, no appointment_date filter). Emits team so
--     the service can count Lightfire ACTIVE setters for Phase-1 staffing:
--     an agent can set appointments this week yet have zero matured in the
--     cohort (all their appointments still in the future), so they are absent
--     from Q3 but must still count toward staffing.
-- ---------------------------------------------------------------------------
SELECT
  trim(replace(l.set_by_name,' - LF','')) AS setter_name,
  max(r.team)                             AS team,
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
-- Q7. SOURCE-MATCHED SIT (counts, not percentages — the service standardises)
-- ---------------------------------------------------------------------------
SELECT
  l.lead_source_detail AS source,
  count(*)  FILTER (WHERE r.team LIKE 'Reece%')                    AS reece_n,
  count(*)  FILTER (WHERE r.team LIKE 'Reece%' AND l.ever_sat)     AS reece_sat,
  count(*)  FILTER (WHERE r.team='Lightfire')                      AS lf_n,
  count(*)  FILTER (WHERE r.team='Lightfire' AND l.ever_sat)       AS lf_sat
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
-- Q8. PRIOR APPROVED SNAPSHOT (§9 trend source) — REWRITTEN for the V2 schema.
--     Frozen numbers only; never recomputed from live lp_leads (D3). Returns
--     zero rows on the first ever run.
-- ---------------------------------------------------------------------------
SELECT r.period_start, r.period_end, r.status,
       m.team, m.issued_sit_pct, m.matured_sit_pct, m.net_issued, m.sat,
       m.no_confirmer, m.matured, m.active_agents
FROM lf_report_runs r
JOIN lf_weekly_team_metrics m ON m.run_id = r.id
WHERE r.status IN ('APPROVED','SENT')
  AND r.period_start < :activity_week_start
  AND r.partner_id = (SELECT id FROM lf_partners WHERE slug = 'lightfire')
ORDER BY r.period_start DESC
LIMIT 2;

-- ---------------------------------------------------------------------------
-- Q9. UNMAPPED SETTERS (validation gate #3 — hard failure when non-empty)
-- ---------------------------------------------------------------------------
SELECT trim(replace(l.set_by_name,' - LF','')) AS unmapped_setter, count(*) AS matured
FROM lp_leads l
WHERE l.set_by_name IS NOT NULL
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN :cohort_set_start AND :cohort_set_end
  AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= :cohort_appt_cutoff
  AND trim(replace(l.set_by_name,' - LF','')) NOT IN (SELECT setter_name FROM lf_setter_roster)
GROUP BY 1 ORDER BY 2 DESC;
