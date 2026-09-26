$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Eseguire una volta da PowerShell come amministratore. Non e' necessario disabilitare il firewall."
}
$name = "IoT-Backend-MQTT-LAN"
if (-not (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $name -DisplayName "IoT backend e MQTT TLS - rete privata locale" `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080,8883 `
        -Profile Private -RemoteAddress LocalSubnet | Out-Null
}
Write-Host "Regola pronta: TCP 8080/8883, solo profilo Privato e sottorete locale."
Write-Host "Verificare che la rete fidata sia classificata Privata. Non aperti PostgreSQL, MQTT 1883 o frontend."
