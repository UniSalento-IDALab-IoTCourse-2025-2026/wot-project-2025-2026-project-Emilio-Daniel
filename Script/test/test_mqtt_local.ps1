param(
    [string]$EdgePassword = "",
    [string]$BackendPassword = "",
    [string]$TestPassword = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CloudDir = Join-Path $ProjectDir "cloud"

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

if (-not $EdgePassword) { $EdgePassword = $env:MQTT_EDGE_PASSWORD }
if (-not $BackendPassword) { $BackendPassword = $env:MQTT_BACKEND_PASSWORD }
if (-not $TestPassword) { $TestPassword = $env:MQTT_TEST_PASSWORD }
if (-not $EdgePassword -or -not $BackendPassword -or -not $TestPassword) {
    throw "Missing MQTT test passwords. Set MQTT_EDGE_PASSWORD, MQTT_BACKEND_PASSWORD and MQTT_TEST_PASSWORD in cloud\.env."
}

Push-Location $CloudDir
try {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker compose up -d mqtt *> $null
    $composeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($composeExitCode -ne 0) {
        throw "Unable to start MQTT service with docker compose."
    }

    Write-Host "Test 1 - edge publish allowed on patient-001"
    $allowedMessage = '{"schema_version":1,"message_id":"script-allowed-001","event_type":"edge_cycle_completed","patient_id":"patient-001","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"online":true}}'
    docker compose exec -T mqtt mosquitto_pub `
        -h localhost -p 1883 `
        -u edge_patient_001 -P $EdgePassword `
        -q 1 `
        -t "iot/patients/patient-001/edge/status" `
        -m $allowedMessage

    Write-Host "Test 2 - edge publish denied/not delivered on patient-999"
    $deniedMessage = '{"schema_version":1,"message_id":"script-denied-999","event_type":"edge_cycle_completed","patient_id":"patient-999","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"online":true}}'
    $deniedResult = docker compose exec -T mqtt sh -c "mosquitto_sub -h localhost -p 1883 -u backend -P '$BackendPassword' -C 1 -W 3 -t 'iot/patients/patient-999/edge/status' -v > /tmp/denied.out 2>&1 & sleep 1; mosquitto_pub -h localhost -p 1883 -u edge_patient_001 -P '$EdgePassword' -q 1 -t 'iot/patients/patient-999/edge/status' -m '$deniedMessage'; wait; cat /tmp/denied.out; rm -f /tmp/denied.out"
    if ($deniedResult -match "script-denied-999") {
        throw "ACL failed: unauthorized patient-999 message was delivered."
    }

    Write-Host "Test 3 - backend command is received by edge"
    $unique = "script$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    $topic = "iot/patients/patient-001/commands/$unique"
    $message = "backend-to-edge-$unique"
    $commandResult = docker compose exec -T mqtt sh -c "mosquitto_sub -h localhost -p 1883 -u edge_patient_001 -P '$EdgePassword' -C 1 -W 10 -t '$topic' -v > /tmp/command.out 2>&1 & sleep 2; mosquitto_pub -h localhost -p 1883 -u backend -P '$BackendPassword' -q 1 -t '$topic' -m '$message'; wait; cat /tmp/command.out; rm -f /tmp/command.out"
    if (-not ($commandResult -match [regex]::Escape($message))) {
        throw "Backend command was not delivered to edge."
    }

    Write-Host "Test 4 - Last Will is published on unexpected edge disconnect"
    docker compose exec -T mqtt mosquitto_pub `
        -h localhost -p 1883 `
        -u edge_patient_001 -P $EdgePassword `
        -q 1 `
        -r -n `
        -t "iot/patients/patient-001/edge/status"

    $willScript = @'
set -eu
WILL='{"schema_version":1,"message_id":"script-will-001","event_type":"edge_offline_unexpected","patient_id":"patient-001","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"online":false,"reason":"mqtt_last_will"}}'
rm -f /tmp/will_backend.out /tmp/will_edge.out
mosquitto_sub -h localhost -p 1883 -u backend -P "$BACKEND_PASSWORD" -C 1 -W 15 -t 'iot/patients/patient-001/edge/status' -v > /tmp/will_backend.out 2>&1 &
subpid=$!
sleep 1
mosquitto_sub -h localhost -p 1883 -u edge_patient_001 -P "$EDGE_PASSWORD" -i edge_will_test --will-topic 'iot/patients/patient-001/edge/status' --will-payload "$WILL" --will-qos 1 -t 'iot/patients/patient-001/commands/#' > /tmp/will_edge.out 2>&1 &
edgepid=$!
sleep 2
kill -9 $edgepid || true
wait $subpid || true
cat /tmp/will_backend.out || true
echo '---EDGE-LAST-WILL-CLIENT---'
cat /tmp/will_edge.out || true
rm -f /tmp/will_backend.out /tmp/will_edge.out
'@
    $willScript = $willScript -replace "`r", ""
    $willResult = $willScript | docker compose exec -T `
        -e BACKEND_PASSWORD=$BackendPassword `
        -e EDGE_PASSWORD=$EdgePassword `
        mqtt sh
    if (-not ($willResult -match "edge_offline_unexpected")) {
        throw "Last Will was not received by backend."
    }

    Write-Host "Test 5 - MQTT over TLS works on 8883"
    $tlsMessage = '{"schema_version":1,"message_id":"script-tls-001","event_type":"edge_cycle_completed","patient_id":"patient-001","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"online":true,"transport":"tls"}}'
    docker compose exec -T mqtt mosquitto_pub `
        -h localhost -p 8883 `
        --cafile /mosquitto/certs/ca.crt `
        -u edge_patient_001 -P $EdgePassword `
        -q 1 `
        -t "iot/patients/patient-001/edge/status" `
        -m $tlsMessage

    Write-Host "Test 6 - MQTT over secure WebSockets handshake works on 9001"
    $wssResult = @'
import base64
import os
import socket
import ssl

key = base64.b64encode(os.urandom(16)).decode("ascii")
ctx = ssl.create_default_context(cafile="mqtt/certs/ca.crt")
with socket.create_connection(("localhost", 9001), timeout=5) as raw:
    with ctx.wrap_socket(raw, server_hostname="localhost") as sock:
        request = (
            "GET /mqtt HTTP/1.1\r\n"
            "Host: localhost:9001\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: mqtt\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096).decode("latin1", errors="replace")

print(response.split("\r\n\r\n", 1)[0])
if not response.startswith("HTTP/1.1 101"):
    raise SystemExit(1)
'@ | python -
    if (-not ($wssResult -match "101 Switching Protocols")) {
        throw "WSS listener did not complete the WebSocket upgrade."
    }

    Write-Host "Test 7 - retained policy keeps only current status retained"
    $retainedStatus = '{"schema_version":1,"message_id":"script-retained-status-001","event_type":"edge_status_current","patient_id":"patient-001","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"online":true,"retained":true}}'
    $telemetryMessage = '{"schema_version":1,"message_id":"script-not-retained-telemetry-001","event_type":"edge_window","patient_id":"patient-001","edge_id":"edge-rpi5-001","timestamp":"2026-07-10T10:00:00Z","payload":{"heart_rate_mean":70}}'
    $retainedResult = docker compose exec -T mqtt sh -c "mosquitto_pub -h localhost -p 1883 -u edge_patient_001 -P '$EdgePassword' -q 1 -r -t 'iot/patients/patient-001/edge/status' -m '$retainedStatus'; mosquitto_pub -h localhost -p 1883 -u edge_patient_001 -P '$EdgePassword' -q 1 -r -n -t 'iot/patients/patient-001/telemetry/window'; mosquitto_pub -h localhost -p 1883 -u edge_patient_001 -P '$EdgePassword' -q 1 -t 'iot/patients/patient-001/telemetry/window' -m '$telemetryMessage'; mosquitto_sub -h localhost -p 1883 -u backend -P '$BackendPassword' -C 1 -W 3 -t 'iot/patients/patient-001/edge/status' -v > /tmp/retained_status.out 2>&1; mosquitto_sub -h localhost -p 1883 -u backend -P '$BackendPassword' -C 1 -W 2 -t 'iot/patients/patient-001/telemetry/window' -v > /tmp/retained_telemetry.out 2>&1 || true; echo '---STATUS---'; cat /tmp/retained_status.out; echo '---TELEMETRY---'; cat /tmp/retained_telemetry.out; rm -f /tmp/retained_status.out /tmp/retained_telemetry.out"
    if (-not ($retainedResult -match "script-retained-status-001")) {
        throw "Current status retained message was not available to late subscribers."
    }
    if ($retainedResult -match "script-not-retained-telemetry-001") {
        throw "Telemetry message was retained unexpectedly."
    }

    Write-Host "All local MQTT tests passed."
}
finally {
    Pop-Location
}
