"""Diagnostic script to verify real keys and service connectivity."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / ".env")

def mask_key(k: str) -> str:
    if not k:
        return "<not set>"
    if len(k) <= 4:
        return "****"
    return "*" * (len(k) - 4) + k[-4:]

def check_gemini():
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return {"status": "FAIL", "reason": "GOOGLE_API_KEY is not set in environment."}
    
    # 1. Test google.genai SDK
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
        # Test listing models
        models = []
        try:
            for m in client.models.list():
                m_name = getattr(m, "name", str(m))
                if "gemini" in m_name.lower():
                    models.append(m_name)
        except Exception as e:
            list_err = str(e)
        else:
            list_err = None

        # Test generation with gemini-3.6-flash (current supported model for this key)
        test_models = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.7-flash"]
        successful_model = None
        gen_response = None
        err_msg = ""
        
        for mod in test_models:
            try:
                resp = client.models.generate_content(
                    model=mod,
                    contents="Reply with 'OK'",
                )
                if resp and resp.text:
                    successful_model = mod
                    gen_response = resp.text.strip()
                    break
            except Exception as ex:
                err_msg = str(ex)
                
        if successful_model:
            return {
                "status": "PASS",
                "model_used": successful_model,
                "response": gen_response,
                "available_gemini_models": models[:10] if models else ["(list call failed: " + str(list_err) + ")"],
                "masked_key": mask_key(api_key),
            }
        else:
            return {
                "status": "FAIL",
                "reason": f"Generate content failed for test models: {err_msg}",
                "masked_key": mask_key(api_key),
            }
    except Exception as e:
        return {"status": "FAIL", "reason": f"Client initialization error: {e}", "masked_key": mask_key(api_key)}

def check_routes_api():
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"status": "FAIL", "reason": "GOOGLE_MAPS_API_KEY is not set."}
    
    import requests
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.legs",
    }
    # Two points in Chennai: Central Hub to Adyar
    payload = {
        "origin": {"location": {"latLng": {"latitude": 13.0827, "longitude": 80.2707}}},
        "destination": {"location": {"latLng": {"latitude": 13.0012, "longitude": 80.2565}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            route = data.get("routes", [{}])[0]
            dist = route.get("distanceMeters", 0)
            dur = route.get("duration", "unknown")
            return {
                "status": "PASS",
                "distance_meters": dist,
                "duration": dur,
                "masked_key": mask_key(api_key),
            }
        else:
            return {
                "status": "FAIL",
                "status_code": resp.status_code,
                "reason": resp.text,
                "masked_key": mask_key(api_key),
            }
    except Exception as e:
        return {"status": "FAIL", "reason": str(e), "masked_key": mask_key(api_key)}

def check_store():
    use_local = os.getenv("USE_LOCAL_STORE", "false").lower() in ("true", "1", "yes")
    if use_local:
        return {
            "status": "PASS",
            "backend": "local_store",
            "reason": "USE_LOCAL_STORE=true is configured. Using atomic JSON persistence (.local_store.json).",
        }
    
    # Try Firestore test write
    try:
        from google.cloud import firestore
        project = os.getenv("GOOGLE_CLOUD_PROJECT", None)
        db = firestore.Client(project=project)
        doc_ref = db.collection("_diagnostics").document("healthcheck")
        doc_ref.set({"status": "healthy", "timestamp": firestore.SERVER_TIMESTAMP})
        return {
            "status": "PASS",
            "backend": "firestore",
            "reason": "Firestore connected and test write succeeded.",
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "backend": "firestore_error",
            "reason": f"Firestore connection failed: {e}. Fallback to local store recommended.",
        }

def check_mcp_server():
    import asyncio
    from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams, StdioServerParameters
    
    async def _test():
        toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "agents.mcp_server"]
                ),
                timeout=15.0,
            )
        )
        try:
            tools = await toolset.get_tools()
            tool_names = [t.name for t in tools]
            await toolset.close()
            return {
                "status": "PASS",
                "tools": tool_names,
                "count": len(tool_names),
            }
        except Exception as e:
            await toolset.close()
            return {"status": "FAIL", "reason": str(e)}

    return asyncio.run(_test())

def run_diagnostics():
    print("=" * 60)
    print("LOGISTICS DISPATCH AGENTS - SYSTEM DIAGNOSTICS")
    print("=" * 60)
    
    gemini = check_gemini()
    print(f"[Gemini API]     : {gemini['status']}")
    if gemini['status'] == 'PASS':
        print(f"  Model Used    : {gemini.get('model_used')}")
        print(f"  Response      : {gemini.get('response')}")
        print(f"  Models Sample : {gemini.get('available_gemini_models')[:4]}")
    else:
        print(f"  Reason        : {gemini.get('reason')}")
    print(f"  Masked Key    : {gemini.get('masked_key')}")
    print("-" * 60)
    
    routes = check_routes_api()
    print(f"[Routes API]     : {routes['status']}")
    if routes['status'] == 'PASS':
        print(f"  Distance (m)  : {routes.get('distance_meters')}")
        print(f"  Duration      : {routes.get('duration')}")
    else:
        print(f"  Reason        : {routes.get('reason')}")
    print(f"  Masked Key    : {routes.get('masked_key')}")
    print("-" * 60)
    
    store = check_store()
    print(f"[Store Backend]  : {store['status']} ({store.get('backend')})")
    print(f"  Details       : {store.get('reason')}")
    print("-" * 60)
    
    mcp = check_mcp_server()
    print(f"[MCP Server]     : {mcp['status']}")
    if mcp['status'] == 'PASS':
        print(f"  Exposed Tools : {mcp.get('tools')}")
    else:
        print(f"  Reason        : {mcp.get('reason')}")
    print("=" * 60)
    
    return {
        "gemini": gemini,
        "routes": routes,
        "store": store,
        "mcp": mcp,
    }

if __name__ == "__main__":
    run_diagnostics()
