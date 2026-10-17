"""Model Context Protocol (MCP) Server for Logistics Dispatch Tools.

Exposes core logistics tools over stdio transport using MCP SDK 2.x MCPServer.
"""

import json
import logging
import sys
from mcp.server.mcpserver import MCPServer
from agents import tools

# Set up logging to stderr so stdout is reserved for JSON-RPC MCP messages
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("LogisticsMCPServer")

server = MCPServer("LogisticsDispatchServer")


@server.tool()
def get_vehicle(vehicle_id: str = "driver-1") -> str:
    """Retrieves current GPS location, telemetry, and status for a dispatch vehicle.

    Args:
        vehicle_id: Vehicle device identifier (e.g. 'driver-1').
    """
    res = tools.get_vehicle(vehicle_id=vehicle_id)
    return json.dumps(res, indent=2)


@server.tool()
def plan_route(
    origin_lat: float,
    origin_lng: float,
    stops_json: str,
    departure_time_str: str = "",
) -> str:
    """Optimizes delivery stop sequence and ETAs using Google Routes API or fallback.

    Args:
        origin_lat: Vehicle starting latitude.
        origin_lng: Vehicle starting longitude.
        stops_json: JSON string representing list of stop objects with latitude, longitude, and stop_id.
        departure_time_str: Optional departure time string in HH:MM format.
    """
    try:
        stops = json.loads(stops_json) if isinstance(stops_json, str) else stops_json
    except Exception as e:
        return json.dumps({"status": "error", "error": f"Invalid stops_json: {e}"})

    res = tools.plan_route(
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        stops=stops,
        departure_time_str=departure_time_str or None,
    )
    return json.dumps(res, indent=2)


@server.tool()
def check_windows(route_plan_json: str, stops_json: str) -> str:
    """Verifies route arrival ETAs against delivery deadline time windows.

    Args:
        route_plan_json: JSON string representing output of plan_route.
        stops_json: JSON string representing original stops list.
    """
    try:
        plan = json.loads(route_plan_json) if isinstance(route_plan_json, str) else route_plan_json
        stops = json.loads(stops_json) if isinstance(stops_json, str) else stops_json
    except Exception as e:
        return json.dumps({"status": "error", "error": f"Invalid JSON inputs: {e}"})

    res = tools.check_windows(route_plan=plan, stops=stops)
    return json.dumps(res, indent=2)


def main():
    """Runs the MCP server over stdio transport."""
    logger.info("Starting Logistics Dispatch MCP Server (stdio)...")
    server.run("stdio")


if __name__ == "__main__":
    main()
