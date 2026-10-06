param(
    [string] $PatientId = "patient-001",
    [switch] $Execute,
    [string] $ConfirmPatientId = "",
    [switch] $IncludeAudit,
    [switch] $TelemetryOnly
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Cloud = Join-Path $Root "cloud"
$BackupDir = Join-Path $Cloud "backups"
$AuditArg = if ($IncludeAudit) { @("--include-audit") } else { @() }
$ScopeArg = if ($TelemetryOnly) { @("--telemetry-only") } else { @() }

Push-Location $Cloud
try {
    docker compose ps --status running --services | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Stack Docker non raggiungibile. Avviare prima Docker Desktop e lo stack PC."
    }

    if (-not $Execute) {
        docker compose exec -T backend python -m scripts.reset_patient_data `
            --patient-id $PatientId @AuditArg @ScopeArg
        if ($LASTEXITCODE -ne 0) { throw "Anteprima pulizia fallita." }
        Write-Host "Anteprima soltanto: nessun dato e' stato modificato."
        Write-Host "Per eseguire: aggiungere -Execute -ConfirmPatientId $PatientId"
        exit 0
    }

    if ($ConfirmPatientId -ne $PatientId) {
        throw "Pulizia rifiutata: -ConfirmPatientId deve coincidere con -PatientId."
    }

    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $BackupName = "pre-reset-$PatientId-$Stamp.dump"
    $ContainerBackup = "/tmp/$BackupName"
    $LocalBackup = Join-Path $BackupDir $BackupName
    $ServicesStopped = $false

    try {
        docker compose stop backend-mqtt-worker backend
        if ($LASTEXITCODE -ne 0) { throw "Impossibile fermare backend e worker." }
        $ServicesStopped = $true

        docker compose exec -T postgres sh -c `
            'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"' `
            -- $ContainerBackup
        if ($LASTEXITCODE -ne 0) { throw "Backup PostgreSQL fallito." }

        docker cp "iot-postgres:$ContainerBackup" $LocalBackup
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $LocalBackup)) {
            throw "Copia locale del backup fallita."
        }

        docker compose run --rm --no-deps backend python -m scripts.reset_patient_data `
            --patient-id $PatientId --execute --confirm $ConfirmPatientId @AuditArg @ScopeArg
        if ($LASTEXITCODE -ne 0) { throw "Pulizia database fallita; il backup resta disponibile." }
    } finally {
        docker compose exec -T postgres rm -f $ContainerBackup 2>$null
        if ($ServicesStopped) {
            docker compose start backend | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Backend non riavviato correttamente." }

            $Ready = $false
            for ($i = 0; $i -lt 30; $i++) {
                try {
                    $Response = Invoke-RestMethod "http://127.0.0.1:8080/ready" -TimeoutSec 2
                    if ($Response.status -eq "ready") { $Ready = $true; break }
                } catch { }
                Start-Sleep -Seconds 2
            }
            if (-not $Ready) { throw "Backend non pronto dopo la pulizia." }

            docker compose start backend-mqtt-worker | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Worker MQTT non riavviato correttamente." }
        }
    }

    Write-Host "Pulizia completata per $PatientId."
    Write-Host "Backup: $LocalBackup"
} finally {
    Pop-Location
}
