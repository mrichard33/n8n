# Handoff V2: Lightfire weekly partner report — generation, approval, delivery

**Repo:** `mrichard33/n8n` **Base:** `main` **Branch:** `feat/lf-weekly-report-automation`
**Also creates:** one new Railway service (`lf-report-render`), nine SQL executions on LP Supabase.
**Supersedes:** Handoff V1. Where they differ, this document wins.

---

## 0. Decisions already made — do not reopen without explicit approval

These were decided by Mark on 2026-08-18 after external review of both the report and the V1 plan. Each is a settled trade-off, not an open question. **Do not relitigate any of them, and do not "improve" past them mid-build.** If you believe one is wrong, stop and raise it before writing code.

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Keep the existing ReportLab generator. Add visual regression testing. Do NOT rebuild the report in HTML/CSS.** | A generator that provably produces the approved output already exists. Rewriting it is the highest-risk path to "no change whatsoever." Print-CSS page-break control is unreliable; getting exactly four pages with no orphaned content took deliberate tuning that would have to be re-solved in a weaker tool. Visual regression answers the drift concern without a rewrite. |
| **D2** | **The vendor-facing report is deterministic. Fixed and conditional templated language selected by computed state. No LLM-generated narrative in the PDF.** | External review of this exact report found rhetorical overreach — claims stated more absolutely than the tests supported. Encoding those guardrails as prompt instructions is far weaker than encoding them as fixed template text, and weekly generation would reintroduce the risk every week in a document going to an outside party. LLM prose is permitted **only** in the internal approval email, never in the PDF. |
| **D3** | **Do not recreate the LP warehouse in Supabase. `lp_leads` remains the source. Reproducibility comes from frozen weekly snapshots.** | Separate `appointments` / `sales` / `confirmation_events` tables would duplicate a warehouse that already holds everything, plus create a permanent sync problem. Frozen snapshots give reproducibility at a fraction of the cost. |
| **D4** | **Four separate workflows, state-driven through Supabase. Not one long-running paused execution.** | n8n restarts, upgrades and execution pruning can strand or wrongly resume a paused Wait. State in the database is inspectable, restartable, auditable and recoverable independently of any n8n execution. |
| **D5** | **Report versioning with SHA-256 verification. The PDF sent to Lightfire must be byte-identical to the version approved.** | `approved_sha256 == sent_sha256` is asserted immediately before send. Mismatch aborts the send. |
| **D6** | **Support `APPROVED`, `EDIT:` and `DENY:`, with data corrections distinguished from narrative edits.** | A data correction rewrites an override, recalculates every affected metric and renders a new version. A narrative edit re-words against the same frozen metric snapshot. **A PDF is never edited in place.** |
| **D7** | **Unresolved partner actions carry forward week to week.** | The report must not forget what Lightfire committed to. Actions carry status, weeks-open and prior-week result. |
| **D8** | **Week-over-week comparison is a first-class requirement** — deltas inside the existing KPI cards plus one concise comparison in the executive paragraph. | A weekly report that cannot say whether things improved is not worth sending. See §9 for the single approved layout deviation this requires. |
| **D9** | **All dates, reporting windows, scheduling and displayed timestamps use `America/New_York`, with automatic EST/EDT handling.** | Never UTC defaults, never hand-rolled offsets. See §3 — this is load-bearing and has four dedicated test fixtures. |
| **D10** | **The approved 2026-08-17 PDF is the canonical visual reference.** Structure, layout, ordering and style do not change. | Shipped as `REFERENCE_golden_output.pdf`. Labelled: **CANONICAL REPORT TEMPLATE — DO NOT REDESIGN.** |

---

## 1. Objective

Every Monday at 08:00 ET, produce the Lightfire Partner Performance Review for the immediately preceding Sunday–Saturday week, email a draft to internal approvers, and — only on explicit human approval — deliver it to Lightfire. Approval, denial, revision, generation and delivery are all auditable.

Worked example: workflow runs **Monday 24 August 2026**; reporting week is **Sunday 16 August – Saturday 22 August 2026**.

**Nothing reaches Lightfire without a human decision. Silence never approves.**

### Files shipped with this handoff

| File | Role |
|---|---|
| `REFERENCE_golden_output.pdf` | **CANONICAL TEMPLATE — DO NOT REDESIGN.** The approved artifact. |
| `REFERENCE_lightfire_lean.py` | The generator that produced it. **This is the layout specification.** |
| `REFERENCE_lf_confirm_charts.py` | Page-2 ownership chart |
| `REFERENCE_sit_chart.py` | Page-1 sit-vs-goal chart |
| `sql_lf_report_v2_schema.sql` | Nine sequenced DDL executions |
| `lf_report_metrics.sql` | Parameterized metric queries (V1 file, still current) |

---

## 2. Architecture

**n8n = orchestration only.** Scheduling, data acquisition, calling the render service, approval routing, email monitoring, delivery, error notification, status transitions. No business logic, no formatting, no statistics.

**Supabase = system of record.** Run state, frozen snapshots, versions, approvals, actions, audit, configuration.

**GitHub = the application.** Calculations, statistics, narrative state machine, renderer, templates, migrations, tests, workflow exports, docs.

### Repository layout

```
services/lf-report-render/
  main.py                  FastAPI: POST /render, POST /validate, GET /health
  schema.py                pydantic ReportPayload
  calculations.py          derived metrics, no I/O
  statistics.py            two-proportion z, direct standardisation
  narrative.py             computed state -> fixed sentence (D2)
  selectors.py             credit observations, headline observation
  report_builder.py        ported from REFERENCE_lightfire_lean.py (D1)
  charts.py                ported from the two REFERENCE chart scripts
  config.py                loads lf_report_config
  requirements.txt         fastapi uvicorn reportlab matplotlib pillow numpy pypdf
  Dockerfile
  tests/
    fixtures/              21 fixtures, see §20
    golden_payload.json    reproduces REFERENCE_golden_output.pdf exactly
    test_windows.py  test_calculations.py  test_statistics.py
    test_narrative.py  test_golden.py  test_visual_regression.py
    baseline/              approved page PNGs
workflows/
  01-weekly-orchestrator.json
  02-approval-processor.json
  03-report-revision.json
  04-external-delivery.json
  90-manual-controls.json
sql/
  lf_report_v2_schema.sql
scripts/
  test-lf-report.py        aggregate runner for CI
docs/
  REPORT_SPEC.md  RUNBOOK.md  ARCHITECTURE.md
.env.example
```

Railway service root directory: `services/lf-report-render`.

---

## 3. Time, and DST (D9)

**Every** date boundary, schedule and displayed timestamp is `America/New_York`. Never UTC defaults, never `now() - interval '7 days'`, never a hardcoded `-05:00`.

### Rules

1. **n8n workflow timezone** set to `America/New_York` in workflow settings. The Schedule Trigger is Monday 08:00 **local**. Do not express it as a UTC cron — that breaks twice a year.
2. **Window computation in Python** using `zoneinfo.ZoneInfo("America/New_York")`. Compute calendar dates in ET, then derive UTC bounds only if a query needs timestamps.
3. **SQL** converts before comparing: `(l.set_date AT TIME ZONE 'America/New_York')::date`. A bare `::date` shifts Sunday sets into Saturday.
4. **Displayed timestamps** render with the correct abbreviation for that date — `EST` or `EDT`, derived from the zone, never hardcoded.
5. **Period bounds** are `period_start 00:00:00 ET` to `period_end 23:59:59.999999 ET`. On a spring-forward Sunday that day is 23 hours; on fall-back it is 25. Calendar-date arithmetic handles this correctly; elapsed-hours arithmetic does not. **Use calendar dates.**

### Window formulas

```python
def compute_windows(run_date: date) -> Windows:
    # run_date must be a Monday in ET
    period_end        = run_date - timedelta(days=2)   # Saturday
    period_start      = run_date - timedelta(days=8)   # Sunday
    prior_period_end  = period_end   - timedelta(days=7)
    prior_period_start= period_start - timedelta(days=7)
    cohort_set_end    = period_end
    cohort_set_start  = period_end - timedelta(days=40)   # Sunday, 6 weeks back
    cohort_appt_cutoff= run_date - timedelta(days=1)      # Sunday
```

### Required DST fixtures (US DST 2026: begins Sun 8 Mar, ends Sun 1 Nov)

| Run date | Reporting week | Tests |
|---|---|---|
| 2026-03-09 | 2026-03-01 → 03-07 | last full EST week |
| 2026-03-16 | 2026-03-08 → 03-14 | **week contains spring-forward; Sunday is 23h** |
| 2026-11-02 | 2026-10-25 → 10-31 | last full EDT week |
| 2026-11-09 | 2026-11-01 → 11-07 | **week contains fall-back; Sunday is 25h** |

Plus year boundary: run 2027-01-04 → week 2026-12-27 → 2027-01-02, spanning the year change. `iso_year`/`iso_week` must be derived from `period_end`, not `run_date`, or the January runs collide.

### Reference assertion — run this first

`compute_windows(date(2026,8,17))` must return `period 08-09→08-15`, `cohort_set 07-06→08-15`, `appt_cutoff 08-16`. **If it does not, stop and fix the date math before writing anything else.**

---

## 4. Metric classification

Every metric declares its type. Never infer from prose.

| Type | Window | Metrics |
|---|---|---|
| `WEEKLY` | `period_start`→`period_end` | appointments set per agent, active agents, staffing movement, set-count WoW deltas |
| `MATURITY_BASED` | set in `cohort_set_start`→`cohort_set_end` **AND** appointment date ≤ `cohort_appt_cutoff` | Issued Sit %, Matured Sit %, sits short, sold, gross, confirmation ownership, stranded, all statistical tests, the ranking |
| `ROLLING` | trailing 6 weeks, deliberate | source-matched sit comparison |
| `REFERENCE` | prior frozen snapshots | week-over-week deltas, action carry-forward, trend statements |

**Why this matters more than anything else in the build:** an appointment set last Saturday may be scheduled three weeks out. Computing sit % on the reporting week measures appointments that have not happened yet, and the number swings wildly for no real reason. This exact confound already produced a false vendor finding that maturity-matched testing reversed at p = 0.986. Implement the classification as an enum on each metric definition and assert it in tests.

The report carries a visible reporting-period label so Lightfire always knows what is being assessed. The existing sub-title line and per-section `DATA PERIOD` stamps already do this — keep them and populate from the payload.

---

## 5. Supabase schema

`sql_lf_report_v2_schema.sql`, nine separate executions in order. Additive only. Execution 9 is `CREATE INDEX CONCURRENTLY` — each statement its own execution, cannot run in a transaction.

Tables: `lf_partners`, `lf_report_config`, `lf_report_approvers`, `lf_vendor_recipients`, `lf_setter_roster`, `lf_report_runs`, `lf_report_versions`, `lf_weekly_team_metrics`, `lf_weekly_agent_metrics`, `lf_report_metrics`, `lf_partner_actions`, `lf_approval_requests`, `lf_approval_events`, `lf_delivery_events`, `lf_metric_overrides`, `lf_audit_events`, `lf_automation_errors`.

**Idempotency:** unique on `(partner_id, period_start, period_end)`. Re-running Monday finds the row; it does not create a second.

**Roster is data (D3-adjacent).** Team assignment and exclusions live in `lf_setter_roster`. Never hardcode a name list — a new hire would silently vanish and nobody would notice. This already happened once: John Manieri, fourth by gross, was omitted from a draft because the list was hardcoded.

---

## 6. Calculation engine

Pure functions, no I/O, fully unit-tested.

```
Issued Sit %   = sat / (gross_issued − cancels_in_issued)      # net_issued
Matured Sit %  = sat / matured
target_sits    = net_issued × issued_sit_goal                  # 0.80
sits_short     = max(0, target_sits − sat)
gross_per_appt = gross_cents / matured
small_denom    = net_issued < small_denominator_min            # 20
```

**Rounding:** never round before presentation. Percentages display to 1 decimal; sits-short to 1 decimal; totals may display whole where the reference does. Compute in full precision, round in the renderer only.

**Null safety:** `net_issued = 0` → `issued_sit_pct = None`, rendered as `—`, never `0.0%` and never NaN. The pre-send gate rejects any NaN or null in a displayed cell.

**Financial opportunity (always framed as potential):**
```
incremental_sits  = max(0, target_sits_team − sat_team)
close_rate        = sold_team / sat_team              # observed, this cohort
avg_ticket        = gross_cents_team / sold_team      # observed
potential_gross   = incremental_sits × close_rate × avg_ticket
```
Rendered wording must always contain *approximately*, *potential*, and the qualifier *"An estimate, not revenue we can claim would certainly have occurred."*

---

## 7. Statistical engine

Code only. No LLM ever computes or interprets a test.

```python
def two_prop_z(x1, n1, x2, n2):
    p1, p2 = x1/n1, x2/n2
    p  = (x1+x2)/(n1+n2)
    se = math.sqrt(p*(1-p)*(1/n1 + 1/n2))
    z  = (p1-p2)/se if se else 0.0
    return z, math.erfc(abs(z)/math.sqrt(2))   # two-sided
```

Persist every test to `lf_report_metrics.stat_tests`: `s1_n, s1_x, s2_n, s2_x, z, p, alpha, verdict`.

### Required tests

1. **No-confirmer rate by team** — reference: 171/446 vs 73/678, p < 0.0001
2. **Strand rate given no confirmer** — reference: 76/171 vs 25/73, p = 0.14
3. **Source mix explanation** — direct standardisation: apply Reece per-source sit rates to Lightfire's source mix, compare expected vs actual, pooled z. Reference: expected 60.5%, actual 34.7%, z = 8.1

### Source-mix state machine

| State | Condition |
|---|---|
| `INSUFFICIENT_SAMPLE` | fewer than 3 shared sources with ≥10 each side |
| `SOURCE_MIX_NOT_EXPLANATORY` | standardised expected − actual ≥ 80% of the raw gap |
| `SOURCE_MIX_PARTIALLY_EXPLANATORY` | 30–80% |
| `SOURCE_MIX_EXPLANATORY` | < 30% |

Narrative is selected from the state. **Never assert the strong conclusion unless the state supports it.**

### The wording rule (non-negotiable)

`p >= alpha` renders **"we find no statistically distinguishable difference"** or **"the data cannot distinguish the rates at this sample size."** It **never** renders "the two teams are the same." Verdict cells for a null read `p = 0.14 — not distinguishable`.

The verdict sentence is selected from the computed p every week. **A hardcoded verdict must never outlive the number it describes.** Assert this in tests: feed a payload where p crosses 0.05 and confirm the sentence flips.

---

## 8. Deterministic narrative (D2)

Two stages. Stage 1: code computes states. Stage 2: a **lookup table** maps state → fixed sentence. No model call.

### States

```
SIT_TREND:      IMPROVED_MATERIAL | IMPROVED_SLIGHT | FLAT | DECLINED_SLIGHT
                | DECLINED_MATERIAL | NO_PRIOR
                (material |Δ| >= 3.0 pts; slight 1.0–3.0; flat < 1.0)
GOAL_STATUS:    AT_OR_ABOVE | WITHIN_5 | BELOW_5_TO_15 | BELOW_15_PLUS
STAT_VERDICT:   SIGNIFICANT | NOT_DISTINGUISHABLE
SOURCE_MIX:     (four states, §7)
STAFFING_TREND: GREW | STABLE | SHRANK_MODERATE | SHRANK_SEVERE  (>= 33% drop)
CONFIRMER_GAP:  WIDE (>= 20 pts) | MODERATE (10–20) | NARROW (3–10) | PARITY (< 3)
ACTIONS:        NONE_OPEN | SOME_OPEN | ALL_RESOLVED | ESCALATED
```

### Sentence bank

Store in `narrative.py` as a dict keyed by state, values matching the reference wording exactly. Example for `SIT_TREND`:

```python
SIT_TREND = {
 "IMPROVED_MATERIAL":  "up {delta:.1f} points from {prior:.1f}% last week",
 "IMPROVED_SLIGHT":    "up {delta:.1f} points from {prior:.1f}%",
 "FLAT":               "effectively unchanged from {prior:.1f}% last week",
 "DECLINED_SLIGHT":    "down {delta:.1f} points from {prior:.1f}%",
 "DECLINED_MATERIAL":  "down {delta:.1f} points from {prior:.1f}% last week",
 "NO_PRIOR":           "",   # first run: omit the clause entirely
}
```

**Every sentence that does not contain a number is copied verbatim from `REFERENCE_lightfire_lean.py` and is not regenerated.** Only numeric substitution and state selection are dynamic. Roughly 30 numbers are embedded inside prose in the reference — find all of them; a stale hardcoded figure inside a sentence is the most likely defect in this build and the least likely to be noticed.

### Credit selector (§7 of the reference, "Credit first, because it is earned")

Rule-based, each candidate backed by a computed metric. Evaluate in priority order, take up to 3:

| Priority | Candidate | Qualifying condition |
|---|---|---|
| 1 | `TOP_VOLUME` | LF agent has highest `matured` across **both** teams |
| 2 | `ABOVE_GOAL` | LF agent with `net_issued >= 20` and `issued_sit_pct >= 80` |
| 3 | `MOST_IMPROVED_SETS` | LF agent `sets_period − sets_prior_period >= 5` |
| 4 | `TEAM_SIT_IMPROVED` | LF `issued_sit_pct` up ≥ 2.0 pts WoW |
| 5 | `CONFIRMED_HOLD_UP` | LF confirmed-appointment issue % within 10 pts of Reece |
| 6 | `CONCENTRATION_EFFORT` | staffed-agent output rose while active agents fell |
| 7 | `GROSS_CONTRIBUTION` | LF agent inside top 6 of the combined ranking |

Rules: no generic praise, no fabricated qualitative claims, no forced praise. Fewer than three qualifiers → fewer bullets. **Zero qualifiers → render one neutral factual line (highest-volume agent, stated without praise framing) and flag it in the internal approval email so a human notices.** The section is part of the frozen structure and is never omitted.

### Headline observation ("The line worth sitting with")

Eligible: `net_issued >= 20`. Score = `sits_short` (dollar consequence and volume are both already embedded in it). Pick the maximum. **This deliberately does not select the most negative statistic** — a 36% agent on 11 appointments loses fewer sits than a 62% agent on 97.

The sentence must state: rank vs volume, sits short, and whether that agent's own no-confirmer rate matches the population cause or differs from it. If their no-confirmer rate is **below** their team average, the template says the gap *"appears to need a different diagnosis from the broader confirmation-coverage problem."* If **at or above**, it says the agent *"is part of the broader confirmation-coverage pattern."* State-selected, both fixed strings.

### Accountability boxes

"Where Reece needs to act" contains only findings originating in Reece-controlled process. "Where Lightfire needs to act" only Lightfire-controlled. **No blame language. No statements about effort, intent, competence or motivation** — an earlier draft said a gap was "unlikely to be effort," which is an inference about a person and was removed in review. Do not reintroduce that class of statement.

---

## 9. Week-over-week rendering (D8)

### KPI card deltas — the one approved layout deviation

The five KPI cards currently render two rows (value, two-line label) via `kpis()`. Deltas require a third small line inside each card:

```
65.8%
Your sit % against
our 80% goal
▲ 2.1 pts vs prior week
```

**This necessarily increases the KPI band height by roughly 9pt.** You cannot add information without changing pixels. This is the **single approved deviation** from the canonical layout (D10), authorised by Mark on 2026-08-18. Consequences:

- Implement as a third row in `kpis()`, style `kpil` at 6.8pt, colour green for favourable / red for unfavourable / slate for flat. Direction is per-KPI: rising sit % is favourable, rising no-confirmer % is not.
- On the first ever run there is no prior — render the third line as an empty string, not "n/a", so the band height stays constant across weeks.
- **Re-bless the visual regression baseline once** when this lands, and record that re-blessing in `docs/REPORT_SPEC.md` with the date and reason. Every subsequent diff is measured against the new baseline.
- Page 1 must still fit. Absorb the ~9pt from the existing page-1 slack; if it overflows, the correct lever is the agent-table row filter (§11), never font size.

### Executive paragraph comparison

One clause inserted into the existing opening sentence, state-selected from `SIT_TREND`:

> "Your book runs **65.8%** *(up 2.1 points from 63.7% last week)*, ours 78.9%; neither of us is where we want to be."

`NO_PRIOR` omits the parenthetical entirely. No other sentence in the paragraph changes.

### Trend source

Read from the **most recent frozen snapshot** of a run whose status is `APPROVED` or `SENT` — never recomputed from live `lp_leads` (D3). A denied or expired week is skipped; the comparison reaches back to the last approved week and the sentence says "last week" only if that snapshot is exactly 7 days prior, otherwise it names the week.

---

## 10. Partner actions carry-forward (D7)

`lf_partner_actions` seeded with the seven actions from the approved report (see DDL execution 6).

Each Monday, before rendering:

1. Increment `weeks_open` for every `OPEN` / `IN_PROGRESS` action.
2. For actions with `auto_metric_key`, evaluate against this week's metrics. Met → `DONE`, set `resolved_run_id`, `resolved_at`. Example: `restore_bench` has `auto_metric_key='lf_active_agents'`, target 8.
3. Past `due_date` and still open → `ESCALATED`.
4. Previously `DONE` but the metric regressed below target → `RECURRED`, and `weeks_open` resumes counting.

Rendering in section 5: `DONE` and `REMOVED` actions drop off. `OPEN`, `IN_PROGRESS`, `ESCALATED` and `RECURRED` render in `tier` then `sort_order` order. For any action with `weeks_open >= 1`, append to the "Done means" cell:

> `Open 2 weeks — last week: 6 active`

`ESCALATED` renders the `#` cell in red. **New actions are created from configuration or by a human, never invented by the system** — no spontaneous contractual demands.

---

## 11. Render service and visual regression (D1)

### API

```
POST /render    body ReportPayload -> 200 application/pdf | 422 validation | 500 pagination
POST /validate  body ReportPayload -> 200 {ok, warnings[]} — gate checks without rendering
GET  /health
Auth: X-Render-Token vs RENDER_TOKEN env.
```

### Porting rules

- **Keep verbatim** from `REFERENCE_lightfire_lean.py`: every entry in the `S` style dict, the `table()` / `kpis()` / `callout()` / `chart()` / `PERIOD()` helpers, `furn()` page furniture, all column widths, page breaks, section order and numbering, confidentiality marking, and all non-numeric prose.
- **Replace only** hardcoded data: KPI values, page-1 agent rows, page-2 confirmation table, page-3 `RANK` list, retention table, staffing sentence numbers, and every number embedded in prose.
- The only structural change permitted is the KPI third row (§9).

### Pagination guard

After build, if `page_count != expected_page_count` (4), return **HTTP 500** `{"error":"pagination","pages":N}`. The orchestrator marks the run `GENERATION_FAILED` and alerts. **Never email a malformed report.**

If a week legitimately has more agents than fit, the correct lever in order: drop agents with `matured < min_matured_for_table`, then `net_issued < 3`, and note the cut in the page-1 footnote. **Never shrink fonts or leading** — that is how the canonical look drifts.

### Visual regression

`tests/baseline/` holds approved page PNGs at 150 dpi. On any template change: render `golden_payload.json`, rasterise with `pdftoppm`, compare per page against baseline. Fail if differing pixel fraction exceeds `visual_diff_tolerance` (0.005). Baseline re-blessing requires an explicit commit that touches `docs/REPORT_SPEC.md` stating the reason — CI fails a baseline change without it.

---

## 12. Versioning and delivery integrity (D5)

- v1 renders at `READY_FOR_REVIEW`. Any revision creates **v2, v3 …**; a version that has entered review is **never overwritten**.
- Each version stores `payload` (frozen), `payload_sha256`, `pdf_storage_path`, `pdf_sha256`, `page_count`, `revision_reason`, `revision_kind`.
- Approval sets `lf_report_runs.approved_version_id`.
- Workflow 04 accepts **only** a `version_id` whose run is `APPROVED`, re-downloads that PDF from storage, recomputes SHA-256, and asserts `== approved_sha256`. Mismatch → abort, log `FAILED`, alert. Never send a recomputed or re-rendered PDF.
- `lf_delivery_events` records both hashes and `hash_verified`.

---

## 13. The four workflows (D4)

State lives in Supabase. No workflow depends on another's execution staying alive.

### 01 — Weekly Orchestrator (Schedule, Mon 08:00 ET)

1. Schedule Trigger, workflow timezone `America/New_York`.
2. Compute windows (§3). Assert `run_date` is a Monday.
3. Kill switch: `LF_REPORT_ENABLED` false → log and exit.
4. Idempotency: select on `(partner_id, period_start, period_end)`.
   - `SENT` / `APPROVED` → exit, log. Never regenerate an approved week.
   - `READY_FOR_REVIEW` → exit (awaiting a human).
   - `BLOCKED` / `GENERATION_FAILED` / absent → proceed, reusing or inserting the row.
   - `manual_regeneration = true` bypasses this gate.
5. `status='INGESTING'`. Run Q2–Q8 from `lf_report_metrics.sql`. **If Lightfire `matured = 0`, go straight to `BLOCKED`** — that means the cohort or roster join is broken, and an empty report must never reach a vendor.
6. Apply any `lf_metric_overrides` for this run where `applied = false`, then mark them applied.
7. Roll actions forward (§10).
8. `status='VALIDATING'`. Run the §15 gates. Any hard failure → `BLOCKED`, write `validation_report`, email internal error notice, **exit without requesting approval**.
9. Compute derived metrics, statistics, narrative states, credit and headline selections.
10. Freeze snapshots: `lf_weekly_team_metrics`, `lf_weekly_agent_metrics`, `lf_report_metrics`. Compute `source_snapshot_hash`.
11. `POST /render`. Non-200 → `GENERATION_FAILED`, alert, exit.
12. Upload PDF to Supabase Storage `lf-reports/{period_start}/v{n}/...`. Insert `lf_report_versions`. Set `current_version_id`, `status='READY_FOR_REVIEW'`.
13. Insert `lf_approval_requests` with `approval_token` `LR-{iso_year}-W{iso_week}-V{n}`. Send the approval email (§14). Audit `APPROVAL_REQUESTED`.

### 02 — Approval Processor (Gmail Trigger + Webhook)

Two entry points, one code path.

- **Gmail Trigger** every 5 min on replies matching the thread.
- **Webhook** `/lf-decision/{token}/{approve|edit|deny}` for the email buttons.

Steps: resolve token → load run and version → verify status is `READY_FOR_REVIEW` → verify sender is an active `lf_report_approvers` row → parse (§14) → write `lf_approval_events` → transition:

| Classification | Transition |
|---|---|
| `APPROVED` | `status='APPROVED'`, `approved_version_id = current_version_id`, resolve request, **trigger Workflow 04** |
| `DENY` | `status='DENIED'`, store reason, audit, notify internally. **Nothing to Lightfire, ever, for this run.** |
| `EDIT` | `status='REVISION_REQUESTED'`, store raw request, classify kind, **trigger Workflow 03** |
| `UNKNOWN` | no state change; send clarification email; stay `READY_FOR_REVIEW` |
| `UNAUTHORIZED` | log, notify Mark, no state change |

Idempotency: a second `APPROVED` on an already-`APPROVED` run logs a duplicate event and does nothing.

Reminders: separate schedule at `[24, 48]` hours on `READY_FOR_REVIEW` runs. **After the last reminder the run stays pending. It never auto-approves and it never expires into a send.**

### 03 — Report Revision (triggered)

1. Load run, current version, raw edit request.
2. Classify `revision_kind` (§14). **`DATA_CORRECTION` → write `lf_metric_overrides` rows, re-run steps 5–12 of Workflow 01 in full** (recalculate everything affected, including statistics and narrative states). **`NARRATIVE_EDIT` → reuse the frozen metric snapshot unchanged**, re-render with the narrative adjustment.
3. Insert as `version_no = max + 1`, with `revision_reason` and `revision_kind`.
4. `status='READY_FOR_REVIEW'`, new `approval_token` ending `-V{n}`, send for approval again.

**A revision is never sent without a second approval.** A PDF is never edited in place.

### 04 — External Delivery (triggered only)

1. Accept `version_id` only.
2. Reload run. **Assert `status='APPROVED'` and `approved_version_id = version_id`.** Anything else → abort and alert.
3. Assert `sent_at IS NULL`. Already sent → exit (idempotent).
4. Download the PDF, recompute SHA-256, assert `== approved_sha256` (D5). Mismatch → abort, alert.
5. `status='SENDING'`. Send to active `lf_vendor_recipients`.
   - Subject: `Lightfire Partner Performance Review — {period_start:%-d %b} – {period_end:%-d %b %Y}`
   - Filename: `Lightfire_Partner_Performance_Review_{period_start}_to_{period_end}.pdf`
6. Insert `lf_delivery_events` with both hashes. `status='SENT'`, `sent_at=now()`. Audit `SENT`. Confirmation copy to approvers.

### 90 — Manual Controls

Regenerate current week; regenerate a specific historical week (`manual_regeneration=true`); resend the approval request; cancel a pending run; preview without emailing; mark an action resolved; re-apply overrides. **External resend requires an explicit confirmation parameter** and re-verifies the hash.

---

## 14. Approval: email, parsing, security (D6)

### Approval email

```
Subject: ACTION REQUIRED — Lightfire Weekly Performance Review — {Sun d Mon} – {Sat d Mon} — [LR-2026-W34-V1]
```

Body, in order: reporting period; version and generation timestamp in ET with the correct EST/EDT abbreviation; validation status; the five headline numbers with WoW deltas; open action carry-forward summary; any credit-selector warning; PDF attached. Then:

```
Reply with one of:
  APPROVED
  EDIT: <what to change>
  DENY: <reason>

Or click:  [ APPROVE ]   [ REQUEST EDIT ]   [ DENY ]
```

LLM prose is permitted **in this email only** (D2) — it never reaches the PDF.

### Reply parsing — implement exactly this order

```
1. Strip quoted history: drop from the first line matching
   /^\s*(On .+ wrote:|-----Original Message-----|_{5,}|From:\s)/m
   and drop every line beginning with '>'.
2. Strip signature: drop from the first line matching /^--\s*$/.
3. Normalise whitespace, lowercase, trim. Take the first 300 chars.
4. The command MUST appear at the START of the remaining reply text.
5. TEST DENY FIRST, ALWAYS:
     /^(deny|denied|reject|hold|do not send|don'?t send)\b/
     OR /^not\s+approved?\b/
   -> DENY, reason = remainder after the keyword.
6. THEN EDIT:
     /^edit\s*:/  ->  EDIT, instruction = remainder.
7. THEN APPROVE:
     /^(approved?|approve it|ok to send|send it)\b/  ->  APPROVED.
8. Anything else -> UNKNOWN. Do NOT guess. Send clarification, stay pending.
```

**The trap:** *"not approved"* contains *"approved"*. Any implementation that tests approve before deny, or uses a bare `includes('approved')`, sends an unapproved report to a vendor. **Steps 5 and 6 before step 7 is mandatory.** Both cases are required fixtures.

Requiring the command at the **start** of the cleaned text is what defeats a quoted older "APPROVED" further down the thread.

### Revision-kind classification

`DATA_CORRECTION` if the instruction contains a numeric assertion about a metric or a correction verb applied to a figure — e.g. *"Craig had 47 appointments, not 49"*, *"his cancels should be 3"*. Regex on digit-bearing correction phrasing, plus a keyword set (`should be`, `not`, `actually`, `wrong`, `incorrect`, `correct to`).

`NARRATIVE_EDIT` otherwise — e.g. *"make the Craig section less strong"*, *"mention he was out Wednesday."*

**Ambiguous → treat as `NARRATIVE_EDIT` and say so in the reply to the approver**, so a human can escalate to a data correction if that was meant. Never guess a number.

### Security

- Sender must match an active `lf_report_approvers` row. Any single active approver may decide.
- Token must resolve to a run currently `READY_FOR_REVIEW`. Subject text alone never approves.
- One-time: a resolved `lf_approval_requests` row rejects further decisions.
- Where the provider API exposes authenticated mailbox metadata, validate it — do not rely on the `From` header alone. Email is not a cryptographic channel; the compensating controls are the allow-list, the token, one-time state and the audit log.

---

## 15. Pre-send validation gates

Run before the approval email. **Hard failures set `BLOCKED` and produce no approval request.**

**Hard:**
1. `period_start` is Sunday, `period_end` is Saturday, span exactly 7 days.
2. Lightfire `matured > 0` and Reece `matured > 0`.
3. Every distinct `set_by_name` in the cohort resolves in `lf_setter_roster` — an unmapped name is a hard failure, not a silent exclusion.
4. `net_issued = gross_issued − cancels_in_issued` for every row.
5. Agent rows sum to team totals: `matured`, `sat`, `sold`, `gross_cents`.
6. Confirmation categories sum to `matured` per team.
7. Every displayed percentage recomputes from its stored numerator and denominator.
8. No NaN, no null, no negative in any displayed cell.
9. Statistical inputs valid: all `n > 0`, `x <= n`.
10. `page_count == 4`.
11. Visual diff within tolerance.

**Soft (warn in the approval email, do not block):**
12. Any team's `matured` moved more than 40% WoW.
13. Fewer than 3 credit observations qualified.
14. `retention` or `staffing` payload absent (§19).
15. Any agent's `issued_sit_pct` moved more than 25 pts WoW.

---

## 16. Audit log

Every transition writes `lf_audit_events`: `REPORT_CREATED`, `SOURCE_SNAPSHOT_TAKEN`, `VALIDATION_PASSED`, `VALIDATION_FAILED`, `PDF_RENDERED`, `APPROVAL_REQUESTED`, `REMINDER_SENT`, `EDIT_REQUESTED`, `VERSION_GENERATED`, `APPROVED`, `DENIED`, `SENT`, `FAILED`, `MANUAL_OVERRIDE` — with `actor`, `run_id`, `version_id`, `metadata` jsonb. Any run's full history must be reconstructable from this table alone.

---

## 17. Configuration and secrets

All of the following live in `lf_report_config` or env, never in code: partner name, approvers, vendor recipients, timezone, run time, sit goal, small-sample threshold, cohort length, alpha, delta thresholds, reminder schedule, expected page count, visual tolerance, report naming.

Env (`.env.example`, no real values committed):
```
RENDER_TOKEN            shared secret, n8n -> render service
SUPABASE_URL / SUPABASE_SERVICE_KEY
LF_REPORT_ENABLED       default false — master kill switch
GMAIL_OAUTH_*           n8n credential reference only
LLM_API_KEY             internal approval email prose only
```
No `.env` committed. No addresses or secrets in source.

---

## 18. Retention formula — verify, do not infer

```
net_retained  = gross_written − cancellations − financing_denied
retention_pct = net_retained / gross_written
```

Reference week 2026-08-02→08-08: Lightfire $331,042 − $95,698 − $34,826 = $200,518 = 60.6%. Reece $537,496 − $49,093 − $0 = $488,403 = 90.9%. Both reconcile.

**Confirm this matches LP Report 137's own definition before shipping** — do not infer it solely from the rendered report. Working/Hold business is *retained* in the source (only permanently lost business deducts); if the source disagrees, the source wins and this handoff is wrong.

Single large outliers must be identifiable so the report can distinguish an outlier from a pattern. The reference correctly reports that one $95,698 cancellation is 29% of Lightfire's gross for the week and explicitly states it is not a pattern. Implement `outlier_flag` where a single contract exceeds 20% of team gross written, and keep that sentence state-selected.

---

## 19. Two verified data gaps

Both confirmed on 2026-08-18. **The renderer omits these cleanly when the payload key is `None`, and the report must still be exactly 4 pages.**

### Retention table (page 4)

`lp_sales_efficiency_setter_history` **exists but has 0 rows**. Until an ingestion exists, `retention: None`. Phase 2 ticket: ingest LP Report 137. The parser pattern exists in `lp_source_cost_history` + `scorecard_report_snapshots` — **and any query there MUST filter `is_current = true`**, because snapshots are re-ingested 2–3× per period and raw sums double- and triple-count. That defect already produced a wrong cost figure once.

### Five9 staffing detail (page 4 prose)

Not mirrored to Supabase. Two Five9 constraints that will bite: the Call Log has a **hard 5,000-row cap** so a day must be pulled in 4–6h windows, and agents who never log out produce impossible login durations (one was exactly 24:00:00 — cap login at the scheduled shift before any arithmetic).

**Phase 1:** derive the honest weaker version from `lp_leads` alone — distinct Lightfire setters with ≥1 set in the period vs the prior period. Define `active_agent` explicitly as **"a setter with ≥1 appointment set during the reporting week"** and state that definition in the Method block so the report cannot claim one definition while the code runs another. Phase 2 adds true dialler-day counts.

---

## 20. Test fixtures

Build all of these under `tests/fixtures/`:

**Data shape:** normal week · zero appointments · single Lightfire setter · all agents small-denominator · no sales · 100% sit rate · zero confirmations · all confirmations · large cancellation outlier · financing-denied outlier · duplicate appointment · missing source feed · unmapped setter name · name variation (`Deer - LF, Craig` vs `Deer, Craig`).

**Time:** the four DST runs from §3 · year boundary (run 2027-01-04) · month boundary.

**Workflow:** report already sent · duplicate approval reply · unauthorized approver · quoted email containing an old `APPROVED` · `"Not approved — hold this"` · `EDIT:` data correction · `EDIT:` narrative edit · `"looks good"` (must classify UNKNOWN) · edit arriving after approval (must reject) · first-ever run with no prior snapshot.

**Golden:** `golden_payload.json` reproducing `REFERENCE_golden_output.pdf` exactly.

---

## 21. CI (GitHub Actions, every PR)

lint + typecheck · unit tests · calculation tests · statistical tests · date-window tests including all four DST fixtures · narrative state-machine tests · template render · golden fixture comparison · PDF generation · visual regression · reply-parser table tests.

**Template changes require an explicit baseline re-bless commit touching `docs/REPORT_SPEC.md`.** CI fails a `tests/baseline/` change without it. No auto-deploy of a changed template from `main` without a passing visual regression.

---

## 22. Acceptance — all must pass before reporting this working

1. `compute_windows(date(2026,8,17))` → period 08-09→08-15, cohort_set 07-06→08-15, cutoff 08-16.
2. All four DST fixtures produce Sunday→Saturday spans of exactly 7 calendar days.
3. Q2 on the reference windows returns Lightfire `matured=446, net_issued=237, sat=157`; Reece `matured=678, net_issued=563, sat=444`. Deviation means the timezone conversion or roster join is wrong — fix before proceeding.
4. Golden render: 4 pages; extracted text contains `65.8%`, `78.9%`, `38.3%`, `10.8%`, `p = 0.14 — not distinguishable`, `Craig Deer`, `$206,000`; visual diff within tolerance.
5. Statistical wording flips: a payload with p < 0.05 on test 2 renders the significant sentence, not the null one.
6. Reply parser: `"Approved"`→APPROVED · `"Not approved — hold this"`→**DENY** · `"deny, Deer numbers look off"`→DENY+reason · `"EDIT: Craig had 47 not 49"`→EDIT/DATA_CORRECTION · `"EDIT: soften the Craig paragraph"`→EDIT/NARRATIVE_EDIT · `"looks good"`→UNKNOWN · `"Approved"` above a quoted thread containing `deny`→APPROVED · reply from an unlisted address→UNAUTHORIZED.
7. Idempotency: run Workflow 01 twice for one week → one `lf_report_runs` row, one version, one approval email.
8. Deny path: deny → `status='DENIED'`, reason stored, **zero** email to any Lightfire address.
9. Data-correction path: `EDIT:` with a number → override row written, metrics recalculated, v2 rendered, second approval requested, v1 retained.
10. Hash integrity: corrupt the stored PDF after approval → Workflow 04 aborts on hash mismatch and sends nothing.
11. Carry-forward: an unresolved action from the prior run renders with `Open N weeks — last week: <value>`.
12. First-ever run: no prior snapshot → KPI third lines empty, exec paragraph omits the comparison clause, band height unchanged.

---

## 23. Deliverable

Branch `feat/lf-weekly-report-automation` off `main`, PR to `main`, **HOLD merge pending Mark's review.** Ship with `LF_REPORT_ENABLED=false`; Mark enables after one manual execution that stops cleanly at the approval email.

```
feat(lf-report): weekly Lightfire partner report — generation, approval, delivery

WHAT
- services/lf-report-render/: FastAPI service rendering the frozen 4-page
  partner report from a metrics payload. Ported from the approved manual
  generator; data-driven only, layout unchanged.
- workflows/: four state-driven n8n workflows — 01 orchestrator (Mon 08:00
  ET), 02 approval processor, 03 revision, 04 external delivery.
- sql/lf_report_v2_schema.sql: 17 tables covering run state, frozen weekly
  snapshots, versions, partner actions, approvals, deliveries, overrides and
  audit. Nine separate executions, additive.
- scripts/test-lf-report.py + tests/: date-window incl. four DST fixtures,
  calculations, statistics, narrative state machine, reply parser, golden
  render, visual regression.

WHY
- The report is produced by hand every Monday. Manual production is why the
  2026-08-17 edition needed four rounds of correction before it was sendable:
  a missing setter (Manieri, 4th by gross) dropped by a hardcoded name list,
  a phantom profile carrying real credit (Rubertone), and two statistical
  claims stated more absolutely than the tests supported.
- Outcome metrics must run on a 6-week matured cohort, not the reporting
  week. Measuring sit % on the reporting week counts appointments that have
  not happened yet; that confound previously produced a false vendor finding
  which maturity-matched testing reversed at p = 0.986.

HOW
- Two windows per run: WEEKLY (prior Sun-Sat, ET) for sets and staffing;
  MATURITY_BASED (6 weeks of sets, appointment date <= run_date-1) for sit %,
  ranking, gross and confirmation analysis. Every metric declares its type.
- All date math, scheduling and displayed timestamps use America/New_York
  with automatic EST/EDT handling. Four DST fixtures are required tests.
- Vendor-facing prose is deterministic: computed state selects a fixed
  sentence. No LLM output reaches the PDF. Null statistical results render
  "no statistically distinguishable difference", never "the same", and the
  verdict is selected from the computed p every week.
- Team assignment and exclusions live in lf_setter_roster, not code, so a
  new hire or departure never silently drops out of the report.
- Reply parsing tests DENY and EDIT before APPROVE and requires the command
  at the start of the cleaned reply. "Not approved" contains "approved"; the
  naive check sends an unapproved report to a vendor.
- Delivery accepts only an APPROVED version_id and asserts
  approved_sha256 == sent_sha256 before sending.
- Render returns 500 on any page count other than 4, so a layout regression
  fails the run instead of emailing a malformed report.

USER-VISIBLE IMPACT
- Mark and Brad receive an approval email each Monday: PDF attached, headline
  numbers with week-over-week deltas, open action carry-forward.
- Lightfire receives the report only after an explicit APPROVED reply or
  approve-link click from an allow-listed address. Silence never approves;
  the run stays pending after two reminders.
- The one approved layout change is a third line in each KPI card carrying
  the week-over-week delta. Baseline re-blessed once, recorded in
  docs/REPORT_SPEC.md.

ENV VARS (documented in .env.example)
- RENDER_TOKEN — shared secret, n8n to render service
- SUPABASE_URL / SUPABASE_SERVICE_KEY
- LF_REPORT_ENABLED (default false) — master kill switch
- GMAIL_OAUTH_* — n8n credential reference
- LLM_API_KEY — internal approval email prose only
```
