#!/usr/bin/env bash
# macOS / Linux installer: venv + package + bootstrap + MCP config snippet.
# Usage: install/install.sh [profile]   (default: example)
set -euo pipefail

PROFILE="${1:-example}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv"
PY="${PYTHON:-python3}"

"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$REPO[test]"

"$VENV/bin/python" -m trajecta_identity.cli --profile "$PROFILE" init

cat <<EOF

Installed. Add this MCP server to your client config:

{
  "mcpServers": {
    "trajecta-identity-$PROFILE": {
      "command": "$VENV/bin/python",
      "args": ["-m", "trajecta_identity.mcp_server", "--profile", "$PROFILE"]
    }
  }
}

Daily decay (optional, e.g. cron): $VENV/bin/python -m trajecta_identity.cli --profile $PROFILE decay
EOF
