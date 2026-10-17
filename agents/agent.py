"""Logistics Dispatch Agents definition.

Implements:
- Multi-model agents (Gemini + LiteLlm)
- Conversation agent (dispatcher root)
- API calls (Google Routes API, Firestore, MCP)
- MCP integration via McpToolset over stdio
- Feedback loop with LoopAgent (planner <-> critic)
- Self-healing callbacks and error recovery
"""

import logging
import os
import sys
from google.adk.agents import LlmAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import exit_loop
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)

from agents import callbacks, config, tools

logger = logging.getLogger("LogisticsAgents")

# Primary Gemini model used for Dispatcher, Intake, Planner, and Notifier
PRIMARY_GEMINI_MODEL = "gemini-3.6-flash"

# Ensure LiteLlm can authenticate with Gemini if no second provider key is set
if config.GOOGLE_API_KEY and "GEMINI_API_KEY" not in os.environ:
    os.environ["GEMINI_API_KEY"] = config.GOOGLE_API_KEY

# Multi-Model selection for Critic Agent via LiteLlm wrapper
if config.OPENAI_API_KEY:
    CRITIC_MODEL = LiteLlm(model="openai/gpt-4o-mini")
    logger.info("[CriticAgent Multi-Model] Configured with OpenAI model family via LiteLlm: openai/gpt-4o-mini")
else:
    CRITIC_MODEL = LiteLlm(model="gemini/gemini-3.6-flash")
    logger.info(
        "[CriticAgent Multi-Model] No second provider key (OPENAI_API_KEY) found. "
        "Falling back to Gemini variant via LiteLlm: gemini/gemini-3.6-flash"
    )

# MCP Toolset connecting to our stdio MCP Server (agents/mcp_server.py)
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "agents.mcp_server"],
        ),
        timeout=15.0,
    )
)

# ---------------------------------------------------------
# Agent 2: Intake Agent (Gemini)
# Parses unstructured messy dispatch orders into validated JSON stops
# ---------------------------------------------------------
intake_agent = LlmAgent(
    name="intake_agent",
    model=PRIMARY_GEMINI_MODEL,
    description="Parses unstructured or messy customer order text into validated structured stops.",
    instruction=(
        "You are an expert logistics order intake specialist. "
        "Your task is to take raw, messy order descriptions from the user or dispatcher "
        "and extract structured delivery stops. "
        "Always call the `parse_orders` tool with the text. "
        "Verify each stop has an address, time window (default 09:00 - 17:00 if not specified), "
        "package count, and special instructions. "
        "Summarize the parsed orders clearly."
    ),
    tools=[tools.parse_orders],
    output_key="parsed_orders",
    before_model_callback=callbacks.before_model_callback,
    before_tool_callback=callbacks.before_tool_callback,
    after_tool_callback=callbacks.after_tool_callback,
    on_tool_error_callback=callbacks.on_tool_error_callback,
)

# ---------------------------------------------------------
# Agent 3: Planner Agent (Gemini)
# Computes optimal route sequence and per-leg ETAs
# ---------------------------------------------------------
planner_agent = LlmAgent(
    name="planner_agent",
    model=PRIMARY_GEMINI_MODEL,
    description="Optimizes vehicle routing, stop sequence, and per-leg arrival ETAs.",
    instruction=(
        "You are an automated route planner. "
        "First check if there is existing `critic_feedback` in the session state. "
        "If the critic previously pointed out delivery window breaches or suggested reordering, "
        "adjust the route or note the timing adjustments. "
        "Obtain the vehicle's starting position using `get_vehicle`. "
        "Then call `plan_route` with the origin coordinates and the list of delivery stops. "
        "Provide a clear summary of the route order, total distance, and ETA for each stop."
    ),
    tools=[
        mcp_toolset,
    ],
    output_key="route_plan",
    before_model_callback=callbacks.before_model_callback,
    before_tool_callback=callbacks.before_tool_callback,
    after_tool_callback=callbacks.after_tool_callback,
    on_tool_error_callback=callbacks.on_tool_error_callback,
)

# ---------------------------------------------------------
# Agent 4: Critic Agent (Multi-Model via LiteLlm)
# Cross-verifies delivery deadlines and controls loop escalation
# ---------------------------------------------------------
critic_agent = LlmAgent(
    name="critic_agent",
    model=CRITIC_MODEL,
    description="Audits the planned route against customer delivery windows and controls loop exit.",
    instruction=(
        "You are the Route Auditor and Critic running on an independent model family. "
        "Your job is to strictly check the route plan against customer time windows. "
        "Call the `check_windows` tool with the latest route plan and stops. "
        "1. If all stops meet their delivery deadlines (all_passed is True), call `complete_feedback_loop` "
        "   with all_passed=True to exit the optimization loop immediately. "
        "2. If any stop breaches its window deadline (ETA exceeds window_end), formulate concrete, "
        "   actionable recommendations for the planner (e.g., 'Move Stop 2 before Stop 1 to avoid a 30m breach'). "
        "   Store this feedback so the planner can refine the plan in the next iteration. "
        "Always state clearly whether windows were satisfied or breached."
    ),
    tools=[
        mcp_toolset,
        tools.complete_feedback_loop,
        exit_loop,
    ],
    output_key="critic_feedback",
    before_model_callback=callbacks.before_model_callback,
    before_tool_callback=callbacks.before_tool_callback,
    after_tool_callback=callbacks.after_tool_callback,
    on_tool_error_callback=callbacks.on_tool_error_callback,
)

# ---------------------------------------------------------
# Feedback Loop: LoopAgent (Planner <-> Critic)
# Iterates up to 3 times or exits early when windows pass
# ---------------------------------------------------------
route_optimizer_loop = LoopAgent(
    name="route_optimizer_loop",
    description="Iterative optimization loop between Planner and Critic to ensure all delivery windows pass.",
    sub_agents=[planner_agent, critic_agent],
    max_iterations=3,
)

# ---------------------------------------------------------
# Agent 5: Notifier Agent (Gemini)
# Drafts customer delay notifications for breached stops
# ---------------------------------------------------------
notifier_agent = LlmAgent(
    name="notifier_agent",
    model=PRIMARY_GEMINI_MODEL,
    description="Drafts professional customer delay notifications when delivery windows cannot be met.",
    instruction=(
        "You are a customer communications specialist. "
        "Review the audit results from the critic or planner. "
        "For any delivery stops that are delayed or breached their promised window, "
        "call `draft_delay_notification` to generate a polite, clear SMS/WhatsApp notification "
        "with the revised ETA and driver tracking information."
    ),
    tools=[tools.draft_delay_notification],
    output_key="delay_notifications",
    before_tool_callback=callbacks.before_tool_callback,
    after_tool_callback=callbacks.after_tool_callback,
    on_tool_error_callback=callbacks.on_tool_error_callback,
)

# ---------------------------------------------------------
# Agent 1: Root Dispatcher (Conversation Agent)
# ---------------------------------------------------------
dispatcher = LlmAgent(
    name="dispatcher",
    model=PRIMARY_GEMINI_MODEL,
    description="Main conversational logistics dispatch assistant. Coordinates tracking, intake, routing, and alerts.",
    instruction=(
        "You are the lead Logistics Dispatch Assistant for autonomous and driver-assisted delivery operations. "
        "You converse naturally with human dispatchers and fleet managers. "
        "\nYour capabilities:"
        "\n1. Live Tracking: Answer questions like 'Where is driver-1?' or 'What is the current vehicle status?' "
        "   by calling `get_vehicle`. "
        "\n2. Order Intake & Routing: When messy delivery orders are submitted (e.g. 'deliver 2 boxes to Adyar before 2, call first'), "
        "   delegate to `intake_agent` to structure them, then execute the `route_optimizer_loop` to plan and verify the route. "
        "\n3. Delay Alerts: If the optimization loop concludes with breached stops, invoke `notifier_agent` to draft delay messages. "
        "\n4. Self-Healing Transparency: If degraded mode (e.g. Haversine route estimation or local storage) is active, "
        "   clearly inform the dispatcher of the fallback mechanism. "
        "\nAlways respond with professional, actionable dispatch information."
    ),
    tools=[
        mcp_toolset,
        tools.parse_orders,
        tools.draft_delay_notification,
    ],
    sub_agents=[
        intake_agent,
        route_optimizer_loop,
        notifier_agent,
    ],
    before_model_callback=callbacks.before_model_callback,
    before_tool_callback=callbacks.before_tool_callback,
    after_tool_callback=callbacks.after_tool_callback,
    on_tool_error_callback=callbacks.on_tool_error_callback,
)

# ADK CLI expects root_agent exposed at the module level
root_agent = dispatcher
