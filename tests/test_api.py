import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def api(mock_settings):
    with TestClient(create_app(mock_settings)) as client:
        yield client


def test_health_reports_model_and_mock_mode(api):
    body = api.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["model"] == "typesafe/jev-1.14"
    assert body["mock_mode"] is True
    assert body["mock_reason"] == "mock_mode_enabled"


def test_root_serves_workbench(api):
    resp = api.get("/")
    assert resp.status_code == 200
    assert "Jev Decision Engine" in resp.text
    assert api.get("/static/js/app.js").status_code == 200


def test_triage_contract(api):
    resp = api.post("/api/v1/triage", json={"text": "Someone hacked my account and 2FA was disabled", "channel": "email"})
    assert resp.status_code == 200
    body = resp.json()
    for field in ("category", "confidence", "distribution", "urgency", "ambiguity_probability", "requires_human_escalation", "latency_ms"):
        assert field in body
    assert set(body["distribution"]) == {"billing", "technical", "security", "feature"}
    assert body["urgency"]["label"] in {"P4 Low", "P3 Medium", "P2 High", "P1 Critical"}


def test_triage_rejects_empty_text(api):
    assert api.post("/api/v1/triage", json={"text": ""}).status_code == 422


def test_route_contract(api):
    body = api.post("/api/v1/route", json={"title": "Review vendor NDA", "description": "Legal review of contract terms"}).json()
    assert body["queue"] in {"engineering", "data_analytics", "finance_ops", "legal_compliance", "customer_success", "human_review"}
    assert body["complexity"]["label"] in {"S", "M", "L", "XL"}


def test_clip_contract(api):
    body = api.post("/api/v1/clip", json={"segment": "Here's the one lesson that changed everything for us."}).json()
    assert body["outcome"] in {"clip", "skip"}
    assert 1 <= body["hook_score"] <= 5
    assert set(body["hook_distribution"]) == {"1", "2", "3", "4", "5"}


def test_decide_playground(api):
    resp = api.post(
        "/api/v1/decide",
        json={
            "state": "CSV export times out every time",
            "questions": {
                "is_bug": {"type": "noul", "instructions": "Is this a bug?", "criteria": {"true": "error timeout", "false": "praise"}},
                "area": {"type": "choice", "instructions": "Area", "criteria": {"export": "CSV export", "billing": "invoices"}},
                "severity": {"type": "score", "instructions": "Severity", "criteria": ["low", "medium", "high"]},
            },
        },
    )
    assert resp.status_code == 200
    answers = resp.json()["answers"]
    assert answers["is_bug"]["type"] == "noul"
    assert answers["area"]["choice"] == "export"
    assert len(answers["severity"]["probabilities"]) == 3


def test_decide_validates_question_shape(api):
    resp = api.post("/api/v1/decide", json={"state": "x", "questions": {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}}})
    assert resp.status_code == 422
