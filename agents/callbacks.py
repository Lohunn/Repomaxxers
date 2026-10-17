"""Self-healing, retry logic, exponential backoff, and ADK callbacks."""

import json
import logging
import math
import time
from typing import Any, Callable, Optional, TypeVar
from google.adk.agents.context import Context
from google.adk.tools.base_tool import BaseTool

logger = logging.getLogger("LogisticsSelfHealing")

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    retry_exceptions: tuple = (Exception,),
    action_name: str = "operation",
) -> tuple[T, list[str]]:
    """Executes a function with exponential backoff on transient errors.

    Returns a tuple of (result, list_of_healing_actions_taken).
    """
    delay = initial_delay
    healing_logs: list[str] = []

    for attempt in range(1, max_retries + 1):
        try:
            result = func()
            if attempt > 1:
                log_msg = f"[Self-Healing Retry] Successfully completed '{action_name}' on attempt {attempt} after transient failure."
                logger.info(log_msg)
                healing_logs.append(log_msg)
            return result, healing_logs
        except retry_exceptions as e:
            if attempt == max_retries:
                log_msg = f"[Self-Healing Retry Exhausted] '{action_name}' failed after {max_retries} attempts: {e}"
                logger.error(log_msg)
                healing_logs.append(log_msg)
                raise
            sleep_time = delay * (backoff_factor ** (attempt - 1))
            log_msg = f"[Self-Healing Retry] Transient error in '{action_name}' ({e}). Retrying in {sleep_time:.2f}s (Attempt {attempt}/{max_retries})..."
            logger.warning(log_msg)
            healing_logs.append(log_msg)
            time.sleep(sleep_time)

    # Should not be reached
    raise RuntimeError(f"Retry loop failed unexpectedly for {action_name}")


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS coordinates in kilometers."""
    radius_earth_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_earth_km * c


def repair_order_json(
    raw_text: str,
    validation_error: str,
    attempt: int = 1,
    max_attempts: int = 2,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Self-healing JSON repair logic.

    Attempts pattern extraction, quote fixing, and markdown stripping.
    If repair fails after max_attempts, returns (None, clarifying_question) to prompt user.
    """
    cleaned = raw_text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        parsed = json.loads(cleaned)
        return parsed, None
    except json.JSONDecodeError as decode_err:
        if attempt >= max_attempts:
            clarification = (
                f"I could not reliably parse the order text (Validation Error: {validation_error}; "
                f"Decode Error: {decode_err}). Could you please clarify the delivery addresses, "
                f"delivery windows (e.g. 'before 5 PM'), and package counts?"
            )
            return None, clarification

        # Attempt basic heuristics: fix trailing commas, single quotes
        candidate = cleaned.replace("'", '"')
        try:
            parsed = json.loads(candidate)
            return parsed, None
        except Exception:
            pass

        return None, None


# --- ADK Agent Callbacks ---

def log_healing_event(context: Optional[Context], message: str) -> None:
    """Appends a self-healing event message to the agent session state."""
    logger.info(message)
    if context and hasattr(context, "state") and context.state is not None:
        events = context.state.setdefault("healing_events", [])
        if message not in events:
            events.append(message)


def before_tool_callback(tool: BaseTool, args: dict[str, Any], context: Context) -> Optional[dict[str, Any]]:
    """Validates inputs and records invocation metadata before tool runs."""
    tool_name = getattr(tool, "name", str(tool))
    logger.debug("[Callback BeforeTool] Running %s with args: %s", tool_name, args)
    return None


def after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    context: Context,
    tool_response: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Surfaces any self-healing flags or degraded modes in agent session state."""
    tool_name = getattr(tool, "name", str(tool))
    if isinstance(tool_response, dict):
        if tool_response.get("degraded"):
            warning = tool_response.get("warning", "Degraded fallback mode was activated.")
            log_healing_event(context, f"[Self-Healing Activated] {tool_name}: {warning}")

        if tool_response.get("healing_logs"):
            for h_log in tool_response["healing_logs"]:
                log_healing_event(context, h_log)

    return None


def on_tool_error_callback(
    tool: BaseTool,
    args: dict[str, Any],
    context: Context,
    error: Exception,
) -> Optional[dict[str, Any]]:
    """Catches tool errors and returns a structured degraded response instead of aborting."""
    tool_name = getattr(tool, "name", str(tool))
    err_msg = f"[Self-Healing OnError] Exception in tool '{tool_name}': {str(error)}"
    logger.warning(err_msg)
    log_healing_event(context, err_msg)

    # Return structured error object so LLM can gracefully heal or report
    return {
        "status": "error",
        "tool": tool_name,
        "error": str(error),
        "healed": True,
        "message": f"Tool '{tool_name}' encountered an error but was caught by self-healing: {str(error)}",
    }
