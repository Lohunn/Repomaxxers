"""Flask Telemetry Ingestion and Vehicle Status Service.

Accepts GPS telemetry from Traccar, OwnTracks, and Simulator clients.
Writes live vehicle location to vehicles/{id} and history track to vehicles/{id}/track in Firestore
(or local store fallback).
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from flask import Flask, jsonify, request

from agents import config, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DispatchFlaskService")

app = Flask(__name__)


def parse_telemetry_payload(req: request) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Normalizes incoming payload from Traccar, OwnTracks, or Simulator into standard format.

    Returns:
        (normalized_dict, provider_name) or (None, None) if parsing fails.
    """
    # 1. Check for JSON body
    body: dict[str, Any] = {}
    if req.is_json:
        try:
            body = req.get_json(silent=True) or {}
        except Exception:
            body = {}

    # 2. Check query params or form data (common for Traccar HTTP client)
    args = req.args.to_dict() if hasattr(req.args, "to_dict") else dict(req.args or {})
    form = req.form.to_dict() if hasattr(req.form, "to_dict") else dict(req.form or {})

    # --- Scenario A: OwnTracks Payload ---
    if body.get("_type") == "location":
        tid = body.get("tid")
        topic = body.get("topic", "")
        # Derive device_id from topic or tid or default
        device_id = topic.split("/")[-1] if "/" in topic else (tid or config.DEFAULT_VEHICLE_ID)
        tst = body.get("tst")
        ts_str = (
            datetime.fromtimestamp(tst, tz=timezone.utc).isoformat()
            if tst
            else datetime.now(timezone.utc).isoformat()
        )
        return {
            "device_id": device_id,
            "latitude": float(body.get("lat", 0.0)),
            "longitude": float(body.get("lon", 0.0)),
            "speed": float(body.get("vel", 0.0)),
            "heading": float(body.get("cog", 0.0)),
            "timestamp": ts_str,
        }, "owntracks"

    # --- Scenario B: Simulator Payload (JSON) ---
    if "device_id" in body or ("latitude" in body and "longitude" in body):
        device_id = str(body.get("device_id") or config.DEFAULT_VEHICLE_ID)
        return {
            "device_id": device_id,
            "latitude": float(body.get("latitude", 0.0)),
            "longitude": float(body.get("longitude", 0.0)),
            "speed": float(body.get("speed", 0.0)),
            "heading": float(body.get("heading", 0.0)),
            "timestamp": body.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        }, "simulator"

    # --- Scenario C: Traccar HTTP protocol (GET or POST parameters) ---
    raw = {}
    raw.update(args)
    raw.update(form)
    raw.update(body)

    device_key = raw.get("id") or raw.get("deviceid") or raw.get("uniqueId")
    lat_key = raw.get("lat") or raw.get("latitude")
    lon_key = raw.get("lon") or raw.get("longitude") or raw.get("lng")

    if lat_key is not None and lon_key is not None:
        device_id = str(device_key or config.DEFAULT_VEHICLE_ID)
        speed = float(raw.get("speed", 0.0))
        bearing = float(raw.get("bearing") or raw.get("heading") or 0.0)
        ts_val = raw.get("timestamp") or raw.get("time") or datetime.now(timezone.utc).isoformat()

        return {
            "device_id": device_id,
            "latitude": float(lat_key),
            "longitude": float(lon_key),
            "speed": speed,
            "heading": bearing,
            "timestamp": str(ts_val),
        }, "traccar"

    return None, None


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for container orchestrators and Cloud Run."""
    return jsonify({
        "status": "healthy",
        "service": "logistics-dispatch-service",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage_mode": "local_store" if config.USE_LOCAL_STORE else "firestore",
        "routes_mode": "mock_haversine" if config.USE_MOCK_ROUTES else "google_routes_api",
    })


@app.route("/location", methods=["GET", "POST"])
def ingest_location():
    """Ingests vehicle GPS telemetry from Traccar, OwnTracks, or Simulator.

    Writes to Firestore vehicles/{id} and vehicles/{id}/track (or local fallback).
    """
    # Optional Tracker Token Verification
    if config.TRACKER_TOKEN:
        auth_header = request.headers.get("Authorization", "")
        token_param = request.args.get("token", "")
        expected = f"Bearer {config.TRACKER_TOKEN}"
        if auth_header and auth_header != expected and token_param != config.TRACKER_TOKEN:
            logger.warning("Unauthorized telemetry post attempt: invalid token")
            return jsonify({"status": "error", "message": "Unauthorized: invalid tracker token"}), 401

    payload, provider = parse_telemetry_payload(request)
    if not payload:
        return jsonify({
            "status": "error",
            "message": "Unrecognized telemetry payload format. Expected Traccar, OwnTracks, or Simulator format.",
        }), 400

    device_id = payload["device_id"]
    res = store.save_vehicle_location(
        device_id=device_id,
        latitude=payload["latitude"],
        longitude=payload["longitude"],
        speed=payload["speed"],
        heading=payload["heading"],
        timestamp=payload["timestamp"],
        provider=provider,
    )

    logger.info(
        "Ingested telemetry from [%s] for vehicle '%s': lat=%s, lon=%s (backend=%s)",
        provider,
        device_id,
        payload["latitude"],
        payload["longitude"],
        res.get("backend"),
    )

    return jsonify({
        "status": "ok",
        "device_id": device_id,
        "backend": res.get("backend"),
        "timestamp": payload["timestamp"],
    })


@app.route("/vehicles/<device_id>", methods=["GET"])
def get_vehicle_status(device_id: str):
    """Retrieves current position and breadcrumbs status for specified vehicle."""
    data = store.get_vehicle_location(device_id)
    if not data:
        return jsonify({
            "status": "error",
            "message": f"Vehicle '{device_id}' has not reported any location telemetry.",
        }), 404

    return jsonify({
        "status": "success",
        "vehicle": data,
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info("Starting Logistics Dispatch Service on port %d...", port)
    app.run(host="0.0.0.0", port=port, debug=False)
