"""LP Supabase data access for the render service (Phase-E adaptation).

Why the render service owns LP I/O instead of n8n: the n8n instance cannot
reach LP Postgres (Supabase direct connections are IPv6-only; the n8n Railway
container has no IPv6 route), and the n8n workflow API refuses to attach
generic HTTP-auth credentials programmatically. So this service — not n8n —
reads lp_leads and writes the lf_* state, connecting as the dedicated
least-privilege role lf_report_svc over Supabase's IPv4 session pooler. The
password lives only in the Railway env var SUPABASE_DB_URL, never in git and
never in n8n JSON. n8n stays orchestration-only (triggers, HTTP, Gmail).

All SQL lives here so the queries are inspectable and diff-reviewable in one
place — the same reasoning that keeps the §14 reply parser in parsing.py. The
canonical query text is mirrored in sql/lf_report_queries.sql; the base cohort
CTE that Q2-Q5b share is composed here because a WITH clause binds to a single
statement. Percent literals in LIKE are doubled (%%) because these statements
also carry %(name)s parameters.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


# ---------------------------------------------------------------------------
# SQL — cohort reads (Q1 CTE composed into Q2/Q3/Q5/Q5b; Q6/Q7/Q8/Q9 standalone)
# ---------------------------------------------------------------------------

_BASE_CTE = """
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
        BETWEEN %(cohort_set_start)s AND %(cohort_set_end)s
    AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= %(cohort_appt_cutoff)s
),
scoped AS (
  SELECT b.*, r.team, r.roster_flag, r.display_name
  FROM base b
  JOIN lf_setter_roster r ON r.setter_name = b.setter
  WHERE r.team <> 'exclude'
)
"""

_Q2_TEAM_TOTALS = _BASE_CTE + """
SELECT
  CASE WHEN team LIKE 'Reece%%' THEN 'Reece' ELSE 'Lightfire' END AS team,
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
FROM scoped GROUP BY 1;
"""

_Q3_AGENTS = _BASE_CTE + """
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
"""

_Q5_CONFIRM_SPLITS = _BASE_CTE + """
SELECT
  CASE WHEN team LIKE 'Reece%%' THEN 'Reece' ELSE 'Lightfire' END AS team,
  (confirmed_by_name IS NOT NULL)                     AS confirmed,
  count(*)                                            AS n,
  count(*) FILTER (WHERE disposition_code='Set')      AS stranded,
  count(*) FILTER (WHERE ever_issued)                 AS issued,
  count(*) FILTER (WHERE ever_sat)                    AS sat,
  count(*) FILTER (WHERE closed_won)                  AS sold
FROM scoped GROUP BY 1,2;
"""

_Q5B_SELFGEN = _BASE_CTE + """
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
"""

# Q6 activity week — adds team so the service can count Lightfire active setters
# (some set appointments this week yet have zero matured in the cohort, so they
# are not in Q3; staffing must still see them).
_Q6_ACTIVITY = """
SELECT
  trim(replace(l.set_by_name,' - LF','')) AS setter_name,
  max(r.team)                             AS team,
  count(*) FILTER (WHERE (l.set_date AT TIME ZONE 'America/New_York')::date
                   BETWEEN %(activity_week_start)s AND %(activity_week_end)s) AS sets_activity_wk,
  count(*) FILTER (WHERE (l.set_date AT TIME ZONE 'America/New_York')::date
                   BETWEEN %(prior_week_start)s AND %(prior_week_end)s)       AS sets_prior_wk
FROM lp_leads l
JOIN lf_setter_roster r ON r.setter_name = trim(replace(l.set_by_name,' - LF',''))
WHERE l.set_by_name IS NOT NULL
  AND r.team <> 'exclude'
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN %(prior_week_start)s AND %(activity_week_end)s
GROUP BY 1;
"""

_Q7_SOURCE_MIX = """
SELECT
  l.lead_source_detail AS source,
  count(*)  FILTER (WHERE r.team LIKE 'Reece%%')                    AS reece_n,
  count(*)  FILTER (WHERE r.team LIKE 'Reece%%' AND l.ever_sat)     AS reece_sat,
  count(*)  FILTER (WHERE r.team='Lightfire')                      AS lf_n,
  count(*)  FILTER (WHERE r.team='Lightfire' AND l.ever_sat)       AS lf_sat
FROM lp_leads l
JOIN lf_setter_roster r ON r.setter_name = trim(replace(l.set_by_name,' - LF',''))
WHERE l.set_by_name IS NOT NULL AND r.team <> 'exclude'
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN %(cohort_set_start)s AND %(cohort_set_end)s
  AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= %(cohort_appt_cutoff)s
GROUP BY 1
HAVING count(*) FILTER (WHERE r.team='Lightfire') >= 10
   AND count(*) FILTER (WHERE r.team LIKE 'Reece%%') >= 10
ORDER BY lf_n DESC;
"""

_Q8_PRIOR = """
SELECT r.id AS run_id, r.period_start, r.period_end, r.status,
       m.team, m.issued_sit_pct, m.matured_sit_pct, m.net_issued, m.sat,
       m.no_confirmer, m.matured, m.active_agents
FROM lf_report_runs r
JOIN lf_weekly_team_metrics m ON m.run_id = r.id
WHERE r.status IN ('APPROVED','SENT')
  AND r.period_start < %(activity_week_start)s
  AND r.partner_id = %(partner_id)s
ORDER BY r.period_start DESC, r.id
LIMIT 6;
"""

_Q9_UNMAPPED = """
SELECT trim(replace(l.set_by_name,' - LF','')) AS unmapped_setter, count(*) AS matured
FROM lp_leads l
WHERE l.set_by_name IS NOT NULL
  AND (l.set_date AT TIME ZONE 'America/New_York')::date
      BETWEEN %(cohort_set_start)s AND %(cohort_set_end)s
  AND (l.appointment_date AT TIME ZONE 'America/New_York')::date <= %(cohort_appt_cutoff)s
  AND trim(replace(l.set_by_name,' - LF','')) NOT IN (SELECT setter_name FROM lf_setter_roster)
GROUP BY 1 ORDER BY 2 DESC;
"""


def _window_params(w) -> dict:
    return {
        "cohort_set_start": w.cohort_set_start,
        "cohort_set_end": w.cohort_set_end,
        "cohort_appt_cutoff": w.cohort_appt_cutoff,
        "activity_week_start": w.period_start,
        "activity_week_end": w.period_end,
        "prior_week_start": w.prior_period_start,
        "prior_week_end": w.prior_period_end,
    }


class Db:
    """Thin data-access wrapper. Public methods return parsed dicts/lists, never
    cursors, so the orchestrator carries no SQL and can be unit-tested against a
    stand-in that implements the same surface."""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("SUPABASE_DB_URL", "")

    # -- connection -------------------------------------------------------
    @contextmanager
    def _conn(self):
        if not self.dsn:
            raise RuntimeError("SUPABASE_DB_URL is not set — the render service cannot reach LP")
        conn = psycopg.connect(self.dsn, connect_timeout=20, row_factory=dict_row,
                               application_name="lf-report-render")
        try:
            yield conn
        finally:
            conn.close()

    def health(self) -> dict:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_user AS who, current_database() AS db")
                row = cur.fetchone()
                return {"ok": True, "role": row["who"], "database": row["db"]}
        except Exception as e:  # noqa: BLE001 — health must never raise
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # -- config / partner -------------------------------------------------
    def get_partner_id(self, slug: str = "lightfire") -> str:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM lf_partners WHERE slug = %s", (slug,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"no lf_partners row for slug {slug!r}")
            return str(row["id"])

    def get_config(self) -> dict:
        """key -> parsed jsonb value from lf_report_config."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT key, value FROM lf_report_config")
            return {r["key"]: r["value"] for r in cur.fetchall()}

    def is_report_enabled(self) -> bool:
        cfg = self.get_config()
        return cfg.get("report_enabled") is True

    def get_approvers(self) -> set[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT lower(email) AS email FROM lf_report_approvers WHERE active")
            return {r["email"] for r in cur.fetchall()}

    def get_vendor_recipients(self, partner_id: str) -> list[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT email FROM lf_vendor_recipients WHERE partner_id = %s AND active",
                        (partner_id,))
            return [r["email"] for r in cur.fetchall()]

    # -- cohort reads -----------------------------------------------------
    def fetch_cohort(self, w) -> dict:
        p = _window_params(w)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(_Q2_TEAM_TOTALS, p); team_totals = cur.fetchall()
            cur.execute(_Q3_AGENTS, p); agents = cur.fetchall()
            cur.execute(_Q5_CONFIRM_SPLITS, p); confirm_splits = cur.fetchall()
            cur.execute(_Q5B_SELFGEN, p); selfgen = cur.fetchone()
            cur.execute(_Q6_ACTIVITY, p); activity = cur.fetchall()
            cur.execute(_Q7_SOURCE_MIX, p); source_mix = cur.fetchall()
            cur.execute(_Q9_UNMAPPED, p); unmapped = cur.fetchall()
        return {"team_totals": team_totals, "agents": agents, "confirm_splits": confirm_splits,
                "selfgen": selfgen, "activity": activity, "source_mix": source_mix,
                "unmapped": unmapped}

    def get_prior_snapshot(self, partner_id: str, w) -> list[dict]:
        params = {"partner_id": partner_id, "activity_week_start": w.period_start}
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(_Q8_PRIOR, params)
            return cur.fetchall()

    def get_actions(self, partner_id: str) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT action_key, tier, sort_order, title, success_definition, owner, "
                "       due_date, status, weeks_open "
                "FROM lf_partner_actions WHERE partner_id = %s AND status <> 'REMOVED' "
                "ORDER BY sort_order", (partner_id,))
            return cur.fetchall()

    # -- run lifecycle ----------------------------------------------------
    def get_existing_run(self, partner_id: str, period_start, period_end) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM lf_report_runs WHERE partner_id=%s AND period_start=%s AND period_end=%s",
                (partner_id, period_start, period_end))
            return cur.fetchone()

    def create_run(self, partner_id: str, w, *, manual_regeneration: bool = False) -> tuple[str, bool]:
        """Insert the run, or return the existing one for this period. The
        second element is True when a NEW run was created."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_report_runs (partner_id, iso_year, iso_week, run_date, period_start, "
                " period_end, cohort_set_start, cohort_set_end, cohort_appt_cutoff, status, "
                " manual_regeneration) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'INGESTING',%s) "
                "ON CONFLICT (partner_id, period_start, period_end) DO NOTHING RETURNING id",
                (partner_id, w.iso_year, w.iso_week, w.run_date, w.period_start, w.period_end,
                 w.cohort_set_start, w.cohort_set_end, w.cohort_appt_cutoff, manual_regeneration))
            row = cur.fetchone()
            if row:
                conn.commit()
                return str(row["id"]), True
            cur.execute(
                "SELECT id FROM lf_report_runs WHERE partner_id=%s AND period_start=%s AND period_end=%s",
                (partner_id, w.period_start, w.period_end))
            return str(cur.fetchone()["id"]), False

    def set_run_status(self, run_id: str, status: str, **fields) -> None:
        cols = ["status = %s", "updated_at = now()"]
        vals: list[Any] = [status]
        for k, v in fields.items():
            cols.append(f"{k} = %s")
            vals.append(Jsonb(v) if k == "validation_report" else v)
        vals.append(run_id)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE lf_report_runs SET {', '.join(cols)} WHERE id = %s", vals)
            conn.commit()

    def roll_forward_actions(self, partner_id: str) -> None:
        """§10: age open actions by one week. Called once, on the INGESTING
        transition of a fresh run, so a re-run never double-increments."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE lf_partner_actions SET weeks_open = weeks_open + 1, updated_at = now() "
                "WHERE partner_id = %s AND status IN ('OPEN','IN_PROGRESS','RECURRED')", (partner_id,))
            conn.commit()

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM lf_report_runs WHERE id = %s", (run_id,))
            return cur.fetchone()

    def get_run_by_token(self, token: str) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ar.id AS approval_request_id, ar.run_id, ar.version_id, ar.sent_to, "
                "       ar.resolved_at, ar.reminded_at, r.status AS run_status, r.partner_id, "
                "       r.approved_version_id "
                "FROM lf_approval_requests ar JOIN lf_report_runs r ON r.id = ar.run_id "
                "WHERE ar.approval_token = %s", (token,))
            return cur.fetchone()

    def get_version(self, version_id: str) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM lf_report_versions WHERE id = %s", (version_id,))
            return cur.fetchone()

    def get_latest_version(self, run_id: str) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM lf_report_versions WHERE run_id = %s ORDER BY version_no DESC LIMIT 1",
                (run_id,))
            return cur.fetchone()

    def get_pdf(self, version_id: str) -> Optional[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT version_id, pdf_bytes, sha256, byte_size FROM lf_report_pdfs "
                        "WHERE version_id = %s", (version_id,))
            row = cur.fetchone()
            if row and isinstance(row["pdf_bytes"], memoryview):
                row["pdf_bytes"] = row["pdf_bytes"].tobytes()
            return row

    # -- atomic version write (D5 hash chain in one transaction) ----------
    def persist_version(self, *, run_id: str, version_no: int, payload: dict, payload_sha256: str,
                        pdf_bytes: bytes, pdf_sha256: str, page_count: int, render_ms: int,
                        source_snapshot_hash: str, team_metrics: list[dict], agent_metrics: list[dict],
                        report_metrics: dict, approval_token: str, sent_to: list[str],
                        revision_reason: Optional[str] = None,
                        revision_kind: Optional[str] = None) -> dict:
        """Freeze snapshots + version + PDF + approval request atomically, move
        the run to READY_FOR_REVIEW, and return the new ids. Everything here is
        one transaction so a partial freeze can never be observed."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO lf_report_versions (run_id, version_no, payload, payload_sha256, "
                    " pdf_storage_path, pdf_sha256, page_count, render_ms, revision_reason, revision_kind) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (run_id, version_no, Jsonb(payload), payload_sha256,
                     f"db://lf_report_pdfs/{{version_id}}", pdf_sha256, page_count, render_ms,
                     revision_reason, revision_kind))
                version_id = str(cur.fetchone()["id"])

                cur.execute(
                    "UPDATE lf_report_versions SET pdf_storage_path = %s WHERE id = %s",
                    (f"db://lf_report_pdfs/{version_id}", version_id))

                cur.execute(
                    "INSERT INTO lf_report_pdfs (version_id, pdf_bytes, sha256, byte_size) "
                    "VALUES (%s,%s,%s,%s)",
                    (version_id, pdf_bytes, pdf_sha256, len(pdf_bytes)))

                for t in team_metrics:
                    cur.execute(
                        "INSERT INTO lf_weekly_team_metrics (run_id, version_id, team, matured, "
                        " gross_issued, cancels_in_issued, net_issued, sat, sold, gross_cents, cxl_all, "
                        " stranded, no_confirmer, confirmed_by_desk, self_confirmed, confirmed_ai_other, "
                        " issued_sit_pct, matured_sit_pct, sits_short, active_agents, active_agents_prior) "
                        "VALUES (%(run_id)s,%(version_id)s,%(team)s,%(matured)s,%(gross_issued)s,"
                        " %(cancels_in_issued)s,%(net_issued)s,%(sat)s,%(sold)s,%(gross_cents)s,%(cxl_all)s,"
                        " %(stranded)s,%(no_confirmer)s,%(confirmed_by_desk)s,%(self_confirmed)s,"
                        " %(confirmed_ai_other)s,%(issued_sit_pct)s,%(matured_sit_pct)s,%(sits_short)s,"
                        " %(active_agents)s,%(active_agents_prior)s) "
                        "ON CONFLICT (run_id, team) DO UPDATE SET version_id = EXCLUDED.version_id",
                        {**t, "run_id": run_id, "version_id": version_id})

                for a in agent_metrics:
                    cur.execute(
                        "INSERT INTO lf_weekly_agent_metrics (run_id, version_id, setter_name, "
                        " display_name, team, roster_flag, matured, gross_issued, cancels, net_issued, "
                        " sat, sold, gross_cents, issued_sit_pct, matured_sit_pct, sits_short, "
                        " sets_period, sets_prior_period, rank_by_gross, small_denominator) "
                        "VALUES (%(run_id)s,%(version_id)s,%(setter_name)s,%(display_name)s,%(team)s,"
                        " %(roster_flag)s,%(matured)s,%(gross_issued)s,%(cancels)s,%(net_issued)s,%(sat)s,"
                        " %(sold)s,%(gross_cents)s,%(issued_sit_pct)s,%(matured_sit_pct)s,%(sits_short)s,"
                        " %(sets_period)s,%(sets_prior_period)s,%(rank_by_gross)s,%(small_denominator)s) "
                        "ON CONFLICT (run_id, setter_name) DO UPDATE SET version_id = EXCLUDED.version_id",
                        {**a, "run_id": run_id, "version_id": version_id})

                cur.execute(
                    "INSERT INTO lf_report_metrics (run_id, stat_tests, narrative_states, "
                    " source_mix_state, credit_observations, headline_observation, financial_opportunity) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (run_id) DO UPDATE SET stat_tests = EXCLUDED.stat_tests, "
                    " narrative_states = EXCLUDED.narrative_states, "
                    " source_mix_state = EXCLUDED.source_mix_state, "
                    " credit_observations = EXCLUDED.credit_observations, "
                    " headline_observation = EXCLUDED.headline_observation, "
                    " financial_opportunity = EXCLUDED.financial_opportunity",
                    (run_id, Jsonb(report_metrics["stat_tests"]),
                     Jsonb(report_metrics["narrative_states"]), report_metrics["source_mix_state"],
                     Jsonb(report_metrics["credit_observations"]),
                     Jsonb(report_metrics.get("headline_observation")),
                     Jsonb(report_metrics["financial_opportunity"])))

                cur.execute(
                    "INSERT INTO lf_approval_requests (run_id, version_id, approval_token, sent_to) "
                    "VALUES (%s,%s,%s,%s) RETURNING id",
                    (run_id, version_id, approval_token, sent_to))
                approval_request_id = str(cur.fetchone()["id"])

                cur.execute(
                    "UPDATE lf_report_runs SET status='READY_FOR_REVIEW', current_version_id=%s, "
                    " source_snapshot_hash=%s, updated_at=now() WHERE id=%s",
                    (version_id, source_snapshot_hash, run_id))

                cur.execute(
                    "INSERT INTO lf_audit_events (run_id, version_id, event_type, actor, metadata) "
                    "VALUES (%s,%s,'VERSION_GENERATED','render-service',%s)",
                    (run_id, version_id, Jsonb({"version_no": version_no, "token": approval_token})))
            conn.commit()
        return {"version_id": version_id, "approval_request_id": approval_request_id}

    # -- approval / delivery ---------------------------------------------
    def record_approval_event(self, *, approval_request_id: str, actor_email: Optional[str],
                              classification: str, revision_kind: Optional[str], raw_reply: str,
                              cleaned_reply: str, channel: str, accepted: bool,
                              reject_reason: Optional[str] = None) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_approval_events (approval_request_id, actor_email, classification, "
                " revision_kind, raw_reply, cleaned_reply, channel, accepted, reject_reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (approval_request_id, actor_email, classification, revision_kind, raw_reply,
                 cleaned_reply, channel, accepted, reject_reason))
            conn.commit()

    def resolve_approval(self, *, approval_request_id: str, run_id: str, outcome: str,
                         approved_version_id: Optional[str] = None, run_status: Optional[str] = None) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE lf_approval_requests SET resolved_at = now(), outcome = %s WHERE id = %s",
                        (outcome, approval_request_id))
            if run_status:
                fields = {"approved_version_id": approved_version_id} if approved_version_id else {}
                sets = ["status = %s", "updated_at = now()"] + [f"{k} = %s" for k in fields]
                cur.execute(f"UPDATE lf_report_runs SET {', '.join(sets)} WHERE id = %s",
                            [run_status, *fields.values(), run_id])
            conn.commit()

    def append_reminded_at(self, approval_request_id: str, ts) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE lf_approval_requests SET reminded_at = array_append(coalesce(reminded_at, '{}'), %s) "
                "WHERE id = %s", (ts, approval_request_id))
            conn.commit()

    def pending_approvals(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ar.id AS approval_request_id, ar.run_id, ar.approval_token, ar.sent_to, "
                "       ar.sent_at, ar.reminded_at "
                "FROM lf_approval_requests ar JOIN lf_report_runs r ON r.id = ar.run_id "
                "WHERE r.status = 'READY_FOR_REVIEW' AND ar.resolved_at IS NULL")
            return cur.fetchall()

    def record_delivery_event(self, *, run_id: str, version_id: str, approved_sha256: str,
                              sent_sha256: str, hash_verified: bool, recipients: list[str],
                              provider_message_id: Optional[str]) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_delivery_events (run_id, version_id, approved_sha256, sent_sha256, "
                " hash_verified, recipients, provider_message_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (run_id, version_id, approved_sha256, sent_sha256, hash_verified, recipients,
                 provider_message_id))
            if hash_verified:
                cur.execute("UPDATE lf_report_runs SET status='SENT', sent_at=now(), updated_at=now() "
                            "WHERE id=%s", (run_id,))
            conn.commit()

    def insert_override(self, *, run_id: str, scope: str, scope_key: str, field: str,
                        original_value, override_value, reason: str, requested_by: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_metric_overrides (run_id, scope, scope_key, field, original_value, "
                " override_value, reason, requested_by, applied) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true)",
                (run_id, scope, scope_key, field, original_value, override_value, reason, requested_by))
            conn.commit()

    # -- audit / errors ---------------------------------------------------
    def audit(self, *, run_id: Optional[str], version_id: Optional[str], event_type: str,
              actor: str = "render-service", metadata: Optional[dict] = None) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_audit_events (run_id, version_id, event_type, actor, metadata) "
                "VALUES (%s,%s,%s,%s,%s)",
                (run_id, version_id, event_type, actor, Jsonb(metadata or {})))
            conn.commit()

    def log_error(self, *, run_id: Optional[str], workflow: str, node: Optional[str],
                  error_class: str, message: str, payload: Optional[dict] = None) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO lf_automation_errors (run_id, workflow, node, error_class, message, payload) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (run_id, workflow, node, error_class, message, Jsonb(payload or {})))
            conn.commit()
