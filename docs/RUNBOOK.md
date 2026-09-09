# Lightfire weekly report — runbook

## State after this PR merges (nothing fires yet)

- `lf_*` schema applied on LP Supabase; roster seeded (44 names); 7 actions
  seeded; approvers = m.richard@ + b.codman@reecewindows.com.
- `lf_report_svc` role + `lf_report_pdfs` table applied
  (`sql/lf_report_svc_role.sql`); the render service reads/writes LP as that
  role over the IPv4 pooler (Phase-E — the service owns all LP I/O, not n8n).
- `report_enabled = false` (kill switch). `lf_vendor_recipients` is EMPTY —
  even an approved run cannot email Lightfire until Mark seeds it.
- Railway service `lf-report-render` deployed (project `n8n`); workflows
  installed INACTIVE in the n8n instance and mirrored in `workflows/`.

## Enable checklist (Mark, in order)

1. Merge the PR; flip the Railway service's deploy branch to `main`.
   Confirm `SUPABASE_DB_URL` is set on the Railway service (the `lf_report_svc`
   pooler URL with its password) and `GET /health` shows `db.ok = true`. The
   password is out-of-band: if the role has none yet,
   `ALTER ROLE lf_report_svc PASSWORD '<secret>'` and put the same secret in
   `SUPABASE_DB_URL`.
2. Run Workflow 90 → "regenerate current week" once. Expected: run reaches
   `READY_FOR_REVIEW` and the approval email lands with the PDF attached.
   Nothing external can send (recipients empty).
3. Reply `APPROVED` (or click Approve) — Workflow 04 must ABORT with
   "no active vendor recipients" and alert. That proves the delivery guard.
4. Seed recipients:
   `INSERT INTO lf_vendor_recipients (email, partner_id, name) SELECT '<addr>', id, '<name>' FROM lf_partners WHERE slug='lightfire';`
5. Activate workflows 01–04 (+90) in n8n.
6. `UPDATE lf_report_config SET value='true' WHERE key='report_enabled';`

## Weekly operation

Monday 08:00 ET: approval email arrives (subject `ACTION REQUIRED — … [LR-…]`).
Reply `APPROVED`, `EDIT: <what to change>`, or `DENY: <reason>` — or use the
buttons. Anything else gets a clarification and the run stays pending.
Reminders at 24 h and 48 h; silence never approves. `EDIT` with a number
(e.g. "Craig had 47 not 49") recalculates everything and produces v2 for a
second approval; a wording-only edit re-renders on the same frozen numbers.

## Managing people

- Approver add/disable: `lf_report_approvers` (email PK, `active` flag).
- Roster: `lf_setter_roster` — team `'Lightfire' | 'Reece' | 'Reece (W)' |
  'exclude'`; a NEW LP name in the cohort hard-BLOCKS the run (gate #3) until
  a roster row exists. That is deliberate: an unmapped name silently excluded
  is how Manieri went missing from a draft.
- Two spellings of one person = two roster rows with the same team;
  `display_name` fixes LP misspellings (see Nievez Moriera).

## Failure triage

| State/alert | Meaning | Do |
|---|---|---|
| `BLOCKED` + validation_report | a §15 hard gate failed (zero matured, unmapped setter, sums broken, degenerate stats) | fix data/roster, re-run via Workflow 90 |
| `GENERATION_FAILED` | render non-200 (pagination guard etc.) | check service logs on Railway; a 500 "pagination" means the layout regressed — do NOT shrink fonts; fix data or the row filters |
| 04 abort "hash mismatch" | stored PDF ≠ approved hash | never force-send; regenerate a new version and re-approve |
| 04 abort "no recipients" | vendor list empty/inactive | seed `lf_vendor_recipients` |
| UNAUTHORIZED approval event | reply from an unlisted address | verify sender; add approver only if legitimate |

Re-render any stored version locally:
`python -c "import json;from report_builder import build_report;from schema import ReportPayload;build_report(ReportPayload.model_validate(json.load(open('payload.json'))),'out.pdf')"`
then `sha256sum out.pdf` — must equal the stored `pdf_sha256` for the same
service version.

## Rollback

Deactivate workflows 01–04 in n8n and set `report_enabled=false`. The
schema is additive; nothing else depends on it. The Railway service can stay
up (stateless, token-gated).

## Phase-2 tickets (out of scope here)

1. Retention: ingest LP Report 137 weekly into
   `lp_sales_efficiency_setter_history`; then fill `payload.retention` (any
   read of `scorecard_report_snapshots` MUST filter `is_current = true`).
2. Five9 dialler-day staffing (5,000-row Call Log cap → 4–6 h windows; cap
   never-logged-out logins at the scheduled shift).
3. Record-level stranded audit automation (`stranded_audit` payload block).
4. n8n GitOps deploy repair (`N8N_API_KEY` empty since 2026-08-04) — until
   then `workflows/*.json` are mirrors, live is truth.
