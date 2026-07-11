param(
    [string]$BackendPassword = "",
    [string]$EdgePassword = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CloudDir = Join-Path $ProjectDir "cloud"
$BackendDir = Join-Path $CloudDir "backend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

function Import-LocalEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $name, $value = $line.Split("=", 2)
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Import-LocalEnv (Join-Path $CloudDir ".env")
Import-LocalEnv (Join-Path $BackendDir ".env")

if (-not $BackendPassword) { $BackendPassword = $env:MQTT_BACKEND_PASSWORD }
if (-not $BackendPassword) { $BackendPassword = $env:IOT_BACKEND_MQTT_PASSWORD }
if (-not $EdgePassword) { $EdgePassword = $env:MQTT_EDGE_PASSWORD }
if (-not $BackendPassword -or -not $EdgePassword) {
    throw "Missing MQTT passwords. Set MQTT_BACKEND_PASSWORD and MQTT_EDGE_PASSWORD in cloud\.env, or pass -BackendPassword and -EdgePassword."
}

function Publish-MqttJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Topic,
        [Parameter(Mandatory = $true)]
        [string]$Payload,
        [Parameter(Mandatory = $true)]
        [string]$Password
    )

    $payloadBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Payload))
    $tempPath = "/tmp/iot_payload_$([Guid]::NewGuid().ToString('N')).json"
    docker compose exec -T mqtt sh -c "printf '%s' '$payloadBase64' | base64 -d > '$tempPath'; mosquitto_pub -h localhost -p 8883 --cafile /mosquitto/certs/ca.crt -u edge_patient_001 -P '$Password' -q 1 -t '$Topic' -f '$tempPath'; rm -f '$tempPath'"
}

if (-not (Test-Path $PythonExe)) {
    throw "Backend virtualenv not found. Run: cd cloud\backend; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}

Push-Location $CloudDir
try {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker compose up -d mqtt postgres *> $null
    $composeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($composeExitCode -ne 0) {
        throw "Unable to start Docker services."
    }

    $deadline = (Get-Date).AddSeconds(60)
    do {
        $postgresStatus = docker inspect -f '{{.State.Health.Status}}' iot-postgres 2>$null
        if ($postgresStatus -eq "healthy") {
            break
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if ($postgresStatus -ne "healthy") {
        throw "PostgreSQL did not become healthy."
    }
}
finally {
    Pop-Location
}

Push-Location $BackendDir
try {
    & $PythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed."
    }

    $stdoutLog = Join-Path $env:TEMP "iot-backend-mqtt-worker.out.log"
    $stderrLog = Join-Path $env:TEMP "iot-backend-mqtt-worker.err.log"
    Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

    Push-Location $CloudDir
    try {
        docker compose exec -T mqtt mosquitto_pub -h localhost -p 1883 -u edge_patient_001 -P $EdgePassword -q 1 -r -n -t "iot/patients/patient-001/edge/status"
    }
    finally {
        Pop-Location
    }

    $worker = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "app.mqtt.worker") `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    try {
        Start-Sleep -Seconds 5

        $suffix = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $windowMessageId = "integration-window-$suffix"
        $decisionMessageId = "integration-decision-$suffix"
        $alertMessageId = "integration-alert-$suffix"

        $windowPayload = @{
            schema_version = 1
            message_id = $windowMessageId
            event_type = "patient_window_updated"
            patient_id = "patient-001"
            edge_id = "edge-rpi5-001"
            timestamp = "2026-07-10T10:00:00Z"
            payload = @{
                window_start = "2026-07-10T10:00:00Z"
                window_end = "2026-07-10T10:04:00Z"
                features = @{
                    heart_rate_mean = 70.0
                    wearable_present = $true
                }
            }
        } | ConvertTo-Json -Depth 8 -Compress

        $decisionPayload = @{
            schema_version = 1
            message_id = $decisionMessageId
            event_type = "decision_updated"
            patient_id = "patient-001"
            edge_id = "edge-rpi5-001"
            timestamp = "2026-07-10T10:00:05Z"
            payload = @{
                level = "green"
                should_publish = $false
                anomaly_score = 0.0
                model_label = "agreement_normal"
            }
        } | ConvertTo-Json -Depth 8 -Compress

        $alertPayload = @{
            schema_version = 1
            message_id = $alertMessageId
            event_type = "alert_created"
            patient_id = "patient-001"
            edge_id = "edge-rpi5-001"
            timestamp = "2026-07-10T10:00:10Z"
            payload = @{
                level = "red"
                title = "Integration test alert"
                category = "technical"
            }
        } | ConvertTo-Json -Depth 8 -Compress

        Push-Location $CloudDir
        try {
            Publish-MqttJson -Topic "iot/patients/patient-001/telemetry/window" -Payload $windowPayload -Password $EdgePassword
            Publish-MqttJson -Topic "iot/patients/patient-001/telemetry/decision" -Payload $decisionPayload -Password $EdgePassword
            Publish-MqttJson -Topic "iot/patients/patient-001/alerts/critical" -Payload $alertPayload -Password $EdgePassword
        }
        finally {
            Pop-Location
        }

        Start-Sleep -Seconds 4

        $sql = @"
select 'feature_windows' as table_name, count(*) from feature_windows where message_id = '$windowMessageId'
union all
select 'decisions', count(*) from decisions where message_id = '$decisionMessageId'
union all
select 'alerts', count(*) from alerts where message_id = '$alertMessageId';
"@
        Push-Location $CloudDir
        try {
            $queryResult = docker compose exec -T postgres psql -U iot_backend -d progetto_iot -t -A -F "," -c $sql
        }
        finally {
            Pop-Location
        }

        $queryText = $queryResult -join "`n"

        if ($queryText -notmatch "feature_windows,1" -or $queryText -notmatch "decisions,1" -or $queryText -notmatch "alerts,1") {
            Write-Host "Worker stdout:"
            if (Test-Path $stdoutLog) { Get-Content $stdoutLog }
            Write-Host "Worker stderr:"
            if (Test-Path $stderrLog) { Get-Content $stderrLog }
            Write-Host "DB query result:"
            Write-Host $queryText
            throw "MQTT integration messages were not stored correctly."
        }

        Write-Host "Backend MQTT integration test passed."
    }
    finally {
        if ($worker -and -not $worker.HasExited) {
            Stop-Process -Id $worker.Id -Force
        }
    }
}
finally {
    Pop-Location
}
