# IT Asset Manager — Windows inventory agent
# Collects real hardware/OS/software detail and reports it to the server.
# Run once, or schedule via Task Scheduler (daily). Requires no admin for most fields.
#
#   powershell -ExecutionPolicy Bypass -File itam_agent.ps1 `
#       -Server "http://itam.corp.local:8000" -Token "<agent-token>"

param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Token
)

$ErrorActionPreference = "SilentlyContinue"

$os   = Get-CimInstance Win32_OperatingSystem
$cs   = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$disk = (Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Measure-Object -Property Size -Sum).Sum

# Installed software from both registry hives (catches 32- and 64-bit).
$paths = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$software = foreach ($p in $paths) {
    Get-ItemProperty $p | Where-Object { $_.DisplayName } | ForEach-Object {
        @{ name = $_.DisplayName; version = "$($_.DisplayVersion)"; publisher = "$($_.Publisher)" }
    }
}
$software = $software | Sort-Object { $_.name } -Unique

$ips  = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }).IPAddress
$macs = (Get-NetAdapter | Where-Object { $_.Status -eq "Up" }).MacAddress

$payload = @{
    hostname       = $env:COMPUTERNAME
    fqdn           = "$($env:COMPUTERNAME).$($env:USERDNSDOMAIN)".TrimEnd(".")
    machine_id     = (Get-CimInstance Win32_ComputerSystemProduct).UUID
    os_name        = "Windows"
    os_version     = "$($os.Caption) $($os.Version)"
    domain         = $cs.Domain
    serial_number  = $bios.SerialNumber
    manufacturer   = $cs.Manufacturer
    model          = $cs.Model
    cpu            = $cpu.Name
    ram_gb         = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    disk_gb        = [math]::Round($disk / 1GB, 1)
    logged_in_user = $cs.UserName
    ip_addresses   = @($ips)
    mac_addresses  = @($macs)
    software       = @($software)
} | ConvertTo-Json -Depth 5 -Compress

try {
    $r = Invoke-RestMethod -Uri "$Server/api/ingest/agent" -Method Post `
        -Headers @{ "X-Agent-Token" = $Token } -ContentType "application/json" -Body $payload
    Write-Host "Reported OK:" ($r | ConvertTo-Json -Compress)
} catch {
    Write-Error "Report failed: $_"
    exit 1
}
