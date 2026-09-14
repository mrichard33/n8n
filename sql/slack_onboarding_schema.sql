-- Slack team onboarding — schema + seed (OPS.SLK-A/B/C/D)
--
-- WHERE: Supabase dashboard → SQL editor → LP MCP instance
--        (project "Reece Lead Perfection Sync", rcjcgjlqzepicbwhnnjl).
-- HOW:   Three SEPARATE executions, in order. Do not paste the whole file at once:
--        execution 3 is CREATE INDEX CONCURRENTLY, which cannot run inside a
--        transaction and fails if it shares a run with anything else.
-- WHO READS THESE: the n8n workflows via PostgREST, authenticating with the n8n
--        credential "LP Supabase" (supabaseApi, service_role key). RLS is
--        enabled with NO policies (last statements of execution 1), so only the
--        service_role key can read or write these tables — team_members holds
--        employee names, emails and phones and must not be readable with the
--        anon key. If that credential is ever recreated with the anon key,
--        every Supabase node returns empty / 401; fix the credential, do not
--        add permissive policies.
-- STATUS: applied to the live project 2026-09-09 (all three executions plus the
--        watch_scope and pro_id columns). Re-running is safe — everything is IF NOT EXISTS /
--        ON CONFLICT DO NOTHING.
--
-- Employees are NEVER GHL contacts. Nothing here touches lp_leads / GHL.

-- =============================================================================
-- Execution 1 — tables (+ RLS)
-- =============================================================================

CREATE TABLE IF NOT EXISTS team_members (
  id              bigserial PRIMARY KEY,
  first_name      text NOT NULL,
  last_name       text NOT NULL,
  email           text NOT NULL UNIQUE,
  phone           text,
  market_code     text,
  role            text NOT NULL CHECK (role IN ('sales_rep','canvasser','sales_manager','canvass_manager','service_lead','dispatch','setter','call_center_manager','leadership')),
  slack_user_id   text,
  -- DEPRECATED 2026-09-14 (per-rep private channels removed). Nothing reads or
  -- writes it any more; kept because dropping a live column is irreversible
  -- and it costs nothing NULL.
  rep_channel_id  text,
  status          text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited','active','departed')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  activated_at    timestamptz,
  departed_at     timestamptz
);

-- Added 2026-09-09 (additive; safe to re-run). Written by OPS.SLK-A from the
-- normalizer. It grants channel membership BEYOND the role map:
--   'all'          -> every channel in slack_channels, including future ones
--                     (WATCH_ALL emails and the call centre manager)
--   'rep_channels' -> every market sales channel, #sales-<slug>
--                     (dispatch and sales managers)
-- 2026-09-14: per-rep private channels were removed, so 'rep_channels' was
-- repointed from those channels to the market sales channels where reps
-- actually live. The value is unchanged so no row needed rewriting.
-- Read by OPS.SLK-D when it fans watchers out.
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS watch_scope text
  CHECK (watch_scope IN ('rep_channels','all'));

-- Added 2026-09-14 (additive; safe to re-run). The person's OWN 4-digit Lead
-- Perfection PRO number — the id they are assigned, NOT the promoter id
-- credited on a lead. Written by OPS.SLK-A from the form; required there for
-- sales_rep, canvasser, sales_manager and canvass_manager, NULL for everyone
-- else. Text, not integer, so a leading zero survives. The partial unique
-- index catches the same PRO number being given to two people, which would
-- quietly corrupt anything built on it later.
ALTER TABLE team_members ADD COLUMN IF NOT EXISTS pro_id text;
CREATE UNIQUE INDEX IF NOT EXISTS idx_team_members_pro_id
  ON team_members(pro_id) WHERE pro_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS slack_channels (
  id               bigserial PRIMARY KEY,
  channel_name     text NOT NULL UNIQUE,
  slack_channel_id text NOT NULL UNIQUE,
  -- 'rep' is DEPRECATED 2026-09-14 — no row has ever used it and nothing
  -- writes one now. Kept in the constraint so an old row would not break.
  channel_type     text NOT NULL CHECK (channel_type IN ('company','sales','canvass','service','rep')),
  market_code      text,
  member_id        bigint REFERENCES team_members(id),
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS slack_role_channels (
  role            text NOT NULL,
  channel_pattern text NOT NULL,
  PRIMARY KEY (role, channel_pattern)
);

CREATE TABLE IF NOT EXISTS slack_market_slugs (
  market_code text PRIMARY KEY,
  market_name text NOT NULL,
  slug        text NOT NULL UNIQUE
);

COMMENT ON TABLE team_members IS
  'Slack onboarding roster (OPS.SLK-A/B/C). One row per employee keyed on company email. NOT a GHL contact — employees never enter the sales funnel. status: invited (form submitted, invite emailed) → active (joined Slack, channels provisioned) → departed (removed from their channels; the Slack account itself is deactivated MANUALLY — Slack has no API for it on this plan).';
COMMENT ON TABLE slack_channels IS
  'Slack channel registry. company/sales/canvass/service rows are loaded by hand once per channel (channel id from Slack → channel → About). Every row is loaded by hand; nothing writes to this table automatically since per-rep channels were removed on 2026-09-14.';
COMMENT ON TABLE slack_role_channels IS
  'Role → channel rules. <market> is replaced with slack_market_slugs.slug for the person''s market, and market rows are skipped for company-wide people. THIS TABLE is where membership rules live — the workflows carry no role logic. Canvassers are never in dispatch.';
COMMENT ON TABLE slack_market_slugs IS
  'market_code (as stored on team_members) → the slug used in channel names (sales-<slug>, canvass-<slug>, service-<slug>).';

-- Only the service_role key (held by the n8n "LP Supabase" credential) may touch these.
ALTER TABLE team_members        ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_channels      ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_role_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE slack_market_slugs  ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Execution 2 — seed data
-- =============================================================================

INSERT INTO slack_market_slugs VALUES
('JAX','Jacksonville','jacksonville'),
('STPET','St. Petersburg','stpetersburg'),
('SAR','Sarasota','sarasota'),
('LAKE','Lakeland','lakeland'),
('FTLAU','Fort Lauderdale','fortlauderdale'),
('ORL','Orlando','orlando'),
('FTMYR','Fort Myers','fortmyers')
ON CONFLICT DO NOTHING;

-- Role → channel rules, as they stand live on 2026-09-14. This is the ONLY
-- place membership rules live; the workflows carry no role logic. Canvassers
-- are never in #dispatch because no row below says so.
INSERT INTO slack_role_channels VALUES
('sales_rep','announcements'),('sales_rep','general'),('sales_rep','dispatch'),('sales_rep','sales-<market>'),
('canvasser','announcements'),('canvasser','general'),('canvasser','canvass-<market>'),
('sales_manager','announcements'),('sales_manager','general'),('sales_manager','dispatch'),('sales_manager','sales-<market>'),('sales_manager','sales-all'),('sales_manager','service-<market>'),
('canvass_manager','announcements'),('canvass_manager','general'),('canvass_manager','canvass-<market>'),('canvass_manager','canvass-all'),
('service_lead','announcements'),('service_lead','general'),('service_lead','service-<market>'),
('dispatch','announcements'),('dispatch','general'),('dispatch','dispatch'),('dispatch','contact-center'),('dispatch','lead-intelligence'),
('setter','announcements'),('setter','general'),('setter','contact-center'),
('call_center_manager','announcements'),('call_center_manager','general'),('call_center_manager','dispatch'),('call_center_manager','contact-center'),('call_center_manager','lead-intelligence'),('call_center_manager','leadership'),('call_center_manager','ops-alerts'),('call_center_manager','sales-all'),('call_center_manager','canvass-all'),
('leadership','announcements'),('leadership','general'),('leadership','lead-intelligence'),('leadership','leadership')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Execution 3 — index (its OWN execution; CONCURRENTLY cannot run in a transaction)
-- =============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_team_members_status ON team_members(status);

-- =============================================================================
-- Verification (read-only, run any time)
-- =============================================================================
-- SELECT count(*) FROM slack_market_slugs;      -- 7
-- SELECT count(*) FROM slack_role_channels;     -- 40
-- SELECT role, count(*) FROM slack_role_channels GROUP BY role ORDER BY role;
-- SELECT count(*) FROM slack_channels;          -- 31 live (10 company + 7 each sales/canvass/service)
--
-- One-time channel load (Verification step 0), one row per real Slack channel:
-- INSERT INTO slack_channels (channel_name, slack_channel_id, channel_type, market_code)
-- VALUES ('announcements','C0XXXXXXX','company',NULL),
--        ('general','C0XXXXXXX','company',NULL),
--        ('dispatch','C0XXXXXXX','company',NULL),
--        ('contact-center','C0XXXXXXX','company',NULL),
--        ('leadership','C0XXXXXXX','company',NULL),
--        ('ops-alerts','C0XXXXXXX','company',NULL),
--        ('sales-fortmyers','C0XXXXXXX','sales','FTMYR'),
--        ('canvass-fortmyers','C0XXXXXXX','canvass','FTMYR'),
--        ('service-fortmyers','C0XXXXXXX','service','FTMYR')
--        -- ... repeat sales/canvass/service for JAX, STPET, SAR, LAKE, FTLAU, ORL
-- ON CONFLICT (channel_name) DO UPDATE SET slack_channel_id = EXCLUDED.slack_channel_id;
