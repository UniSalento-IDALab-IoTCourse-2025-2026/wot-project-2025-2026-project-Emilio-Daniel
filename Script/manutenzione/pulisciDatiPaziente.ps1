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

function Invoke-DockerNative {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)

    $PreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $Output = @(& docker @Arguments 2>&1)
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
    return [PSCustomObject]@{
        ExitCode = $ExitCode
        Output = $Output
    }
}

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory = $true)][string[]] $Arguments,
        [Parameter(Mandatory = $true)][string] $FailureMessage
    )

    $Result = Invoke-DockerNative -Arguments $Arguments
    if ($Result.ExitCode -ne 0) {
        $Details = ($Result.Output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "$FailureMessage`n$Details"
    }
    return $Result.Output
}

function Test-ComposeServiceRunning {
    param([Parameter(Mandatory = $true)][string] $Service)

    $Result = Invoke-DockerNative -Arguments @("compose", "ps", "--status", "running", "--services")
    return $Result.ExitCode -eq 0 -and $Result.Output -contains $Service
}

function Wait-PostgresReady {
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        $Ready = $false
        $Result = Invoke-DockerNative -Arguments @(
            "compose", "exec", "-T", "postgres", "sh", "-c",
            'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
        )
        $Ready = $Result.ExitCode -eq 0
        if ($Ready) { return }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL non pronto dopo 60 secondi."
}

Push-Location $Cloud
try {
    $ComposeStatus = Invoke-DockerNative -Arguments @("compose", "ps", "--status", "running", "--services")
    if ($ComposeStatus.ExitCode -ne 0) {
        throw "Stack Docker non raggiungibile. Avviare prima Docker Desktop e lo stack PC."
    }

    if (-not (Test-ComposeServiceRunning -Service "postgres")) {
        Write-Host "PostgreSQL non attivo: avvio del servizio..."
        Invoke-DockerChecked -Arguments @("compose", "up", "-d", "postgres") `
            -FailureMessage "Impossibile avviare PostgreSQL." | Out-Null
    }
    Wait-PostgresReady

    if (-not $Execute) {
        $PreviewArguments = @("compose", "exec", "-T", "backend", "python", "-m", "scripts.reset_patient_data", "--patient-id", $PatientId)
        $PreviewArguments += $AuditArg
        $PreviewArguments += $ScopeArg
        Invoke-DockerChecked -Arguments $PreviewArguments -FailureMessage "Anteprima pulizia fallita." | ForEach-Object { Write-Host $_ }
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
        Invoke-DockerChecked -Arguments @("compose", "stop", "backend-mqtt-worker", "backend") `
            -FailureMessage "Impossibile fermare backend e worker." | Out-Null
        $ServicesStopped = $true

        Invoke-DockerChecked -Arguments @(
            "compose", "exec", "-T", "postgres", "sh", "-c",
            'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"',
            "--", $ContainerBackup
        ) -FailureMessage "Backup PostgreSQL fallito." | Out-Null

        Invoke-DockerChecked -Arguments @("cp", "iot-postgres:$ContainerBackup", $LocalBackup) `
            -FailureMessage "Copia locale del backup fallita." | Out-Null
        if (-not (Test-Path -LiteralPath $LocalBackup)) {
            throw "Copia locale del backup fallita."
        }

        $ResetArguments = @(
            "compose", "run", "--rm", "--no-deps", "backend", "python", "-m", "scripts.reset_patient_data",
            "--patient-id", $PatientId, "--execute", "--confirm", $ConfirmPatientId
        )
        $ResetArguments += $AuditArg
        $ResetArguments += $ScopeArg
        Invoke-DockerChecked -Arguments $ResetArguments `
            -FailureMessage "Pulizia database fallita; il backup resta disponibile." | ForEach-Object { Write-Host $_ }
    } finally {
        try {
            if (Test-ComposeServiceRunning -Service "postgres") {
                Invoke-DockerNative -Arguments @("compose", "exec", "-T", "postgres", "rm", "-f", $ContainerBackup) | Out-Null
            }
        } catch {
            Write-Warning "Impossibile rimuovere il backup temporaneo dal container PostgreSQL."
        }
        if ($ServicesStopped) {
            Invoke-DockerChecked -Arguments @("compose", "start", "backend") `
                -FailureMessage "Backend non riavviato correttamente." | Out-Null

            $Ready = $false
            for ($i = 0; $i -lt 30; $i++) {
                try {
                    $Response = Invoke-RestMethod "http://127.0.0.1:8080/ready" -TimeoutSec 2
                    if ($Response.status -eq "ready") { $Ready = $true; break }
                } catch { }
                Start-Sleep -Seconds 2
            }
            if (-not $Ready) { throw "Backend non pronto dopo la pulizia." }

            Invoke-DockerChecked -Arguments @("compose", "start", "backend-mqtt-worker") `
                -FailureMessage "Worker MQTT non riavviato correttamente." | Out-Null
        }
    }

    Write-Host "Pulizia completata per $PatientId."
    Write-Host "Backup: $LocalBackup"
} finally {
    Pop-Location
}
