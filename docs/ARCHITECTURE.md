# Lightfire weekly report — architecture

Three planes, strictly separated (Handoff V2 §2):

- **n8n = orchestration only.** Scheduling, calling the render service,
  mailbox monitoring, sending Gmail, error notification. No business logic, no
  formatting, no statistics, no reply parsing — **and no SQL** (see the
  Phase-E note below). n8n holds triggers, HTTP calls and Gmail sends only.
- **Supabase (LP project) = system of record.** Run state machine, frozen
  snapshots, versions, approvals, actions, deliveries, overrides, audit,
  configuration. Tables are the `lf_*` family (`sql/lf_report_v2_schema.sql`).
- **GitHub (this repo) = the application.**
  `services/lf-report-render/` computes, renders **and owns all LP I/O**;
  `sql/` holds schema and the production queries; `workflows/` mirrors the
  installed n8n workflows.

## Phase-E adaptation: the render service owns LP data I/O

The original design had n8n run the SQL (Postgres nodes) and call the render
service. Two hard facts made that impossible: the n8n instance cannot reach LP
Postgres (Supabase direct connections are IPv6-only; the n8n Railway container
has no IPv6 route), and the n8n workflow API refuses to attach generic
HTTP-auth credentials programmatically. So the render service reads `lp_leads`
and reads/writes the `lf_*` state itself, connecting as the dedicated
least-privilege role `lf_report_svc` over Supabase's IPv4 session pooler
(`db.py`). The password lives ONLY in the Railway env var `SUPABASE_DB_URL` —
never in git, never in n8n JSON. This is arguably *more* faithful to §2: the
maturity rule is business logic, and it now lives with the rest of it. The
five workflows stay exactly as specified but thin — triggers, HTTP to the
service, Gmail, alerts. PDFs live in `lf_report_pdfs` (bytea) so the D5 hash
chain is one datastore and one transaction. See
`docs/REPORT_SPEC.md` deviations and `sql/lf_report_svc_role.sql`.

## Render service

FastAPI, stateless, deployed on Railway (project `n8n`, service
`lf-report-render`, root `services/lf-report-render`).

```
Stateless rendering (payload in / PDF out):
POST /validate            payload -> {ok, failures, warnings, derived}
POST /render              payload -> application/pdf (X-Pdf-Sha256, X-Page-Count)
POST /classify-reply      {raw}   -> APPROVED | DENY | EDIT | UNKNOWN (+ kind)

LP-backed pipeline (db.py owns every read/write; orchestrator.py the logic):
POST /orchestrate/weekly  {run_date?, force?}  -> gates -> freeze -> render -> approval fields
POST /approval/decide     {token, sender_email, raw_reply, channel} -> §14 route
POST /revise              {run_id, revision_kind, instruction, overrides?} -> v(n+1)
POST /deliver/prepare     {version_id} -> hash + recipients guard, go/no-go
POST /deliver/confirm     {version_id} -> record delivery, run -> SENT
POST /reminders/tick      {}      -> due 24h/48h reminders (never approves)
GET  /reports/{id}/pdf            -> application/pdf (Gmail attachment source)
GET  /health                      -> service + DB status
```

`/validate` and `/render` run the SAME derivation (`assemble.py`) on the same
frozen payload, so the metrics the orchestrator persists and the document it
renders cannot diverge. The payload carries raw query results; every
displayed value is derived deterministically — same payload, same PDF,
byte-comparable by SHA-256. `build_payload` (in `orchestrator.py`) is the pure
translation from query rows to that payload; the pipeline endpoints wrap it
with the gates and the state transitions.

## Run state machine (`lf_report_runs.status`)

```
SCHEDULED -> INGESTING -> VALIDATING -> READY_FOR_REVIEW -> APPROVED -> SENDING -> SENT
                 |             |               |                |
                 |             +-> BLOCKED     +-> DENIED       +-> (04 hash mismatch -> FAILED alert)
                 +-> GENERATION_FAILED         +-> REVISION_REQUESTED -> (03) -> READY_FOR_REVIEW (v2, new token)
```

- Idempotency: unique `(partner_id, period_start, period_end)`; a re-run
  finds the row. SENT/APPROVED/READY_FOR_REVIEW → exit without side effects.
- Kill switch: `lf_report_config.report_enabled` (DB, auditable — D4), read
  by Workflow 01 step 3.
- Nothing auto-approves. Reminders at 24 h/48 h; after the last one the run
  stays pending forever.

## The four workflows (+ manual controls)

Under Phase-E each workflow is a thin trigger → HTTP-to-service → Gmail shell;
the verb after "→ service" names the endpoint that does the work.

| Workflow | Trigger | Job |
|---|---|---|
| 01 weekly orchestrator | Schedule Mon 08:00 ET (workflow TZ `America/New_York`) | → `POST /orchestrate/weekly` → Gmail the returned approval email + PDF to approvers |
| 02 approval processor | Gmail Trigger (5 min) + Webhook `/lf-decision/{token}/{action}` + hourly reminder schedule | → `POST /approval/decide`; on `deliver` call 04, on `edit` call 03, on `deny`/`unauthorized`/`unknown` Gmail internal. Reminder branch → `POST /reminders/tick` → Gmail |
| 03 report revision | called by 02 on EDIT | → `POST /revise` (service applies overrides to the frozen payload and re-renders) → Gmail the new approval email. New version, new token, second approval |
| 04 external delivery | called by 02 on APPROVED | → `POST /deliver/prepare` (recipients + SHA-256 guard); if `ok`, fetch `GET /reports/{id}/pdf`, Gmail to `lf_vendor_recipients`, then `POST /deliver/confirm` → run `SENT`. Empty recipients or hash mismatch → abort + alert |
| 90 manual controls | manual | `force`/`manual_regeneration` regenerate, resend approval, preview, resolve action, re-apply overrides via the same endpoints |

## Integrity chain (D5)

`lf_report_versions` stores the frozen payload + `payload_sha256` +
`pdf_sha256` + `page_count`; the PDF bytes live in `lf_report_pdfs` keyed by
`version_id` (`pdf_storage_path = db://lf_report_pdfs/{version_id}`). Approval
binds `approved_version_id`. `/deliver/prepare` re-reads the stored PDF and
recomputes its hash immediately before send — it must equal both the stored
`sha256` and the version's `pdf_sha256`, or delivery aborts (the corrupted-PDF
guard). `/deliver/confirm` recomputes again and records `approved_sha256`,
`sent_sha256`, `hash_verified` in `lf_delivery_events`, flipping the run to
`SENT` only when verified. A PDF is never edited in place; a revision is a new
version requiring a new approval.

## Email security model (§14)

Not cryptographic — compensating controls: sender allow-list
(`lf_report_approvers`), run-scoped one-time token in the subject
(`LR-{iso_year}-W{week}-V{n}`), decisions accepted only in state
`READY_FOR_REVIEW`, resolved requests reject further decisions, full audit
trail (`lf_approval_events`, raw + cleaned reply). Reply parsing tests DENY
and EDIT before APPROVE and anchors the command at the start of the cleaned
text — "not approved" contains "approved"; the naive check sends an
unapproved report to a vendor.
