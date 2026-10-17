"""Real reports from Hurricane Helene for the demo queue: NWS Local Storm Reports (public domain).

During Helene the NWS Greenville-Spartanburg office logged reports from 911 centers, emergency
managers, amateur radio and the public. The Iowa Environmental Mesonet archives them:
https://mesonet.agron.iastate.edu/lsr/  (this script uses its GeoJSON endpoint).

    python sync/fetch_helene_reports.py      # writes data/helene_lsr.jsonl

The report text is the NWS remark word for word (typos included), plus the location the NWS
logged with it. A few reports are left out: gauge readings and county-wide summaries with no
place to send anyone. The console loads these on Reset demo on the channel "nws-helene",
so real reports are told apart from the sample ones.
"""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from stormdesk.config import COUNTIES  # noqa: E402

URL = "https://mesonet.agron.iastate.edu/geojson/lsr.php"
PARAMS = {"sts": "202409251200", "ets": "202410010000", "wfos": "GSP"}  # Helene, NWS Greenville-Spartanburg
SKIP = ("Gauge reading", "many trees down across the county", "Numerous roads flooded around the county",
        "Reports are for", "Light damage to barn roofs")  # no actionable place or need
OUT = ROOT / "data" / "helene_lsr.jsonl"


def main():
    feats = requests.get(URL, params=PARAMS, timeout=60).json()["features"]
    rows = []
    for f in feats:
        p = f["properties"]
        if p.get("state") != "NC" or p.get("county") not in COUNTIES:
            continue
        remark = (p.get("remark") or "").strip()
        if not remark or any(s.lower() in remark.lower() for s in SKIP):
            continue
        lon, lat = f["geometry"]["coordinates"]
        rows.append({"text": f"{remark} ({p['city']}, {p['county']} County)", "channel": "nws-helene",
                     "valid": p["valid"], "type": p["typetext"], "source": p["source"],
                     "lat": lat, "lon": lon, "ref": "NWS Local Storm Report via Iowa Environmental Mesonet"})
    rows.sort(key=lambda r: r["valid"])
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} Helene storm reports to {OUT}")


if __name__ == "__main__":
    main()
