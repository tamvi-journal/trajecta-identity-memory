# Windows installer: venv + package + bootstrap + MCP config snippet.
# Usage: powershell -ExecutionPolicy Bypass -File install\install.ps1 [-AgentProfile example]
param([string]$AgentProfile = "example")
$ErrorActionPreference = "Stop"

$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$Venv = Join-Path $Repo ".venv"
$Py = if ($env:PYTHON) { $env:PYTHON } else { "py" }

& $Py -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
if (-not (Test-Path $Venv)) { & $Py -m venv $Venv }
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --quiet --upgrade pip
& $VPy -m pip install --quiet -e "$Repo[test]"
& $VPy -m trajecta_identity.cli --profile $AgentProfile init

$VPyJson = $VPy -replace '\\', '\\'
Write-Host @"

Installed. Add this MCP server to your client config:

{
  "mcpServers": {
    "trajecta-identity-$AgentProfile": {
      "command": "$VPyJson",
      "args": ["-m", "trajecta_identity.mcp_server", "--profile", "$AgentProfile"]
    }
  }
}

Daily decay (optional, Task Scheduler): $VPy -m trajecta_identity.cli --profile $AgentProfile decay
"@
