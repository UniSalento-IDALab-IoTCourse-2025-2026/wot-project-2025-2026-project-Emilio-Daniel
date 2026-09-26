param(
    [Parameter(Mandatory = $true)] [string] $PcHost,
    [switch] $Replace
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
Push-Location (Join-Path $Root "edge_node")
try {
    $arguments = @("-m", "edge_deploy.cli", "certificate", "--pc-host", $PcHost)
    if ($Replace) { $arguments += "--replace" }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Preparazione certificati non completata. Leggere il messaggio precedente." }
} finally { Pop-Location }
