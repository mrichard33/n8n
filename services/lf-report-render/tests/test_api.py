"""HTTP surface: auth, /validate, /render headers, pagination 500,
/classify-reply."""
import copy
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

GOLDEN = json.loads((Path(__file__).parent / "golden_payload.json").read_text())


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("RENDER_TOKEN", "test-token")
    import config
    importlib.reload(config)
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_health_open(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_auth_enforced(client):
    assert client.post("/validate", json=GOLDEN).status_code == 401
    assert client.post("/classify-reply", json={"raw": "Approved"}).status_code == 401


def _h():
    return {"X-Render-Token": "test-token"}


def test_validate_ok_with_derived(client):
    r = client.post("/validate", json=GOLDEN, headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["derived"]["source_mix_state"] == "SOURCE_MIX_NOT_EXPLANATORY"
    lf = body["derived"]["team_display_totals"]["Lightfire"]
    assert round(lf["issued_sit_pct"], 1) == 65.8
    assert any("display_overrides" in w for w in body["warnings"])


def test_validate_gate_failure(client):
    bad = copy.deepcopy(GOLDEN)
    bad["lightfire_base"]["unconfirmed"].update(n=0, issued=0, sat=0, sold=0, stranded=0)
    bad["lightfire_base"].update(no_confirmer=0, confirmed_by_desk=271,
                                 confirmed={"n": 446, "issued": 241, "sat": 157, "sold": 47, "stranded": 79})
    r = client.post("/validate", json=bad, headers=_h())
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["failures"]


def test_render_pdf_and_headers(client):
    r = client.post("/render", json=GOLDEN, headers=_h())
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["X-Page-Count"] == "4"
    assert len(r.headers["X-Pdf-Sha256"]) == 64
    assert r.content[:5] == b"%PDF-"


def test_render_pagination_500(client):
    bad = copy.deepcopy(GOLDEN)
    bad["config"]["expected_page_count"] = 5
    r = client.post("/render", json=bad, headers=_h())
    assert r.status_code == 500
    assert r.json() == {"error": "pagination", "pages": 4}


def test_render_schema_violation_422(client):
    bad = copy.deepcopy(GOLDEN)
    bad["meta"]["period_end"] = "2026-08-14"  # a Friday
    assert client.post("/render", json=bad, headers=_h()).status_code == 422


def test_classify_reply_endpoint(client):
    r = client.post("/classify-reply", json={"raw": "Not approved — hold this"}, headers=_h())
    assert r.status_code == 200
    assert r.json()["classification"] == "DENY"
