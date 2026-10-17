# StormDesk

An offline disaster-response agent for North Carolina, built entirely on small open models.

When Hurricane Helene hit western NC in 2024, internet and cell service were down for days, so cloud AI was useless right when it mattered most. StormDesk runs on one local machine. It triages messy incoming reports, checks road closures, weather alerts and shelters through tool calls, and drafts dispatch plans that a human approves.

**Hackathon:** NVIDIA x Red Hat Small Models Hack (Raleigh)
**Track:** Tool-Calling, plus the Nemotron 3.5 Lightning and Red Hat vLLM bounties
**Model budget:** Nemotron 3.5 Lightning (30B-A3B) + triage model (~1.7B) = ~32B, under the 33B cap

## Architecture

```
Incoming reports (text / call transcript / social post)
        |
        v
Triage model (~1.7B, fine-tuned on HumAID)          vLLM :8001
   -> category, urgency 1-5, location text
        |
        v
Incident queue (sorted by urgency)
        |
        v
Lightning agent (tool calling)                      vLLM :8000
   tools: geocode_location   (offline gazetteer)
          get_road_closures  (cached NCDOT + reports from the public)
          plan_route         (offline OSM road graph)
          get_weather_alerts (cached NOAA)
          find_shelters      (local shelter list)
          report_closure     (adds a closure learned from a report)
          draft_dispatch     (writes to review queue, CANNOT send)
        |
        v
Human dispatcher: Approve / Edit / Reject          (web console)

Everything runs inside an NVIDIA OpenShell sandbox: network allow-list
only, no outbound messaging, every allow/deny logged.
```

## Repo layout

```
stormdesk/          core package
  config.py         ports, model names, paths (reads .env)
  db.py             SQLite cache: closures, alerts, incidents, dispatch queue
  triage.py         calls the triage model with a JSON schema
  agent.py          Lightning tool-calling loop + guard checks
  tool_schemas.py   OpenAI-style tool definitions
  tools/            one file per tool
sync/               scripts that refresh caches while internet is up
training/           HumAID prep, Unsloth LoRA fine-tune, triage eval
eval/               test incidents + agent benchmark
ui/server.py        dispatcher console (FastAPI + ui/static, fully offline)
scripts/            vLLM serve commands, demo report streamer
openshell/          policy notes for the sandbox
data/               sample shelters, gazetteer, demo reports (SAMPLE DATA)
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# 1. Initialize the local database and load sample data
python -m stormdesk.db --init --load-samples

# 2. While online: refresh caches for McDowell, Buncombe, Yancey, Mitchell, Burke and Rutherford
#    (change the list with STORMDESK_COUNTIES in .env)
python sync/sync_all.py           # roads, gazetteer, shelters, NWS alerts, DriveNC closures
python sync/sync_all.py --quick   # daily refresh: closures, alerts, shelters only

# 3. On the GPU box (Brev): start both models
bash scripts/serve_lightning.sh
bash scripts/serve_triage.sh

# 4. Run the console, then open http://localhost:8080
python ui/server.py

# 5. Stream demo reports into the queue
python scripts/stream_reports.py --file data/demo_reports.jsonl --delay 3

# Check everything is ready (add --skip-models on a laptop in mock mode)
python scripts/preflight.py

# Reset before each rehearsal (clears reports, drafts and learned closures; keeps the synced data)
python scripts/reset_demo.py --empty
```

No GPU yet? Set `STORMDESK_MOCK_LLM=1` in `.env` to run the UI and tools with stubbed model responses.

## Fine-tuning the triage model

```bash
python training/prepare_humaid.py            # builds training/data/*.jsonl
python training/train_triage.py              # Unsloth LoRA on Qwen3-1.7B
python training/eval_triage.py --model http://localhost:8001/v1   # F1 vs base model
```


## Improving Lightning on dispatch (synthetic practice data)

```bash
python training/gen_agent_tasks.py          # 175 practice incidents -> training/agent_tasks.jsonl
python training/collect_trajectories.py     # run Lightning on them, keep only perfect runs
```

`training/agent_tasks.jsonl` is synthetic and published here. Each report comes from a hand-written
template for one incident type (rescue, shelter, medical, fire, welfare, supply, road, multi-step,
vague, noise, prompt injection), filled with a real road name from the OpenStreetMap gazetteer in the
six counties. No model wrote them. Roads named in `eval/incidents.jsonl` are excluded, so the 62 eval
cases stay unseen. The collector grades each run with the same scoring as the eval and the NeMo Gym
environment (`stormdesk/scoring.py`) and keeps a run only if every check passed with no guard blocks
or tool errors. Those runs are the fine-tuning set; the eval before and after measures the change.

## Triage safety nets

The triage model is right about 3 times in 4 (macro F1 0.755), and it learned from tweets about
disasters, not from people in them. On a Brev test it labeled "has anyone heard from my brother",
"huge fire on nanneytown road" and "im having a seizure" as unimportant. So urgency has three
layers, and each can only raise it:

1. **Triage model:** the category sets a starting urgency.
2. **Keyword safety nets:** missing people, medical emergencies, fire, gas, live wires, water and
   entrapment, violence, and calls for help set urgency 4 or higher, unless negated ("nobody trapped").
   `tests/test_triage_probe.py` holds 62 emergencies and 20 harmless reports they must sort correctly.
3. **Lightning's second opinion:** every report is also sent to Lightning with one question, is a
   life at risk? It runs in parallel with triage and catches what no keyword list can ("lips are
   turning blue"). Same model as the agent, so the parameter budget does not change. If Lightning
   is slow or down, intake falls back to layers 1 and 2.

A raised report stays in the queue and shows why (`possible medical emergency`,
`second opinion: ...`), so the dispatcher sees where the model and the safety nets disagreed.

## Data sources

- HumAID (QCRI): https://huggingface.co/datasets/QCRI/HumAID-all
- NCDOT road events via DriveNC (free developer key): https://drivenc.gov/help/endpoint/event
  (the old TIMS endpoint was retired May 27, 2026)
- NOAA/NWS alerts: https://api.weather.gov/alerts/active?area=NC
- FEMA Open Shelters (ESF#6, synced with Red Cross): https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer
- NC OneMap Potential Emergency Shelters (NC CGIA): https://services.nconemap.gov/secure/rest/services/NC1Map_Emergency_Law_Enforcement/FeatureServer/2
- OpenStreetMap via osmnx: roads and place names (Geofabrik NC extract for full offline use)

Files named `*_sample.*` and `data/demo_reports.jsonl` are **sample/demo data**, not real records.
The synced cache (`data/stormdesk.db`, `data/cache/`) holds real public data.

## License

Code, eval tasks and the Gym environment: MIT (see `LICENSE`).
The triage model weights are CC BY-NC-SA 4.0 because they are trained on HumAID, which uses that license (see `training/MODEL_CARD.md`).
Synced map and road data keep their sources' terms (OpenStreetMap is ODbL).

Nathan DeMoss
