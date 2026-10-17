#!/usr/bin/env bash
# Copy the StormDesk environment into a NeMo Gym checkout (Linux/macOS/WSL2).
#   bash gym/install_into_gym.sh ~/Gym
# Gym loads environments from its resources_servers/ folder. A real copy, not a symlink: the
# requirements file installs Gym from "../../", which must resolve inside the Gym checkout.
# Rerun after changing anything under gym/stormdesk_dispatch. The copy finds the StormDesk
# package (tools, scoring, data) through the .stormdesk_root file written here.
set -euo pipefail
GYM=${1:?usage: bash gym/install_into_gym.sh <path to NeMo Gym checkout>}
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/stormdesk_dispatch/build_data.py"
DEST="$GYM/resources_servers/stormdesk_dispatch"
rm -rf "$DEST"
cp -r "$HERE/stormdesk_dispatch" "$DEST"
dirname "$HERE" > "$DEST/.stormdesk_root"
echo "copied to $DEST (StormDesk repo: $(cat "$DEST/.stormdesk_root"))"
echo "The environment copies data/stormdesk.db per rollout; build it first if missing:"
echo "  python -m stormdesk.db --init --load-samples && python sync/sync_all.py"
