"""Orchestrator: the pure query-rows -> ReportPayload translation, and the
run/decide/revise/deliver/reminder state machine against an in-memory Db
stand-in. No live database — the SQL itself is validated separately against LP
via the Supabase MCP; here we prove the logic that sits on top of the rows.

The cohort fixture is the golden payload inverted back into query-row shape, so
run_weekly renders a real four-page PDF on the production (Phase-1, no-dialler)
staffing path — the path the golden fixture never exercises.
"""
import copy
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import orchestrator
from windows import compute_windows
from datetime import date

GOLDEN = json.loads((Path(__file__).parent / "golden_payload.json").read_text())

CONFIG = {
    "issued_sit_goal": 0.80, "small_denominator_min": 20, "min_matured_for_table": 1,
    "alpha": 0.05, "material_delta_pts": 3.0, "slight_delta_pts": 1.0, "expected_page_count": 4,
    "report_enabled": True, "approval_reminder_hours": [24, 48],
}

ACTION_SEED = [
    ("confirmation_ownership_rule", "IMMEDIATE", 1,
     "A written confirmation ownership rule — every appointment carries one named owning desk before its date",
     "Rule agreed and in force both sides", "Both", date(2026, 9, 1)),
    ("reece_desk_coverage", "IMMEDIATE", 2, "Reece commits coverage on Reece-supplied leads you set",
     "Coverage staffed, measured weekly", "Reece", date(2026, 9, 1)),
    ("lf_selfgen_coverage", "IMMEDIATE", 3,
     "Lightfire commits coverage on Self Generated leads, or they route to our desk",
     "Named owner on every one", "Lightfire", date(2026, 9, 1)),
    ("weekly_sit_reporting", "IMMEDIATE", 4,
     "Issued Sit % reported weekly by agent — Deer, Walker and Wright first",
     "Lightfire book >= 75% by 1 Oct", "Lightfire", date(2026, 10, 1)),
    ("restore_bench", "IMMEDIATE", 5, "Restore the bench — named agents, expected days per week",
     ">= 8 agents producing in a week", "Lightfire", date(2026, 9, 1)),
    ("offdialler_reporting", "SECONDARY", 6, "Agree reporting for agents dialling from your own system",
     "Method agreed and in use", "Both", date(2026, 9, 15)),
    ("financing_denied_review", "SECONDARY", 7, "Review the three financing-denied contracts together",
     "Reviewed; retention monthly", "Both", date(2026, 9, 15)),
]


def golden_to_cohort() -> dict:
    """Invert golden_payload.json into Q2/Q3/Q5/Q5b/Q6/Q7 row shapes."""
    g = GOLDEN
    agents = []
    activity = []
    for a in g["agents"]:
        agents.append({
            "setter_name": a["setter_name"], "display_name": a.get("display_name"),
            "team": a["team"], "roster_flag": a.get("roster_flag"), "matured": a["matured"],
            "gross_issued": a["gross_issued"], "cancels": a["cancels"], "net_issued": a["net_issued"],
            "sat": a["sat"], "sold": a["sold"], "gross_cents": a["gross_cents"],
            "no_confirmer": a.get("no_confirmer", 0), "stranded": a.get("stranded", 0)})
        activity.append({"setter_name": a["setter_name"], "team": a["team"],
                         "sets_activity_wk": a.get("sets_period", 0),
                         "sets_prior_wk": a.get("sets_prior_period", 0)})

    def team_row(team, base):
        return {"team": team, "matured": base["matured"], "no_confirmer": base["no_confirmer"],
                "confirmed_by_desk": base["confirmed_by_desk"], "self_confirmed": base["self_confirmed"],
                "confirmed_ai_other": base["confirmed_ai_other"], "stranded": base["stranded"],
                "cxl_all": base["cancels_all"]}

    def splits(team, base):
        rows = []
        for flag, key in ((True, "confirmed"), (False, "unconfirmed")):
            s = base[key]
            rows.append({"team": team, "confirmed": flag, "n": s["n"], "issued": s["issued"],
                         "sat": s["sat"], "sold": s["sold"], "stranded": s["stranded"]})
        return rows

    return {
        "team_totals": [team_row("Lightfire", g["lightfire_base"]), team_row("Reece", g["reece_base"])],
        "agents": agents,
        "confirm_splits": splits("Lightfire", g["lightfire_base"]) + splits("Reece", g["reece_base"]),
        "selfgen": {"selfgen_matured": g["selfgen"]["matured"],
                    "selfgen_no_confirmer": g["selfgen"]["no_confirmer"],
                    "selfgen_stranded": g["selfgen"]["stranded"],
                    "stranded_on_reece_leads": g["lightfire_base"]["stranded_on_reece_leads"]},
        "activity": activity,
        "source_mix": [dict(r) for r in g["source_mix"]],
        "unmapped": [],
    }


class FakeDb:
    """In-memory Db surface. Stores what the pipeline writes so tests can assert
    on the frozen state."""

    def __init__(self, *, cohort=None, config=None, enabled=True,
                 approvers=("m.richard@reecewindows.com", "b.codman@reecewindows.com"),
                 recipients=()):
        self.partner_id = "partner-1"
        self._cohort = cohort if cohort is not None else golden_to_cohort()
        self._config = dict(config or CONFIG)
        self._config["report_enabled"] = enabled
        self._approvers = {a.lower() for a in approvers}
        self._recipients = list(recipients)
        self.runs = {}
        self.versions = {}
        self.pdfs = {}
        self.approval_requests = {}
        self.team_metrics = {}
        self.agent_metrics = {}
        self.report_metrics = {}
        self.approval_events = []
        self.delivery_events = []
        self.overrides = []
        self.audit_events = []
        self.reminded = {}
        self.actions = [
            {"action_key": k, "tier": t, "sort_order": o, "title": ti, "success_definition": sd,
             "owner": ow, "due_date": dd, "status": "OPEN", "weeks_open": 0}
            for (k, t, o, ti, sd, ow, dd) in ACTION_SEED]
        self.actions_rolled = 0

    # reads
    def is_report_enabled(self): return self._config.get("report_enabled") is True
    def get_partner_id(self, slug="lightfire"): return self.partner_id
    def get_config(self): return dict(self._config)
    def get_approvers(self): return set(self._approvers)
    def get_vendor_recipients(self, partner_id): return list(self._recipients)
    def get_actions(self, partner_id): return [dict(a) for a in self.actions if a["status"] != "REMOVED"]
    def fetch_cohort(self, w): return copy.deepcopy(self._cohort)
    def get_prior_snapshot(self, partner_id, w): return []

    def get_existing_run(self, partner_id, ps, pe):
        for r in self.runs.values():
            if r["period_start"] == ps and r["period_end"] == pe:
                return dict(r)
        return None

    def get_run(self, run_id): return dict(self.runs[run_id]) if run_id in self.runs else None
    def get_version(self, vid): return dict(self.versions[vid]) if vid in self.versions else None

    def get_latest_version(self, run_id):
        vs = [v for v in self.versions.values() if v["run_id"] == run_id]
        return dict(max(vs, key=lambda v: v["version_no"])) if vs else None

    def get_pdf(self, vid):
        return dict(self.pdfs[vid]) if vid in self.pdfs else None

    def get_run_by_token(self, token):
        for ar in self.approval_requests.values():
            if ar["approval_token"] == token:
                run = self.runs[ar["run_id"]]
                return {"approval_request_id": ar["id"], "run_id": ar["run_id"],
                        "version_id": ar["version_id"], "sent_to": ar["sent_to"],
                        "resolved_at": ar.get("resolved_at"), "reminded_at": ar.get("reminded_at"),
                        "run_status": run["status"], "partner_id": run["partner_id"],
                        "approved_version_id": run.get("approved_version_id")}
        return None

    def pending_approvals(self):
        out = []
        for ar in self.approval_requests.values():
            run = self.runs[ar["run_id"]]
            if run["status"] == "READY_FOR_REVIEW" and not ar.get("resolved_at"):
                out.append({"approval_request_id": ar["id"], "run_id": ar["run_id"],
                            "approval_token": ar["approval_token"], "sent_to": ar["sent_to"],
                            "sent_at": ar["sent_at"], "reminded_at": ar.get("reminded_at")})
        return out

    # writes
    def create_run(self, partner_id, w, *, manual_regeneration=False):
        existing = self.get_existing_run(partner_id, w.period_start, w.period_end)
        if existing:
            return existing["id"], False
        rid = "run-" + uuid.uuid4().hex[:8]
        self.runs[rid] = {"id": rid, "partner_id": partner_id, "status": "INGESTING",
                          "period_start": w.period_start, "period_end": w.period_end,
                          "approved_version_id": None, "sent_at": None, "current_version_id": None,
                          "manual_regeneration": manual_regeneration}
        return rid, True

    def set_run_status(self, run_id, status, **fields):
        self.runs[run_id].update(status=status, **fields)

    def roll_forward_actions(self, partner_id):
        self.actions_rolled += 1
        for a in self.actions:
            if a["status"] in ("OPEN", "IN_PROGRESS", "RECURRED"):
                a["weeks_open"] += 1

    def audit(self, *, run_id, version_id, event_type, actor="render-service", metadata=None):
        self.audit_events.append({"run_id": run_id, "version_id": version_id,
                                  "event_type": event_type, "actor": actor, "metadata": metadata or {}})

    def persist_version(self, *, run_id, version_no, payload, payload_sha256, pdf_bytes, pdf_sha256,
                        page_count, render_ms, source_snapshot_hash, team_metrics, agent_metrics,
                        report_metrics, approval_token, sent_to, revision_reason=None,
                        revision_kind=None):
        vid = "ver-" + uuid.uuid4().hex[:8]
        self.versions[vid] = {"id": vid, "run_id": run_id, "version_no": version_no,
                              "payload": payload, "payload_sha256": payload_sha256,
                              "pdf_sha256": pdf_sha256, "page_count": page_count,
                              "source_snapshot_hash": source_snapshot_hash,
                              "revision_kind": revision_kind}
        self.pdfs[vid] = {"version_id": vid, "pdf_bytes": pdf_bytes, "sha256": pdf_sha256,
                          "byte_size": len(pdf_bytes)}
        self.team_metrics[run_id] = team_metrics
        self.agent_metrics[run_id] = agent_metrics
        self.report_metrics[run_id] = report_metrics
        arid = "ar-" + uuid.uuid4().hex[:8]
        self.approval_requests[arid] = {"id": arid, "run_id": run_id, "version_id": vid,
                                        "approval_token": approval_token, "sent_to": sent_to,
                                        "sent_at": datetime.now(timezone.utc), "reminded_at": [],
                                        "resolved_at": None, "outcome": None}
        self.runs[run_id].update(status="READY_FOR_REVIEW", current_version_id=vid,
                                 source_snapshot_hash=source_snapshot_hash)
        return {"version_id": vid, "approval_request_id": arid}

    def record_approval_event(self, **kw): self.approval_events.append(kw)

    def resolve_approval(self, *, approval_request_id, run_id, outcome, approved_version_id=None,
                         run_status=None):
        self.approval_requests[approval_request_id].update(resolved_at=datetime.now(timezone.utc),
                                                           outcome=outcome)
        if run_status:
            self.runs[run_id]["status"] = run_status
            if approved_version_id:
                self.runs[run_id]["approved_version_id"] = approved_version_id

    def append_reminded_at(self, arid, ts):
        self.approval_requests[arid].setdefault("reminded_at", []).append(ts)

    def record_delivery_event(self, *, run_id, version_id, approved_sha256, sent_sha256,
                              hash_verified, recipients, provider_message_id):
        self.delivery_events.append({"run_id": run_id, "version_id": version_id,
                                     "approved_sha256": approved_sha256, "sent_sha256": sent_sha256,
                                     "hash_verified": hash_verified, "recipients": recipients,
                                     "provider_message_id": provider_message_id})
        if hash_verified:
            self.runs[run_id].update(status="SENT", sent_at=datetime.now(timezone.utc))

    def insert_override(self, **kw): self.overrides.append(kw)


REF_MONDAY = date(2026, 8, 17)  # -> period 08-09..08-15, cohort 07-06..08-15, cutoff 08-16


# ---------------------------------------------------------------------------
# build_payload (pure)
# ---------------------------------------------------------------------------

def test_build_payload_maps_and_validates():
    w = compute_windows(REF_MONDAY)
    db = FakeDb()
    p = orchestrator.build_payload(w, db.get_config(), db.fetch_cohort(w), [], db.get_actions("p"))
    # window + team bases straight from the rows
    assert p.lightfire_base.matured == 446
    assert p.reece_base.matured == 678
    # gate #6 (category sum) held on the way out, or model_validate would have raised
    assert (p.lightfire_base.no_confirmer + p.lightfire_base.confirmed_by_desk
            + p.lightfire_base.self_confirmed + p.lightfire_base.confirmed_ai_other) == 446
    assert p.lightfire_base.stranded_on_reece_leads == 53
    # Phase-1 staffing is SET-BASED, not the golden's dialler count of 4
    assert p.staffing.dialler is None
    assert p.staffing.active_agents == sum(
        1 for a in GOLDEN["agents"] if a["team"] == "Lightfire" and a.get("sets_period", 0) > 0)
    # action title bolding + by-label
    assert p.actions[0].title_html.startswith("<b>A written confirmation ownership rule</b> — ")
    assert p.actions[0].by_label == "1 Sep"
    assert p.prior is None  # no prior rows


def test_build_payload_prior_snapshot_maps():
    w = compute_windows(REF_MONDAY)
    db = FakeDb()
    prior_rows = [
        {"run_id": "r0", "period_start": date(2026, 8, 2), "period_end": date(2026, 8, 8),
         "status": "SENT", "team": "Lightfire", "issued_sit_pct": 63.5, "matured_sit_pct": 34.0,
         "net_issued": 230, "sat": 146, "no_confirmer": 170, "matured": 440, "active_agents": 12},
        {"run_id": "r0", "period_start": date(2026, 8, 2), "period_end": date(2026, 8, 8),
         "status": "SENT", "team": "Reece", "issued_sit_pct": 79.0, "matured_sit_pct": 60.0,
         "net_issued": 560, "sat": 442, "no_confirmer": 70, "matured": 675, "active_agents": None},
    ]
    p = orchestrator.build_payload(w, db.get_config(), db.fetch_cohort(w), prior_rows, db.get_actions("p"))
    assert p.prior is not None
    assert p.prior.lf_issued_sit_pct == 63.5
    assert p.prior.reece_issued_sit_pct == 79.0
    assert p.prior.is_exactly_prior_week is True   # 08-02 == this run's prior_period_start
    assert p.prior.kpi5_prior == 12


# ---------------------------------------------------------------------------
# run_weekly
# ---------------------------------------------------------------------------

def test_run_weekly_renders_four_pages_and_freezes_state():
    db = FakeDb(recipients=[])
    out = orchestrator.run_weekly(db, REF_MONDAY)
    assert out["status"] == "READY_FOR_REVIEW"
    assert out["page_count"] == 4                       # production Phase-1 path is 4 pages
    run_id = out["run_id"]
    assert db.runs[run_id]["status"] == "READY_FOR_REVIEW"
    # a version, its PDF, and an approval request were frozen
    vid = out["version_id"]
    assert vid in db.versions and vid in db.pdfs
    assert db.pdfs[vid]["sha256"] == out["pdf_sha256"]
    assert len(db.team_metrics[run_id]) == 2
    assert db.agent_metrics[run_id]                     # ranked agents persisted
    # approval email carries the headline the report shows
    assert out["email"]["headline"]["lf_matured"] == 446
    assert "[LR-2026-W33-V1]" in out["email"]["subject"]
    assert set(out["email"]["to"]) == db.get_approvers()
    assert db.actions_rolled == 1                       # §10 rolled once


def test_run_weekly_disabled_skips():
    db = FakeDb(enabled=False)
    out = orchestrator.run_weekly(db, REF_MONDAY)
    assert out == {"status": "DISABLED", "skipped": True}
    assert not db.runs


def test_run_weekly_idempotent_when_already_ready():
    db = FakeDb()
    first = orchestrator.run_weekly(db, REF_MONDAY)
    assert first["status"] == "READY_FOR_REVIEW"
    again = orchestrator.run_weekly(db, REF_MONDAY)
    assert again["skipped"] is True and again["idempotent"] is True
    assert db.actions_rolled == 1                       # NOT rolled a second time


def test_run_weekly_unmapped_blocks():
    cohort = golden_to_cohort()
    cohort["unmapped"] = [{"unmapped_setter": "Newperson, Jane", "matured": 5}]
    db = FakeDb(cohort=cohort)
    out = orchestrator.run_weekly(db, REF_MONDAY)
    assert out["status"] == "BLOCKED"
    assert "Newperson, Jane" in out["reasons"][0]
    assert db.runs[out["run_id"]]["status"] == "BLOCKED"


def test_run_weekly_zero_matured_blocks():
    cohort = golden_to_cohort()
    cohort["team_totals"] = [t for t in cohort["team_totals"] if t["team"] != "Lightfire"]
    db = FakeDb(cohort=cohort)
    out = orchestrator.run_weekly(db, REF_MONDAY)
    assert out["status"] == "BLOCKED"


def test_run_weekly_force_regenerates_without_rerolling():
    db = FakeDb()
    orchestrator.run_weekly(db, REF_MONDAY)
    out = orchestrator.run_weekly(db, REF_MONDAY, force=True, manual_regeneration=True)
    assert out["status"] == "READY_FOR_REVIEW"
    assert db.actions_rolled == 1                       # force reuses the run; no second roll


# ---------------------------------------------------------------------------
# apply_decision (§14 routing)
# ---------------------------------------------------------------------------

def _ready(db):
    out = orchestrator.run_weekly(db, REF_MONDAY)
    return out["approval_token"], out["run_id"], out["version_id"]


def test_decision_approved_marks_and_flags_delivery():
    db = FakeDb()
    token, run_id, vid = _ready(db)
    r = orchestrator.apply_decision(db, token=token, sender_email="M.Richard@reecewindows.com",
                                    raw_reply="Approved", channel="email_reply")
    assert r == {"action": "approved", "deliver": True, "run_id": run_id, "version_id": vid}
    assert db.runs[run_id]["status"] == "APPROVED"
    assert db.runs[run_id]["approved_version_id"] == vid


def test_decision_not_approved_is_deny():
    db = FakeDb()
    token, run_id, _ = _ready(db)
    r = orchestrator.apply_decision(db, token=token, sender_email="b.codman@reecewindows.com",
                                    raw_reply="Not approved — hold this", channel="email_reply")
    assert r["action"] == "deny"
    assert db.runs[run_id]["status"] == "DENIED"


def test_decision_edit_requests_revision():
    db = FakeDb()
    token, run_id, _ = _ready(db)
    r = orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                    raw_reply="EDIT: Craig had 47 issued, not 49", channel="email_reply")
    assert r["action"] == "edit" and r["revision_kind"] == "DATA_CORRECTION"
    assert db.runs[run_id]["status"] == "REVISION_REQUESTED"


def test_decision_unauthorized_sender():
    db = FakeDb()
    token, run_id, _ = _ready(db)
    r = orchestrator.apply_decision(db, token=token, sender_email="stranger@example.com",
                                    raw_reply="Approved", channel="email_reply")
    assert r["action"] == "unauthorized" and r["alert"] is True
    assert db.runs[run_id]["status"] == "READY_FOR_REVIEW"      # unchanged


def test_decision_unknown_stays_pending():
    db = FakeDb()
    token, run_id, _ = _ready(db)
    r = orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                    raw_reply="looks interesting, thoughts?", channel="email_reply")
    assert r["action"] == "unknown" and r["clarify"] is True
    assert db.runs[run_id]["status"] == "READY_FOR_REVIEW"


def test_decision_duplicate_approve_is_noop():
    db = FakeDb()
    token, run_id, _ = _ready(db)
    orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                raw_reply="Approved", channel="email_reply")
    r = orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                    raw_reply="Approved", channel="email_reply")
    assert r["action"] == "noop"


# ---------------------------------------------------------------------------
# delivery (§13.4)
# ---------------------------------------------------------------------------

def _approved(db):
    token, run_id, vid = _ready(db)
    orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                raw_reply="Approved", channel="email_reply")
    return run_id, vid


def test_delivery_aborts_on_empty_recipients():
    db = FakeDb(recipients=[])
    _, vid = _approved(db)
    r = orchestrator.prepare_delivery(db, vid)
    assert r["ok"] is False and r["reason"] == "no_recipients" and r["abort"] is True


def test_delivery_aborts_on_corrupted_pdf():
    db = FakeDb(recipients=["partner@lightfire.example"])
    _, vid = _approved(db)
    db.pdfs[vid]["pdf_bytes"] = db.pdfs[vid]["pdf_bytes"] + b"tamper"   # sha no longer matches
    r = orchestrator.prepare_delivery(db, vid)
    assert r["ok"] is False and r["reason"] == "hash_mismatch" and r["abort"] is True


def test_delivery_prepare_then_confirm_sends():
    db = FakeDb(recipients=["partner@lightfire.example"])
    run_id, vid = _approved(db)
    prep = orchestrator.prepare_delivery(db, vid)
    assert prep["ok"] is True and prep["recipients"] == ["partner@lightfire.example"]
    assert prep["approved_sha256"] == prep["sent_sha256"]
    conf = orchestrator.confirm_delivery(db, vid, provider_message_id="gmail-123")
    assert conf["ok"] is True and conf["status"] == "SENT"
    assert db.runs[run_id]["status"] == "SENT"
    assert db.delivery_events[-1]["hash_verified"] is True


# ---------------------------------------------------------------------------
# revision (§13.3) — data correction produces v2 for a fresh approval
# ---------------------------------------------------------------------------

def test_revise_data_correction_new_version():
    db = FakeDb()
    token, run_id, vid = _ready(db)
    orchestrator.apply_decision(db, token=token, sender_email="m.richard@reecewindows.com",
                                raw_reply="EDIT: Deer had 95 issued, not 99", channel="email_reply")
    r = orchestrator.revise(db, run_id=run_id, revision_kind="DATA_CORRECTION",
                            instruction="Deer had 95 issued, not 99", requested_by="m.richard@reecewindows.com",
                            overrides=[{"scope": "agent", "scope_key": "Deer, Craig",
                                        "field": "gross_issued", "override_value": 95}])
    assert r["ok"] is True and r["status"] == "READY_FOR_REVIEW"
    assert "V2" in r["approval_token"]
    latest = db.get_latest_version(run_id)
    assert latest["version_no"] == 2
    deer = next(a for a in latest["payload"]["agents"] if a["setter_name"] == "Deer, Craig")
    assert deer["gross_issued"] == 95 and deer["net_issued"] == 95 - deer["cancels"]
    assert db.overrides and db.overrides[0]["field"] == "gross_issued"


# ---------------------------------------------------------------------------
# reminders (§13.2 — never auto-approves)
# ---------------------------------------------------------------------------

def test_reminders_fire_at_thresholds_and_never_approve():
    db = FakeDb()
    _ready(db)
    ar = next(iter(db.approval_requests.values()))
    # nothing due yet
    assert orchestrator.reminders_tick(db, now=ar["sent_at"] + timedelta(hours=1))["reminders"] == []
    # 24h crossed -> one reminder
    due = orchestrator.reminders_tick(db, now=ar["sent_at"] + timedelta(hours=25))["reminders"]
    assert len(due) == 1 and due[0]["tier_hours"] == 24
    # same window -> not repeated
    assert orchestrator.reminders_tick(db, now=ar["sent_at"] + timedelta(hours=26))["reminders"] == []
    # 48h crossed -> second reminder
    due2 = orchestrator.reminders_tick(db, now=ar["sent_at"] + timedelta(hours=49))["reminders"]
    assert len(due2) == 1 and due2[0]["tier_hours"] == 48
    # still pending — reminders never approve
    assert db.runs[due2[0]["run_id"]]["status"] == "READY_FOR_REVIEW"
