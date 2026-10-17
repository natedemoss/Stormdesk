# OpenShell sandbox

StormDesk runs inside an NVIDIA OpenShell sandbox. The agent, its tools and the
console all live in one sandbox whose only network access is the local vLLM
servers on the host.

Syntax in these files was checked against the OpenShell source and docs in
`~/OpenShell` (commit d8a613f). Re-run the prover on the Brev box before the demo,
since the event may ship a newer OpenShell.

## Files

| File | What it is |
|---|---|
| `policy.yaml` | The sandbox policy. Read `/app`, write `/tmp`, reach only `host.openshell.internal:8000/8001` (`POST /v1/chat/completions`, `GET /v1/models`). |
| `boundary.yaml` | The most access a StormDesk sandbox may ever have. The prover checks `policy.yaml` against it. |
| `bad-policy.yaml` | Demo only: `policy.yaml` plus an SMS gateway rule. The prover rejects it. Never deploy it. |
| `Dockerfile` | Image with code and cached data baked in, policy at `/etc/openshell/policy.yaml`. |
| `../scripts/openshell_up.sh` | Prove, build, create sandbox, enable audit JSON, forward port 8080. |

## Three layers, one line each

- **OpenShell** decides what is *allowed* (kernel and proxy enforcement, outside our code).
- **Guard** (`stormdesk/agent.py`) checks each tool call is *correct*.
- **Dispatcher** decides it *should happen*. `draft_dispatch` has no send path.

## What the demo shows

1. **Proved, not promised.** `openshell-prover check policy.yaml --boundary boundary.yaml`
   returns `within_boundary`. The same check on `bad-policy.yaml` returns
   `exceeds_boundary` with a counterexample naming the SMS gateway.
2. **Live enforcement.** The console's Sandbox panel runs red-team checks from inside
   the sandbox (`stormdesk/redteam.py`): text the reporter, post to an injected
   webhook, fall back to a cloud LLM, fetch from the internet, read SSH keys. Each
   should be blocked; the local vLLM call should be allowed.
3. **OpenShell's own audit log.** In a terminal next to the console:
   `openshell logs stormdesk --tail --source sandbox`. Each red-team check shows up as an
   OCSF record written by the OpenShell supervisor, for example
   `NET:OPEN [MED] DENIED python3.12 -> api.weather.gov:443 [reason:transparent_tcp_policy_denied]`.
   With OpenShell 0.1.4's Docker driver the supervisor runs in a companion container, so the
   log never appears inside the StormDesk container (`/var/log/openshell-ocsf.*.log` is empty
   there). StormDesk cannot read or alter its own audit trail; the console says so.

Checked on the laptop (WSL 2 + Docker Desktop, OpenShell 0.1.4, `MOCK=1`, 2026-10-13): all five
"should be blocked" checks were blocked. The vLLM check reached the policy's allowed mapping
(`host.openshell.internal` ports 8000 and 8001) and failed only because no model runs on the laptop.

## Notes and unknowns to confirm on the day

- Host services must be addressed as `host.openshell.internal`, not `localhost`
  (OpenShell never authorizes loopback). The image sets `AGENT_BASE_URL` and
  `TRIAGE_BASE_URL` accordingly. Make sure vLLM listens on an address the sandbox
  can reach (default `vllm serve` binds 0.0.0.0).
- `binaries` must name the real interpreter path. In `python:3.12-slim` that is
  `/usr/local/bin/python3.12`. If the base image changes, update both policy files.
- The sync scripts need the internet, so they run on the host before `docker build`,
  never inside this sandbox.
- Exact log/record fields can vary by OpenShell version; `stormdesk/audit.py`
  reads the documented OCSF fields and falls back to the `message` text.
