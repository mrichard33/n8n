# n8n/sql — history, not a queue

**New schema does not go here (Fix 1, 2026-10-12).** The LightFire report tables, the Slack onboarding
tables and `lf_aged_lead_sent_log` live in the LP Supabase project, and every schema change for that
project is now a file in `LP-MCP/supabase/migrations/`, checked and applied by CI there. Doctrine:
`LP-MCP/sql/README.md`.

The seven files here are the record of what was applied by hand (and, for `lf_report_svc_role.sql`,
through a migration recorded as `20260728000000_create_lf_report_svc_role`). Keep them for their comments;
do not add to them.

| File | What it created |
|---|---|
| `lf_report_v2_schema.sql`, `sql_lf_report_v2_schema.sql` | LightFire weekly report tables (`lf_*`) |
| `lf_report_svc_role.sql` | the `lf_report_svc` role, `lf_report_pdfs`, RLS policies |
| `lf_report_metrics.sql`, `lf_report_queries.sql` | report metric views and queries |
| `lf_aged_lead_sent_log.sql` | the aged-leads sent log (2026-10-06) |
| `slack_onboarding_schema.sql` | `team_members`, `slack_channels`, `slack_role_channels`, `slack_market_slugs` |

A workflow that needs a new table: open a PR in LP-MCP with the migration, merge it, then ship the
workflow change here.
