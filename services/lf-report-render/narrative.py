"""Deterministic narrative (D2, §8). Two stages: calculations.py computes
states; this module maps state -> fixed sentence. No model call, ever.

Every sentence that does not contain a number is copied VERBATIM from
REFERENCE_lightfire_lean.py and is not regenerated. Only numeric substitution
and state selection are dynamic. The enumeration of every parameterized number
lives in docs/REPORT_SPEC.md — a stale hardcoded figure inside a sentence is
the most likely defect in this build and the least likely to be noticed.

Strings marked NOT-IN-REFERENCE are fixed alternatives for states the approved
report did not exhibit (e.g. a significant strand-rate test). They are authored
once here, reviewed with the PR, and never generated at run time.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# §8 SIT_TREND — the WoW clause inside the executive paragraph (§9). NO_PRIOR
# omits the clause entirely; the caller drops the parenthetical, not the
# sentence.
# ---------------------------------------------------------------------------

# NOTE: the handoff's §8 example bank omitted "last week" on the SLIGHT
# variants, but its §9 canonical example renders a 2.1-pt (slight) move as
# "(up 2.1 points from 63.7% last week)". §9 is the requirement (D8); the
# SLIGHT entries carry the suffix too. Recorded in REPORT_SPEC.
SIT_TREND = {
    "IMPROVED_MATERIAL": "up {delta:.1f} points from {prior:.1f}% last week",
    "IMPROVED_SLIGHT":   "up {delta:.1f} points from {prior:.1f}% last week",
    "FLAT":              "effectively unchanged from {prior:.1f}% last week",
    "DECLINED_SLIGHT":   "down {delta:.1f} points from {prior:.1f}% last week",
    "DECLINED_MATERIAL": "down {delta:.1f} points from {prior:.1f}% last week",
    "NO_PRIOR":          "",
}

# When the prior approved snapshot is not exactly 7 days back (§9 trend
# source), "last week" is replaced by the named week.
SIT_TREND_NAMED_WEEK = {
    "IMPROVED_MATERIAL": "up {delta:.1f} points from {prior:.1f}% in the week of {week_label}",
    "IMPROVED_SLIGHT":   "up {delta:.1f} points from {prior:.1f}% in the week of {week_label}",
    "FLAT":              "effectively unchanged from {prior:.1f}% in the week of {week_label}",
    "DECLINED_SLIGHT":   "down {delta:.1f} points from {prior:.1f}% in the week of {week_label}",
    "DECLINED_MATERIAL": "down {delta:.1f} points from {prior:.1f}% in the week of {week_label}",
    "NO_PRIOR":          "",
}


def trend_clause(state: str, delta: float | None, prior: float | None,
                 week_label: str | None = None) -> str:
    """The parenthetical for the exec paragraph: ' (up 2.1 points from 63.7%
    last week)' — empty string on NO_PRIOR so the sentence closes cleanly."""
    if state == "NO_PRIOR" or delta is None or prior is None:
        return ""
    bank = SIT_TREND_NAMED_WEEK if week_label else SIT_TREND
    body = bank[state].format(delta=abs(delta), prior=prior, week_label=week_label or "")
    return f" <i>({body})</i>"


# ---------------------------------------------------------------------------
# Executive paragraph ("The whole review in one paragraph") — reference prose
# verbatim, numbers slotted. The held-constant clause is selected by the
# STAT_VERDICT of the strand-rate test (acceptance #5 flips it).
# ---------------------------------------------------------------------------

HELD_CONSTANT = {
    "NOT_DISTINGUISHABLE": (
        "and once confirmation status is held constant we find no "
        "statistically distinguishable difference between the two teams"),
    # NOT-IN-REFERENCE: fixed alternative for a significant result.
    "SIGNIFICANT": (
        "and even once confirmation status is held constant, a statistically "
        "significant gap remains between the two teams"),
}


def executive_paragraph(*, goal_pct: float, lf_pct: float, reece_pct: float,
                        lf_noconf_pct: float, reece_noconf_pct: float,
                        desk_share_lf_pct: float, desk_share_reece_pct: float,
                        stat_verdict: str, trend: str) -> str:
    """Reference wording with the §9 trend parenthetical inserted after the
    Lightfire number. `trend` is the output of trend_clause() ('' on NO_PRIOR)."""
    return (
        "Sit % — sits divided by issued appointments net of cancellations — is the number our floor is "
        f"managed to, and our standard is <b>{goal_pct:.0f}%</b>. Your book runs <b>{lf_pct:.1f}%</b>{trend}, "
        f"ours {reece_pct:.1f}%; neither of us is where we want to be. The cause is not qualification and not "
        f"the leads you work: <b>{lf_noconf_pct:.0f}% of Lightfire-set appointments have no confirmer of record, "
        f"against {reece_noconf_pct:.0f}% of ours</b>, {HELD_CONSTANT[stat_verdict]}. "
        f"<b>A substantial share of that fix is ours</b> — our desk covers {desk_share_lf_pct:.0f}% of your "
        f"book and {desk_share_reece_pct:.0f}% of our own. We are asking for a shared confirmation-ownership "
        "rule, your bench restaffed, and sit % reported weekly by agent."
    )


# ---------------------------------------------------------------------------
# Page-2 held-constant paragraph — reference verbatim, state-selected verdict
# sentence, numbers slotted.
# ---------------------------------------------------------------------------

PAGE2_VERDICT = {
    "NOT_DISTINGUISHABLE": (
        "<b>Once confirmation status is held constant, we find no statistically distinguishable difference "
        "between the two teams in this cohort.</b> An appointment with no confirmer strands at "
        "{lf_strand_pct:.1f}% on your book and {reece_strand_pct:.1f}% on ours — a gap our data cannot "
        "separate from chance at this sample size."),
    # NOT-IN-REFERENCE: fixed alternative for a significant result.
    "SIGNIFICANT": (
        "<b>Even once confirmation status is held constant, the two teams differ in this cohort.</b> An "
        "appointment with no confirmer strands at {lf_strand_pct:.1f}% on your book and "
        "{reece_strand_pct:.1f}% on ours — a gap unlikely to be chance at this sample size."),
}

PAGE2_VERDICT_CLOSE = (
    " On the evidence here, <b>the strongest measurable driver of the difference between the two books is "
    "whether an appointment receives confirmation coverage at all.</b>"
)

PAGE2_DOWNSTREAM = (
    "And that coverage predicts almost everything downstream. Appointments carrying a confirmer of record "
    "issue at {conf_issue_range} and sit at {conf_sit_range}. Appointments without one issue at "
    "{unconf_issue_range} and, across both teams, <b>{unconf_total} matured appointments with no confirmer "
    "of record produced zero sales between them.</b>"
)

# NOT-IN-REFERENCE fallback: when either team's no-confirmer slice DID produce
# sales, the zero-sales claim must not render. State-selected, fixed.
PAGE2_DOWNSTREAM_NONZERO = (
    "And that coverage predicts almost everything downstream. Appointments carrying a confirmer of record "
    "issue at {conf_issue_range} and sit at {conf_sit_range}. Appointments without one issue at "
    "{unconf_issue_range} and, across both teams, {unconf_total} matured appointments with no confirmer of "
    "record produced <b>{unconf_sales}</b> sales between them."
)

# Stranded-audit sentences (page 2 opener). The two record-level audit counts
# are a MANUAL input (not derivable from lp_leads); when the payload omits the
# audit block, only the first sentence renders. Documented in REPORT_SPEC.
PAGE2_AUDIT_FULL = (
    "We audited all {stranded_n} of your appointments that matured still reading ‘Set’, record by "
    "record, looking for any sign a confirmation process touched them — a confirmer of record, a dial "
    "from our desk, a confirmations-board message or an AI touch. <b>{any_evidence_n} showed any evidence at "
    "all. {desk_reached_n} reached a Reece confirmer.</b> That sent us back to the full cohort."
)
PAGE2_AUDIT_ABSENT = (
    "{stranded_n} of your appointments matured still reading ‘Set’ — issued, sat by no one, "
    "and never moved. The confirmation-ownership split below is where the pattern shows."
)

# ---------------------------------------------------------------------------
# Accountability boxes — reference verbatim, numbers slotted. No blame
# language; no statements about effort, intent, competence or motivation (§8).
# ---------------------------------------------------------------------------

REECE_BOX = (
    "<b>Our desk confirms {desk_share_lf_pct:.0f}% of your book and {desk_share_reece_pct:.0f}% of our "
    "own.</b> <b>{stranded_on_reece_leads} of the {stranded_n} stranded appointments sit on leads we "
    "supplied</b> — our leads, our system, nobody on our side called them. {desk_dial_no_confirm} got a "
    "desk dial that never became a confirmation. Lead Perfection has <b>no confirmation-owner field</b>, so "
    "neither side can prove an appointment was queued and skipped. And our own {reece_noconf_pct:.1f}% "
    "never-confirmed rate is not clean either."
)

LF_BOX = (
    "Your <b>Self Generated</b> leads — {selfgen_matured} matured, {selfgen_noconf} never confirmed, "
    "{selfgen_stranded} stranded — never enter our confirmation process at all. Your agents who confirm "
    "their own book barely strand ({best_selfconf_name} {best_selfconf_strand_pct:.0f}%); the agents nobody "
    "confirms strand at up to {worst_unconf_strand_pct:.0f}%. And the <b>{lf_cancel_pct:.0f}% cancellation "
    "rate</b> on your set appointments, against {reece_cancel_pct:.0f}% on ours, is a separate qualification "
    "question this audit does not answer."
)

SOURCE_MIX_FOOT = {
    "SOURCE_MIX_NOT_EXPLANATORY": (
        "We also tested the obvious alternative — that we hand you harder leads. It does not hold: the "
        "gap appears in <b>every shared lead source</b>, and standardising for your exact source mix explains "
        "none of it (z = {z:.1f}, p &lt; 0.0001). We are happy to share that working."),
    # NOT-IN-REFERENCE alternatives, fixed:
    "SOURCE_MIX_PARTIALLY_EXPLANATORY": (
        "We also tested whether lead mix explains the gap. It explains part of it — standardising for "
        "your exact source mix closes some but not most of the difference (z = {z:.1f}). The remainder tracks "
        "confirmation coverage. We are happy to share that working."),
    "SOURCE_MIX_EXPLANATORY": (
        "We also tested whether lead mix explains the gap, and it largely does: standardising for your exact "
        "source mix closes most of the difference. That moves the conversation to lead routing rather than "
        "confirmation coverage alone. We are happy to share that working."),
    "INSUFFICIENT_SAMPLE": (
        "We also looked at lead mix. Too few sources carry enough volume on both sides this cohort for a "
        "like-for-like comparison, so we draw no conclusion from it this week."),
}

# ---------------------------------------------------------------------------
# Headline observation ("The line worth sitting with") — §8. The diagnosis
# ending is state-selected between two fixed strings.
# ---------------------------------------------------------------------------

HEADLINE_DIAGNOSIS = {
    "DIFFERENT": ("appears to need a different diagnosis from the broader "
                  "confirmation-coverage problem"),
    "PART_OF_PATTERN": "is part of the broader confirmation-coverage pattern",
}

# Reference sentence, numbers slotted; ending chosen by whether the agent's own
# no-confirmer rate is below the team average (DIFFERENT) or not.
HEADLINE_TEMPLATE = (
    "<b>{name} ranks {rank_word} in dollars while setting the most appointments in the company.</b> He sets "
    "{set_lead_pct:.0f}% more than our top setter and produces {dollar_gap_pct:.0f}% fewer dollars. He is "
    "also {sits_short:.1f} sits short of the {goal_pct:.0f}% goal — more than any setter on either team, "
    "because he carries the most volume. <b>He is the single largest opportunity in this document.</b> "
    "Because he self-confirms most of his own book and has only a {strand_pct:.0f}% strand rate, his gap "
    "{diagnosis} — which is exactly what we would like to work out with him directly."
)

# NOT-IN-REFERENCE: generic headline for a week where the selected agent is not
# the company-wide volume leader (the reference agent was). Same shape, no
# unearned superlatives.
HEADLINE_TEMPLATE_GENERIC = (
    "<b>{name} is {sits_short:.1f} sits short of the {goal_pct:.0f}% goal — more than any setter on "
    "either team — on {net_issued} net issued appointments.</b> Volume is what makes the gap this large, "
    "and volume is also what makes it worth fixing. Because his own no-confirmer rate {noconf_relation} his "
    "team’s average, the gap {diagnosis}."
)

# ---------------------------------------------------------------------------
# Credit section (§8): one fixed template per candidate type. Fewer than three
# qualifiers -> fewer bullets. Zero -> the neutral line, flagged in the
# internal approval email (never in the PDF).
# ---------------------------------------------------------------------------

CREDIT_TEMPLATES = {
    "TOP_VOLUME": (
        "<b>{name} sets more appointments than any setter in our company</b> — {matured} in six weeks, "
        "{sets_week} in the week of {week_label} alone."),
    "ABOVE_GOAL": (
        "<b>{name} is above the {goal_pct:.0f}% goal on real volume</b> — {sit_pct:.1f}% on "
        "{net_issued} net issued appointments."),
    "MOST_IMPROVED_SETS": (
        "<b>{name} doubled her output</b> ({prior_sets} → {sets}), and your three staffed agents raised "
        "combined output {staffed_output_delta_pct:.0f}% while covering an absent bench."),
    "TEAM_SIT_IMPROVED": (
        "<b>Your book’s sit % improved {delta:.1f} points week over week</b> — from "
        "{prior_pct:.1f}% to {pct:.1f}%."),
    "CONFIRMED_HOLD_UP": (
        "<b>Your confirmed appointments hold up</b> — they issue at {lf_conf_issue_pct:.1f}% against "
        "our {reece_conf_issue_pct:.1f}%."),
    "CONCENTRATION_EFFORT": (
        "<b>Your staffed agents raised their own production {output_delta_pct:.0f}%</b> while the active "
        "bench fell from {prior_agents} to {agents}."),
    "GROSS_CONTRIBUTION": (
        "<b>{name} sits inside the top {top_n} of the combined ranking</b> — ${gross:,.0f} in gross "
        "contract dollars this cohort."),
    # Zero-qualifier fallback: neutral, factual, no praise framing (§8).
    "NEUTRAL_FALLBACK": (
        "<b>{name} set the most appointments on your book this cohort</b> — {matured} matured "
        "appointments."),
}

# NOTE ON MOST_IMPROVED_SETS: the reference bullet's "doubled her output" and
# the staffed-agents clause were specific to the approved week. The template
# above preserves that sentence for golden fidelity; selectors.py only chooses
# this candidate when sets >= 2 × prior_sets AND the staffing concentration
# also holds — otherwise it falls through to the plain improvement wording
# below. Both are fixed strings.
CREDIT_MOST_IMPROVED_PLAIN = (
    "<b>{name} raised her output</b> ({prior_sets} → {sets}) — the largest week-over-week set "
    "increase on your book."
)

# ---------------------------------------------------------------------------
# Page-4 staffing paragraphs — reference verbatim, numbers slotted; the
# movement sentence is selected by STAFFING_TREND.
# ---------------------------------------------------------------------------

STAFFING_LEAD = (
    "<b>{prior_agents_word} of your agents set appointments in the week of {prior_week_label}. "
    "{agents_word} appeared on our dialler in the week of {week_label}</b> — {named_detail}. "
)

STAFFING_MOVEMENT = {
    "SHRANK_SEVERE": (
        "{departed_detail}Output held only because the three staffed agents raised their own production "
        "{output_delta_pct:.0f}%, which concentrates production in three people and creates clear continuity "
        "risk. Our Monday board shows it: your contribution fell from {board_prior} appointments to "
        "{board_now}."),
    # NOT-IN-REFERENCE alternatives, fixed:
    "SHRANK_MODERATE": (
        "{departed_detail}The bench is thinner than the prior week, which concentrates production and adds "
        "continuity risk. Our Monday board shows your contribution at {board_now} appointments against "
        "{board_prior} the week before."),
    "STABLE": (
        "{departed_detail}Staffing held level week over week. Our Monday board shows your contribution at "
        "{board_now} appointments against {board_prior} the week before."),
    "GREW": (
        "{departed_detail}The bench grew week over week. Our Monday board shows your contribution at "
        "{board_now} appointments against {board_prior} the week before."),
}

STAFFING_OFFDIALLER = (
    "Separately, several of your agents set appointments without ever logging into our dialler — "
    "consistent with working from your own system. We are not objecting, but we cannot see that activity, "
    "and it is the same population as the Self Generated leads above."
)

# Phase-1 set-based movement (§19): used when Five9 dialler detail is absent, so
# there is no "Monday board" or per-agent dialler productivity to cite. Board
# counts here are appointments SET in the week (the Phase-1 definition stated in
# Method), and no clause hardcodes a headcount. The dialler bank above stays the
# canonical reference path (the 2026-08-17 report used it); this bank is only
# selected when staffing.dialler is None.
STAFFING_MOVEMENT_SETBASED = {
    "SHRANK_SEVERE": (
        "{departed_detail}That is a sharp contraction of your setting bench, which concentrates production "
        "in a few people and creates clear continuity risk. Appointments set fell from {board_prior} the "
        "week before to {board_now}."),
    "SHRANK_MODERATE": (
        "{departed_detail}The bench is thinner than the prior week, which concentrates production and adds "
        "continuity risk. Appointments set were {board_now} against {board_prior} the week before."),
    "STABLE": (
        "{departed_detail}Staffing held level week over week. Appointments set were {board_now} against "
        "{board_prior} the week before."),
    "GREW": (
        "{departed_detail}The bench grew week over week. Appointments set were {board_now} against "
        "{board_prior} the week before."),
}

RETENTION_OUTLIER = {
    True: (
        "The cancellation figure is <b>one contract</b> — a single ${outlier_amount:,.0f} cancellation "
        "on {outlier_agent}’s largest write. Not a pattern, and we do not read it as one. The financing "
        "figure is not one contract: <b>${fin_amount:,.0f} across {fin_count}</b>, against ${reece_fin:,.0f} "
        "on our side that week."),
    False: (
        "Cancellations were spread across contracts this week rather than concentrated in one. The financing "
        "figure: <b>${fin_amount:,.0f} across {fin_count}</b>, against ${reece_fin:,.0f} on our side that "
        "week."),
}

# ---------------------------------------------------------------------------
# KPI third row (§9) — the one approved layout deviation.
# ---------------------------------------------------------------------------


def kpi_delta_line(delta: float | None, *, unit: str, favourable_up: bool) -> tuple[str, str]:
    """('▲ 2.1 pts vs prior week', 'good'|'bad'|'flat'). Empty text on no
    prior (first run) so the band height stays constant (§9). Direction is
    per-KPI: rising sit % is favourable, rising no-confirmer % is not."""
    if delta is None:
        return "", "flat"
    if abs(delta) < 0.05:
        return f"▬ level with prior week", "flat"
    arrow = "▲" if delta > 0 else "▼"
    good = (delta > 0) == favourable_up
    return f"{arrow} {abs(delta):.1f} {unit} vs prior week", ("good" if good else "bad")
