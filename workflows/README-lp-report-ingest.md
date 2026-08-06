# LP report ingest — the five workflows, and the three that are retired

Five independent workflows carry the LeadPerfection scheduled reports from
Gmail into LP-MCP. Each is a thin transport: Gmail Trigger → filter on the LP
report ID in the attachment FILENAME → POST the raw PDF → telemetry on failure
only. No parsing happens here.

| Workflow | Report | n8n ID | Endpoint |
|---|---|---|---|
| `I.LPRA` | 134 Jobs by Milestone Date | `mmgiTOWznsTfz8c9` | `/lp-report-ingest/jobs-by-milestone` |
| `I.LPRB` | 133 Jobs By Status | `fzDXhS0mC5DSbgRj` | `/lp-report-ingest/jobs-by-status` |
| `I.LPRC` | 135 Lead Disposition Detail | `0cEoJ0GI5tBrQFp7` | `/lp-report-ingest/lead-disposition` |
| `I.LPRD` | 136 Marketing Sub-Source Cost | `7aFZC5BLzvp9QgaK` | `/lp-report-ingest/source-cost` |
| `I.LPRE` | 137 Sales Efficiency by Market | `OyjpSpcDbSf2hC7G` | `/lp-report-ingest/sales-efficiency` |

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

**The IF is positive, and TRUE ends the run.** The condition reads
`{{ $json.success }} equals true`; output 0 (TRUE) goes nowhere and output 1
(FALSE) goes to telemetry, alongside the HTTP node's error output. An earlier
build had these reversed, so every SUCCESSFUL ingest filed a bogus
`transport_error`.

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
