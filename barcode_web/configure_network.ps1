param([string]$InterfaceAlias = 'Wi-Fi 4')

# Run only after choosing to trust this network. No certificate trust is changed.
$ErrorActionPreference = 'Stop'
$scannerRoot = Split-Path -Parent $PSScriptRoot
$scannerData = Join-Path $scannerRoot 'data\barcode_web'
New-Item -ItemType Directory -Force -Path $scannerData | Out-Null
$result = @{ ok = $false; interface = $InterfaceAlias }
try {
    Set-NetConnectionProfile -InterfaceAlias $InterfaceAlias -NetworkCategory Private
    if (-not (Get-NetFirewallRule -Name 'WarehouseBarcodeScannerLAN' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'WarehouseBarcodeScannerLAN' -DisplayName 'Warehouse Barcode Scanner (LAN)' `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765,8766 `
            -RemoteAddress LocalSubnet -Profile Private | Out-Null
    }
    $result.profile = (Get-NetConnectionProfile -InterfaceAlias $InterfaceAlias).NetworkCategory.ToString()
    $result.ok = $result.profile -eq 'Private'
} catch {
    $result.error = $_.Exception.Message
} finally {
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $scannerData 'network-setup.json') -Encoding UTF8
}
if (-not $result.ok) { exit 1 }
