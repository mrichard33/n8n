"""Credit and headline selection (§8). Rule-based; every candidate is backed
by a computed metric.

Filename note: the handoff's layout sketch names this file selectors.py, which
shadows the Python stdlib `selectors` module that subprocess/asyncio (and so
uvicorn) import — the service cannot run under that name. Renamed alongside
statistics.py -> stats_engine.py for the same reason. No generic praise, no fabricated qualitative claims, no
forced praise — fewer than three qualifiers means fewer bullets, and zero
qualifiers renders one neutral factual line plus a flag in the internal
approval email so a human notices (the flag never appears in the PDF).
"""
from __future__ import annotations

from dataclasses import dataclass

from calculations import AgentDerived, TeamDisplayTotal
from narrative import (
    CREDIT_MOST_IMPROVED_PLAIN, CREDIT_TEMPLATES, HEADLINE_DIAGNOSIS,
    HEADLINE_TEMPLATE, HEADLINE_TEMPLATE_GENERIC,
)

_RANK_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
               6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}


@dataclass(frozen=True)
class CreditObservation:
    kind: str
    text: str
    supporting_metric: dict  # persisted to lf_report_metrics.credit_observations

    def as_record(self) -> dict:
        return {"kind": self.kind, "text": self.text, "metric": self.supporting_metric}


@dataclass(frozen=True)
class CreditResult:
    observations: list[CreditObservation]
    neutral_fallback_used: bool  # -> warning line in the approval email


def select_credit(
    lf_agents: list[AgentDerived],
    all_agents_ranked: list[AgentDerived],
    *,
    goal_pct: float,
    week_label: str,
    lf_week_sets: dict[str, int],        # setter -> sets in the reporting week
    team_sit_pct: float | None,          # THE display-derived total
    team_sit_prior_pct: float | None,
    lf_conf_issue_pct: float | None,     # issue % of confirmed LF appointments
    reece_conf_issue_pct: float | None,
    active_agents: int,
    prior_active_agents: int,
    staffed_output_delta_pct: float | None,
    max_bullets: int = 3,
) -> CreditResult:
    """§8 priority order, up to three. Candidates evaluated strictly in the
    priority-table order; within a candidate type the best-qualifying agent is
    taken."""
    out: list[CreditObservation] = []
    lf = [a for a in lf_agents]

    def add(kind: str, text: str, metric: dict) -> None:
        if len(out) < max_bullets:
            out.append(CreditObservation(kind, text, metric))

    # 1 TOP_VOLUME — an LF agent has the highest matured across BOTH teams.
    if lf and all_agents_ranked:
        top = max(all_agents_ranked, key=lambda a: a.agent.matured)
        if top.agent.team == "Lightfire":
            add("TOP_VOLUME", CREDIT_TEMPLATES["TOP_VOLUME"].format(
                name=_display_first_last(top), matured=top.agent.matured,
                sets_week=lf_week_sets.get(top.agent.setter_name, 0), week_label=week_label),
                {"setter": top.agent.setter_name, "matured": top.agent.matured})

    # 2 ABOVE_GOAL — net_issued >= 20 and issued sit >= 80.
    above = [a for a in lf if a.agent.net_issued >= 20 and (a.issued_sit_pct or 0) >= 80]
    if above:
        best = max(above, key=lambda a: a.issued_sit_pct or 0)
        add("ABOVE_GOAL", CREDIT_TEMPLATES["ABOVE_GOAL"].format(
            name=_display_first_last(best), goal_pct=goal_pct,
            sit_pct=best.issued_sit_pct, net_issued=best.agent.net_issued),
            {"setter": best.agent.setter_name, "issued_sit_pct": round(best.issued_sit_pct or 0, 1)})

    # 3 MOST_IMPROVED_SETS — sets up >= 5 WoW. The reference's "doubled her
    # output" sentence is used only when the doubling and the staffing
    # concentration both actually hold; otherwise the plain fixed wording.
    improved = [a for a in lf if a.agent.sets_period - a.agent.sets_prior_period >= 5]
    if improved:
        best = max(improved, key=lambda a: a.agent.sets_period - a.agent.sets_prior_period)
        doubled = (best.agent.sets_prior_period > 0
                   and best.agent.sets_period >= 2 * best.agent.sets_prior_period)
        if doubled and staffed_output_delta_pct is not None and active_agents < prior_active_agents:
            text = CREDIT_TEMPLATES["MOST_IMPROVED_SETS"].format(
                name=_display_first_last(best), prior_sets=best.agent.sets_prior_period,
                sets=best.agent.sets_period, staffed_output_delta_pct=staffed_output_delta_pct)
        else:
            text = CREDIT_MOST_IMPROVED_PLAIN.format(
                name=_display_first_last(best), prior_sets=best.agent.sets_prior_period,
                sets=best.agent.sets_period)
        add("MOST_IMPROVED_SETS", text,
            {"setter": best.agent.setter_name,
             "sets": best.agent.sets_period, "prior_sets": best.agent.sets_prior_period})

    # 4 TEAM_SIT_IMPROVED — the display-derived team sit % up >= 2.0 WoW.
    if team_sit_pct is not None and team_sit_prior_pct is not None and team_sit_pct - team_sit_prior_pct >= 2.0:
        add("TEAM_SIT_IMPROVED", CREDIT_TEMPLATES["TEAM_SIT_IMPROVED"].format(
            delta=team_sit_pct - team_sit_prior_pct, prior_pct=team_sit_prior_pct, pct=team_sit_pct),
            {"pct": round(team_sit_pct, 1), "prior_pct": round(team_sit_prior_pct, 1)})

    # 5 CONFIRMED_HOLD_UP — LF confirmed-appointment issue % within 10 pts of Reece.
    if (lf_conf_issue_pct is not None and reece_conf_issue_pct is not None
            and abs(reece_conf_issue_pct - lf_conf_issue_pct) <= 10):
        add("CONFIRMED_HOLD_UP", CREDIT_TEMPLATES["CONFIRMED_HOLD_UP"].format(
            lf_conf_issue_pct=lf_conf_issue_pct, reece_conf_issue_pct=reece_conf_issue_pct),
            {"lf": round(lf_conf_issue_pct, 1), "reece": round(reece_conf_issue_pct, 1)})

    # 6 CONCENTRATION_EFFORT — staffed output rose while active agents fell.
    if (staffed_output_delta_pct is not None and staffed_output_delta_pct > 0
            and active_agents < prior_active_agents):
        add("CONCENTRATION_EFFORT", CREDIT_TEMPLATES["CONCENTRATION_EFFORT"].format(
            output_delta_pct=staffed_output_delta_pct, prior_agents=prior_active_agents,
            agents=active_agents),
            {"output_delta_pct": round(staffed_output_delta_pct, 1),
             "agents": active_agents, "prior_agents": prior_active_agents})

    # 7 GROSS_CONTRIBUTION — an LF agent inside the top 6 combined ranking.
    top6 = [a for a in all_agents_ranked if (a.rank_by_gross or 99) <= 6 and a.agent.team == "Lightfire"]
    if top6:
        best = min(top6, key=lambda a: a.rank_by_gross or 99)
        add("GROSS_CONTRIBUTION", CREDIT_TEMPLATES["GROSS_CONTRIBUTION"].format(
            name=_display_first_last(best), top_n=6, gross=best.agent.gross_cents / 100),
            {"setter": best.agent.setter_name, "rank": best.rank_by_gross})

    if out:
        return CreditResult(out, neutral_fallback_used=False)

    # Zero qualifiers: one neutral factual line, flagged for the approval email.
    if lf:
        top = max(lf, key=lambda a: a.agent.matured)
        return CreditResult(
            [CreditObservation("NEUTRAL_FALLBACK", CREDIT_TEMPLATES["NEUTRAL_FALLBACK"].format(
                name=_display_first_last(top), matured=top.agent.matured),
                {"setter": top.agent.setter_name, "matured": top.agent.matured})],
            neutral_fallback_used=True)
    return CreditResult([], neutral_fallback_used=True)


# ---------------------------------------------------------------------------
# Headline observation — "The line worth sitting with"
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadlineObservation:
    setter_name: str
    text: str
    score: float                  # == sits_short of the selected agent
    supporting_metric: dict

    def as_record(self) -> dict:
        return {"setter": self.setter_name, "score": round(self.score, 2),
                "text": self.text, "metric": self.supporting_metric}


def select_headline(
    lf_agents: list[AgentDerived],
    all_agents_ranked: list[AgentDerived],
    *,
    goal_pct: float,
    agent_noconf_pct: dict[str, float],   # setter -> own no-confirmer %
    agent_strand_pct: dict[str, float],   # setter -> own strand %
    team_noconf_pct: float,
    min_net_issued: int = 20,
) -> HeadlineObservation | None:
    """Eligible: net_issued >= 20. Score = sits_short — deliberately NOT the
    most negative statistic (§8): a 36% agent on 11 appointments loses fewer
    sits than a 62% agent on 97. Returns None when nobody is eligible (the
    renderer then omits the callout body gracefully — flagged in validation as
    a soft warning, never invented)."""
    eligible = [a for a in lf_agents if a.agent.net_issued >= min_net_issued]
    if not eligible:
        return None
    pick = max(eligible, key=lambda a: a.sits_short)
    # lf_agents rows carry no rank; resolve the pick against the ranked list.
    pick = next((a for a in all_agents_ranked
                 if a.agent.setter_name == pick.agent.setter_name), pick)
    own_noconf = agent_noconf_pct.get(pick.agent.setter_name, team_noconf_pct)
    diagnosis_state = "DIFFERENT" if own_noconf < team_noconf_pct else "PART_OF_PATTERN"
    diagnosis = HEADLINE_DIAGNOSIS[diagnosis_state]

    is_volume_leader = pick.agent.matured == max(a.agent.matured for a in all_agents_ranked)
    top_gross = max(a.agent.gross_cents for a in all_agents_ranked)
    if is_volume_leader and pick.rank_by_gross and top_gross > 0:
        top_other = max((a for a in all_agents_ranked if a.agent.setter_name != pick.agent.setter_name),
                        key=lambda a: a.agent.matured)
        text = HEADLINE_TEMPLATE.format(
            name=_display_first_last(pick),
            rank_word=_RANK_WORDS.get(pick.rank_by_gross, f"#{pick.rank_by_gross}"),
            set_lead_pct=100.0 * (pick.agent.matured - top_other.agent.matured) / top_other.agent.matured,
            dollar_gap_pct=100.0 * (top_gross - pick.agent.gross_cents) / top_gross,
            sits_short=pick.sits_short, goal_pct=goal_pct,
            strand_pct=agent_strand_pct.get(pick.agent.setter_name, 0.0),
            diagnosis=diagnosis)
    else:
        text = HEADLINE_TEMPLATE_GENERIC.format(
            name=_display_first_last(pick), sits_short=pick.sits_short, goal_pct=goal_pct,
            net_issued=pick.agent.net_issued,
            noconf_relation=("runs below" if diagnosis_state == "DIFFERENT" else "matches"),
            diagnosis=diagnosis)
    return HeadlineObservation(pick.agent.setter_name, text, pick.sits_short,
                               {"net_issued": pick.agent.net_issued,
                                "sits_short": round(pick.sits_short, 1),
                                "own_noconf_pct": round(own_noconf, 1),
                                "team_noconf_pct": round(team_noconf_pct, 1),
                                "diagnosis": diagnosis_state})


def _display_first_last(a: AgentDerived) -> str:
    """'Deer, Craig' -> 'Craig Deer' — prose uses first-last, tables keep
    last-first exactly as the reference does."""
    name = a.name
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name
