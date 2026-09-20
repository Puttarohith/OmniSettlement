"""
Integration Tests for OmniSettlement API Server & Chaos Injection Endpoints
"""
import pytest
from fastapi.testclient import TestClient
from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "OmniSettlement" in response.text
    assert "Dispute Studio" in response.text


def test_ledger_state_endpoint(client):
    response = client.get("/api/ledger/state")
    assert response.status_code == 200
    data = response.json()
    assert "balances" in data
    assert "PLATFORM_ESCROW" in data["balances"]
    assert "audit_log" in data


def test_chaos_injection_scenarios(client):
    scenarios = [
        "CUSTOMER_LATE_CANCEL",
        "MERCHANT_KITCHEN_FAILURE",
        "PROMPT_INJECTION_ATTACK",
        "LOW_CONFIDENCE_ARBITRATION",
        "DUPLICATE_REPLAY_ATTACK"
    ]
    for sc in scenarios:
        res = client.post("/api/chaos/inject", json={"scenario": sc})
        assert res.status_code == 200
        data = res.json()
        assert "execution_id" in data
        assert "steps" in data
        assert len(data["steps"]) >= 1


def test_recent_events_endpoint(client):
    response = client.get("/api/events/recent")
    assert response.status_code == 200
    events = response.json()
    assert isinstance(events, list)
    assert len(events) >= 1
