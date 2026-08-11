# I.LPRA (LP report 134) — transport fix, to apply by hand in the n8n UI

**Workflow:** `I.LPRA LP Report 134 Jobs by Milestone Date Ingest`
**n8n id:** `mmgiTOWznsTfz8c9` · **Status:** active, published (`versionId == activeVersionId`)
**Written:** 2026-08-11, against the live instance — not against this repo.

> Apply these in the n8n UI, then **Publish**. Do not deploy them from this repo:
> `/workflows` has drifted from live for two months (every GitOps run since
> 2026-06-22 failed on an empty `N8N_API_KEY`), so the stored copy of I.LPRA is
> not what is running. Live is authoritative.

---

## What is actually wrong

134 has been dark on the schedule while its five siblings ingest normally.

Execution `239249` (2026-08-11T00:00:36Z, `mode: trigger`, status `success`) is the
proof. The Gmail trigger fired and downloaded three CSV attachments:

```
_260810040200_Export.csv   78.6 kB   "Jobs by Milestone Date July 2026"
_260810040157_Export.csv   98.1 kB   "Jobs by Milestone Date June 2026"
_260810040154_Export.csv   95.4 kB   "Jobs by Milestone Date May 2026"
```

The next node — `Select report 134 attachments (filename _134_)` — emitted `[]`.
The run finished in **41 ms** having done nothing, and reported success.

The cause is the first line of that Code node:

```js
const RE = /_134_/;
```

LP names every CSV export `_<YYMMDDHHMMSS>_Export.csv`. **There is no report id in
the filename.** The regex can never match, so every attachment is dropped. Because
the node returns an empty list rather than throwing, nothing reaches the IF node,
no telemetry fires, and the workflow logs a clean success. It has been failing
silently, not loudly.

This is the same defect that was fixed on I.LPRB–I.LPRE on 2026-08-10; I.LPRA was
left behind. Its own sibling I.LPRC documents it on the canvas.

## Which edits are load-bearing

Three edits are required. A fourth is recommended for consistency but is **not**
what is breaking 134 — worth knowing so you can judge the risk of each.

| # | Edit | Required? | Why |
|---|---|---|---|
| 1 | Code node filename regex | **Yes** | This is why 134 is dark. Nothing else runs until it matches. |
| 2 | `Content-Type` header → `text/csv` | **Yes** | LP-MCP parses the body with `express.text({type:['text/csv','text/plain','application/octet-stream']})`. `application/pdf` is not in that list, so the body arrives empty and the route 400s. |
| 3 | URL → the `lp-csv-ingest` route | **Yes** | The `lp-report-ingest` route is the PDF parser. It will not read a CSV. |
| 4 | Body mode `binaryData` → `raw` + `csv_text` | Recommended, not required | Matches I.LPRB–E. **Binary mode does work** when the Content-Type header is right — I.LPRF (report 138) posts `binaryData` and ingests successfully on every scheduled run. Included below so all six workflows read the same way. |

Edit 2 is the one that was misdiagnosed in the original write-up: the Aug-10 400s
were caused by the `application/pdf` header, not by binary body mode.

---

## Edit 1 — Code node `Select report 134 attachments (filename _134_)`

Replace the entire `jsCode` with:

```js
// Select report 134 attachments and hand the CSV to the HTTP node as TEXT.
//
// There is deliberately NO `_134_` filename test. LP names every CSV export
// `_<YYMMDDHHMMSS>_Export.csv` — the report id is not in the filename, so that
// regex matched nothing and this node returned an empty list on every run. The
// workflow then "succeeded" in 41ms having dropped the file, with no telemetry,
// which is why 134 went dark unnoticed (execution 239249, 2026-08-11).
//
// Report identity is decided by LP-MCP's header fingerprint. Scope comes from
// the Gmail subject query on the trigger, which already narrows this workflow to
// "Jobs by Milestone Date".
//
// The ingest route reads the body with express.text(), so hand it a string.
const out = [];
const items = $input.all();
for (let i = 0; i < items.length; i++) {
  const bin = items[i].binary ?? {};
  for (const key of Object.keys(bin)) {
    const fileName = bin[key]?.fileName ?? '';
    if (!/\.csv$/i.test(fileName)) continue;
    const buf = await this.helpers.getBinaryDataBuffer(i, key);
    out.push({
      json: {
        lp_report_id: '134',
        attachment_file_name: fileName,
        csv_text: buf.toString('utf8'),
      },
    });
  }
}
return out;
```

Two things to keep: the loop must be **indexed** (`getBinaryDataBuffer` needs the
item index), and the output carries **no `binary` key** — the payload moves into
`json.csv_text`.

The node name still says `(filename _134_)`. Leave it. `connections` reference
nodes by name, and renaming risks breaking the wiring for no functional gain —
I.LPRB–E carry the same stale names after the same fix.

## Edit 2 — HTTP node `POST raw PDF to LP-MCP ingest`

| Field | From | To |
|---|---|---|
| URL | `…/n8n/admin/lp-report-ingest/jobs-by-milestone` | `…/n8n/admin/lp-csv-ingest/jobs-by-milestone` |
| Header `Content-Type` | `application/pdf` | `text/csv` |
| Body Content Type | `n8n Binary File` | `Raw` |
| Raw Content Type | — | `text/csv` |
| Body | — | `={{ $json.csv_text }}` |
| Input Data Field Name | `attachment_0` | *(remove)* |

Leave unchanged: `x-ghl-signature`, `timeout: 120000`, `retryOnFail: true`,
`maxTries: 3`, `waitBetweenTries: 5000`, `onError: continueErrorOutput`.

Full target parameter set, for comparison against I.LPRC:

```json
{
  "method": "POST",
  "url": "https://lp-mcp-production.up.railway.app/n8n/admin/lp-csv-ingest/jobs-by-milestone",
  "sendHeaders": true,
  "headerParameters": {
    "parameters": [
      { "name": "Content-Type",    "value": "text/csv" },
      { "name": "x-ghl-signature", "value": "=ef14dba08435f1a7dcf38ac449a4838281fb0e72bb490cb8330c9e7fddddc269" }
    ]
  },
  "sendBody": true,
  "contentType": "raw",
  "rawContentType": "text/csv",
  "body": "={{ $json.csv_text }}",
  "options": { "timeout": 120000 }
}
```

## Do NOT change the Gmail trigger

Live I.LPRA already polls hourly with:

```
to:lp-reports@reecewindowsmail.com from: ReportScheduler@leadperfection.com
subject:"Jobs by Milestone Date" has:attachment filename:csv
```

That is correct and is what makes the report-scoping safe. It is also why there is
no duplicate-posting risk: each workflow is subject-scoped to its own report, so
none of them can pick up a sibling's file.

## Then Publish

n8n runs the **published** version, not the autosaved draft. After publishing,
confirm `versionId == activeVersionId`.

---

## I.LPRF (report 138) — mostly fine, one cosmetic defect

**n8n id:** `x4IebASKtAFWdiND` · active, published, 8 Gmail triggers (one per month
plus the recurring current-month one).

**It is working.** On 2026-08-11 it ran six times in `mode: trigger` at 00:00 and
every run produced an `appt_stats_by_rep_source` row in `scorecard_ingest_log`
within about a second. Its Code node already uses `/\.csv$/i` — no `_138_` regex.
**No transport fix is needed.**

One thing is wrong but tolerated: its URL posts to
`…/n8n/admin/lp-csv-ingest/sales-efficiency`, which is report **137**'s slug.
Report 138 has no slug of its own. It still lands correctly because
`detectReportFromHeader` fingerprints the file and overrides the slug — but every
run logs `header says appt_stats_by_rep_source, routing there instead`. Two ways
to clear it, neither urgent:

- add an `appt-stats` slug to `CSV_REPORT_TYPES` in LP-MCP and point I.LPRF at it, or
- leave it and treat the warning as expected.

Its canvas note still says *"Keep INACTIVE until the 138 parser PR merges"*. That
merged in PR #657 (the identity gate was downgraded to warnings), so the note is
stale and the workflow is correctly active. Worth editing the note so the next
reader is not misled.

---

## How to verify — from a scheduled run, not a manual one

A manual run exercises the POST node but not the Gmail trigger or the published-
version path, which is where the last two failures lived.

**1. The execution emitted items.** After the next hourly poll that has a 134 email
waiting, open the run and confirm the Code node output is not `[]`. A ~40 ms
success with an empty Code node output means the regex is still wrong.

**2. A row landed.**

```sql
SELECT report_type, status, source, row_count, created_at
FROM scorecard_ingest_log
WHERE report_type = 'jobs_by_milestone'
ORDER BY created_at DESC
LIMIT 10;
```

⚠ **`source` cannot tell you scheduled from manual.** LP-MCP reads it from
`req.query.source` and defaults to `'manual'`; none of the six workflows append
`?source=n8n`, so every n8n post logs as `manual`. Correlate on **timestamp**
against the n8n execution instead — the ingest row lands within a second or two of
the run. (Appending `?source=n8n` to all six URLs would fix this properly, and is
worth doing separately.)

**3. The snapshot advanced.**

```sql
SELECT period_start, period_end, is_current, report_generated_at, row_count
FROM scorecard_report_snapshots
WHERE report_type = 'jobs_by_milestone' AND scope = 'mtd'
ORDER BY ingested_at DESC
LIMIT 5;
```

Exactly one `is_current = true` row, with `period_end` at or after the previous
one's.

## Backfill is not automatic

A Gmail polling trigger is forward-only and dedupes on message id, so this fix
restores the **next** arrival and recovers nothing already polled. The May/June/
July files from the 2026-08-10 batch are gone as far as the trigger is concerned.
Recover them with a direct POST of the CSV text to
`…/n8n/admin/lp-csv-ingest/jobs-by-milestone?source=manual-backfill`.
