-- sql/lf_report_v2_schema.sql
-- Lightfire weekly partner report — V2 schema.
-- ADDITIVE ONLY. All new tables on new names. Nothing existing is touched.
-- lp_leads remains the source of record; these tables hold run state, frozen
-- snapshots, versions, actions and audit. We do NOT re-model the LP warehouse.
--
-- Execute in the Supabase dashboard SQL editor, LP MCP instance.
-- NINE SEPARATE EXECUTIONS, in this order. Do not combine.
-- Execution 9 contains CREATE INDEX CONCURRENTLY and cannot run in a transaction.
--
-- Amendments vs the handoff-shipped copy (docs/REPORT_SPEC.md documents both):
--   * min_matured_for_table seeds as 1, not 3 (Mark, 2026-08-18): every roster
--     agent with >=1 matured appointment gets a page-1 row, so the summed
--     display total equals the cohort total by construction. The old value of
--     3 silently dropped 1-2 matured agents most weeks and produced a third,
--     undisclosed team number.
--   * lf_report_approvers seeds with the two approver addresses Mark named.
--   * report_enabled (false) is the master kill switch — Workflow 01 exits
--     when it is not true. It lives here rather than in an n8n env var so the
--     switch is inspectable and auditable (D4).

-- =====================================================================
-- EXECUTION 1 — partner, config, approvers
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_partners (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text UNIQUE NOT NULL,
  display_name  text NOT NULL,
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
INSERT INTO lf_partners (slug, display_name)
VALUES ('lightfire','Lightfire') ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS lf_report_config (
  key         text PRIMARY KEY,
  value       jsonb NOT NULL,
  note        text,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
INSERT INTO lf_report_config (key, value, note) VALUES
  ('timezone',                '"America/New_York"',      'ALL date math, scheduling and displayed timestamps'),
  ('run_dow',                 '1',                       'Monday, ISO weekday'),
  ('run_local_time',          '"08:00"',                 'Local ET; DST handled by tz, never by offset arithmetic'),
  ('issued_sit_goal',         '0.80',                    'Sit % goal'),
  ('small_denominator_min',   '20',                      'net_issued below this = small sample (styling flag, never an exclusion)'),
  ('min_matured_for_table',   '1',                       'every agent with >=1 matured displays; display total == cohort total by construction (Mark 2026-08-18)'),
  ('report_enabled',          'false',                   'master kill switch — Workflow 01 exits unless true'),
  ('cohort_weeks',            '6',                       'matured cohort length'),
  ('alpha',                   '0.05',                    'two-sided significance threshold'),
  ('material_delta_pts',      '3.0',                     'WoW change treated as material'),
  ('slight_delta_pts',        '1.0',                     'WoW change treated as slight; below = flat'),
  ('approval_reminder_hours', '[24, 48]',                'reminder schedule; never auto-approves'),
  ('source_min_n_each_side',  '10',                      'shared-source test minimum per team'),
  ('expected_page_count',     '4',                       'render fails the run if not matched'),
  ('visual_diff_tolerance',   '0.005',                   'max fraction of differing pixels per page')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS lf_report_approvers (
  email           text PRIMARY KEY,
  name            text NOT NULL,
  active          boolean NOT NULL DEFAULT true,
  approval_level  int NOT NULL DEFAULT 1,
  created_at      timestamptz NOT NULL DEFAULT now()
);
-- Any single active approver may decide. Addresses confirmed by Mark 2026-08-18.
INSERT INTO lf_report_approvers (email, name) VALUES
  ('m.richard@reecewindows.com', 'Mark Richard'),
  ('b.codman@reecewindows.com',  'Brad Codman')
ON CONFLICT (email) DO NOTHING;

CREATE TABLE IF NOT EXISTS lf_vendor_recipients (
  email       text PRIMARY KEY,
  partner_id  uuid NOT NULL REFERENCES lf_partners(id),
  name        text,
  active      boolean NOT NULL DEFAULT true
);

-- =====================================================================
-- EXECUTION 2 — setter roster (team assignment and exclusions are DATA)
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_setter_roster (
  setter_name   text PRIMARY KEY,      -- canonical: trim(replace(set_by_name,' - LF',''))
  display_name  text,                  -- overrides setter_name for rendering (LP misspellings)
  team          text NOT NULL,         -- 'Lightfire' | 'Reece' | 'Reece (W)' | 'exclude'
  roster_flag   text,                  -- NULL | 'departed' | 'off_account' | 'phantom'
  note          text,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO lf_setter_roster (setter_name, display_name, team, roster_flag, note) VALUES
  ('Deer, Craig',null,'Lightfire',null,null),
  ('Wright, Carla',null,'Lightfire',null,null),
  ('Walker, Shari',null,'Lightfire',null,null),
  ('Slowely, Diamoneke',null,'Lightfire',null,null),
  ('Martin, Nickalos',null,'Lightfire',null,null),
  ('Francis, Yanique',null,'Lightfire',null,null),
  ('Bryce, Shaday',null,'Lightfire',null,null),
  ('Green, Sherika',null,'Lightfire',null,null),
  ('Smith, Shakeriah',null,'Lightfire',null,null),
  ('Campbell, Brittany',null,'Lightfire',null,null),
  ('Dennis, Jodian',null,'Lightfire',null,null),
  ('Evans, Tresharna',null,'Lightfire','off_account','Off account w/e 2026-08-15'),
  ('Gordon, Grecian',null,'Lightfire','off_account','Off account w/e 2026-08-15'),
  ('Miller, Afiya',null,'Lightfire',null,null),
  ('Linan, Ashley',null,'Reece',null,null),
  ('Zeffield, Kevin',null,'Reece',null,null),
  ('Nunes, Dylan',null,'Reece',null,null),
  ('Nunes, Jonathan',null,'Reece',null,'Distinct person from Dylan Nunes. Never merge.'),
  ('Jakob, Robert',null,'Reece',null,null),
  ('Flanders, Jamal',null,'Reece',null,null),
  ('Nievez Moriera, Jardel','Nievez Moreira, Jardel','Reece',null,'LP misspells surname'),
  ('Julien, Lynslee',null,'Reece',null,null),
  ('Toussaint, Marcorie',null,'Reece',null,null),
  ('Giraldo, Miguel',null,'Reece',null,null),
  ('Jacobson, David',null,'Reece',null,null),
  ('Elliott, Andre',null,'Reece',null,null),
  ('Manieri, John',null,'Reece (W)',null,'West rehash role; rolls into Reece for team totals'),
  ('Avril, Chantal',null,'Reece','departed','Left for school 2026-08-17'),
  ('Demosthene, Jianna',null,'Reece','departed','Terminated 2026-08-17'),
  ('James, Kamryn',null,'exclude','departed',null),
  ('Rivera, Bryant',null,'exclude','departed',null),
  ('Moore, Ashley',null,'exclude','departed',null),
  ('Towns, Jazmine',null,'exclude','departed',null),
  ('Souto, Hellen',null,'exclude','departed',null),
  ('Rochelle, Cayla',null,'exclude',null,'Unverified, not on roster'),
  ('Rubertone, Bob',null,'exclude','phantom','NOT A REAL PERSON - confirmed Mark 2026-08-17'),
  ('Clavio, Craig',null,'exclude','phantom','Unverified off-roster; phantom until confirmed'),
  ('No, Setter',null,'exclude',null,'House / unassigned'),
  ('Agent, Revin',null,'exclude',null,'AI setting agent'),
  ('Integration, GoHighLevel',null,'exclude',null,'Automation'),
  ('Internet, Lead Gurus',null,'exclude',null,'Vendor auto-set'),
  ('Affiliate, MVP Marketing',null,'exclude',null,'Vendor auto-set'),
  ('Heisler, Joshua - LKLND',null,'exclude',null,'Out of market'),
  ('Price, Trevor - SARA',null,'exclude',null,'Out of market')
ON CONFLICT (setter_name) DO NOTHING;

-- =====================================================================
-- EXECUTION 3 — report runs (state machine)
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_report_runs (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  partner_id            uuid NOT NULL REFERENCES lf_partners(id),
  iso_year              int  NOT NULL,
  iso_week              int  NOT NULL,
  run_date              date NOT NULL,          -- Monday, ET
  period_start          date NOT NULL,          -- prior Sunday, ET
  period_end            date NOT NULL,          -- prior Saturday, ET
  cohort_set_start      date NOT NULL,
  cohort_set_end        date NOT NULL,
  cohort_appt_cutoff    date NOT NULL,
  status                text NOT NULL DEFAULT 'SCHEDULED',
    -- SCHEDULED INGESTING VALIDATING BLOCKED GENERATION_FAILED
    -- READY_FOR_REVIEW REVISION_REQUESTED REGENERATING
    -- APPROVED SENDING SENT DENIED
  current_version_id    uuid,
  approved_version_id   uuid,
  source_snapshot_hash  text,
  validation_report     jsonb,
  blocked_reason        text,
  sent_at               timestamptz,
  manual_regeneration   boolean NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lf_report_runs_period_uniq
  ON lf_report_runs (partner_id, period_start, period_end);

-- =====================================================================
-- EXECUTION 4 — report versions (immutable once reviewed)
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_report_versions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id             uuid NOT NULL REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  version_no         int  NOT NULL,
  payload            jsonb NOT NULL,          -- exact render input, frozen
  payload_sha256     text  NOT NULL,
  pdf_storage_path   text  NOT NULL,
  pdf_sha256         text  NOT NULL,
  page_count         int   NOT NULL,
  render_ms          int,
  revision_reason    text,                    -- null on v1
  revision_kind      text,                    -- null | 'DATA_CORRECTION' | 'NARRATIVE_EDIT'
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lf_report_versions_run_no_uniq
  ON lf_report_versions (run_id, version_no);

-- =====================================================================
-- EXECUTION 5 — frozen weekly snapshots (never recomputed from live data)
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_weekly_team_metrics (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id              uuid NOT NULL REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  version_id          uuid REFERENCES lf_report_versions(id) ON DELETE CASCADE,
  team                text NOT NULL,
  matured             int NOT NULL,
  gross_issued        int NOT NULL,
  cancels_in_issued   int NOT NULL,
  net_issued          int NOT NULL,
  sat                 int NOT NULL,
  sold                int NOT NULL,
  gross_cents         bigint NOT NULL,
  cxl_all             int NOT NULL,
  stranded            int NOT NULL,
  no_confirmer        int NOT NULL,
  confirmed_by_desk   int NOT NULL,
  self_confirmed      int NOT NULL,
  confirmed_ai_other  int NOT NULL,
  issued_sit_pct      numeric(5,2),
  matured_sit_pct     numeric(5,2),
  sits_short          numeric(6,2),
  active_agents       int,
  active_agents_prior int,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lf_weekly_team_run_team_uniq
  ON lf_weekly_team_metrics (run_id, team);

CREATE TABLE IF NOT EXISTS lf_weekly_agent_metrics (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            uuid NOT NULL REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  version_id        uuid REFERENCES lf_report_versions(id) ON DELETE CASCADE,
  setter_name       text NOT NULL,
  display_name      text,
  team              text NOT NULL,
  roster_flag       text,
  matured           int NOT NULL,
  gross_issued      int NOT NULL,
  cancels           int NOT NULL,
  net_issued        int NOT NULL,
  sat               int NOT NULL,
  sold              int NOT NULL,
  gross_cents       bigint NOT NULL,
  issued_sit_pct    numeric(5,2),
  matured_sit_pct   numeric(5,2),
  sits_short        numeric(6,2),
  sets_period       int,
  sets_prior_period int,
  rank_by_gross     int,
  small_denominator boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lf_weekly_agent_run_setter_uniq
  ON lf_weekly_agent_metrics (run_id, setter_name);

-- Statistical results and derived narrative states, one row per run.
CREATE TABLE IF NOT EXISTS lf_report_metrics (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                uuid NOT NULL UNIQUE REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  stat_tests            jsonb NOT NULL,   -- [{name,s1_n,s1_x,s2_n,s2_x,z,p,alpha,verdict}]
  narrative_states      jsonb NOT NULL,   -- {sit_trend, goal_status, stat_verdict, source_mix, ...}
  source_mix_state      text  NOT NULL,   -- SOURCE_MIX_NOT_EXPLANATORY | ..._PARTIALLY | ..._EXPLANATORY | INSUFFICIENT_SAMPLE
  credit_observations   jsonb NOT NULL,   -- selected, each with its supporting metric
  headline_observation  jsonb,            -- "the line worth sitting with" selection + score
  financial_opportunity jsonb NOT NULL,   -- {incremental_sits, close_rate, avg_ticket_cents, potential_gross_cents}
  created_at            timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- EXECUTION 6 — partner actions (carry forward week to week)
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_partner_actions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  partner_id          uuid NOT NULL REFERENCES lf_partners(id),
  action_key          text NOT NULL,        -- stable slug, e.g. 'confirmation_ownership_rule'
  tier                text NOT NULL,       -- 'IMMEDIATE' | 'SECONDARY'
  sort_order          int  NOT NULL,
  title               text NOT NULL,
  success_definition  text NOT NULL,
  owner               text NOT NULL,       -- 'Reece' | 'Lightfire' | 'Both'
  due_date            date,
  status              text NOT NULL DEFAULT 'OPEN',
    -- OPEN IN_PROGRESS DONE RECURRED ESCALATED REMOVED
  opened_run_id       uuid REFERENCES lf_report_runs(id),
  resolved_run_id     uuid REFERENCES lf_report_runs(id),
  resolved_at         timestamptz,
  resolution_notes    text,
  auto_metric_key     text,                -- optional: metric that auto-resolves this
  auto_metric_target  numeric,
  weeks_open          int NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lf_partner_actions_key_uniq
  ON lf_partner_actions (partner_id, action_key);

-- Seed the seven actions from the approved 2026-08-17 report.
INSERT INTO lf_partner_actions
  (partner_id, action_key, tier, sort_order, title, success_definition, owner, due_date, auto_metric_key, auto_metric_target)
SELECT p.id, v.action_key, v.tier, v.sort_order, v.title, v.success_definition, v.owner, v.due_date::date,
       v.auto_metric_key, v.auto_metric_target
FROM lf_partners p, (VALUES
 ('confirmation_ownership_rule','IMMEDIATE',1,
  'A written confirmation ownership rule — every appointment carries one named owning desk before its date',
  'Rule agreed and in force both sides','Both','2026-09-01',null,null::numeric),
 ('reece_desk_coverage','IMMEDIATE',2,
  'Reece commits coverage on Reece-supplied leads you set',
  'Coverage staffed, measured weekly','Reece','2026-09-01','reece_desk_share_of_lf_book',0.50),
 ('lf_selfgen_coverage','IMMEDIATE',3,
  'Lightfire commits coverage on Self Generated leads, or they route to our desk',
  'Named owner on every one','Lightfire','2026-09-01',null,null),
 ('weekly_sit_reporting','IMMEDIATE',4,
  'Issued Sit % reported weekly by agent — Deer, Walker and Wright first',
  'Lightfire book >= 75% by 1 Oct','Lightfire','2026-10-01','lf_issued_sit_pct',75.0),
 ('restore_bench','IMMEDIATE',5,
  'Restore the bench — named agents, expected days per week',
  '>= 8 agents producing in a week','Lightfire','2026-09-01','lf_active_agents',8),
 ('offdialler_reporting','SECONDARY',6,
  'Agree reporting for agents dialling from your own system',
  'Method agreed and in use','Both','2026-09-15',null,null),
 ('financing_denied_review','SECONDARY',7,
  'Review the three financing-denied contracts together',
  'Reviewed; retention monthly','Both','2026-09-15',null,null)
) AS v(action_key,tier,sort_order,title,success_definition,owner,due_date,auto_metric_key,auto_metric_target)
WHERE p.slug='lightfire'
ON CONFLICT (partner_id, action_key) DO NOTHING;

-- =====================================================================
-- EXECUTION 7 — approval, delivery, overrides
-- =====================================================================
CREATE TABLE IF NOT EXISTS lf_approval_requests (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            uuid NOT NULL REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  version_id        uuid NOT NULL REFERENCES lf_report_versions(id) ON DELETE CASCADE,
  approval_token    text NOT NULL UNIQUE,   -- e.g. LR-2026-34-V1
  message_id        text,
  thread_id         text,
  sent_to           text[] NOT NULL,
  sent_at           timestamptz NOT NULL DEFAULT now(),
  reminded_at       timestamptz[],
  resolved_at       timestamptz,
  outcome           text,                   -- APPROVED | DENIED | EDIT | null
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lf_approval_events (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  approval_request_id uuid NOT NULL REFERENCES lf_approval_requests(id) ON DELETE CASCADE,
  actor_email        text,
  classification     text NOT NULL,        -- APPROVED | DENY | EDIT | UNKNOWN | UNAUTHORIZED
  revision_kind      text,                 -- DATA_CORRECTION | NARRATIVE_EDIT | null
  raw_reply          text,
  cleaned_reply      text,
  channel            text NOT NULL,        -- 'email_reply' | 'webhook_button'
  accepted           boolean NOT NULL,
  reject_reason      text,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lf_delivery_events (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            uuid NOT NULL REFERENCES lf_report_runs(id),
  version_id        uuid NOT NULL REFERENCES lf_report_versions(id),
  approved_sha256   text NOT NULL,
  sent_sha256       text NOT NULL,
  hash_verified     boolean NOT NULL,
  recipients        text[] NOT NULL,
  provider_message_id text,
  sent_at           timestamptz NOT NULL DEFAULT now()
);

-- Data corrections. The correction path NEVER edits a PDF; it writes an
-- override, recalculates, and renders a new version.
CREATE TABLE IF NOT EXISTS lf_metric_overrides (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id        uuid NOT NULL REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  scope         text NOT NULL,        -- 'agent' | 'team' | 'retention'
  scope_key     text NOT NULL,        -- setter_name or team
  field         text NOT NULL,        -- e.g. 'gross_issued'
  original_value numeric,
  override_value numeric NOT NULL,
  reason        text NOT NULL,
  requested_by  text NOT NULL,
  applied       boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lf_audit_events (
  id             bigserial PRIMARY KEY,
  run_id         uuid REFERENCES lf_report_runs(id) ON DELETE CASCADE,
  version_id     uuid REFERENCES lf_report_versions(id) ON DELETE CASCADE,
  event_type     text NOT NULL,
    -- REPORT_CREATED SOURCE_SNAPSHOT_TAKEN VALIDATION_PASSED VALIDATION_FAILED
    -- PDF_RENDERED APPROVAL_REQUESTED REMINDER_SENT EDIT_REQUESTED
    -- VERSION_GENERATED APPROVED DENIED SENT FAILED MANUAL_OVERRIDE
  actor          text,
  metadata       jsonb,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lf_automation_errors (
  id           bigserial PRIMARY KEY,
  run_id       uuid REFERENCES lf_report_runs(id) ON DELETE SET NULL,
  workflow     text NOT NULL,
  node         text,
  error_class  text,
  message      text,
  payload      jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- EXECUTION 8 — FK back-references deferred to avoid circular creation
-- =====================================================================
ALTER TABLE lf_report_runs
  ADD CONSTRAINT lf_report_runs_current_version_fk
  FOREIGN KEY (current_version_id) REFERENCES lf_report_versions(id) ON DELETE SET NULL;
ALTER TABLE lf_report_runs
  ADD CONSTRAINT lf_report_runs_approved_version_fk
  FOREIGN KEY (approved_version_id) REFERENCES lf_report_versions(id) ON DELETE SET NULL;

-- =====================================================================
-- EXECUTION 9 — indexes. CONCURRENTLY cannot run inside a transaction.
-- Run each statement as its OWN execution.
-- =====================================================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS lf_audit_events_run_idx
  ON lf_audit_events (run_id, created_at DESC);
-- then, separately:
CREATE INDEX CONCURRENTLY IF NOT EXISTS lf_weekly_agent_setter_idx
  ON lf_weekly_agent_metrics (setter_name, created_at DESC);
-- then, separately:
CREATE INDEX CONCURRENTLY IF NOT EXISTS lf_report_runs_status_idx
  ON lf_report_runs (status, period_start DESC);
