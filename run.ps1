$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
. ".\.venv\Scripts\Activate.ps1"
uvicorn main:app --reload --port 8765
