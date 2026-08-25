# Lightfire weekly report — architecture

Three planes, strictly separated (Handoff V2 §2):

- **n8n = orchestration only.** Scheduling, SQL I/O, calling the render
  service, approval routing, mailbox monitoring, delivery, error
  notification, status transitions. No business logic, no formatting, no
  statistics, no reply parsing.
- **Supabase (LP project) = system of record.** Run state machine, frozen
  snapshots, versions, approvals, actions, deliveries, overrides, audit,
  configuration. Tables are the `lf_*` family (`sql/lf_report_v2_schema.sql`).
- **GitHub (this repo) = the application.**
  `services/lf-report-render/` computes and renders; `sql/` holds schema and
  the production queries; `workflows/` mirrors the installed n8n workflows.

## Render service

FastAPI, stateless, deployed on Railway (project `n8n`, service
`lf-report-render`, root `services/lf-report-render`).

```
POST /validate        payload -> {ok, failures, warnings, derived}
POST /render          payload -> application/pdf (X-Pdf-Sha256, X-Page-Count)
POST /classify-reply  {raw}   -> APPROVED | DENY | EDIT | UNKNOWN (+ kind)
GET  /health
```

`/validate` and `/render` run the SAME derivation (`assemble.py`) on the same
frozen payload, so the metrics the orchestrator persists and the document it
renders cannot diverge. The payload carries raw query results; every
displayed value is derived deterministically — same payload, same PDF,
byte-comparable by SHA-256.

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

| Workflow | Trigger | Job |
|---|---|---|
| 01 weekly orchestrator | Schedule Mon 08:00 ET (workflow TZ `America/New_York`) | windows → gates → snapshots → render → upload → approval email |
| 02 approval processor | Gmail Trigger (5 min) + Webhook `/lf-decision/{token}/{action}` + reminder schedule | classify (via `/classify-reply`) → transition |
| 03 report revision | called by 02 on EDIT | DATA_CORRECTION: overrides + full re-run of 01 steps 5–12; NARRATIVE_EDIT: re-render on the frozen snapshot. New version, new token, second approval |
| 04 external delivery | called by 02 on APPROVED | assert APPROVED + version match + not sent; re-download PDF; SHA-256 must equal `approved_sha256`; send to `lf_vendor_recipients`; record both hashes |
| 90 manual controls | manual | regenerate / resend approval / cancel / preview / resolve action / re-apply overrides |

## Integrity chain (D5)

`lf_report_versions` stores the frozen payload + `payload_sha256` +
`pdf_sha256` + `page_count`. Approval binds `approved_version_id`. Workflow
04 re-downloads the stored PDF and recomputes the hash immediately before
send; mismatch aborts. `lf_delivery_events` records `approved_sha256`,
`sent_sha256`, `hash_verified`. A PDF is never edited in place; a revision is
a new version requiring a new approval.

## Email security model (§14)

Not cryptographic — compensating controls: sender allow-list
(`lf_report_approvers`), run-scoped one-time token in the subject
(`LR-{iso_year}-W{week}-V{n}`), decisions accepted only in state
`READY_FOR_REVIEW`, resolved requests reject further decisions, full audit
trail (`lf_approval_events`, raw + cleaned reply). Reply parsing tests DENY
and EDIT before APPROVE and anchors the command at the start of the cleaned
text — "not approved" contains "approved"; the naive check sends an
unapproved report to a vendor.
