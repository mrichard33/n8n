# LP report ingest — the five workflows, and the three that are retired

Five independent workflows carry the LeadPerfection scheduled reports from
Gmail into LP-MCP. Each is a thin transport: Gmail Trigger → keep every `.csv`
attachment → POST the CSV **text** → telemetry. No parsing happens here.

`I.LPRB`–`I.LPRE` (133, 135, 136, 137) report BOTH outcomes. `I.LPRA` (134) and
`I.LPRF` (138) still report failures only — see "The IF is positive" below for
why that gap matters, and treat it as outstanding work rather than a choice.

| Workflow | Report | n8n ID | Endpoint | Reports success? |
|---|---|---|---|---|
| `I.LPRA` | 134 Jobs by Milestone Date | `mmgiTOWznsTfz8c9` | `/lp-csv-ingest/jobs-by-milestone` | ❌ failures only |
| `I.LPRB` | 133 Jobs By Status | `fzDXhS0mC5DSbgRj` | `/lp-csv-ingest/job-status` | ✅ |
| `I.LPRC` | 135 Lead Disposition Detail | `0cEoJ0GI5tBrQFp7` | `/lp-csv-ingest/lead-disposition` | ✅ |
| `I.LPRD` | 136 Marketing Sub-Source Cost | `7aFZC5BLzvp9QgaK` | `/lp-csv-ingest/source-cost` | ✅ |
| `I.LPRE` | 137 Sales Efficiency by Market | `OyjpSpcDbSf2hC7G` | `/lp-csv-ingest/sales-efficiency` | ✅ |

**⚠️ COMMITTED FILES CAN DRIFT FROM LIVE, AND THAT DRIFT IS DANGEROUS.** On
2026-08-29 all four of `I.LPRB`–`I.LPRE` still carried a Gmail trigger querying
`filename:pdf` with no `to:` or `subject:` scoping, weeks after LP moved to CSV.
Pasting any of those files into n8n would have matched zero attachments and
silently stopped that report's daily ingest — no error, because zero items is
not an error. They have since been reconciled. **Before applying any file here,
diff it against the live workflow first.**

## Why five, not one

The combined `I.LPR` router handled one report per poll and silently dropped
its siblings when several arrived in the same window. Five independent triggers
cannot drop each other's report, and a change to one can never risk the other
four.

## Two properties that must not regress

**Every message, every attachment.** The Gmail query is deliberately broad
(sender + `has:attachment` + `filename:pdf`) so no subject-string change can
quietly stop a feed. Routing happens in the Code node on the report ID in the
filename (`_133_` … `_137_`), and it iterates `$input.all()` and every binary
key within each item. A workflow takes its own attachments and leaves the rest
to its siblings — a non-matching filename is a sibling's item, not a dropped
one.

**The IF is positive.** The condition reads `{{ $json.success === true }}`
OR `{{ $json.duplicate === true }}`; output 1 (FALSE) goes to
`/events/lp_report_ingest_failed`, alongside the HTTP node's error output. An
earlier build had these reversed, so every SUCCESSFUL ingest filed a bogus
`transport_error`.

Output 0 (TRUE) used to go NOWHERE. On `I.LPRB`–`I.LPRE` it now goes to
`/events/lp_report_ingest_succeeded`. That silence was a real defect, not a
tidy default: `scorecard_ingest_log` under report_type `jobs_by_status` could
only ever receive failure rows, so the table showed 133 as permanently broken
for the eight days AFTER it was fixed — its last row was the 2026-08-21
rejection while the parser ingested cleanly every morning. A signal that can
only go red tells you nothing when it is red.

**`I.LPRA` (134) and `I.LPRF` (138) still dead-end their TRUE branch** and so
remain blind in exactly the same way. That is outstanding work, not a decision.

Note the row this writes is TELEMETRY, not the ingest record. The authoritative
row is the one LP-MCP writes itself; this one attests only that n8n got a green
answer back, which is the only fact n8n can vouch for.

**⚠️ On 135, 136 and 137 the telemetry row shares its `report_type` with the
parser, so a successful run writes TWO rows.** 133 is the exception, not the
rule: its telemetry lands under `jobs_by_status` while its parser writes
`job_status_ytd`, so the two never collide. For the others `REPORT_TYPE_SLUGS`
maps `lead-disposition` → `lead_disposition`, `source-cost` → `source_cost` and
`sales-efficiency` → `sales_efficiency` — the same value the parser uses. Tell
them apart by `source` (`n8n_telemetry` vs `n8n`) and by `snapshot_id`, which is
null on the telemetry row. **Any query counting successes MUST filter on
`source`, or it will double-count every green run.**

The duplicate clause is belt-and-braces: LP-MCP already returns
`success: true, duplicate: true` for a re-send, so the first condition covers
it. The second exists so that a future change to the response shape still
cannot page GroupMe for a benign no-op. Both sides are written as `=== true`
expressions rather than bare fields because `typeValidation` is `strict` and
`$json.duplicate` is absent — not `false` — on a normal success.

## The CSV branch — I.LPRA owns it for all five reports

LP now schedules CSV exports, so `I.LPRA` carries a second branch:
`Select CSV attachments (any report)` → `POST CSV to LP-MCP ingest`. Three
things about it are deliberate.

**There is no filename routing, and there cannot be.** CSV attachments are all
named `<user>_<YYMMDDHHMMSS>_Export.csv` — identical in shape for every report,
with no `_134_` to match. LP-MCP identifies the report from the CSV **header
row** and returns the resolved `report_type`. Do not try to infer it here; the
retired `…Sales Efficiency by Mode Ingest copy` above is what guessing costs.

**Every workflow now takes CSVs — and the double-post it used to risk is
prevented by SCOPING, not by keeping four of them on PDF.** The old arrangement
left `I.LPRB`–`I.LPRE` on a PDF branch because all five polled one broad query,
so if each also took every CSV, one morning's batch would post 25 times instead
of 5. Each trigger is now scoped by `to:` AND `subject:`, so a workflow sees
only its own report and the arithmetic no longer applies. **Do not remove that
scoping** — it is the only thing standing between this design and the
25-posts-a-morning failure.

**`Content-Type: text/csv` is set explicitly.** LP-MCP mounts a global
`express.json()`; without the header it claims the body first and the route
returns a 400 that reads like a missing body when the body was fine and merely
mistyped.

The slug in the CSV URL (`/lp-csv-ingest/jobs-by-milestone`) is only a hint —
the header fingerprint overrides it, which is exactly what lets one workflow
post all five reports to one endpoint.

LP-MCP still serves the PDF routes (`/lp-report-ingest/{lead-disposition|source-cost|sales-efficiency}`)
for legacy replays of the 18 PDF-sourced snapshots, but no workflow posts to
them any more.

## 138 rides I.LPRA too — there is deliberately no sixth workflow

LP report **138 Appointment Stats by Sales Rep with Source** (canonical Reece
id; LP also exposes it as ReportView `Rpt=229`, which is a URL parameter and not
an identifier) needs **no n8n change at all**. Its export is a CSV from the same
`ReportScheduler@leadperfection.com` sender, so `I.LPRA`'s
`Select CSV attachments (any report)` already picks it up, and LP-MCP resolves it
from the header row the moment its fingerprint is registered.

A sixth workflow was specified and is deliberately not built. It would poll the
same broad query as the other five, so it would take every CSV, not only 138 —
turning one morning's batch into twelve posts instead of six, half of them
duplicates burying the ingest log. (That arithmetic is also what USED to keep
`I.LPRB`–`I.LPRE` on a PDF branch; subject scoping has since replaced it.)

Scoping a sixth workflow by Gmail subject would avoid the double-post, but it
reintroduces exactly the subject-string fragility the broad query exists to
prevent. If 138 ever needs its own workflow, that trade is the decision to make
consciously — not a copy of `I.LPRB` with the numbers changed.

## Retired — deactivated 2026-08-06, kept for reference

These were still `active` and still polling. Two of them are why the same
report was being submitted more than once, which is what produced eight
snapshots of one `jobs_by_milestone` period with distinct byte hashes — two of
them landing 20 ms apart.

| Workflow | n8n ID | Why it was retired |
|---|---|---|
| `I.LPR LP Report Router (133–137)` | `wakX7NzvbOJa1UZt` | The combined router. Superseded by the five above. |
| `I.LPRD LP Report D Marketing Sub-Source Cost Ingest` | `TTMwTyfpItCy8gnA` | A **duplicate** of the canonical `I.LPRD` — both polled for report 136 and both POSTed it to `/source-cost`, so every 136 email was submitted twice. The 2026-08-05 rollback recorded this one as archived; it was not. |
| `I.LPRD LP Report E Sales Efficiency by Mode Ingest copy` | `XYPxEEmBm8iWXzXl` | **Misrouted.** Its Gmail filter matched report 137 (`Sales Efficiency by Mode`) but it POSTed to `/source-cost` — feeding Sales Efficiency PDFs into the Source Cost endpoint. |

Deactivated, not deleted: `active: false` is reversible in one click, and the
definitions stay readable. Neither carries a canonical export in this repo,
which is itself part of how they survived — a workflow that exists only in the
n8n instance is invisible to review.

## When adding a workflow here

Export it into `workflows/` under its canonical `I.LPRx` name and add it to the
table above. An unexported live workflow cannot be diffed, reviewed, or noticed.
