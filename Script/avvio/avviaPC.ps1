param(
    [switch] $Stop,
    [switch] $SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Cloud = Join-Path $Root "cloud"
$Dashboard = Join-Path $Root "Dashboard"
$StateFile = Join-Path $Dashboard ".pc-launch.json"

function Stop-Dashboard {
    if (-not (Test-Path -LiteralPath $StateFile)) { return }
    $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq "node" -and
        $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $state.startTicks) {
        Stop-Process -Id $process.Id
    }
    Remove-Item -LiteralPath $StateFile
}

if ($Stop) {
    Stop-Dashboard
    Push-Location $Cloud
    try {
        docker compose stop
        if ($LASTEXITCODE -ne 0) { throw "Arresto Docker fallito." }
    } finally { Pop-Location }
    Write-Host "Stack PC fermato; volumi e dati conservati. Raspberry non modificato."
    exit 0
}

foreach ($file in @("cloud\.env", "cloud\backend\.env", "Dashboard\.env",
                    "cloud\mqtt\passwd", "cloud\mqtt\certs\server.crt",
                    "cloud\mqtt\certs\server.key", "cloud\mqtt\certs\ca.crt")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root $file))) {
        throw "Manca $file. Consultare la sezione Installazione e avvio del README.md."
    }
}
$null = Get-Command docker -ErrorAction Stop
$node = (Get-Command node -ErrorAction Stop).Source
$null = Get-Command npm.cmd -ErrorAction Stop

# Do not silently reuse an unrelated process on the dashboard port.
Stop-Dashboard
$listener = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw "Porta 5173 occupata. Fermare la precedente dashboard prima di avviare questo script." }

Push-Location $Cloud
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $Cloud "model-metrics") | Out-Null
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Avviare Docker Desktop e attendere che il motore sia pronto." }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "Stack Docker non pronto. Controllare docker compose ps -a e logs." }
    $backendReady = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $response = Invoke-RestMethod "http://127.0.0.1:8080/ready" -TimeoutSec 2
            if ($response.status -eq "ready") { $backendReady = $true; break }
        } catch { }
        Start-Sleep -Seconds 3
    }
    if (-not $backendReady) { throw "Backend non pronto dopo l'attesa. Leggere i log di backend-migrations e backend." }
    $running = @(docker compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) { throw "Impossibile verificare i servizi Docker." }
    foreach ($service in @("mqtt", "postgres", "backend", "backend-mqtt-worker")) {
        if ($running -notcontains $service) { throw "Servizio $service non in esecuzione: controllare docker compose logs $service." }
    }
} finally { Pop-Location }

Push-Location $Dashboard
try {
    if (-not $SkipBuild) {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze Dashboard fallita." }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Build Dashboard fallita." }
    } elseif (-not (Test-Path "dist\index.html")) {
        throw "Build assente: rilanciare senza -SkipBuild."
    }
    $vite = Join-Path $Dashboard "node_modules\vite\bin\vite.js"
    $process = Start-Process -FilePath $node -ArgumentList @("`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "5173", "--strictPort") `
        -WorkingDirectory $Dashboard -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Dashboard "dist\preview.stdout.log") `
        -RedirectStandardError (Join-Path $Dashboard "dist\preview.stderr.log")
    @{ pid = $process.Id; startTicks = $process.StartTime.ToUniversalTime().Ticks.ToString() } |
        ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        if ($process.HasExited) { break }
        try {
            $null = Invoke-WebRequest "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { Stop-Dashboard; throw "Dashboard non pronta: vedere Dashboard/dist/preview.stderr.log." }
} finally { Pop-Location }
Write-Host "Dashboard: http://127.0.0.1:5173"
Write-Host "Backend: http://IP_LAN_PC:8080/api/v1 - MQTT TLS: IP_LAN_PC:8883"
Write-Host "Nessuna pipeline Edge avviata sul PC. Il Raspberry usa iot-edge.service."
Write-Host "Stop: .\Script\avvio\avviaPC.ps1 -Stop (non elimina i dati)"
