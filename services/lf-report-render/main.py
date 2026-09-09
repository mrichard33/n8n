"""FastAPI shell (§11). n8n is orchestration only; every computation and every
LP read/write happens here, on the frozen payload and the lf_* state.

  Rendering (stateless, payload in / PDF out):
  POST /render          ReportPayload -> 200 application/pdf | 422 | 500
  POST /validate        ReportPayload -> {ok, warnings[], failures[], derived}
  POST /classify-reply  {raw} -> §14 classification (DENY before APPROVE)

  Pipeline (LP-backed; the render service owns all LP I/O — Phase-E adaptation):
  POST /orchestrate/weekly  {run_date?, force?, manual_regeneration?}
  POST /approval/decide     {token, sender_email, raw_reply, channel}
  POST /revise              {run_id, revision_kind, instruction, requested_by, overrides?}
  POST /deliver/prepare     {version_id}
  POST /deliver/confirm     {version_id, provider_message_id?}
  POST /reminders/tick      {}
  GET  /reports/{version_id}/pdf   -> 200 application/pdf   (Gmail attachment source)

  GET  /health          service + DB status

Auth: X-Render-Token vs RENDER_TOKEN env on every route except /health.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from datetime import date
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import config
import orchestrator
from assemble import GateFailure, assemble
from db import Db
from parsing import classify_reply
from report_builder import PaginationError, build_report
from schema import ReportPayload

app = FastAPI(title="lf-report-render", docs_url=None, redoc_url=None)

# One Db for the process. Constructing it opens no connection (that happens per
# call), so import is cheap and DB-less tests can run /render and /validate.
# Endpoint tests swap in a stand-in via main._DB.
_DB = Db()


def _check_token(x_render_token: str | None) -> None:
    if not config.AUTH_ENFORCED:
        return
    if x_render_token != config.RENDER_TOKEN:
        raise HTTPException(status_code=401, detail="bad or missing X-Render-Token")


@app.get("/health")
def health() -> dict:
    db_status = _DB.health() if _DB.dsn else {"ok": False, "configured": False}
    return {"ok": True, "service": "lf-report-render",
            "auth": "enforced" if config.AUTH_ENFORCED else "OPEN (RENDER_TOKEN unset)",
            "db": db_status}


# ---------------------------------------------------------------------------
# Stateless rendering
# ---------------------------------------------------------------------------

@app.post("/validate")
def validate(payload: ReportPayload, x_render_token: str | None = Header(default=None)) -> JSONResponse:
    _check_token(x_render_token)
    try:
        d = assemble(payload)
    except GateFailure as g:
        return JSONResponse({"ok": False, "failures": g.failures, "warnings": []}, status_code=200)
    return JSONResponse({"ok": True, "failures": [], "warnings": d.warnings,
                         "derived": d.metrics_record()})


@app.post("/render")
def render(payload: ReportPayload, x_render_token: str | None = Header(default=None)) -> Response:
    _check_token(x_render_token)
    started = time.monotonic()
    out = os.path.join(tempfile.mkdtemp(prefix="lfreport"), "report.pdf")
    try:
        result = build_report(payload, out)
    except GateFailure as g:
        raise HTTPException(status_code=422, detail={"error": "validation", "failures": g.failures})
    except PaginationError as e:
        return JSONResponse({"error": "pagination", "pages": e.pages}, status_code=500)
    with open(result.path, "rb") as f:
        pdf = f.read()
    sha = hashlib.sha256(pdf).hexdigest()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={
            "X-Page-Count": str(result.page_count),
            "X-Pdf-Sha256": sha,
            "X-Render-Ms": str(int((time.monotonic() - started) * 1000)),
            "X-Warnings": str(len(result.derived.warnings)),
        })


class ReplyIn(BaseModel):
    raw: str


@app.post("/classify-reply")
def classify(body: ReplyIn, x_render_token: str | None = Header(default=None)) -> dict:
    _check_token(x_render_token)
    return classify_reply(body.raw).as_record()


# ---------------------------------------------------------------------------
# LP-backed pipeline
# ---------------------------------------------------------------------------

def _guard_db(x_render_token: str | None):
    _check_token(x_render_token)
    if not _DB.dsn:
        raise HTTPException(status_code=503, detail="SUPABASE_DB_URL not configured")


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface DB/render failures as 500
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


class OrchestrateIn(BaseModel):
    run_date: Optional[date] = None
    force: bool = False
    manual_regeneration: bool = False


@app.post("/orchestrate/weekly")
def orchestrate_weekly(body: OrchestrateIn, x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    run_date = body.run_date or date.today()
    return _run(orchestrator.run_weekly, _DB, run_date, force=body.force,
                manual_regeneration=body.manual_regeneration)


class DecideIn(BaseModel):
    token: str
    sender_email: str
    raw_reply: str
    channel: str = "email_reply"


@app.post("/approval/decide")
def approval_decide(body: DecideIn, x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    return _run(orchestrator.apply_decision, _DB, token=body.token, sender_email=body.sender_email,
                raw_reply=body.raw_reply, channel=body.channel)


class Override(BaseModel):
    scope: str
    scope_key: str
    field: str
    override_value: float
    original_value: Optional[float] = None
    reason: Optional[str] = None


class ReviseIn(BaseModel):
    run_id: str
    revision_kind: str
    instruction: str
    requested_by: str
    overrides: Optional[list[Override]] = None


@app.post("/revise")
def revise(body: ReviseIn, x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    overrides = [o.model_dump() for o in body.overrides] if body.overrides else None
    return _run(orchestrator.revise, _DB, run_id=body.run_id, revision_kind=body.revision_kind,
                instruction=body.instruction, requested_by=body.requested_by, overrides=overrides)


class VersionIn(BaseModel):
    version_id: str
    provider_message_id: Optional[str] = None


@app.post("/deliver/prepare")
def deliver_prepare(body: VersionIn, x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    return _run(orchestrator.prepare_delivery, _DB, body.version_id)


@app.post("/deliver/confirm")
def deliver_confirm(body: VersionIn, x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    return _run(orchestrator.confirm_delivery, _DB, body.version_id,
                provider_message_id=body.provider_message_id)


@app.post("/reminders/tick")
def reminders_tick(x_render_token: str | None = Header(default=None)) -> dict:
    _guard_db(x_render_token)
    return _run(orchestrator.reminders_tick, _DB)


@app.get("/reports/{version_id}/pdf")
def get_report_pdf(version_id: str, x_render_token: str | None = Header(default=None)) -> Response:
    _guard_db(x_render_token)
    pdf = _run(_DB.get_pdf, version_id)
    if not pdf:
        raise HTTPException(status_code=404, detail="no stored PDF for that version")
    return Response(content=pdf["pdf_bytes"], media_type="application/pdf",
                    headers={"X-Pdf-Sha256": pdf["sha256"],
                             "Content-Disposition": f'attachment; filename="report-{version_id}.pdf"'})
