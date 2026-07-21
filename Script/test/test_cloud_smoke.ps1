param(
    [string] $BaseUrl = "http://127.0.0.1:8080",
    [switch] $StartCompose
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CloudDir = Join-Path $ProjectDir "cloud"

function Wait-HttpOk {
    param(
        [string] $Url,
        [int] $TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 5
            return $response
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "Endpoint non raggiungibile: $Url"
}

Push-Location $CloudDir
try {
    if ($StartCompose) {
        docker compose up -d mqtt postgres backend backend-mqtt-worker
        if ($LASTEXITCODE -ne 0) {
            throw "Avvio Docker Compose fallito."
        }
    }

    docker compose exec -T postgres pg_isready -U iot_backend -d progetto_iot | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL non pronto."
    }
}
finally {
    Pop-Location
}

$health = Wait-HttpOk "$BaseUrl/health"
$ready = Wait-HttpOk "$BaseUrl/ready"
$apiReady = Wait-HttpOk "$BaseUrl/api/v1/ready"
$metrics = Wait-HttpOk "$BaseUrl/api/v1/metrics"

if ($health.status -ne "ok") {
    throw "Health non valido."
}
if ($ready.status -ne "ready" -or $apiReady.status -ne "ready") {
    throw "Readiness non valida."
}
if (-not $metrics.counters) {
    throw "Metriche non disponibili."
}

Write-Host "Smoke test Cloud completato."
Write-Host "Health: $($health.status)"
Write-Host "Ready: $($ready.status)"
Write-Host "Metriche: disponibili"
