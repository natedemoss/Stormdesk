import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(env: str, default: str) -> Path:
    p = Path(os.getenv(env, default))
    return p if p.is_absolute() else ROOT / p


AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://localhost:8000/v1")
AGENT_MODEL = os.getenv("AGENT_MODEL", "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16")
TRIAGE_BASE_URL = os.getenv("TRIAGE_BASE_URL", "http://localhost:8001/v1")
TRIAGE_MODEL = os.getenv("TRIAGE_MODEL", "stormdesk-triage")
MOCK_LLM = os.getenv("STORMDESK_MOCK_LLM", "0") == "1"
# Lightning double-checks every incoming report for risk to life (stormdesk/triage.py). On by default.
SECOND_OPINION = os.getenv("STORMDESK_SECOND_OPINION", "1") == "1"
SECOND_OPINION_TIMEOUT = float(os.getenv("STORMDESK_SECOND_OPINION_TIMEOUT", "20"))

DB_PATH = _path("STORMDESK_DB", "data/stormdesk.db")
ROAD_GRAPH = _path("ROAD_GRAPH", "data/cache/road_graph.graphml")
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
try:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:  # read-only inside the OpenShell sandbox; sync runs outside it
    pass

# Set in the sandbox image. Enables the red-team checks and the audit-log panel.
IN_SANDBOX = os.getenv("STORMDESK_SANDBOX", "0") == "1"
OCSF_LOG_GLOB = os.getenv("OPENSHELL_OCSF_GLOB", "/var/log/openshell-ocsf.*.log")

NWS_USER_AGENT = os.getenv("NWS_USER_AGENT", "StormDesk hackathon")

# Counties the sync scripts cache (roads, places, shelters, closures). Default: McDowell and
# the neighbors Hurricane Helene hit hardest. Override with STORMDESK_COUNTIES=McDowell,Burke
COUNTIES = [c.strip() for c in os.getenv(
    "STORMDESK_COUNTIES", "McDowell,Buncombe,Yancey,Mitchell,Burke,Rutherford").split(",") if c.strip()]
# Each county's staging point is its county seat, looked up in the gazetteer (OSM coordinates).
COUNTY_SEATS = {"McDowell": "Marion", "Buncombe": "Asheville", "Yancey": "Burnsville",
                "Mitchell": "Bakersville", "Burke": "Morganton", "Rutherford": "Rutherfordton"}


def osm_county(county: str) -> str:
    """'Burke' -> 'Burke County, North Carolina', the form OSM place lookups expect."""
    return f"{county} County, North Carolina"

MAX_AGENT_STEPS = 16  # a normal run uses 6-7 calls; leaves room for guard corrections and retries
