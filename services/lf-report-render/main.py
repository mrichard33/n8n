"""FastAPI shell (§11). n8n is orchestration only; every computation happens
here, on the frozen payload.

  POST /render          ReportPayload -> 200 application/pdf
                        422 validation | 500 pagination
  POST /validate        ReportPayload -> {ok, warnings[], failures[], derived}
                        (gate checks + the derived metrics record, no PDF)
  POST /classify-reply  {raw} -> §14 classification (DENY before APPROVE)
  GET  /health

Auth: X-Render-Token vs RENDER_TOKEN env; /health is open.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import config
from assemble import GateFailure, assemble
from parsing import classify_reply
from report_builder import PaginationError, build_report
from schema import ReportPayload

app = FastAPI(title="lf-report-render", docs_url=None, redoc_url=None)


def _check_token(x_render_token: str | None) -> None:
    if not config.AUTH_ENFORCED:
        return
    if x_render_token != config.RENDER_TOKEN:
        raise HTTPException(status_code=401, detail="bad or missing X-Render-Token")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "lf-report-render",
            "auth": "enforced" if config.AUTH_ENFORCED else "OPEN (RENDER_TOKEN unset)"}


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
        # §11: never email a malformed report — the orchestrator marks the run
        # GENERATION_FAILED on any non-200.
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
