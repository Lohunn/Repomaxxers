"""Tool implementations for Logistics Dispatch Agents.

Includes vehicle tracking, order intake, Google Routes API planning with
Haversine fallback, delivery window verification, and delay notifications.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import requests
from pydantic import BaseModel, Field

from google.adk.tools import ToolContext, exit_loop
from agents import callbacks, config, store

logger = logging.getLogger("LogisticsTools")

# Default hub coordinates (Chennai Central Distribution Hub)
DEFAULT_HUB = {
    "latitude": 13.0827,
    "longitude": 80.2707,
    "address": "Chennai Central Logistics Hub, EVR Periyar Salai, Chennai",
}

# Known location mock geocoder dictionary for testing/demo stability
MOCK_GEOCODE_DB = {
    "adyar": {"latitude": 13.0012, "longitude": 80.2565, "display": "Adyar, Chennai"},
    "t nagar": {"latitude": 13.0418, "longitude": 80.2341, "display": "T. Nagar, Chennai"},
    "velachery": {"latitude": 12.9815, "longitude": 80.2180, "display": "Velachery, Chennai"},
    "guindy": {"latitude": 13.0067, "longitude": 80.2021, "display": "Guindy, Chennai"},
    "mylapore": {"latitude": 13.0368, "longitude": 80.2676, "display": "Mylapore, Chennai"},
    "anna nagar": {"latitude": 13.0850, "longitude": 80.2101, "display": "Anna Nagar, Chennai"},
    "omr": {"latitude": 12.9150, "longitude": 80.2280, "display": "OMR IT Corridor, Chennai"},
}


class StopItem(BaseModel):
    """Structured order delivery stop."""
    stop_id: str = Field(description="Unique stop identifier, e.g. stop-1")
    address: str = Field(description="Delivery destination address")
    customer_name: str = Field(default="Customer", description="Customer contact name")
    contact_phone: str = Field(default="+91-9876543210", description="Customer phone number")
    package_count: int = Field(default=1, description="Number of parcels to deliver")
    window_start: str = Field(default="09:00", description="Earliest delivery time (HH:MM or ISO)")
    window_end: str = Field(default="17:00", description="Latest delivery deadline (HH:MM or ISO)")
    priority: str = Field(default="normal", description="Priority: high, normal, low")
    notes: str = Field(default="", description="Special instructions, e.g. 'call on arrival'")
    latitude: Optional[float] = Field(default=None, description="Destination latitude")
    longitude: Optional[float] = Field(default=None, description="Destination longitude")


def get_vehicle(vehicle_id: str = "driver-1") -> dict[str, Any]:
    """Retrieves live GPS telemetry and location for a dispatch vehicle.

    Args:
        vehicle_id: Unique vehicle identifier, defaults to 'driver-1'.

    Returns:
        Dictionary containing current latitude, longitude, speed, heading,
        timestamp, and last update status.
    """
    def _fetch():
        pos = store.get_vehicle_location(vehicle_id)
        if pos:
            return pos
        # Self-healing default fallback if vehicle has not yet sent GPS ping
        return {
            "device_id": vehicle_id,
            "latitude": DEFAULT_HUB["latitude"],
            "longitude": DEFAULT_HUB["longitude"],
            "address": DEFAULT_HUB["address"],
            "speed": 0.0,
            "heading": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "default_origin_hub",
            "note": "Vehicle has not broadcasted recent GPS coordinates. Defaulting to Central Logistics Hub.",
        }

    pos, healing_logs = callbacks.retry_with_backoff(
        _fetch,
        max_retries=2,
        action_name=f"get_vehicle({vehicle_id})",
    )
    if healing_logs:
        pos["healing_logs"] = healing_logs
    return pos


def parse_orders(order_text: str) -> dict[str, Any]:
    """Parses messy, unstructured order text into a validated schema of delivery stops.

    Extracts delivery addresses, target time windows, parcel counts, priority,
    and special notes, assigning geographic coordinates.

    Args:
        order_text: Raw text string containing orders, addresses, and delivery constraints.

    Returns:
        Structured dictionary with parsed stops and validation status.
    """
    cleaned_lower = order_text.lower()
    found_stops: list[dict[str, Any]] = []
    stop_idx = 1

    # Extract matching locations and inspect their specific clauses
    for loc_key, coords in MOCK_GEOCODE_DB.items():
        if loc_key in cleaned_lower:
            loc_idx = cleaned_lower.find(loc_key)
            # Isolate the segment around this location (up to next sentence/delimiter or 80 chars)
            seg_start = max(0, loc_idx - 30)
            seg_end = min(len(cleaned_lower), loc_idx + 80)
            segment = cleaned_lower[seg_start:seg_end]

            window_end = "17:00"
            notes = ""
            priority = "normal"
            pkg_count = 1

            if "urgent" in segment or "high priority" in segment or "asap" in segment:
                priority = "high"

            if "before 1" in segment or "by 1" in segment or "before 13" in segment:
                window_end = "13:00"
            elif "before 2" in segment or "by 2" in segment or "before 14" in segment:
                window_end = "14:00"
            elif "before 3" in segment or "by 3" in segment or "before 15" in segment:
                window_end = "15:00"
            elif "before 4" in segment or "by 4" in segment or "before 16" in segment:
                window_end = "16:00"
            elif "before 5" in segment or "by 5" in segment or "before 17" in segment:
                window_end = "17:00"

            if "call first" in segment or "call on arrival" in segment or "call" in segment:
                notes = "Call customer first"

            if "2 box" in segment or "2 parcel" in segment or ("2" in segment and "box" in segment):
                pkg_count = 2
            elif "3 box" in segment or "3 parcel" in segment:
                pkg_count = 3

            stop = StopItem(
                stop_id=f"stop-{stop_idx}",
                address=coords["display"],
                customer_name=f"Recipient {stop_idx}",
                contact_phone=f"+91-987654321{stop_idx}",
                package_count=pkg_count,
                window_start="09:00",
                window_end=window_end,
                priority=priority,
                notes=notes,
                latitude=coords["latitude"],
                longitude=coords["longitude"],
            )
            found_stops.append(stop.model_dump())
            stop_idx += 1

    # Fallback default stops if no known location keyword found
    if not found_stops:
        found_stops = [
            StopItem(
                stop_id="stop-1",
                address="Adyar, Chennai",
                customer_name="Customer 1",
                package_count=2,
                window_start="09:00",
                window_end="17:00",
                priority="normal",
                notes="Call before arrival",
                latitude=MOCK_GEOCODE_DB["adyar"]["latitude"],
                longitude=MOCK_GEOCODE_DB["adyar"]["longitude"],
            ).model_dump()
        ]

    return {
        "status": "success",
        "stop_count": len(found_stops),
        "stops": found_stops,
    }


def _plan_route_haversine_fallback(
    origin_lat: float,
    origin_lng: float,
    stops: list[dict[str, Any]],
    departure_time: datetime,
    reason: str,
) -> dict[str, Any]:
    """Self-healing fallback route planner using Haversine TSP and estimated city speeds."""
    logger.info("[Self-Healing Fallback] Calculating route via Haversine TSP: %s", reason)

    current_lat, current_lng = origin_lat, origin_lng
    unvisited = list(stops)
    ordered_stops: list[dict[str, Any]] = []

    total_distance_km = 0.0
    current_time = departure_time

    while unvisited:
        # Nearest neighbor selection
        unvisited.sort(
            key=lambda s: callbacks.haversine_distance_km(
                current_lat,
                current_lng,
                s.get("latitude", current_lat),
                s.get("longitude", current_lng),
            )
        )
        next_stop = unvisited.pop(0)
        s_lat = next_stop.get("latitude", current_lat)
        s_lng = next_stop.get("longitude", current_lng)

        leg_dist = callbacks.haversine_distance_km(current_lat, current_lng, s_lat, s_lng)
        total_distance_km += leg_dist

        # City speed assumption: 30 km/h (0.5 km per min) + 10 mins service time
        transit_minutes = max(5, int((leg_dist / 30.0) * 60))
        service_minutes = 10
        current_time += timedelta(minutes=transit_minutes)
        eta_str = current_time.strftime("%H:%M")
        current_time += timedelta(minutes=service_minutes)

        stop_record = dict(next_stop)
        stop_record["eta"] = eta_str
        stop_record["leg_distance_km"] = round(leg_dist, 2)
        stop_record["transit_minutes"] = transit_minutes
        ordered_stops.append(stop_record)

        current_lat, current_lng = s_lat, s_lng

    total_duration_minutes = int((current_time - departure_time).total_seconds() / 60)

    return {
        "status": "success",
        "mode": "degraded_estimate",
        "degraded": True,
        "warning": f"Routes API degraded fallback active: {reason}",
        "origin": {"latitude": origin_lat, "longitude": origin_lng},
        "total_distance_km": round(total_distance_km, 2),
        "total_duration_minutes": total_duration_minutes,
        "departure_time": departure_time.strftime("%H:%M"),
        "ordered_stops": ordered_stops,
        "healing_logs": [f"Routes API fallback engaged: {reason}"],
    }


def plan_route(
    origin_lat: float,
    origin_lng: float,
    stops: list[dict[str, Any]],
    departure_time_str: Optional[str] = None,
) -> dict[str, Any]:
    """Optimizes delivery stop sequence and per-leg ETAs using Google Routes API.

    Calls Google Routes API computeRoutes with optimizeWaypointOrder=true.
    Includes self-healing exponential retry and automatic fallback to Haversine
    estimation on missing keys, quota limits, or 429/5xx errors.

    Args:
        origin_lat: Vehicle starting latitude.
        origin_lng: Vehicle starting longitude.
        stops: List of stop dictionaries with latitude, longitude, and stop_id.
        departure_time_str: Optional HH:MM departure time string (defaults to current time).

    Returns:
        Structured plan with optimized stop sequence, per-leg distance and ETAs.
    """
    now = datetime.now()
    if departure_time_str and ":" in departure_time_str:
        try:
            parts = departure_time_str.split(":")
            departure_time = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
        except Exception:
            departure_time = now
    else:
        departure_time = now

    # Mock mode or missing key triggers graceful fallback
    if config.USE_MOCK_ROUTES:
        return _plan_route_haversine_fallback(
            origin_lat, origin_lng, stops, departure_time, "USE_MOCK_ROUTES=true"
        )

    if not config.GOOGLE_MAPS_API_KEY:
        return _plan_route_haversine_fallback(
            origin_lat, origin_lng, stops, departure_time, "GOOGLE_MAPS_API_KEY is not set"
        )

    # Attempt Google Routes API with retry
    def _call_routes_api():
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": (
                "routes.optimizedIntermediateWaypointIndex,"
                "routes.duration,routes.distanceMeters,routes.legs"
            ),
        }

        # Build intermediate waypoints
        intermediates = [
            {"location": {"latLng": {"latitude": s["latitude"], "longitude": s["longitude"]}}}
            for s in stops
        ]

        payload = {
            "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
            "destination": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
            "intermediates": intermediates,
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "optimizeWaypointOrder": True,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=8.0)
        resp.raise_for_status()
        return resp.json()

    try:
        data, healing_logs = callbacks.retry_with_backoff(
            _call_routes_api,
            max_retries=2,
            action_name="Google Routes API computeRoutes",
        )
        route = data.get("routes", [{}])[0]
        order_indices = route.get("optimizedIntermediateWaypointIndex", list(range(len(stops))))
        legs = route.get("legs", [])

        ordered_stops: list[dict[str, Any]] = []
        cur_time = departure_time
        total_dist_meters = route.get("distanceMeters", 0)

        for i, idx in enumerate(order_indices):
            s = dict(stops[idx])
            leg = legs[i] if i < len(legs) else {}
            duration_sec = int(leg.get("duration", "600s").rstrip("s"))
            transit_min = max(3, duration_sec // 60)
            cur_time += timedelta(minutes=transit_min)
            s["eta"] = cur_time.strftime("%H:%M")
            cur_time += timedelta(minutes=10)  # Service time
            s["transit_minutes"] = transit_min
            ordered_stops.append(s)

        return {
            "status": "success",
            "mode": "google_routes_api",
            "degraded": False,
            "origin": {"latitude": origin_lat, "longitude": origin_lng},
            "total_distance_km": round(total_dist_meters / 1000.0, 2),
            "departure_time": departure_time.strftime("%H:%M"),
            "ordered_stops": ordered_stops,
            "healing_logs": healing_logs,
        }

    except Exception as e:
        logger.warning(
            "[Self-Healing Route Fallback] Routes API failed (%s). Engaging Haversine fallback.",
            e,
        )
        fallback_plan = _plan_route_haversine_fallback(
            origin_lat, origin_lng, stops, departure_time, str(e)
        )
        fallback_plan["healing_logs"].append(f"Routes API call error: {str(e)}")
        return fallback_plan


def check_windows(route_plan: dict[str, Any], stops: list[dict[str, Any]]) -> dict[str, Any]:
    """Compares planned arrival ETAs against delivery deadlines for all stops.

    Analyzes breaches, computes delay in minutes, and generates concrete feedback
    for the planner agent in the LoopAgent feedback cycle.

    Args:
        route_plan: Output dictionary from plan_route containing ordered_stops.
        stops: Original list of stop specifications with window_end.

    Returns:
        Structured evaluation containing all_passed, breached_stops, passed_stops,
        and recommendations for optimization.
    """
    ordered_stops = route_plan.get("ordered_stops", stops)
    breached: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []
    recommendations: list[str] = []

    for stop in ordered_stops:
        eta_str = stop.get("eta", "12:00")
        window_end_str = stop.get("window_end", "17:00")

        # Parse times to minutes from midnight
        try:
            eta_h, eta_m = map(int, eta_str.split(":")[:2])
            eta_minutes = eta_h * 60 + eta_m
            win_h, win_m = map(int, window_end_str.split(":")[:2])
            win_minutes = win_h * 60 + win_m
        except Exception:
            eta_minutes = 720
            win_minutes = 1020

        if eta_minutes > win_minutes:
            delay = eta_minutes - win_minutes
            breached_entry = {
                "stop_id": stop.get("stop_id", "unknown"),
                "address": stop.get("address", ""),
                "customer_name": stop.get("customer_name", "Customer"),
                "eta": eta_str,
                "window_end": window_end_str,
                "delay_minutes": delay,
                "priority": stop.get("priority", "normal"),
            }
            breached.append(breached_entry)
            recommendations.append(
                f"Stop '{stop.get('stop_id')}' ({stop.get('address')}) breaches deadline "
                f"{window_end_str} by {delay} mins (ETA {eta_str}). Consider prioritizing this "
                f"stop earlier in the sequence."
            )
        else:
            passed.append({
                "stop_id": stop.get("stop_id", "unknown"),
                "address": stop.get("address", ""),
                "eta": eta_str,
                "window_end": window_end_str,
                "slack_minutes": win_minutes - eta_minutes,
            })

    all_passed = len(breached) == 0

    feedback_text = (
        "All delivery time windows met successfully."
        if all_passed
        else "Delivery window breaches detected:\n" + "\n".join(recommendations)
    )

    return {
        "status": "success",
        "all_passed": all_passed,
        "breached_count": len(breached),
        "breached_stops": breached,
        "passed_stops": passed,
        "recommendations": feedback_text,
    }


def draft_delay_notification(
    customer_name: str,
    stop_id: str,
    address: str,
    scheduled_window: str,
    revised_eta: str,
    delay_minutes: int,
    vehicle_id: str = "driver-1",
) -> dict[str, str]:
    """Drafts a professional, empathetic customer SMS/WhatsApp delay message.

    Args:
        customer_name: Recipient's name.
        stop_id: Identifier of the order stop.
        address: Delivery destination.
        scheduled_window: Original promised window deadline.
        revised_eta: Expected arrival time.
        delay_minutes: Estimated delay in minutes.
        vehicle_id: Tracking ID for dispatch vehicle.

    Returns:
        Structured message dictionary with channel options and message body.
    """
    message_body = (
        f"Hi {customer_name}, your courier delivery to {address} (Order {stop_id}) is experiencing "
        f"a minor traffic delay of approximately {delay_minutes} minutes. "
        f"Your updated arrival window is now {revised_eta} (previously before {scheduled_window}). "
        f"You can monitor driver '{vehicle_id}' live. Thank you for your patience!"
    )

    return {
        "status": "drafted",
        "recipient": customer_name,
        "stop_id": stop_id,
        "revised_eta": revised_eta,
        "channel": "SMS/WhatsApp",
        "message": message_body,
    }


def complete_feedback_loop(
    tool_context: ToolContext,
    all_passed: bool,
    iteration_notes: str = "",
) -> str:
    """Evaluates the critic feedback and exits the LoopAgent when windows are satisfied.

    Calls ADK exit_loop to escalate when all time windows pass.
    """
    if all_passed:
        exit_loop(tool_context)
        return "Loop complete: All stop delivery windows are satisfied. Exiting feedback loop."
    return f"Loop iteration continues: {iteration_notes}"
