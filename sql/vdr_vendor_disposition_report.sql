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
  send_time time not null default '09:00',
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
