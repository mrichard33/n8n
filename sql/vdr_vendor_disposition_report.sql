-- Weekly Vendor Disposition Report (VDR). LP Supabase (rcjcgjlqzepicbwhnnjl). Mark, 2026-10-13.
-- Used by n8n "06 VDR Weekly Vendor Disposition Report" (frlZu30c88H5bnkZ).
--   every hour -> POST /rest/v1/rpc/vdr_due_vendors   (who is due right now)
--   after send -> POST /rest/v1/vdr_send_log          (one row per vendor per attempt)
-- To add / pause / remove a vendor: edit vdr_vendor_config. No workflow change needed.

create table if not exists public.vdr_vendor_config (
  id bigserial primary key,
  vendor_name text not null unique,
  lp_sub_sources text[] not null,                 -- LP SourceSubDescr values that belong to this vendor
  recipients_to text[] not null default '{}',
  recipients_cc text[] not null default '{}',
  send_dow int not null default 1 check (send_dow between 1 and 7),   -- 1=Mon ... 7=Sun
  send_time time not null default '00:00',   -- 00:00 since 2026-10-14: the Monday ~6:30 AM feed email is the trigger (Mark)
  timezone text not null default 'America/New_York',
  lookback_days int not null default 90 check (lookback_days between 1 and 365),
  is_active boolean not null default true,        -- false = no report (sources still count as "mapped")
  dry_run boolean not null default true,          -- true = report goes to Mark only
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.vdr_send_log (
  id bigserial primary key,
  vendor_id bigint references public.vdr_vendor_config(id) on delete set null,
  vendor_name text not null,
  week_start date not null,
  scheduled_for timestamptz,
  attempted_at timestamptz not null default now(),
  dry_run boolean not null,
  status text not null check (status in ('sent','failed','blocked','empty')),
  lead_count int,
  recipients text,
  out_file text,
  reason text,
  source_file text,
  source_row_count int,
  feed_received_at timestamptz,
  n8n_execution_id text
);
create index if not exists vdr_send_log_vendor_week_idx on public.vdr_send_log (vendor_id, week_start);
-- Duplicate guard: one successful send per vendor per week (dry run and live counted separately).
create unique index if not exists vdr_send_log_one_send_per_week
  on public.vdr_send_log (vendor_id, week_start, dry_run) where status = 'sent';

create or replace function public.vdr_touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end $$;
drop trigger if exists vdr_vendor_config_touch on public.vdr_vendor_config;
create trigger vdr_vendor_config_touch before update on public.vdr_vendor_config
  for each row execute function public.vdr_touch_updated_at();

-- Who is due right now. A vendor is due once its send slot this week has passed and it has
-- no 'sent'/'empty' row this week. Blocked/failed attempts retry hourly, max 3 per week.
create or replace function public.vdr_due_vendors()
returns jsonb language sql stable as $$
  with v as (
    select c.*,
           (now() at time zone c.timezone) as local_now,
           date_trunc('week', now() at time zone c.timezone)::date as week_start
    from public.vdr_vendor_config c
    where c.is_active
  ), s as (
    select v.*, (v.week_start + (v.send_dow - 1) + v.send_time) as slot_local from v
  )
  select jsonb_build_object(
    'due', coalesce((
      select jsonb_agg(jsonb_build_object(
        'vendor_id', s.id, 'vendor_name', s.vendor_name, 'lp_sub_sources', s.lp_sub_sources,
        'recipients_to', s.recipients_to, 'recipients_cc', s.recipients_cc,
        'dry_run', s.dry_run, 'lookback_days', s.lookback_days, 'week_start', s.week_start,
        'scheduled_for', (s.slot_local at time zone s.timezone)) order by s.vendor_name)
      from s
      where s.local_now >= s.slot_local
        and not exists (select 1 from public.vdr_send_log l
                        where l.vendor_id = s.id and l.week_start = s.week_start
                          and l.dry_run = s.dry_run and l.status in ('sent','empty'))
        and (select count(*) from public.vdr_send_log l
             where l.vendor_id = s.id and l.week_start = s.week_start and l.dry_run = s.dry_run) < 3
    ), '[]'::jsonb),
    -- every sub-source assigned to ANY vendor row (active or not) -> used for the unmapped-source check
    'mapped_sub_sources', coalesce((
      select jsonb_agg(distinct x) from public.vdr_vendor_config c, unnest(c.lp_sub_sources) x
    ), '[]'::jsonb),
    -- last successful feed size -> used for the "file much smaller than usual" check
    'prev_source_rows', (
      select l.source_row_count from public.vdr_send_log l
      where l.status = 'sent' and l.source_row_count is not null
      order by l.attempted_at desc limit 1
    )
  );
$$;

alter table public.vdr_vendor_config enable row level security;
alter table public.vdr_send_log enable row level security;
revoke all on table public.vdr_vendor_config, public.vdr_send_log from anon, authenticated;
grant all on table public.vdr_vendor_config, public.vdr_send_log to service_role;
grant usage, select on sequence public.vdr_vendor_config_id_seq, public.vdr_send_log_id_seq to service_role;
revoke all on function public.vdr_due_vendors() from public, anon, authenticated;
grant execute on function public.vdr_due_vendors() to service_role;

-- Seed. All reporting vendors start in dry run (reports go to Mark only) with no recipients.
-- Inactive rows send nothing; they exist so their sub-sources are not flagged as unmapped.
insert into public.vdr_vendor_config (vendor_name, lp_sub_sources, is_active, notes) values
  ('Modernize', '{Modernize}', true, null),
  ('HomeBuddy', '{HomeBuddy}', true, null),
  ('Lead Gurus', '{"Lead Gurus"}', true, null),
  ('MyHomePros', '{MyHomePros}', true, null),
  ('Swish Leads', '{"Swish Leads"}', true, null),
  ('Prolific Marketing', '{"Prolific Marketing"}', true, null),
  ('Taste of Latino', '{"Taste of Latino"}', true, null),
  ('MVP Marketing', '{"MVP Marketing"}', true, null),
  ('Socius Marketing', '{"Socius Marketing","Google PPC PMAX","Google PPC Windows","Google PPC Roofs"}', true, 'Socius runs Google PPC + SEO. All Google PPC sub-sources assigned to Socius by Mark 2026-10-13'),
  ('Contractor Appointment Rev Share', '{"Contractor Appointment Rev Share"}', true, 'Confirmed as a vendor by Mark 2026-10-13'),
  ('Bing PPC', '{"Bing PPC"}', false, 'Ad platform, no report'),
  ('Canvass', '{Canvass,"Canvass Sticky"}', false, 'Internal, no report'),
  ('Previous Customer / Referral', '{"Previous Customer","Customer Referral"}', false, 'Internal, no report')
on conflict (vendor_name) do nothing;

notify pgrst, 'reload schema';

-- ===== Rev share: Payable Jobs (RTP) — 2026-10-13 =====
-- Rev-share vendors (LeadPilot, Contractor Appointment Rev Share) are paid per job RELEASED TO PRODUCTION,
-- not per lead. Each week they also get a "Payable Jobs" CSV: every job from their LP sub-sources whose
-- RTP date fell in the PRIOR Sunday..Saturday pay period. vdr_payable_jobs is the ledger that keeps a job
-- from ever being listed as payable twice (dry run and live are separate ledgers, like vdr_send_log).
--
-- JOIN PATH (verified 2026-10-13, 119/119 RTP jobs 09-27..10-10 matched):
--   lp_job_milestones.lp_job_id::text = lp_job_status_history.job_id::text  (latest row per job = max id)
--   -> lp_job_status_history.lp_id   = the 135 Lead Disposition Detail 2 lead id
--   -> lp_job_status_history.sub_source = the vendor attribution
-- lp_job_milestones.lp_lead_id is LP-MCP's own lead id space (e.g. 574903), NOT the 135 id (e.g. 462203).
-- It is used ONLY as a fallback through lp_jobs -> lp_leads.lead_source_detail to attribute an RTP job that
-- 133 Jobs By Status has not reported yet (the user, 2026-10-13: an unrelated unmatched job must not block
-- a rev-share vendor; one that is theirs, or cannot be attributed at all, does).
-- lp_job_milestones.act_date is stored at midnight UTC: compare act_date::date, never "at time zone".

alter table public.vdr_vendor_config add column if not exists rev_share boolean not null default false;

insert into public.vdr_vendor_config (vendor_name, lp_sub_sources, is_active, rev_share, notes)
values ('LeadPilot', '{LeadPilot,LeadPilotData}', true, true, 'Rev share. Both LP sub-sources per Mark 2026-10-13')
on conflict (vendor_name) do nothing;
update public.vdr_vendor_config set rev_share = true where vendor_name = 'Contractor Appointment Rev Share';

create table if not exists public.vdr_payable_jobs (
  id bigserial primary key,
  vendor_id bigint references public.vdr_vendor_config(id) on delete set null,
  vendor_name text not null,
  lp_job_id text not null,
  lp_lead_id text,                       -- the 135 lead id (job_status_history.lp_id)
  sub_source text,
  rtp_date date not null,
  period_start date not null,
  period_end date not null,
  gross_cents bigint,
  job_status text,
  dry_run boolean not null,
  listed_at timestamptz not null default now(),
  n8n_execution_id text
);
-- A job is payable once per vendor (dry run and live counted separately).
create unique index if not exists vdr_payable_jobs_once on public.vdr_payable_jobs (vendor_id, lp_job_id, dry_run);
alter table public.vdr_payable_jobs enable row level security;
revoke all on table public.vdr_payable_jobs from anon, authenticated;
grant all on table public.vdr_payable_jobs to service_role;
grant usage, select on sequence public.vdr_payable_jobs_id_seq to service_role;

-- vdr_due_vendors(): same as before, plus rev_share on each due vendor.
create or replace function public.vdr_due_vendors()
returns jsonb language sql stable as $$
  with v as (
    select c.*,
           (now() at time zone c.timezone) as local_now,
           date_trunc('week', now() at time zone c.timezone)::date as week_start
    from public.vdr_vendor_config c
    where c.is_active
  ), s as (
    select v.*, (v.week_start + (v.send_dow - 1) + v.send_time) as slot_local from v
  )
  select jsonb_build_object(
    'due', coalesce((
      select jsonb_agg(jsonb_build_object(
        'vendor_id', s.id, 'vendor_name', s.vendor_name, 'lp_sub_sources', s.lp_sub_sources,
        'recipients_to', s.recipients_to, 'recipients_cc', s.recipients_cc,
        'dry_run', s.dry_run, 'rev_share', s.rev_share, 'lookback_days', s.lookback_days, 'week_start', s.week_start,
        'scheduled_for', (s.slot_local at time zone s.timezone)) order by s.vendor_name)
      from s
      where s.local_now >= s.slot_local
        and not exists (select 1 from public.vdr_send_log l
                        where l.vendor_id = s.id and l.week_start = s.week_start
                          and l.dry_run = s.dry_run and l.status in ('sent','empty'))
        and (select count(*) from public.vdr_send_log l
             where l.vendor_id = s.id and l.week_start = s.week_start and l.dry_run = s.dry_run) < 3
    ), '[]'::jsonb),
    'mapped_sub_sources', coalesce((
      select jsonb_agg(distinct x) from public.vdr_vendor_config c, unnest(c.lp_sub_sources) x
    ), '[]'::jsonb),
    'prev_source_rows', (
      select l.source_row_count from public.vdr_send_log l
      where l.status = 'sent' and l.source_row_count is not null
      order by l.attempted_at desc limit 1
    )
  );
$$;

-- vdr_rev_share_data(): for every ACTIVE rev-share vendor, the prior Sun..Sat pay period, the payable jobs
-- in it, every RTP of the vendor's jobs (all time, for the Job # / RTP Date columns on the lead CSV), and
-- the health facts the workflow fails closed on.
create or replace function public.vdr_rev_share_data()
returns jsonb language sql stable as $$
  with v as (
    select c.id, c.vendor_name, c.lp_sub_sources, c.dry_run, c.timezone,
           array(select lower(trim(x)) from unnest(c.lp_sub_sources) x) as subs_norm,
           ((now() at time zone c.timezone)::date
             - (extract(dow from (now() at time zone c.timezone)::date)::int + 1)) as period_end
    from public.vdr_vendor_config c
    where c.is_active and c.rev_share
  ), vp as (
    select v.*, (v.period_end - 6) as period_start from v
  ), js as (
    -- latest 133 Jobs By Status row per job
    select distinct on (h.job_id) h.job_id::text as job_id, h.lp_id, h.sub_source,
           lower(trim(h.sub_source)) as sub_norm, h.customer_name, h.contract_date, h.gross_cents,
           h.status_raw, h.bucket
    from public.lp_job_status_history h
    where h.job_id is not null
    order by h.job_id, h.id desc
  ), rtp as (
    select m.lp_job_id::text as job_id, m.act_date::date as rtp_date
    from public.lp_job_milestones m
    where m.datetype = 'RTP' and m.act_date is not null and m.lp_job_id is not null
  ), unmatched as (
    -- RTP jobs 133 has not reported: attributed, if at all, through lp_jobs -> lp_leads
    select r.job_id, r.rtp_date, l.lead_source_detail as fallback_source,
           nullif(lower(trim(l.lead_source_detail)), '') as fallback_norm
    from rtp r
    left join js on js.job_id = r.job_id
    left join public.lp_jobs j on j.lp_job_id::text = r.job_id
    left join public.lp_leads l on l.lp_lead_id = j.lp_lead_id
    where js.job_id is null
  ), in_period as (
    select u.* from unmatched u
    where exists (select 1 from vp where u.rtp_date between vp.period_start and vp.period_end)
  )
  select jsonb_build_object(
    'vendors', coalesce((
      select jsonb_agg(jsonb_build_object(
        'vendor_id', vp.id, 'vendor_name', vp.vendor_name, 'rev_share', true, 'dry_run', vp.dry_run,
        'period_start', vp.period_start, 'period_end', vp.period_end,
        'payable', coalesce((
          select jsonb_agg(jsonb_build_object(
            'lp_job_id', js.job_id, 'lp_lead_id', js.lp_id, 'customer_name', js.customer_name,
            'sub_source', js.sub_source, 'contract_date', js.contract_date, 'rtp_date', r.rtp_date,
            'sale_amount', round(coalesce(js.gross_cents, 0) / 100.0, 2), 'gross_cents', js.gross_cents,
            'job_status', js.status_raw, 'bucket', js.bucket,
            'already_listed', exists (select 1 from public.vdr_payable_jobs p
                                      where p.vendor_id = vp.id and p.lp_job_id = js.job_id and p.dry_run = vp.dry_run)
          ) order by r.rtp_date, js.job_id)
          from rtp r join js on js.job_id = r.job_id
          where r.rtp_date between vp.period_start and vp.period_end
            and js.sub_norm = any (vp.subs_norm)
        ), '[]'::jsonb),
        'lead_rtp', coalesce((
          select jsonb_agg(jsonb_build_object('lp_lead_id', js.lp_id, 'lp_job_id', js.job_id, 'rtp_date', r.rtp_date)
                           order by r.rtp_date, js.job_id)
          from rtp r join js on js.job_id = r.job_id
          where js.sub_norm = any (vp.subs_norm)
        ), '[]'::jsonb),
        'rtp_unresolved_in_period', (
          select count(*) from in_period u
          where u.rtp_date between vp.period_start and vp.period_end and u.fallback_norm = any (vp.subs_norm))
      ) order by vp.vendor_name)
      from vp
    ), '[]'::jsonb),
    'milestones_last_sync', (select max(synced_at) from public.lp_job_milestones),
    'jobstatus_last_contract', (select max(contract_date) from public.lp_job_status_history),
    'rtp_unmatched_in_period', (select count(*) from in_period),
    'rtp_unattributed_in_period', (select count(*) from in_period u where u.fallback_norm is null),
    'rtp_unmatched_detail', coalesce((
      select jsonb_agg(jsonb_build_object('lp_job_id', u.job_id, 'rtp_date', u.rtp_date, 'fallback_source', u.fallback_source)
                       order by u.rtp_date, u.job_id)
      from in_period u
    ), '[]'::jsonb)
  );
$$;
revoke all on function public.vdr_rev_share_data() from public, anon, authenticated;
grant execute on function public.vdr_rev_share_data() to service_role;

notify pgrst, 'reload schema';

-- ===== Report frequency: weekly (Monday) or monthly (the 1st) — 2026-10-14 =====
-- Mark: "control the report frequency, monthly or weekly, in the dashboard. If monthly, send the report on the
-- first of each month; if weekly, send it every Monday morning." The run starts when LP's daily feed email lands
-- (~6:30 AM ET), so "Monday" means the first feed email on or after Monday 00:00 and "the 1st" the first feed
-- email on or after the 1st at 00:00. vdr_due_vendors() now works on a PERIOD start per vendor (Monday of this
-- week, or the 1st of this month) and still returns it as week_start, so the workflow and vdr_send_log.week_start
-- are unchanged: that column is the period start. "Sent this period" and the 3-attempt count read
-- week_start >= period_start, so a vendor switched weekly -> monthly after a Monday send is not sent again that
-- month, and monthly -> weekly after a 1st-of-month send waits for the next Monday.

alter table public.vdr_vendor_config
  add column if not exists frequency text not null default 'weekly'
  check (frequency in ('weekly','monthly'));

create or replace function public.vdr_due_vendors()
returns jsonb language sql stable as $$
  with v as (
    select c.*,
           (now() at time zone c.timezone) as local_now,
           case when c.frequency = 'monthly' then date_trunc('month', now() at time zone c.timezone)::date
                else date_trunc('week', now() at time zone c.timezone)::date end as period_start
    from public.vdr_vendor_config c
    where c.is_active
  ), s as (
    select v.*,
           case when v.frequency = 'monthly' then (v.period_start + v.send_time)
                else (v.period_start + (v.send_dow - 1) + v.send_time) end as slot_local
    from v
  )
  select jsonb_build_object(
    'due', coalesce((
      select jsonb_agg(jsonb_build_object(
        'vendor_id', s.id, 'vendor_name', s.vendor_name, 'lp_sub_sources', s.lp_sub_sources,
        'recipients_to', s.recipients_to, 'recipients_cc', s.recipients_cc,
        'dry_run', s.dry_run, 'rev_share', s.rev_share, 'lookback_days', s.lookback_days,
        'frequency', s.frequency, 'week_start', s.period_start, 'period_start', s.period_start,
        'scheduled_for', (s.slot_local at time zone s.timezone)) order by s.vendor_name)
      from s
      where s.local_now >= s.slot_local
        and not exists (select 1 from public.vdr_send_log l
                        where l.vendor_id = s.id and l.week_start >= s.period_start
                          and l.dry_run = s.dry_run and l.status in ('sent','empty'))
        and (select count(*) from public.vdr_send_log l
             where l.vendor_id = s.id and l.week_start >= s.period_start and l.dry_run = s.dry_run) < 3
    ), '[]'::jsonb),
    'mapped_sub_sources', coalesce((
      select jsonb_agg(distinct x) from public.vdr_vendor_config c, unnest(c.lp_sub_sources) x
    ), '[]'::jsonb),
    'prev_source_rows', (
      select l.source_row_count from public.vdr_send_log l
      where l.status = 'sent' and l.source_row_count is not null
      order by l.attempted_at desc limit 1
    )
  );
$$;

notify pgrst, 'reload schema';

-- ===== BCC per vendor, shown and edited on the dashboard — 2026-10-15 =====
-- Mark: "add b.codman@reecewindows.com as a bcc as well for now. I would actually like to add and show the BCC as a
-- tab in the dashboard right below the CC so that the BCC can be updated and seen who it is being sent to." The
-- hidden copy used to be the hard-coded m.richard@reecewindows.com in the Build node. Now vdr_vendor_config carries
-- recipients_bcc, vdr_due_vendors() returns it, and the Build node sends BCC = m.richard@reecewindows.com plus the
-- row's list (de-duplicated), so an edit on the page can never drop Mark. The seed below gives every active vendor
-- Mark + Brad; it is guarded on an empty list so a re-run changes nothing.

alter table public.vdr_vendor_config add column if not exists recipients_bcc text[] not null default '{}';

update public.vdr_vendor_config
   set recipients_bcc = '{m.richard@reecewindows.com,b.codman@reecewindows.com}'
 where is_active and recipients_bcc = '{}';

create or replace function public.vdr_due_vendors()
returns jsonb language sql stable as $$
  with v as (
    select c.*,
           (now() at time zone c.timezone) as local_now,
           case when c.frequency = 'monthly' then date_trunc('month', now() at time zone c.timezone)::date
                else date_trunc('week', now() at time zone c.timezone)::date end as period_start
    from public.vdr_vendor_config c
    where c.is_active
  ), s as (
    select v.*,
           case when v.frequency = 'monthly' then (v.period_start + v.send_time)
                else (v.period_start + (v.send_dow - 1) + v.send_time) end as slot_local
    from v
  )
  select jsonb_build_object(
    'due', coalesce((
      select jsonb_agg(jsonb_build_object(
        'vendor_id', s.id, 'vendor_name', s.vendor_name, 'lp_sub_sources', s.lp_sub_sources,
        'recipients_to', s.recipients_to, 'recipients_cc', s.recipients_cc, 'recipients_bcc', s.recipients_bcc,
        'dry_run', s.dry_run, 'rev_share', s.rev_share, 'lookback_days', s.lookback_days,
        'frequency', s.frequency, 'week_start', s.period_start, 'period_start', s.period_start,
        'scheduled_for', (s.slot_local at time zone s.timezone)) order by s.vendor_name)
      from s
      where s.local_now >= s.slot_local
        and not exists (select 1 from public.vdr_send_log l
                        where l.vendor_id = s.id and l.week_start >= s.period_start
                          and l.dry_run = s.dry_run and l.status in ('sent','empty'))
        and (select count(*) from public.vdr_send_log l
             where l.vendor_id = s.id and l.week_start >= s.period_start and l.dry_run = s.dry_run) < 3
    ), '[]'::jsonb),
    'mapped_sub_sources', coalesce((
      select jsonb_agg(distinct x) from public.vdr_vendor_config c, unnest(c.lp_sub_sources) x
    ), '[]'::jsonb),
    'prev_source_rows', (
      select l.source_row_count from public.vdr_send_log l
      where l.status = 'sent' and l.source_row_count is not null
      order by l.attempted_at desc limit 1
    )
  );
$$;

notify pgrst, 'reload schema';


-- ===== Saved copy of the daily 90-day feed + "Send now (saved feed)" — 2026-10-15 =====
-- The user: save each day's feed, "but I want to make sure that each day when the last 90 days arrive we should be
-- updating the pre existing values to match instead of add the duplicates." vdr_feed_leads holds ONE row per LP lead
-- (the row the Build node keeps), overwritten by each feed; vdr_feed_runs holds one row per feed email. The workflow's
-- "Prepare feed for database" branch stores each feed in chunks and marks it complete; the "Send now (saved feed)"
-- button builds from rpc/vdr_saved_feed. Same file in LP-MCP: supabase/migrations/20261015150000_vdr_feed_snapshot.sql
-- (applied 2026-10-15, recorded in supabase_migrations.schema_migrations).
create table if not exists public.vdr_feed_runs (
  id               bigserial primary key,
  gmail_message_id text        not null unique,
  received_at      timestamptz not null,
  source_file      text,
  header           text[]      not null default '{}',   -- the feed columns kept in vdr_feed_leads.row, in feed order
  raw_row_count    int         not null,                -- rows in the CSV (several per lead)
  lead_count       int         not null,                -- distinct leads the run carries
  window_start     date,
  complete         boolean     not null default false,
  saved_at         timestamptz not null default now(),
  completed_at     timestamptz
);
create index if not exists vdr_feed_runs_complete_received_idx
  on public.vdr_feed_runs (received_at desc) where complete;

create table if not exists public.vdr_feed_leads (
  lead_id       text        primary key,
  entry_date    date,
  sub_source    text,
  row           jsonb       not null,                   -- { "<feed column>": "<value>" } for vdr_feed_runs.header
  first_seen_at timestamptz not null,
  last_seen_at  timestamptz not null,                   -- received_at of the feed that last wrote this lead
  last_run_id   bigint      not null references public.vdr_feed_runs (id),
  updated_at    timestamptz not null default now()
);
create index if not exists vdr_feed_leads_last_run_idx on public.vdr_feed_leads (last_run_id);

alter table public.vdr_feed_runs  enable row level security;
alter table public.vdr_feed_leads enable row level security;
revoke all on public.vdr_feed_runs, public.vdr_feed_leads from anon, authenticated;
revoke all on sequence public.vdr_feed_runs_id_seq from anon, authenticated;

-- One chunk of a feed: the run (created on the first chunk, by Gmail message id) and up to a few thousand leads.
create or replace function public.vdr_store_feed_chunk(p_run jsonb, p_leads jsonb)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_run public.vdr_feed_runs;
  v_n   int;
begin
  if coalesce(p_run->>'gmail_message_id', '') = '' or coalesce(p_run->>'received_at', '') = '' then
    raise exception 'vdr_store_feed_chunk: gmail_message_id and received_at are required';
  end if;
  insert into public.vdr_feed_runs (gmail_message_id, received_at, source_file, header, raw_row_count, lead_count, window_start)
  values (p_run->>'gmail_message_id',
          (p_run->>'received_at')::timestamptz,
          p_run->>'source_file',
          coalesce(array(select jsonb_array_elements_text(coalesce(p_run->'header', '[]'::jsonb))), '{}'),
          (p_run->>'raw_row_count')::int,
          (p_run->>'lead_count')::int,
          nullif(p_run->>'window_start', '')::date)
  on conflict (gmail_message_id) do update set saved_at = now()
  returning * into v_run;

  insert into public.vdr_feed_leads as t (lead_id, entry_date, sub_source, row, first_seen_at, last_seen_at, last_run_id, updated_at)
  select distinct on (l->>'lead_id')
         l->>'lead_id', nullif(l->>'entry_date', '')::date, nullif(l->>'sub_source', ''), l->'row',
         v_run.received_at, v_run.received_at, v_run.id, now()
    from jsonb_array_elements(coalesce(p_leads, '[]'::jsonb)) l
   where coalesce(l->>'lead_id', '') <> ''
   order by l->>'lead_id'
  on conflict (lead_id) do update
     set entry_date   = excluded.entry_date,
         sub_source   = excluded.sub_source,
         row          = excluded.row,
         last_seen_at = excluded.last_seen_at,
         last_run_id  = excluded.last_run_id,
         updated_at   = now()
   where t.last_seen_at <= excluded.last_seen_at;   -- an older email never overwrites a newer feed
  get diagnostics v_n = row_count;
  return jsonb_build_object('run_id', v_run.id, 'stored', v_n);
end;
$$;

-- After the last chunk: the run is usable only when every lead it carried is stored under it.
create or replace function public.vdr_finish_feed(p_message_id text)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_run   public.vdr_feed_runs;
  v_saved int;
begin
  select * into v_run from public.vdr_feed_runs where gmail_message_id = p_message_id;
  if not found then
    return jsonb_build_object('complete', false, 'reason', 'run_not_found', 'saved', 0, 'expected', null);
  end if;
  select count(*) into v_saved from public.vdr_feed_leads where last_run_id = v_run.id;
  if v_saved = v_run.lead_count and v_run.lead_count > 0 then
    update public.vdr_feed_runs set complete = true, completed_at = coalesce(completed_at, now()) where id = v_run.id;
  end if;
  return jsonb_build_object('complete', v_saved = v_run.lead_count and v_run.lead_count > 0,
                            'saved', v_saved, 'expected', v_run.lead_count,
                            'run_id', v_run.id, 'received_at', v_run.received_at);
end;
$$;

-- The newest complete feed, with its leads, for the workflow's "Send now (saved feed)" button.
create or replace function public.vdr_saved_feed()
returns jsonb
language sql
stable
set search_path = public
as $$
  with r as (
    select * from public.vdr_feed_runs where complete order by received_at desc, id desc limit 1
  )
  select coalesce(
    (select jsonb_build_object(
              'found', true, 'run_id', r.id, 'gmail_message_id', r.gmail_message_id,
              'received_at', r.received_at, 'source_file', r.source_file, 'header', to_jsonb(r.header),
              'raw_row_count', r.raw_row_count, 'lead_count', r.lead_count, 'window_start', r.window_start,
              'leads', coalesce((select jsonb_agg(l.row order by l.lead_id)
                                   from public.vdr_feed_leads l where l.last_run_id = r.id), '[]'::jsonb))
       from r),
    jsonb_build_object('found', false));
$$;

revoke all on function public.vdr_store_feed_chunk(jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.vdr_finish_feed(text)               from public, anon, authenticated;
revoke all on function public.vdr_saved_feed()                    from public, anon, authenticated;
grant execute on function public.vdr_store_feed_chunk(jsonb, jsonb) to service_role;
grant execute on function public.vdr_finish_feed(text)               to service_role;
grant execute on function public.vdr_saved_feed()                    to service_role;

notify pgrst, 'reload schema';


-- ===== Vendor Lead Report v2: live vendor leads — 2026-10-15 =====
-- Handoff "Vendor Lead Report v2": sends read LIVE data, the 135 feed above is only a cross-check. vdr_vendor_report is
-- what LP-MCP GET /vdr/report.xlsx builds the branded workbook from; the workflow calls that endpoint per due vendor.
-- Window: whole Eastern days, as_of's date minus lookback_days through as_of's date. Calls: Five9 only. Same file in
-- LP-MCP: supabase/migrations/20261015170000_vdr_vendor_leads_live.sql (applied 2026-10-15, recorded in the ledger).

create or replace function public.vdr_vendor_leads(p_vendor_id bigint, p_as_of timestamptz default now())
returns table (
  prospect_id           text,
  repeat_prospect       boolean,
  sub_source            text,
  market_code           text,
  market                text,
  entry_at              timestamp,      -- Eastern wall clock
  entry_week            date,           -- Monday of the entry week
  first_name            text,
  last_name             text,
  phone                 text,           -- 10 digits
  email                 text,
  city                  text,
  zip                   text,
  five9_dials           integer,
  minutes_to_first_dial numeric,
  last_call_result      text,
  contacted             boolean,
  appt_set_at           timestamp,
  appt_at               timestamp,
  days_set_to_appt      numeric,
  confirmed_at          timestamp,
  is_set                boolean,
  is_confirmed          boolean,
  issue_date            date,
  is_issued             boolean,
  is_net_issued         boolean,
  is_demo               boolean,
  is_sold               boolean,
  gross_sale            numeric,
  lp_status             text
)
language sql
stable
set search_path = public
as $$
  with cfg as (
    select c.lp_sub_sources, c.lookback_days,
           (p_as_of at time zone 'America/New_York')::date - c.lookback_days as start_date,
           (p_as_of at time zone 'America/New_York')::date                   as end_date
      from public.vdr_vendor_config c
     where c.id = p_vendor_id
  ),
  l as (
    select l.*,
           (l.created_at_lp at time zone 'UTC')                                         as entry_wall,
           ((l.created_at_lp at time zone 'UTC') at time zone 'America/New_York')       as entry_real,
           right(regexp_replace(coalesce(l.phone, ''), '[^0-9]', '', 'g'), 10)          as ph10,
           coalesce(a.resolved_market_code, l.lp_branch_id, 'UNASSIGNED')              as mkt
      from public.lp_leads l
      join cfg on l.lead_source_detail = any(cfg.lp_sub_sources)
      left join public.lp_lead_market_assignments a on a.lead_id = l.lp_lead_id
     where l.lp_deleted_at is null
       and (l.created_at_lp at time zone 'UTC')::date between cfg.start_date and cfg.end_date
  ),
  phones as (
    select distinct l.ph10 from l where length(l.ph10) = 10
  ),
  -- One pass over Five9: every event whose ani OR dnis (last 10 digits) is one of this vendor's lead phones.
  ev as materialized (
    select e.id, e.call_id, e.call_start_at, e.disposition_name, x.ph10
      from public.five9_events_raw e
     cross join lateral (values
             (right(regexp_replace(coalesce(e.ani, ''),  '[^0-9]', '', 'g'), 10)),
             (right(regexp_replace(coalesce(e.dnis, ''), '[^0-9]', '', 'g'), 10))) x(ph10)
     where e.call_start_at >= (select min(l.entry_real) from l) - interval '10 minutes'
       and e.call_start_at <= p_as_of
       and x.ph10 in (select phones.ph10 from phones)
  ),
  f as (
    select l.lp_lead_id,
           count(distinct coalesce(ev.call_id, ev.id::text))                          as dials,
           min(ev.call_start_at)                                                       as first_call,
           (array_agg(ev.disposition_name order by ev.call_start_at desc, ev.id desc))[1] as last_result,
           bool_or(ev.disposition_name = any (array[
             'Not Interested', 'Appointment Set', 'Confirmed', 'Callback', 'Cant Do Project', 'Bought Competition',
             'Spanish - Send data to Spanish list', 'Below Minimum', 'Renter - mobile home', 'Verified',
             'Do Not Call', 'DNC', 'Out of Area', 'Service Call', 'Reset', 'Construction', 'Insurance Claim',
             'Duplicate', 'Canvass Confirmed']))                                      as contacted   -- CONTACTED
      from l
      join ev on ev.ph10 = l.ph10 and ev.call_start_at >= l.entry_real - interval '10 minutes'
     group by l.lp_lead_id
  )
  select
    l.lp_prospect_id,
    count(*) over (partition by l.lp_prospect_id) > 1,
    l.lead_source_detail,
    l.mkt,
    case
      when l.mkt in ('ORL_MKT', 'ORL', 'LAKE')        then 'Orlando'
      when l.mkt in ('STPET_MKT', 'STPET')            then 'St. Petersburg'
      when l.mkt in ('JAX_MKT', 'JAX')                then 'Jacksonville'
      when l.mkt in ('FTLAU_MKT', 'FTLAU', 'BOCA')    then 'Fort Lauderdale'
      when l.mkt in ('FTMYR_MKT', 'FTMYR')            then 'Fort Myers'
      when l.mkt in ('SAR_MKT', 'SAR')                then 'Sarasota'
      else 'Outside Service Area'
    end,
    l.entry_wall,
    date_trunc('week', l.entry_wall)::date,
    l.first_name,
    l.last_name,
    nullif(l.ph10, ''),
    l.email,
    initcap(nullif(btrim(l.city), '')),
    nullif(btrim(l.zip), ''),
    coalesce(f.dials, 0)::integer,
    case when f.first_call is null then null
         else round(greatest(extract(epoch from (f.first_call - l.entry_real)) / 60.0, 0)::numeric, 1) end,
    f.last_result,
    coalesce(f.contacted, false),
    (l.set_date at time zone 'UTC'),
    (l.appointment_date at time zone 'UTC'),
    case when l.set_date is not null and l.appointment_date is not null
         then round((extract(epoch from (l.appointment_date - l.set_date)) / 86400.0)::numeric, 1) end,
    (l.confirmed_date at time zone 'UTC'),
    coalesce(l.ever_set, false),
    coalesce(l.ever_confirmed, false),
    case when l.ever_issued then (l.appointment_date at time zone 'UTC')::date end,
    coalesce(l.ever_issued, false),
    coalesce(l.ever_net_issued, false),
    coalesce(l.demo_completed, false),
    coalesce(l.closed_won, false),
    case when l.closed_won then l.job_value end,
    coalesce(d.disposition_label, coalesce(nullif(l.raw_lp_data->>'disposition', ''), l.disposition_code))
  from l
  left join public.lp_dispositions d
    on d.disposition_code = coalesce(nullif(l.raw_lp_data->>'disposition', ''), l.disposition_code)
  left join f on f.lp_lead_id = l.lp_lead_id
  order by l.entry_wall desc, l.lp_prospect_id;
$$;

-- The same rows as ONE jsonb document for GET /vdr/report.xlsx (a set-returning RPC is capped by PostgREST's
-- max rows), with the window, the lead-sync time (the n8n freshness gate) and the 135 cross-check: the newest
-- COMPLETE saved 135 feed (vdr_feed_runs) received in the 36 hours before as_of, counted over this vendor's
-- sub-sources and window. The cross-check never blocks a send; n8n lists a gap over 2% in Mark's summary.
create or replace function public.vdr_vendor_report(p_vendor_id bigint, p_as_of timestamptz default now())
returns jsonb
language sql
stable
set search_path = public
as $$
  with cfg as (
    select c.id, c.vendor_name, c.lp_sub_sources, c.lookback_days,
           (p_as_of at time zone 'America/New_York')::date - c.lookback_days as start_date,
           (p_as_of at time zone 'America/New_York')::date                   as end_date
      from public.vdr_vendor_config c
     where c.id = p_vendor_id
  ),
  feed as (
    select r.id, r.received_at
      from public.vdr_feed_runs r
     where r.complete
       and r.received_at > p_as_of - interval '36 hours'
       and r.received_at <= p_as_of
     order by r.received_at desc, r.id desc
     limit 1
  )
  select case when not exists (select 1 from cfg) then jsonb_build_object('found', false) else (
    select jsonb_build_object(
      'found', true,
      'vendor_id', cfg.id,
      'vendor_name', cfg.vendor_name,
      'lp_sub_sources', to_jsonb(cfg.lp_sub_sources),
      'lookback_days', cfg.lookback_days,
      'start_date', cfg.start_date,
      'end_date', cfg.end_date,
      'as_of', p_as_of,
      'lead_synced_at', (select max(synced_at) from public.lp_leads),
      'feed_check', (
        select jsonb_build_object(
          'run_id', feed.id, 'received_at', feed.received_at,
          'leads', (select count(distinct fl.lead_id) from public.vdr_feed_leads fl
                     where fl.last_run_id = feed.id
                       and fl.sub_source = any(cfg.lp_sub_sources)
                       and fl.entry_date >= cfg.start_date and fl.entry_date <= cfg.end_date))
          from feed),
      'rows', coalesce((select jsonb_agg(to_jsonb(v)) from public.vdr_vendor_leads(p_vendor_id, p_as_of) v), '[]'::jsonb))
    from cfg) end;
$$;

revoke all on function public.vdr_vendor_leads(bigint, timestamptz)  from public, anon, authenticated;
revoke all on function public.vdr_vendor_report(bigint, timestamptz) from public, anon, authenticated;
grant execute on function public.vdr_vendor_leads(bigint, timestamptz)  to service_role;
grant execute on function public.vdr_vendor_report(bigint, timestamptz) to service_role;

notify pgrst, 'reload schema';
