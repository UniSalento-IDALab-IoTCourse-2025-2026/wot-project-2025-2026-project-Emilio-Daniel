param(
    [string]$BackendUrl = "http://127.0.0.1:8080/api/v1",
    [string]$Email = "medico.demo@localhost.invalid",
    [string]$Password = "provaprova",
    [string]$PatientId = "patient-001"
)

$ErrorActionPreference = "Stop"

Write-Host "Diagnosi Dashboard IoT avviata..." -ForegroundColor Cyan
Write-Host "Backend: $BackendUrl"
Write-Host "Paziente: $PatientId"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[ATTENZIONE] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[ERRORE] $Message" -ForegroundColor Red
}

Write-Step "1. Controllo ultimo ciclo Edge"
$lastCyclePath = Join-Path $PSScriptRoot "..\..\edge_node\outputs\last-cycle.json"
if (Test-Path $lastCyclePath) {
    $lastCycle = Get-Content $lastCyclePath -Raw | ConvertFrom-Json
    $mqtt = $lastCycle.mqtt_publish
    Write-Host "Config Edge: $($lastCycle.config)"
    Write-Host "Finestra: $($lastCycle.window_start_local) -> $($lastCycle.window_end_local)"
    Write-Host "Decisione: $($lastCycle.decision_level)"
    if ($mqtt) {
        Write-Host "MQTT: enabled=$($mqtt.enabled), status=$($mqtt.status), published=$($mqtt.published), queued=$($mqtt.queued), queue_depth=$($mqtt.queue_depth)"
        if ($mqtt.enabled -and $mqtt.published -gt 0) {
            Write-Ok "Edge sta pubblicando su MQTT."
        } elseif (-not $mqtt.enabled) {
            Write-Fail "MQTT disabilitato nel config Edge usato dal runtime."
        } else {
            Write-WarnLine "MQTT attivo ma non risultano messaggi pubblicati."
        }
    } else {
        Write-WarnLine "Il last-cycle non contiene mqtt_publish."
    }
} else {
    Write-WarnLine "last-cycle.json non trovato."
}

Write-Step "2. Controllo login backend"
$loginBody = @{
    email = $Email
    password = $Password
} | ConvertTo-Json

try {
    $session = Invoke-RestMethod -Method Post -Uri "$BackendUrl/auth/login" -ContentType "application/json" -Body $loginBody
    Write-Ok "Login riuscito come $($session.user.email), ruolo $($session.user.role)."
} catch {
    Write-Fail "Login fallito verso $BackendUrl/auth/login"
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
    exit 1
}

$headers = @{ Authorization = "Bearer $($session.access_token)" }

Write-Step "3. Controllo lista pazienti REST"
try {
    $patients = Invoke-RestMethod -Method Get -Uri "$BackendUrl/patients" -Headers $headers
    $count = @($patients.items).Count
    Write-Host "Pazienti restituiti: $count"
    if ($count -gt 0) {
        $patients.items | Select-Object patient_id, display_name, level, last_update, edge_online, watch_present | Format-Table
        Write-Ok "Il backend espone pazienti alla dashboard."
    } else {
        Write-Fail "Il backend risponde, ma non restituisce pazienti. Verificare ingestion MQTT o assegnazioni paziente/utente."
    }
} catch {
    Write-Fail "Errore leggendo /patients"
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
}

Write-Step "4. Controllo stato corrente paziente"
try {
    $current = Invoke-RestMethod -Method Get -Uri "$BackendUrl/patients/$PatientId/current" -Headers $headers
    $current | ConvertTo-Json -Depth 8
    Write-Ok "Il backend espone lo stato corrente di $PatientId."
} catch {
    Write-Fail "Errore leggendo /patients/$PatientId/current"
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
}

Write-Step "5. Controllo tabelle PostgreSQL via Docker"
try {
    docker compose -f cloud\docker-compose.yml exec -T postgres psql -U iot_backend -d progetto_iot -c "select count(*) as feature_windows from feature_windows; select count(*) as decisions from decisions;"
    docker compose -f cloud\docker-compose.yml exec -T postgres psql -U iot_backend -d progetto_iot -c "select patient_id, window_start, created_at from feature_windows order by created_at desc limit 3;"
    Write-Ok "Controllo DB completato."
} catch {
    Write-WarnLine "Non riesco a interrogare PostgreSQL via Docker. Controllare che Docker Desktop e cloud/docker-compose.yml siano attivi."
    Write-Host $_.Exception.Message
}

Write-Step "6. Lettura log MQTT recenti"
try {
    docker logs --tail 30 iot-mqtt
} catch {
    Write-WarnLine "Non riesco a leggere i log del container iot-mqtt."
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "Diagnosi completata." -ForegroundColor Cyan
