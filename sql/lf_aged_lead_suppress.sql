-- LightFire aged leads: partner (Ross / RFED) + One-Leg block. Applied to LP Supabase (rcjcgjlqzepicbwhnnjl) 2026-10-23.
-- Used by n8n "05 LF Daily Aged Leads Delivery" (KQpmuov6oNBpmQ85), node "Build final CSV".
-- Note: the CSV "id" column (and lf_aged_lead_sent_log.lp_lead_id) is the LP PROSPECT id.

create table if not exists public.lf_aged_lead_suppress (
  id bigserial primary key,
  prospect_id text,
  phone10 text,
  reason text not null,
  origin_lp_lead_id text,
  added_at timestamptz not null default now()
);
create index if not exists lf_aged_lead_suppress_prosp_idx on public.lf_aged_lead_suppress (prospect_id);
create index if not exists lf_aged_lead_suppress_phone_idx on public.lf_aged_lead_suppress (phone10);
alter table public.lf_aged_lead_suppress enable row level security;
revoke all on table public.lf_aged_lead_suppress from anon, authenticated;
grant all on table public.lf_aged_lead_suppress to service_role;
grant usage, select on sequence public.lf_aged_lead_suppress_id_seq to service_role;

-- Seed: Ross's top 50 One-Leg leads (picked 2026-10-22). 50 prospects, 52 phones.
insert into public.lf_aged_lead_suppress (prospect_id, phone10, reason, origin_lp_lead_id)
select distinct o.lp_prospect_id, right(regexp_replace(p,'\D','','g'),10), 'ROSS_RFED_TOP50_2026-10-22', o.lp_lead_id
from lp_leads o
join lp_leads a on a.lp_prospect_id = o.lp_prospect_id
cross join lateral unnest(array[a.phone, a.phone_alt]) p
where o.lp_lead_id = any(string_to_array('564157,569515,568736,575860,561890,562554,571740,571080,573089,565402,561125,571412,576060,567518,572649,574343,570620,572979,565074,564015,548342,576068,566668,556763,569064,564527,576682,559659,555512,574232,420011,571373,564738,541511,571520,562094,573782,558514,561530,549842,569069,556000,550689,558342,557755,561690,511563,546802,570995,566607',','))
  and p is not null and length(regexp_replace(p,'\D','','g')) >= 10;

create or replace function public.lf_aged_already_sent(p_ids text[], p_phones text[])
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'ids', coalesce((select jsonb_agg(distinct lp_lead_id) from public.lf_aged_lead_sent_log where lp_lead_id = any(p_ids)), '[]'::jsonb),
    'phones', coalesce((select jsonb_agg(distinct phone10) from public.lf_aged_lead_sent_log where phone10 = any(p_phones)), '[]'::jsonb),
    'log_rows', (select count(*) from public.lf_aged_lead_sent_log),
    'partner_ids', coalesce((select jsonb_agg(distinct x) from (
        select prospect_id x from public.lf_aged_lead_suppress where prospect_id = any(p_ids)
        union select lp_prospect_id from public.partner_rfed_batch where lp_prospect_id = any(p_ids)) q), '[]'::jsonb),
    'partner_phones', coalesce((select jsonb_agg(distinct phone10) from public.lf_aged_lead_suppress where phone10 = any(p_phones)), '[]'::jsonb),
    'oneleg_ids', coalesce((select jsonb_agg(distinct lp_prospect_id) from public.lp_leads
        where disposition_code = '1Leg' and lp_deleted_at is null and lp_prospect_id = any(p_ids)), '[]'::jsonb),
    'oneleg_phones', coalesce((select jsonb_agg(distinct ph) from (
        select right(regexp_replace(p,'\D','','g'),10) ph from public.lp_leads l
        cross join lateral unnest(array[l.phone, l.phone_alt]) p
        where l.disposition_code = '1Leg' and l.lp_deleted_at is null and p is not null) q
        where ph = any(p_phones)), '[]'::jsonb)
  );
$$;
revoke all on function public.lf_aged_already_sent(text[], text[]) from public, anon, authenticated;
grant execute on function public.lf_aged_already_sent(text[], text[]) to service_role;
notify pgrst, 'reload schema';
