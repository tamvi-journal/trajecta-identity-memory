#!/usr/bin/env bash
# macOS / Linux: create a venv, install, bootstrap the profile, print the MCP config.
# Usage: install/install.sh [profile]   (name, folder, .json file or URL; default: example)
set -euo pipefail

PROFILE="${1:-example}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv"
PY="${PYTHON:-python3}"

"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$REPO[test]"
"$VENV/bin/python" -m trajecta_identity.cli --profile "$PROFILE" setup
