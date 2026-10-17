"""Unit tests for the Flask Web UI, API endpoints, and SSE Chat stream."""

import json
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_serves_html(client):
    """Verifies that the pure-white minimalist UI is served at root."""
    res = client.get("/")
    assert res.status_code == 200
    assert b"LOGISTICS DISPATCH AGENTS" in res.data
    assert b"Google ADK 2.12" in res.data


def test_api_config(client):
    """Verifies client runtime configuration endpoint."""
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.get_json()
    assert "default_vehicle_id" in data
    assert "storage_mode" in data
    assert "routes_mode" in data


def test_api_state(client):
    """Verifies live dispatch state endpoint."""
    res = client.get("/api/state?vehicle_id=driver-1")
    assert res.status_code == 200
    data = res.get_json()
    assert "vehicle" in data
    assert "stats" in data
    assert "on_time_rate" in data["stats"]


def test_api_diagnostics(client):
    """Verifies diagnostic health probe endpoint."""
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    data = res.get_json()
    assert "gemini" in data
    assert "routes" in data
    assert "store" in data
    assert "mcp" in data
    assert data["gemini"]["status"] in ["PASS", "FAIL"]
    assert data["store"]["status"] == "PASS"
    assert data["mcp"]["status"] == "PASS"


def test_api_sim_start_and_stop(client):
    """Verifies simulator background start and stop controls."""
    res_start = client.post("/api/sim/start")
    assert res_start.status_code == 200
    data_start = res_start.get_json()
    assert data_start["running"] is True

    res_stop = client.post("/api/sim/stop")
    assert res_stop.status_code == 200
    data_stop = res_stop.get_json()
    assert data_stop["running"] is False


def test_api_chat_sse_stream(client):
    """Verifies conversational dispatch chat streams SSE events."""
    payload = {"message": "Where is driver-1?", "vehicle_id": "driver-1"}
    res = client.post("/api/chat", json=payload)
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    content = res.data.decode("utf-8")
    assert "event: agent_step" in content
    assert "event: tool_call" in content
    assert "event: message" in content
    assert "event: done" in content
