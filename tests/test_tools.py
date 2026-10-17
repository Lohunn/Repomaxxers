"""Unit tests for dispatch tools: order parsing, routing, window auditing, and messaging."""

from unittest.mock import MagicMock
import pytest
from google.adk.tools import ToolContext
from agents import config, tools


def test_parse_orders_structured():
    """Verifies that messy order text is parsed into structured StopItem models."""
    sample_text = (
        "Deliver 2 boxes to Adyar before 2, call first. "
        "Also drop off parcels at Guindy before 5 urgent."
    )
    result = tools.parse_orders(sample_text)
    assert result["status"] == "success"
    assert result["stop_count"] >= 2
    stops = result["stops"]

    # Verify Adyar stop
    adyar = next(s for s in stops if "Adyar" in s["address"])
    assert adyar["window_end"] == "14:00"
    assert adyar["package_count"] == 2
    assert "Call" in adyar["notes"] or "call" in adyar["notes"]

    # Verify Guindy stop
    guindy = next(s for s in stops if "Guindy" in s["address"])
    assert guindy["window_end"] == "17:00"
    assert guindy["priority"] == "high"


def test_get_vehicle_fallback_and_retrieval():
    """Verifies vehicle retrieval and default hub fallback."""
    config.USE_LOCAL_STORE = True
    # Test fallback for unknown vehicle
    res = tools.get_vehicle("non-existent-vehicle-999")
    assert res["device_id"] == "non-existent-vehicle-999"
    assert res["status"] == "default_origin_hub"
    assert res["latitude"] == tools.DEFAULT_HUB["latitude"]


def test_plan_route_haversine_fallback():
    """Verifies route planning and ETA generation in fallback mode."""
    config.USE_MOCK_ROUTES = True
    stops = [
        {"stop_id": "stop-1", "address": "Adyar, Chennai", "latitude": 13.0012, "longitude": 80.2565, "window_end": "14:00"},
        {"stop_id": "stop-2", "address": "Guindy, Chennai", "latitude": 13.0067, "longitude": 80.2021, "window_end": "17:00"},
    ]
    origin_lat, origin_lng = 13.0827, 80.2707  # Central Hub

    plan = tools.plan_route(origin_lat, origin_lng, stops, departure_time_str="10:00")
    assert plan["status"] == "success"
    assert plan["mode"] == "degraded_estimate"
    assert plan["degraded"] is True
    assert plan["total_distance_km"] > 0
    assert len(plan["ordered_stops"]) == 2

    # Check ETAs are assigned
    for s in plan["ordered_stops"]:
        assert "eta" in s
        assert ":" in s["eta"]


def test_check_windows_passing():
    """Verifies window auditing when all stops arrive before window_end."""
    route_plan = {
        "ordered_stops": [
            {"stop_id": "stop-1", "address": "Adyar", "eta": "11:30", "window_end": "14:00"},
            {"stop_id": "stop-2", "address": "Guindy", "eta": "12:45", "window_end": "17:00"},
        ]
    }
    audit = tools.check_windows(route_plan, route_plan["ordered_stops"])
    assert audit["status"] == "success"
    assert audit["all_passed"] is True
    assert len(audit["breached_stops"]) == 0
    assert len(audit["passed_stops"]) == 2
    assert "successfully" in audit["recommendations"].lower()


def test_check_windows_breached():
    """Verifies window auditing and feedback generation when a stop breaches its deadline."""
    route_plan = {
        "ordered_stops": [
            {"stop_id": "stop-1", "address": "Guindy", "eta": "14:30", "window_end": "13:00"},
            {"stop_id": "stop-2", "address": "Adyar", "eta": "15:45", "window_end": "17:00"},
        ]
    }
    audit = tools.check_windows(route_plan, route_plan["ordered_stops"])
    assert audit["status"] == "success"
    assert audit["all_passed"] is False
    assert len(audit["breached_stops"]) == 1
    breached = audit["breached_stops"][0]
    assert breached["stop_id"] == "stop-1"
    assert breached["delay_minutes"] == 90
    assert "breaches deadline" in audit["recommendations"]


def test_draft_delay_notification():
    """Verifies drafting of customer delay notification."""
    notif = tools.draft_delay_notification(
        customer_name="Priya Sharma",
        stop_id="stop-1",
        address="Adyar, Chennai",
        scheduled_window="13:00",
        revised_eta="14:30",
        delay_minutes=90,
        vehicle_id="driver-1",
    )
    assert notif["status"] == "drafted"
    assert notif["recipient"] == "Priya Sharma"
    assert "90 minutes" in notif["message"]
    assert "14:30" in notif["message"]
    assert "driver-1" in notif["message"]


def test_complete_feedback_loop_escalates_on_pass():
    """Verifies that complete_feedback_loop escalates and exits the loop when all passed."""
    mock_ctx = MagicMock(spec=ToolContext)
    mock_ctx.actions = MagicMock()
    msg = tools.complete_feedback_loop(mock_ctx, all_passed=True)
    assert "Exiting feedback loop" in msg
    assert mock_ctx.actions.escalate is True
