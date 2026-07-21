param(
    [string] $BackupDir = "",
    [int] $KeepLast = 7
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CloudDir = Join-Path $ProjectDir "cloud"
if (-not $BackupDir) {
    $BackupDir = Join-Path $CloudDir "backups"
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $BackupDir "progetto_iot_$timestamp.sql"

Push-Location $CloudDir
try {
    Write-Host "Creo backup PostgreSQL: $backupFile"
    docker compose exec -T postgres pg_dump -U iot_backend -d progetto_iot > $backupFile
    if ($LASTEXITCODE -ne 0) {
        throw "Backup PostgreSQL fallito."
    }
}
finally {
    Pop-Location
}

Get-ChildItem $BackupDir -Filter "progetto_iot_*.sql" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepLast |
    Remove-Item -Force

Write-Host "Backup completato."
Write-Host $backupFile
