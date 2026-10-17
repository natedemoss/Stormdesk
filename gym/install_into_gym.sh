#!/usr/bin/env bash
# Link the StormDesk environment into a NeMo Gym checkout (Linux/macOS/WSL2).
#   bash gym/install_into_gym.sh ~/Gym
# Gym loads environments from its resources_servers/ folder; a symlink keeps one copy of
# the code in this repo. app.py finds the StormDesk package through the resolved link.
set -euo pipefail
GYM=${1:?usage: bash gym/install_into_gym.sh <path to NeMo Gym checkout>}
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/stormdesk_dispatch/build_data.py"
ln -sfn "$HERE/stormdesk_dispatch" "$GYM/resources_servers/stormdesk_dispatch"
echo "linked $GYM/resources_servers/stormdesk_dispatch -> $HERE/stormdesk_dispatch"
echo "The environment copies data/stormdesk.db per rollout; build it first if missing:"
echo "  python -m stormdesk.db --init --load-samples && python sync/build_road_graph.py && python sync/build_gazetteer.py"
