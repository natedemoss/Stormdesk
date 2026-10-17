#!/usr/bin/env bash
# Run StormDesk inside an OpenShell sandbox on the Brev box.
#   bash scripts/openshell_up.sh          # Brev: real models
#   MOCK=1 bash scripts/openshell_up.sh   # laptop (WSL 2 + Docker): scripted agent, no GPU
#
# Prereqs: OpenShell installed with a gateway (Docker driver), both vLLM servers
# running on the host (scripts/serve_lightning.sh, scripts/serve_triage.sh) unless MOCK=1,
# and the sync scripts already run so data/ holds the cached data.
#
# CLI flags here come from the OpenShell source in ~/OpenShell (commit d8a613f).
# If a command fails on the event's OpenShell version, check `openshell <cmd> --help`.
set -euo pipefail
cd "$(dirname "$0")/.."
# Not $NAME: WSL sets NAME to the machine hostname, which is not a valid sandbox name.
NAME=${SANDBOX_NAME:-stormdesk}
MOCK=${MOCK:-0}

echo "== 1. Prove the policy stays inside the boundary (no outbound messaging, local inference only)"
# Results are saved into openshell/ so the image (and the console's Sandbox tab) carries the proof.
if command -v openshell-prover >/dev/null; then
  openshell-prover check openshell/policy.yaml --boundary openshell/boundary.yaml | tee openshell/prover-policy.txt
  echo "   and show the prover catching an unsafe change:"
  openshell-prover check openshell/bad-policy.yaml --boundary openshell/boundary.yaml | tee openshell/prover-bad-policy.txt || true
elif [ -f openshell/prover-policy.txt ]; then
  echo "   openshell-prover not installed; using the saved results:"
  cat openshell/prover-policy.txt
else
  echo "openshell-prover not installed and no saved results; see openshell/POLICY.md" >&2
  exit 1
fi

echo "== 2. Build the sandbox image (code + cached data baked in; MOCK=$MOCK)"
docker build -f openshell/Dockerfile --build-arg MOCK="$MOCK" -t stormdesk:local .

echo "== 3. Create the sandbox with the StormDesk policy"
openshell sandbox delete "$NAME" >/dev/null 2>&1 || true
openshell sandbox create \
  --name "$NAME" \
  --from stormdesk:local \
  --policy openshell/policy.yaml \
  --no-auto-providers \
  --detach \
  -- python3.12 scripts/sandbox_start.py

echo "== 4. Turn on OCSF JSON audit logs so the console can show allow/deny decisions"
openshell settings set "$NAME" --key ocsf_json_enabled --value true

echo "== 5. Forward the console to this machine"
openshell forward start 8080 "$NAME" --background

cat <<EOF

StormDesk is running inside OpenShell sandbox '$NAME'.
  Console:          http://localhost:8080   (from your laptop: ssh -L 8080:localhost:8080 <brev-host>)
  Live audit log:   openshell logs $NAME --tail --source sandbox
  Effective policy: openshell policy get $NAME --full
  Stop:             openshell forward stop 8080 $NAME && openshell sandbox delete $NAME
EOF
