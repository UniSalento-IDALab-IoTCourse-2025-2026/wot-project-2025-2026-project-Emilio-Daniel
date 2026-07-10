param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ExtraArgs
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$EdgeDir = Join-Path $ProjectDir "edge_node"
$ConfigFile = Join-Path $EdgeDir "config\edge.yml"
$LocalPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $ConfigFile)) {
    Write-Host "ERRORE: manca edge_node\config\edge.yml"
    Write-Host "Crea il file reale partendo da edge_node\config\edge.example.yml e inserisci token/config locali."
    exit 1
}

if (Test-Path $LocalPython) {
    $PythonExe = $LocalPython
} else {
    $PythonExe = "python"
}

Push-Location $EdgeDir
try {
    Write-Host "Avvio sistema IoT: receiver + runtime + baseline automatica 7 giorni."
    Write-Host "Se il modello personale esiste gia, verra usato automaticamente."
    & $PythonExe -m edge_stack.cli --config "config\edge.yml" @ExtraArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
