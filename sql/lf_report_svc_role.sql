-- sql/lf_report_svc_role.sql
-- Dedicated least-privilege role + PDF store for the lf-report-render service
-- (Phase-E adaptation). ADDITIVE ONLY; runs after lf_report_v2_schema.sql.
--
-- Why this exists: the n8n instance cannot reach LP Postgres (Supabase direct
-- connections are IPv6-only; the n8n Railway container has no IPv6 route) and
-- the n8n workflow API refuses to attach generic HTTP-auth credentials
-- programmatically. So the render service — not n8n — owns every LP read and
-- write, connecting as lf_report_svc over Supabase's IPv4 session pooler
-- (aws-0-us-east-2.pooler.supabase.com:5432, user "lf_report_svc.<project ref>").
--
-- PASSWORD IS OUT OF BAND. This migration creates the role WITHOUT a password,
-- so it cannot log in until an operator sets one:
--     ALTER ROLE lf_report_svc PASSWORD '<generated secret>';
-- The secret lives only in the Railway env var SUPABASE_DB_URL — never in this
-- repo, never in n8n workflow JSON. Rotation: run the ALTER ROLE again and
-- update SUPABASE_DB_URL. (Applied live 2026-09-09 as migration
-- lf_report_svc_role_and_pdfs; this file is the repo record.)
--
-- RLS NOTE: every lf_* table and lp_leads has row-level security ENABLED with
-- zero policies — existing access is exclusively through the RLS-bypassing
-- service_role. lf_report_svc is an ordinary role, so each surface needs an
-- explicit policy below or every read returns empty. The GRANTs still decide
-- which verbs are allowed; the USING (true) policies just admit the rows.

DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lf_report_svc') THEN
    CREATE ROLE lf_report_svc LOGIN CONNECTION LIMIT 10;
  END IF;
END $$;

-- Approved PDFs live in the DB (~150 KB/week) so the D5 hash chain
-- (approved_sha256 == sent_sha256) verifies in one datastore and one
-- transaction. Write-once: the service gets INSERT + SELECT, never UPDATE.
CREATE TABLE IF NOT EXISTS lf_report_pdfs (
  version_id uuid PRIMARY KEY REFERENCES lf_report_versions(id) ON DELETE CASCADE,
  pdf_bytes  bytea NOT NULL,
  sha256     text  NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  byte_size  integer NOT NULL CHECK (byte_size > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE lf_report_pdfs ENABLE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA public TO lf_report_svc;

-- Read-only surfaces: source data + operator-managed config.
GRANT SELECT ON lp_leads, lf_setter_roster, lf_partners, lf_report_config,
               lf_report_approvers, lf_vendor_recipients TO lf_report_svc;

-- Report state: SELECT/INSERT/UPDATE, deliberately no DELETE (production rows
-- are append/transition-only; test-row cleanup is a manual service_role op).
GRANT SELECT, INSERT, UPDATE ON lf_report_runs, lf_report_versions,
  lf_report_metrics, lf_weekly_agent_metrics, lf_weekly_team_metrics,
  lf_partner_actions, lf_approval_requests, lf_approval_events,
  lf_delivery_events, lf_metric_overrides, lf_audit_events,
  lf_automation_errors TO lf_report_svc;

GRANT SELECT, INSERT ON lf_report_pdfs TO lf_report_svc;

GRANT USAGE, SELECT ON SEQUENCE lf_audit_events_id_seq,
  lf_automation_errors_id_seq TO lf_report_svc;

-- Row-admitting policies (verbs still gated by the GRANTs above).
CREATE POLICY lf_svc_select ON lp_leads             FOR SELECT TO lf_report_svc USING (true);
CREATE POLICY lf_svc_select ON lf_setter_roster     FOR SELECT TO lf_report_svc USING (true);
CREATE POLICY lf_svc_select ON lf_partners          FOR SELECT TO lf_report_svc USING (true);
CREATE POLICY lf_svc_select ON lf_report_config     FOR SELECT TO lf_report_svc USING (true);
CREATE POLICY lf_svc_select ON lf_report_approvers  FOR SELECT TO lf_report_svc USING (true);
CREATE POLICY lf_svc_select ON lf_vendor_recipients FOR SELECT TO lf_report_svc USING (true);

CREATE POLICY lf_svc_all ON lf_report_runs          FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_report_versions      FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_report_metrics       FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_weekly_agent_metrics FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_weekly_team_metrics  FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_partner_actions      FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_approval_requests    FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_approval_events      FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_delivery_events      FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_metric_overrides     FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_audit_events         FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_automation_errors    FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
CREATE POLICY lf_svc_all ON lf_report_pdfs          FOR ALL TO lf_report_svc USING (true) WITH CHECK (true);
