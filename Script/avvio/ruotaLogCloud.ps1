param(
    [long] $MaxBytes = 10485760,
    [int] $KeepLast = 5
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$LogDir = Join-Path $ProjectDir "cloud\mqtt\log"

if (-not (Test-Path $LogDir)) {
    Write-Host "Cartella log MQTT non presente: $LogDir"
    exit 0
}

Get-ChildItem $LogDir -File -Filter "*.log" | ForEach-Object {
    if ($_.Length -lt $MaxBytes) {
        return
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archivePath = Join-Path $_.DirectoryName "$($_.BaseName).$timestamp.log"
    Move-Item -LiteralPath $_.FullName -Destination $archivePath -Force
    New-Item -ItemType File -Path $_.FullName -Force | Out-Null
    Write-Host "Ruotato log: $($_.Name) -> $(Split-Path -Leaf $archivePath)"
}

Get-ChildItem $LogDir -File -Filter "*.log" |
    Where-Object { $_.Name -match "\.\d{8}-\d{6}\.log$" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepLast |
    Remove-Item -Force

Write-Host "Rotazione log completata."
