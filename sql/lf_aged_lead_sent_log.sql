-- LightFire daily aged-leads sent log. Applied to LP Supabase (rcjcgjlqzepicbwhnnjl) on 2026-10-06.
-- Used by n8n "05 LF Daily Aged Leads Delivery" (KQpmuov6oNBpmQ85):
--   before sending  -> POST /rest/v1/rpc/lf_aged_already_sent  {p_ids, p_phones}
--   after sending   -> POST /rest/v1/lf_aged_lead_sent_log      [rows]
-- Any lead whose LP id OR phone is already here is never sent to LightFire again.

create table if not exists public.lf_aged_lead_sent_log (
  id bigserial primary key,
  lp_lead_id text,
  phone10 text,
  last_name text,
  entry_date text,
  disposition text,
  sent_date date not null,
  source_file text,
  out_file text,
  created_at timestamptz not null default now()
);
create index if not exists lf_aged_lead_sent_log_lead_idx on public.lf_aged_lead_sent_log (lp_lead_id);
create index if not exists lf_aged_lead_sent_log_phone_idx on public.lf_aged_lead_sent_log (phone10);
alter table public.lf_aged_lead_sent_log enable row level security;

create or replace function public.lf_aged_already_sent(p_ids text[], p_phones text[])
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'ids', coalesce((select jsonb_agg(distinct lp_lead_id) from public.lf_aged_lead_sent_log where lp_lead_id = any(p_ids)), '[]'::jsonb),
    'phones', coalesce((select jsonb_agg(distinct phone10) from public.lf_aged_lead_sent_log where phone10 = any(p_phones)), '[]'::jsonb),
    'log_rows', (select count(*) from public.lf_aged_lead_sent_log)
  );
$$;

revoke all on function public.lf_aged_already_sent(text[], text[]) from public, anon, authenticated;
grant execute on function public.lf_aged_already_sent(text[], text[]) to service_role;
revoke all on table public.lf_aged_lead_sent_log from anon, authenticated;
grant all on table public.lf_aged_lead_sent_log to service_role;
grant usage, select on sequence public.lf_aged_lead_sent_log_id_seq to service_role;
notify pgrst, 'reload schema';
