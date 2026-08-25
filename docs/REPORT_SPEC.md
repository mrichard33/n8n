# Lightfire Partner Performance Review — report specification

**CANONICAL REPORT TEMPLATE — DO NOT REDESIGN (D10).** The approved
2026-08-17 edition (`REFERENCE_golden_output.pdf` in the handoff bundle) is
the visual reference. Structure, layout, ordering and style do not change.
`services/lf-report-render/report_builder.py` ports the approved generator
verbatim; only data is dynamic.

## Baseline re-bless log

A `tests/baseline/` change is valid only with a same-PR entry here (CI
enforces it).

| Date | Reason |
|---|---|
| 2026-08-18 | Initial bless, from the first golden render. Pixel-identity with the hand-issued 8/17 PDF is impossible because of the §9 KPI third row (the single approved layout deviation, authorised by Mark 2026-08-18); §9 pre-authorises exactly this one re-bless. |

## The one approved layout deviation

Each KPI card carries a third small line with the week-over-week delta
(`kpid` style, 6.8 pt; green favourable / red unfavourable / slate flat;
direction is per-KPI — rising sit % is favourable, rising no-confirmer % is
not). On a first run the line renders as an **empty string**, not "n/a", so
the band height stays constant across weeks.

## Deviations from the handoff, with reasons

1. **`min_matured_for_table` = 1, not 3** (Mark, 2026-08-18). At 3, agents
   with 1–2 matured appointments dropped from page 1 and the summed total
   became a third, undisclosed number (e.g. 156/236 = 66.1%). At 1 the
   display sum equals the cohort total by construction. `small_denominator`
   (net_issued < 20) remains a styling flag and never excludes a row. The
   page-3 footnote's "below N matured" exclusion clause renders only when the
   configured threshold exceeds 1 — the report states the definition the code
   runs.
2. **One team total, derived from the displayed rows** (Mark, 2026-08-18).
   `calculations.team_display_total()` is the only producer; the page-1 total
   row, the KPI card, "vs goal", team sits-short, the financial opportunity
   and the executive paragraph all read it. No cohort-level sit % exists in
   the payload or the code. Full-cohort aggregates serve only the
   confirmation analysis and statistical tests.
3. **Cohort starts on a Monday.** `period_end − 40` (41 days inclusive). The
   handoff §3 comment says "Sunday"; the formula, the §3 reference assertion
   (2026-07-06), and the canonical PDF's own subtitle ("set 6 July – 15
   August") all say Monday. The formula is authoritative.
4. **Module renames**: `selectors.py` → `report_selectors.py` and
   `statistics.py` → `stats_engine.py`. The handoff's names shadow Python
   stdlib modules; `selectors` is imported by `subprocess`/`asyncio`, so
   uvicorn cannot even boot with that filename present.
5. **SIT_TREND slight variants carry "last week."** The handoff's §8 example
   bank omitted the suffix on IMPROVED_SLIGHT/DECLINED_SLIGHT, but its §9
   canonical example renders a 2.1-pt (slight) move as "(up 2.1 points from
   63.7% last week)". §9 is the requirement (D8).
6. **Q8 rewritten** (`sql/lf_report_queries.sql`): the shipped V1 query
   referenced columns that do not exist in the V2 schema.
7. **No LLM anywhere in v1.** D2 permits LLM prose in the internal approval
   email only; the v1 approval email is deterministic (built from the same
   computed states), so `LLM_API_KEY` is unused and one failure mode is gone.
8. **Reply parsing and revision-kind classification live in the render
   service** (`parsing.py`, `POST /classify-reply`) rather than in n8n
   expressions — the DENY-before-APPROVE ordering is the most safety-critical
   logic in the system and stays unit-tested in one place.

## Golden fixture (`tests/golden_payload.json`)

Reconstructed from the approved artifact (page-1 table × page-3 ranking; the
11 Lightfire rows sum to exactly the approved total row 238/4/234/154 →
65.8%). Known, documented properties:

- **Two golden-only pins** in `display_overrides` (production payloads never
  set them; `/validate` warns when any pin is present):
  - `potential_gross_cents = 20600000` — the approved report's hand
    calculation. The §6 formula on the frozen rows yields ~$211.3k; the
    approved figure used a mixed basis. With the matured floor at 1 the two
    bases coincide going forward, so the ambiguity no longer exists.
  - `reece_total = 570/7/563/444` — the approved artifact's Reece summary
    row. Its own agent rows (fixed by the displayed page-3 percentages) sum
    to sat 445; the hand-built table understated by one. The golden must
    render the approved 78.9%.
- **Green, Sherika is absent.** The artifact counted her 2 sits on page 3 but
  not in the page-1 total; under the one-total rule including her renders
  66.7%, breaking the canonical 65.8%. Consequences: the golden page 3 has
  26 rows (not 27), and the Lightfire box's "strand at up to X%" computes
  53% rather than the artifact's 71% — that 71% is literally Green (5 of 7
  stranded).
- **Source-mix rows are synthetic** (the real Q7 rows were not shipped);
  they reproduce the NOT_EXPLANATORY state and expected ≈ 60.5% but the z
  renders ≈ 3.9, not the artifact's 8.1. Not an acceptance string.
- **`run_date` is 2026-08-18 (a Tuesday)** — the day the approved edition was
  actually issued ("issued 18 August"). Scheduled production runs are
  Mondays; `compute_windows` enforces that, the payload schema deliberately
  does not.
- **Stranded-audit numbers (Fifteen / Three / Eight) are a manual input**
  carried in the optional `stranded_audit` block; production omits the block
  until an audit is run and the page-2 opener renders its shorter variant.
- Page-3 percentage cells can differ by 1 from the artifact where the hand
  report rendered pre-rounded 1-dp values (e.g. Deer 39% vs 40%): §6 mandates
  full precision rounded once at render, so the service's cells are the
  spec-correct ones. The zero-gross tail of the ranking orders by matured
  descending (deterministic tie-break), which swaps Nievez/Francis vs the
  hand artifact.

## Every number embedded in prose (parameterisation map)

The handoff calls a stale hardcoded figure inside a sentence the most likely
defect in this build. Every number below is substituted at render time;
nothing numeric in prose is a literal.

**Page 1** — KPI values ×5 and their two range labels (`goal_pct`,
`unconf_total`); exec paragraph: `goal_pct`, `lf_sit` (+ optional trend delta
and prior), `reece_sit`, `lf_noconf_pct`, `reece_noconf_pct`,
`desk_share_lf`, `desk_share_reece`; credit bullets: per-template metrics
(matured, week sets, week label, prior→now sets, staffed output Δ, confirmed
issue % both teams); footnote: `small_denominator_min`, volume-agent count
word + name/pct list, `goal_pct`, team `sits_short`, `potential` dollars.

**Page 2** — audit opener: `stranded_n`, `any_evidence_n` (word),
`desk_reached_n` (word); chart title `lf_noconf_pct`; the 4×4 table (all
counts/percentages + both verdict cells, selected from computed p); held-
constant paragraph: both strand %; downstream: three ranges + `unconf_total`
(+ `unconf_sales` in the non-zero variant); Reece box: both desk shares,
`stranded_on_reece_leads`, `stranded_n`, desk-dial word, `reece_noconf_pct`;
Lightfire box: selfgen triple, best self-confirmer name + strand %, worst
unconfirmed strand %, both cancel %; mix footnote: z (state-selected
sentence).

**Page 3** — footnote: example agent name + issued/matured %, flag legends
(conditional), threshold clause (conditional); headline: name, rank word,
set-lead %, dollar-gap %, `sits_short`, `goal_pct`, strand %, diagnosis
(state-selected).

**Page 4** — staffing: prior/current agent words, both week labels, named/
departed detail (payload strings), output Δ, board prior/now; retention table
(all six money cells + both retention %); outlier sentence: amount, agent,
financing amount + count word, Reece financing; asking-for intro: item count
words; action rows: carry-forward "Open N weeks — last week: …" (ESCALATED
renders the # red); next step: session week (run+7), headline agent,
`stranded_n`; Method: cohort dates, cutoff date, retention limit clause
(conditional), active-agent definition (conditional, §19).

## Data gaps (§19, verified 2026-08-18)

- **Retention** (`lp_sales_efficiency_setter_history`, 0 rows): payload
  `retention: None` → the table and outlier sentence are omitted, the Method
  clause says "retention withheld this week (source feed pending)", the run
  proceeds with a soft warning. Phase-2 ticket: ingest LP Report 137 weekly —
  and any query on `scorecard_report_snapshots` MUST filter
  `is_current = true` (snapshots re-ingest 2–3× per period; raw sums
  double-count — this defect already produced a wrong cost figure once).
- **Five9 staffing**: Phase 1 derives active agents from `lp_leads`
  (definition stated in Method: "a setter with ≥1 appointment set during the
  reporting week"). Phase 2 adds true dialler-day counts (Call Log hard
  5,000-row cap → pull days in 4–6 h windows; cap never-logged-out logins at
  the scheduled shift before any arithmetic).
