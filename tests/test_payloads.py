"""Unit tests for Flask telemetry ingestion (/location) and payload parsing."""

import json
import pytest
from app import app
from agents import config


@pytest.fixture
def client():
    app.config["TESTING"] = True
    config.USE_LOCAL_STORE = True
    with app.test_client() as client:
        yield client


def test_health_check(client):
    """Verifies that /health returns a healthy status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert "logistics-dispatch-service" in data["service"]


def test_simulator_payload_ingest(client):
    """Verifies ingestion of standard simulator JSON telemetry."""
    payload = {
        "device_id": "sim-van-01",
        "latitude": 13.0827,
        "longitude": 80.2707,
        "speed": 35.5,
        "heading": 180.0,
    }
    headers = {"Authorization": f"Bearer {config.TRACKER_TOKEN}"}
    resp = client.post("/location", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["device_id"] == "sim-van-01"

    # Verify vehicle state can be retrieved
    v_resp = client.get("/vehicles/sim-van-01")
    assert v_resp.status_code == 200
    v_data = v_resp.get_json()["vehicle"]
    assert v_data["latitude"] == 13.0827
    assert v_data["longitude"] == 80.2707


def test_owntracks_payload_ingest(client):
    """Verifies ingestion of OwnTracks mobile GPS JSON payload."""
    payload = {
        "_type": "location",
        "tid": "OT1",
        "topic": "owntracks/dispatch/driver-owntracks",
        "lat": 13.0012,
        "lon": 80.2565,
        "vel": 25,
        "cog": 90,
        "tst": 1700000000,
    }
    headers = {"Authorization": f"Bearer {config.TRACKER_TOKEN}"}
    resp = client.post("/location", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["device_id"] == "driver-owntracks"


def test_traccar_payload_ingest(client):
    """Verifies ingestion of Traccar HTTP GPS tracking payload."""
    headers = {"Authorization": f"Bearer {config.TRACKER_TOKEN}"}
    params = {
        "id": "traccar-unit-9",
        "lat": 13.0418,
        "lon": 80.2341,
        "speed": 42.0,
        "bearing": 135.0,
    }
    resp = client.get("/location", query_string=params, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["device_id"] == "traccar-unit-9"


def test_invalid_payload_rejected(client):
    """Verifies that unparseable payloads receive HTTP 400 Bad Request."""
    headers = {"Authorization": f"Bearer {config.TRACKER_TOKEN}"}
    resp = client.post("/location", json={"bogus_key": 123}, headers=headers)
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["status"] == "error"


def test_unauthorized_token_rejected(client):
    """Verifies that requests with invalid token are rejected with HTTP 401."""
    headers = {"Authorization": "Bearer wrong-token-value"}
    resp = client.post("/location", json={"device_id": "test"}, headers=headers)
    assert resp.status_code == 401
