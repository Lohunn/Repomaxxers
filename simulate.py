"""Fake Driver Telemetry Simulator.

Simulates a driver traversing an urban delivery route, posting periodic GPS
telemetry to the /location endpoint using Simulator, Traccar, or OwnTracks formats.
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Simulator] %(message)s")
logger = logging.getLogger("DriverSimulator")

# Realistic urban delivery waypoints (Chennai metropolitan delivery corridor)
ROUTE_WAYPOINTS = [
    {"name": "Central Hub", "lat": 13.0827, "lon": 80.2707, "speed": 35.0, "heading": 190.0},
    {"name": "Anna Salai Junction", "lat": 13.0600, "lon": 80.2500, "speed": 40.0, "heading": 205.0},
    {"name": "T. Nagar Commercial Hub", "lat": 13.0418, "lon": 80.2341, "speed": 22.0, "heading": 180.0},
    {"name": "Guindy Industrial Estate", "lat": 13.0067, "lon": 80.2021, "speed": 45.0, "heading": 135.0},
    {"name": "Adyar Delivery Zone", "lat": 13.0012, "lon": 80.2565, "speed": 28.0, "heading": 90.0},
    {"name": "OMR Tech Corridor", "lat": 12.9150, "lon": 80.2280, "speed": 50.0, "heading": 175.0},
]


def interpolate_points(waypoints: list[dict], steps_per_leg: int = 5) -> list[dict]:
    """Generates smooth interpolated intermediate GPS coordinates between waypoints."""
    points = []
    for i in range(len(waypoints) - 1):
        w1 = waypoints[i]
        w2 = waypoints[i + 1]
        for step in range(steps_per_leg):
            t = step / float(steps_per_leg)
            lat = w1["lat"] + (w2["lat"] - w1["lat"]) * t
            lon = w1["lon"] + (w2["lon"] - w1["lon"]) * t
            speed = w1["speed"] + (w2["speed"] - w1["speed"]) * t
            points.append({
                "name": f"{w1['name']} -> {w2['name']} (step {step+1}/{steps_per_leg})",
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "speed": round(speed, 1),
                "heading": w1["heading"],
            })
    points.append(waypoints[-1])
    return points


def send_location_ping(
    url: str,
    device_id: str,
    point: dict,
    fmt: str = "simulator",
    token: str = "dispatch-secret-token-123",
) -> tuple[int, str]:
    """Sends a single GPS coordinate ping in the chosen protocol format."""
    now_iso = datetime.now(timezone.utc).isoformat()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    if fmt == "owntracks":
        payload = {
            "_type": "location",
            "tid": device_id,
            "topic": f"owntracks/dispatch/{device_id}",
            "lat": point["lat"],
            "lon": point["lon"],
            "vel": int(point["speed"]),
            "cog": int(point["heading"]),
            "tst": int(time.time()),
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        return resp.status_code, resp.text

    elif fmt == "traccar":
        params = {
            "id": device_id,
            "lat": point["lat"],
            "lon": point["lon"],
            "speed": point["speed"],
            "bearing": point["heading"],
            "timestamp": now_iso,
        }
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        return resp.status_code, resp.text

    else:  # standard simulator JSON
        payload = {
            "device_id": device_id,
            "latitude": point["lat"],
            "longitude": point["lon"],
            "speed": point["speed"],
            "heading": point["heading"],
            "timestamp": now_iso,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        return resp.status_code, resp.text


def main():
    parser = argparse.ArgumentParser(description="Simulate driver movement and send telemetry.")
    parser.add_argument("--url", default="http://127.0.0.1:8080/location", help="Telemetry endpoint URL")
    parser.add_argument("--device", default="driver-1", help="Vehicle device ID")
    parser.add_argument("--interval", type=float, default=1.0, help="Interval in seconds between pings")
    parser.add_argument("--steps", type=int, default=15, help="Number of steps to simulate (0 for loop)")
    parser.add_argument("--format", choices=["simulator", "owntracks", "traccar"], default="simulator")
    parser.add_argument("--token", default="dispatch-secret-token-123", help="Bearer auth token")
    args = parser.parse_args()

    points = interpolate_points(ROUTE_WAYPOINTS, steps_per_leg=4)
    total_points = len(points)
    count = min(args.steps, total_points) if args.steps > 0 else total_points

    logger.info("Starting driver simulation for '%s' (%s format)", args.device, args.format)
    logger.info("Target endpoint: %s | Pinging %d locations...", args.url, count)

    for i in range(count):
        pt = points[i % total_points]
        try:
            status, text = send_location_ping(
                url=args.url,
                device_id=args.device,
                point=pt,
                fmt=args.format,
                token=args.token,
            )
            logger.info(
                "[%d/%d] %s -> lat=%.5f, lon=%.5f, speed=%.1f km/h | HTTP %d",
                i + 1,
                count,
                pt.get("name", "Waypoint"),
                pt["lat"],
                pt["lon"],
                pt["speed"],
                status,
            )
        except Exception as e:
            logger.error("[%d/%d] Ping failed to %s: %s", i + 1, count, args.url, e)

        if i < count - 1:
            time.sleep(args.interval)

    logger.info("Simulation completed for vehicle '%s'.", args.device)


if __name__ == "__main__":
    main()
