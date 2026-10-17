"""Unit tests for self-healing: retries, Haversine distance, JSON repair, and callbacks."""

from unittest.mock import MagicMock
import pytest
from google.adk.agents.context import Context
from google.adk.tools.base_tool import BaseTool
from agents import callbacks


def test_retry_with_backoff_success_first_try():
    """Verifies that an operation succeeding on the first attempt does not retry."""
    call_count = 0

    def op():
        nonlocal call_count
        call_count += 1
        return "ok"

    res, logs = callbacks.retry_with_backoff(op, max_retries=3, initial_delay=0.01)
    assert res == "ok"
    assert call_count == 1
    assert len(logs) == 0


def test_retry_with_backoff_heals_after_transient_failure():
    """Verifies that a transient failure is healed on subsequent retry attempts."""
    call_count = 0

    def op():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("Transient network drop")
        return "healed_result"

    res, logs = callbacks.retry_with_backoff(
        op,
        max_retries=3,
        initial_delay=0.01,
        retry_exceptions=(ConnectionError,),
        action_name="test_op",
    )
    assert res == "healed_result"
    assert call_count == 2
    assert any("Transient error" in log for log in logs)
    assert any("Successfully completed" in log for log in logs)


def test_retry_with_backoff_exhaustion():
    """Verifies that retry_with_backoff raises when all attempts fail."""
    def op():
        raise TimeoutError("Persistent timeout")

    with pytest.raises(TimeoutError):
        callbacks.retry_with_backoff(
            op,
            max_retries=2,
            initial_delay=0.01,
            retry_exceptions=(TimeoutError,),
        )


def test_haversine_distance():
    """Verifies Haversine calculation against known geographical distance."""
    # Chennai Central (13.0827, 80.2707) to Adyar (13.0012, 80.2565) ~9.2 km
    dist = callbacks.haversine_distance_km(13.0827, 80.2707, 13.0012, 80.2565)
    assert 8.5 < dist < 10.5

    # Same point distance must be 0
    assert callbacks.haversine_distance_km(13.0827, 80.2707, 13.0827, 80.2707) == 0.0


def test_repair_order_json_markdown():
    """Verifies stripping of markdown code fences during JSON repair."""
    raw = "```json\n{\"address\": \"Adyar\", \"packages\": 2}\n```"
    parsed, clar = callbacks.repair_order_json(raw, "syntax error", attempt=1)
    assert parsed == {"address": "Adyar", "packages": 2}
    assert clar is None


def test_repair_order_json_exhausted_produces_clarification():
    """Verifies that unfixable JSON generates a clarifying question after max attempts."""
    raw = "completely unintelligible non-json text"
    parsed, clar = callbacks.repair_order_json(raw, "Invalid JSON format", attempt=2, max_attempts=2)
    assert parsed is None
    assert clar is not None
    assert "clarify" in clar.lower()


def test_on_tool_error_callback_heals():
    """Verifies that on_tool_error_callback captures the exception into a structured dict."""
    mock_tool = MagicMock(spec=BaseTool)
    mock_tool.name = "plan_route"
    mock_context = MagicMock(spec=Context)
    mock_context.state = {}

    err = ValueError("Invalid latitude parameter")
    result = callbacks.on_tool_error_callback(mock_tool, {}, mock_context, err)

    assert result["status"] == "error"
    assert result["healed"] is True
    assert result["tool"] == "plan_route"
    assert "healing_events" in mock_context.state
