"""Exercise the deployed contract, input boundaries and privacy guarantees."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import app
from ofi.api import WindowLimiter, global_limiter, limiter


@pytest.fixture
def client():
    limiter.events.clear()
    global_limiter.events.clear()
    with TestClient(app) as instance:
        yield instance


def test_full_research_flow(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    overview = client.get("/api/overview").json()
    assert len(overview["series"]) >= 4
    for series in overview["series"]:
        response = client.get(f"/api/data/{series['id']}")
        assert response.status_code == 200
        rows = response.json()["observations"]
        assert len(rows) > 50
        assert rows == sorted(rows, key=lambda row: row["date"])
        assert series["source_url"].startswith("https://")
    forecast = overview["forecast"]
    assert forecast["lower"] <= forecast["value"] <= forecast["upper"]
    assert forecast["model_version"]
    assert len(overview["evaluation"]["metrics"]) >= 2
    assert client.get("/openapi.json").status_code == 200


def test_dates_and_untrusted_series_ids(client):
    series_id = client.get("/api/series").json()["series"][0]["id"]
    response = client.get(f"/api/data/{series_id}?start=2020-01-01&end=2020-12-31")
    assert response.status_code == 200
    assert all("2020-01-01" <= r["date"] <= "2020-12-31" for r in response.json()["observations"])
    assert client.get(f"/api/data/{series_id}?start=2025-01-01&end=2020-01-01").status_code == 422
    assert client.get(f"/api/data/{series_id}?start=wrong").status_code == 422
    assert client.get("/api/data/x%27%3Bdrop%20table%20observations").status_code == 404
    assert client.get(f"/api/data/{series_id}?start=2099-01-01").json()["observations"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "x"},
        {"question": "x" * 601},
        {"question": "          "},
        {"question": "Inflation target?", "secret": 1},
    ],
)
def test_invalid_questions(client, payload):
    assert client.post("/api/ask", json=payload).status_code == 422


def test_body_size_is_bounded_before_parsing(client):
    response = client.post(
        "/api/ask", content=b"x" * 8193, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_answer_and_abstention_contract(client, monkeypatch):
    monkeypatch.setenv("OFI_LLM_ENABLED", "false")
    for question in ["What is the UK inflation target?", "What is the best pizza recipe?"]:
        response = client.post("/api/ask", json={"question": question})
        assert response.status_code == 200
        result = response.json()
        assert {"answer", "abstained", "mode", "sources", "confidence"} <= result.keys()
    assert result["abstained"] is True


def test_request_logs_never_record_questions_or_query_secrets(client, caplog):
    with caplog.at_level(logging.INFO, logger="ofi.requests"):
        response = client.post(
            "/api/ask?token=private-query-token", json={"question": "private-question-abcdef"}
        )
    assert response.headers["x-request-id"]
    assert "private-query-token" not in "\n".join(
        r.message for r in caplog.records if r.name == "ofi.requests"
    )
    assert "private-question-abcdef" not in "\n".join(
        r.message for r in caplog.records if r.name == "ofi.requests"
    )


def test_limiter_expires_and_bounds_memory():
    guard = WindowLimiter(limit=2, window=10, capacity=2)
    assert guard.allow("one", now=0)
    assert guard.allow("one", now=1)
    assert not guard.allow("one", now=2)
    assert guard.allow("two", now=2)
    assert not guard.allow("three", now=2)
    assert guard.allow("three", now=12)


def test_rate_limited_api_response(client, monkeypatch):
    monkeypatch.setattr(limiter, "allow", lambda key: False)
    response = client.post("/api/ask", json={"question": "What is the inflation target?"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_runtime_oidc_is_request_scoped_and_not_returned(client, monkeypatch):
    from ofi import rag

    seen = []

    def fake_answer(question, *, oidc_token=None):
        seen.append(oidc_token)
        return {"answer": "Test evidence", "mode": "grounded_llm", "abstained": False}

    monkeypatch.setattr(rag, "answer_question", fake_answer)
    monkeypatch.setenv("VERCEL", "1")
    for token in ["first-request-token", "second-request-token"]:
        response = client.post(
            "/api/ask",
            json={"question": "What is the inflation target?"},
            headers={"x-vercel-oidc-token": token},
        )
        assert response.status_code == 200
        assert token not in response.text
    monkeypatch.delenv("VERCEL")
    client.post(
        "/api/ask",
        json={"question": "What is the inflation target?"},
        headers={"x-vercel-oidc-token": "untrusted-local-header"},
    )
    assert seen == ["first-request-token", "second-request-token", None]


def test_interface_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Open Finance Intelligence" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
