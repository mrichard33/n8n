-- Slack team onboarding — schema + seed (OPS.SLK-A/B/C)
--
-- WHERE: Supabase dashboard → SQL editor → LP MCP instance
--        (project "Reece Lead Perfection Sync", rcjcgjlqzepicbwhnnjl).
-- HOW:   Three SEPARATE executions, in order. Do not paste the whole file at once:
--        execution 3 is CREATE INDEX CONCURRENTLY, which cannot run inside a
--        transaction and fails if it shares a run with anything else.
-- WHO READS THESE: the n8n workflows via PostgREST with the LP_SUPABASE_KEY that
--        is already set on the "n8n main instance" Railway service. RLS is
--        enabled with NO policies (last statements of execution 1), so only the
--        service_role key can read or write these tables — team_members holds
--        employee names, emails and phones and must not be readable with the
--        anon key. If the n8n key turns out to be the anon key, swap it for the
--        service_role key; do not add permissive policies.
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
  role            text NOT NULL CHECK (role IN ('sales_rep','canvasser','sales_manager','canvass_manager','service_lead','dispatch','contact_center','leadership')),
  slack_user_id   text,
  rep_channel_id  text,
  status          text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited','active','departed')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  activated_at    timestamptz,
  departed_at     timestamptz
);

CREATE TABLE IF NOT EXISTS slack_channels (
  id               bigserial PRIMARY KEY,
  channel_name     text NOT NULL UNIQUE,
  slack_channel_id text NOT NULL UNIQUE,
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
  'Slack onboarding roster (OPS.SLK-A/B/C). One row per employee keyed on company email. NOT a GHL contact — employees never enter the sales funnel. status: invited (form submitted, invite emailed) → active (joined Slack, channels provisioned) → departed (kicked + rep channel archived; Slack account deactivated MANUALLY).';
COMMENT ON TABLE slack_channels IS
  'Slack channel registry. company/sales/canvass/service rows are loaded by hand once per channel (channel id from Slack → channel → About). rep rows are written by OPS.SLK-B when it creates a per-rep private channel.';
COMMENT ON TABLE slack_role_channels IS
  'Role → channel rules. <market> is replaced with slack_market_slugs.slug for the person''s market, and market rows are skipped for company-wide people. THIS TABLE is where membership rules live — the workflows carry no role logic. Canvassers are never in dispatch.';
COMMENT ON TABLE slack_market_slugs IS
  'market_code (as stored on team_members) → the slug used in channel names (sales-<slug>, canvass-<slug>, service-<slug>, sales-<slug>-<rep>).';

-- Only the service_role key (what n8n holds as LP_SUPABASE_KEY) may touch these.
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

INSERT INTO slack_role_channels VALUES
('sales_rep','announcements'),('sales_rep','general'),('sales_rep','dispatch'),('sales_rep','sales-<market>'),
('canvasser','announcements'),('canvasser','general'),('canvasser','canvass-<market>'),
('sales_manager','announcements'),('sales_manager','general'),('sales_manager','dispatch'),('sales_manager','sales-<market>'),('sales_manager','service-<market>'),
('canvass_manager','announcements'),('canvass_manager','general'),('canvass_manager','canvass-<market>'),
('service_lead','announcements'),('service_lead','general'),('service_lead','service-<market>'),
('dispatch','announcements'),('dispatch','general'),('dispatch','dispatch'),('dispatch','contact-center'),
('contact_center','announcements'),('contact_center','general'),('contact_center','contact-center'),
('leadership','announcements'),('leadership','general'),('leadership','leadership')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Execution 3 — index (its OWN execution; CONCURRENTLY cannot run in a transaction)
-- =============================================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_team_members_status ON team_members(status);

-- =============================================================================
-- Verification (read-only, run any time)
-- =============================================================================
-- SELECT count(*) FROM slack_market_slugs;      -- 7
-- SELECT count(*) FROM slack_role_channels;     -- 28
-- SELECT role, count(*) FROM slack_role_channels GROUP BY role ORDER BY role;
-- SELECT count(*) FROM slack_channels;          -- 27 once Verification step 0 is done
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
