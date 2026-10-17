"""Storage layer supporting Google Cloud Firestore and local JSON fallback."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from agents import config

logger = logging.getLogger("LogisticsStore")

_firestore_client = None


def get_firestore_client():
    """Lazily initializes and returns the Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore

        project = config.GOOGLE_CLOUD_PROJECT or None
        _firestore_client = firestore.Client(project=project)
    return _firestore_client


def _load_local_store() -> dict[str, Any]:
    """Reads the local JSON store."""
    if not config.LOCAL_STORE_FILE.exists():
        return {"vehicles": {}}
    try:
        with open(config.LOCAL_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read local store file, initializing new store: %s", e)
        return {"vehicles": {}}


def _save_local_store(data: dict[str, Any]) -> None:
    """Writes the local JSON store atomically."""
    temp_file = config.LOCAL_STORE_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    temp_file.replace(config.LOCAL_STORE_FILE)


def save_vehicle_location(
    device_id: str,
    latitude: float,
    longitude: float,
    speed: float = 0.0,
    heading: float = 0.0,
    timestamp: Optional[str] = None,
    raw_payload: Optional[dict[str, Any]] = None,
    provider: str = "simulator",
) -> dict[str, Any]:
    """Saves vehicle position to vehicles/{id} and appends to vehicles/{id}/track.

    Respects USE_LOCAL_STORE flag, and provides self-healing fallback to local
    store if Firestore encounters permission or connection errors.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "device_id": device_id,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "speed": float(speed),
        "heading": float(heading),
        "timestamp": timestamp or now_iso,
        "updated_at": now_iso,
        "provider": provider,
    }

    if not config.USE_LOCAL_STORE:
        try:
            db = get_firestore_client()
            # 1. Update latest vehicle state
            doc_ref = db.collection("vehicles").document(device_id)
            doc_ref.set(record)

            # 2. Append to historical breadcrumbs track
            track_ref = doc_ref.collection("track").document()
            track_ref.set({
                "latitude": float(latitude),
                "longitude": float(longitude),
                "speed": float(speed),
                "heading": float(heading),
                "timestamp": timestamp or now_iso,
                "created_at": now_iso,
            })
            return {"status": "success", "backend": "firestore", "vehicle": record}
        except Exception as e:
            logger.warning(
                "[Self-Healing Store] Firestore write failed (%s). Falling back to local store.",
                e,
            )

    # Local Store fallback / mock path
    data = _load_local_store()
    vehicles = data.setdefault("vehicles", {})
    vehicle_entry = vehicles.setdefault(device_id, {})
    vehicle_entry.update(record)
    track = vehicle_entry.setdefault("track", [])
    track.append({
        "latitude": float(latitude),
        "longitude": float(longitude),
        "speed": float(speed),
        "heading": float(heading),
        "timestamp": timestamp or now_iso,
        "created_at": now_iso,
    })
    # Keep track capped at 500 entries locally
    if len(track) > 500:
        vehicle_entry["track"] = track[-500:]
    _save_local_store(data)

    return {"status": "success", "backend": "local_store", "vehicle": record}


def get_vehicle_location(device_id: str) -> Optional[dict[str, Any]]:
    """Retrieves current vehicle location from Firestore or local store."""
    if not config.USE_LOCAL_STORE:
        try:
            db = get_firestore_client()
            doc = db.collection("vehicles").document(device_id).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            logger.warning(
                "[Self-Healing Store] Firestore read failed (%s). Falling back to local store.",
                e,
            )

    # Local Store read
    data = _load_local_store()
    vehicle = data.get("vehicles", {}).get(device_id)
    if vehicle:
        return {
            "device_id": vehicle.get("device_id", device_id),
            "latitude": vehicle.get("latitude"),
            "longitude": vehicle.get("longitude"),
            "speed": vehicle.get("speed", 0.0),
            "heading": vehicle.get("heading", 0.0),
            "timestamp": vehicle.get("timestamp"),
            "updated_at": vehicle.get("updated_at"),
            "provider": vehicle.get("provider", "local"),
        }
    return None
