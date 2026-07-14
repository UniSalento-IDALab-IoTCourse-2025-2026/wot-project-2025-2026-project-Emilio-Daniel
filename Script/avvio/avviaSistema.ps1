param(
    [switch] $Completo,
    [switch] $NoDocker,
    [switch] $NoMigration,
    [switch] $NoWorker,
    [string] $BackendHost = "0.0.0.0",
    [int] $BackendPort = 8080,
    [string] $ReceiverHost = "0.0.0.0",
    [int] $ReceiverPort = 8000,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ExtraArgs
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$EdgeDir = Join-Path $ProjectDir "edge_node"
$CloudDir = Join-Path $ProjectDir "cloud"
$BackendDir = Join-Path $CloudDir "backend"
$ConfigFile = Join-Path $EdgeDir "config\edge.yml"
$LocalPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$StartedProcesses = @()

function Get-LanIp {
    $address = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object InterfaceMetric |
        Select-Object -First 1
    if ($address) {
        return $address.IPAddress
    }
    return "IP_PC_O_RPI"
}

function Test-PortInUse {
    param([int] $Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    return $null -ne $connection
}

function Start-ManagedProcess {
    param(
        [string] $Name,
        [string] $FilePath,
        [string[]] $ArgumentList,
        [string] $WorkingDirectory
    )
    Write-Host "Avvio $Name..."
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -NoNewWindow `
        -PassThru
    $script:StartedProcesses += $process
    Start-Sleep -Seconds 2
}

function Wait-Postgres {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "ATTENZIONE: docker non trovato. Salto attesa PostgreSQL."
        return
    }
    Push-Location $CloudDir
    try {
        for ($i = 1; $i -le 30; $i++) {
            docker compose exec -T postgres pg_isready -U iot_backend -d progetto_iot *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "PostgreSQL pronto."
                return
            }
            Start-Sleep -Seconds 2
        }
        Write-Host "ATTENZIONE: PostgreSQL non risulta pronto dopo l'attesa."
    } finally {
        Pop-Location
    }
}

function Stop-StartedProcesses {
    foreach ($process in $script:StartedProcesses) {
        if ($process -and -not $process.HasExited) {
            Write-Host "Arresto processo $($process.Id)..."
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

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

$LanIp = Get-LanIp

if (Test-PortInUse -Port $ReceiverPort) {
    $owner = Get-NetTCPConnection -LocalPort $ReceiverPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    Write-Host "ERRORE: la porta $ReceiverPort e' gia occupata."
    if ($owner) {
        Write-Host "PID in ascolto: $($owner.OwningProcess)"
        Write-Host "Per chiuderlo, se sei sicuro che sia un vecchio receiver:"
        Write-Host "Stop-Process -Id $($owner.OwningProcess)"
    }
    Write-Host "Non avvio un secondo receiver per evitare conflitti."
    exit 1
}

Push-Location $EdgeDir
try {
    if ($Completo) {
        Write-Host "Avvio sistema IoT completo: Docker + backend + worker MQTT + Edge."
        if (-not (Test-Path $BackendPython)) {
            Write-Host "ERRORE: manca cloud\backend\.venv\Scripts\python.exe"
            Write-Host "Crea l'ambiente backend e installa cloud\backend\requirements.txt."
            exit 1
        }

        if (-not $NoDocker) {
            Push-Location $CloudDir
            try {
                Write-Host "Avvio Docker: mqtt + postgres..."
                docker compose up -d mqtt postgres
                if ($LASTEXITCODE -ne 0) {
                    exit $LASTEXITCODE
                }
            } finally {
                Pop-Location
            }
            Wait-Postgres
        }

        if (-not $NoMigration) {
            Push-Location $BackendDir
            try {
                Write-Host "Migrazioni database Alembic..."
                & $BackendPython -m alembic upgrade head
                if ($LASTEXITCODE -ne 0) {
                    exit $LASTEXITCODE
                }
            } finally {
                Pop-Location
            }
        }

        if (Test-PortInUse -Port $BackendPort) {
            Write-Host "Backend: porta $BackendPort gia in ascolto, riuso il backend esistente."
        } else {
            Start-ManagedProcess `
                -Name "backend clinico su ${BackendHost}:$BackendPort" `
                -FilePath $BackendPython `
                -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $BackendHost, "--port", "$BackendPort") `
                -WorkingDirectory $BackendDir
        }

        if (-not $NoWorker) {
            Start-ManagedProcess `
                -Name "worker MQTT backend" `
                -FilePath $BackendPython `
                -ArgumentList @("-m", "app.mqtt.worker") `
                -WorkingDirectory $BackendDir
        }

        Write-Host ""
        Write-Host "URL da usare nell'app Android:"
        Write-Host "Receiver BLE     http://$LanIp`:$ReceiverPort/ble/sample"
        Write-Host "Backend clinico  http://$LanIp`:$BackendPort/api/v1"
        Write-Host "Backend docs     http://$LanIp`:$BackendPort/docs"
        Write-Host ""
    } else {
        Write-Host "Avvio sistema IoT Edge: receiver + runtime + MQTT se abilitato + baseline automatica 7 giorni."
        Write-Host "Per avviare anche backend e worker MQTT sul PC: .\Script\avvio\avviaSistema.ps1 -Completo"
    }
    Write-Host "Se il modello personale esiste gia, verra usato automaticamente."
    & $PythonExe -m edge_stack.cli --config "config\edge.yml" --host $ReceiverHost --port $ReceiverPort @ExtraArgs
    exit $LASTEXITCODE
} finally {
    Stop-StartedProcesses
    Pop-Location
}
