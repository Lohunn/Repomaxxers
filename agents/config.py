"""Configuration management and demo-safe flags for Logistics Dispatch Agents."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from current directory or parent directory
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / ".env")
load_dotenv(Path.cwd() / ".env")

# Demo-safe flags
USE_MOCK_ROUTES: bool = os.getenv("USE_MOCK_ROUTES", "false").lower() in ("true", "1", "yes")
USE_LOCAL_STORE: bool = os.getenv("USE_LOCAL_STORE", "false").lower() in ("true", "1", "yes")
FORCE_ROUTES_FAILURE: bool = os.getenv("FORCE_ROUTES_FAILURE", "false").lower() in ("true", "1", "yes")

# API Keys & Cloud Configuration
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_GENAI_USE_VERTEXAI: str = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
TRACKER_TOKEN: str = os.getenv("TRACKER_TOKEN", "dispatch-secret-token-123")
GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# Operational defaults
DEFAULT_VEHICLE_ID: str = os.getenv("DEFAULT_VEHICLE_ID", "driver-1")
LOCAL_STORE_FILE: Path = base_dir / ".local_store.json"

# Ensure environment flags are exported for sub-processes/SDK
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = GOOGLE_GENAI_USE_VERTEXAI
if GOOGLE_API_KEY and "GOOGLE_API_KEY" not in os.environ:
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY


def validate_environment(check_routes: bool = True, check_firestore: bool = True) -> list[str]:
    """Validates required credentials based on active operational mode.

    Returns a list of clear warning messages for any missing credentials.
    Part of the self-healing and defensive configuration system.
    """
    warnings: list[str] = []

    if not GOOGLE_API_KEY:
        warnings.append(
            "Missing environment variable 'GOOGLE_API_KEY'. Required for Gemini LLM agents. "
            "Set it in .env or via your shell."
        )

    if check_routes and not USE_MOCK_ROUTES and not GOOGLE_MAPS_API_KEY:
        warnings.append(
            "Missing environment variable 'GOOGLE_MAPS_API_KEY' while USE_MOCK_ROUTES is false. "
            "Self-healing will automatically degrade to Haversine route estimation."
        )

    if check_firestore and not USE_LOCAL_STORE and not GOOGLE_CLOUD_PROJECT:
        warnings.append(
            "Missing environment variable 'GOOGLE_CLOUD_PROJECT' while USE_LOCAL_STORE is false. "
            "Firestore requires a project ID or application default credentials."
        )

    return warnings
