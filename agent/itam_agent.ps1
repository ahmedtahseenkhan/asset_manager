# IT Asset Manager - Windows inventory agent (schema v2)
#
# Collects hardware, OS, software, hotfixes, services, local accounts and
# admin-group members, security posture (antivirus, firewall, BitLocker, TPM,
# Secure Boot), disks, network adapters, monitors and printers, and reports
# them to the server. Windows PowerShell 5.1+; no modules to install.
#
#   powershell -ExecutionPolicy Bypass -File itam_agent.ps1 -Server "http://itam.corp.local:8080" -Token "<agent-token>"
#   powershell -ExecutionPolicy Bypass -File itam_agent.ps1 -DryRun     # print the report, send nothing
#
# -Server/-Token fall back to the ITAM_SERVER / ITAM_TOKEN environment variables.
# Run as an administrator or SYSTEM (install_agent.ps1 does) for complete data:
# BitLocker, TPM and some account details need elevation.

param(
    [string]$Server = $env:ITAM_SERVER,
    [string]$Token = $env:ITAM_TOKEN,
    [switch]$DryRun
)

$AgentVersion = '2.0.0'
$ErrorActionPreference = 'Stop'

# Run one collector. A collector that fails reports $null ("not collected") so
# the server keeps what it had instead of wiping it. The leading comma keeps
# PowerShell from unrolling a 0- or 1-element array into $null or a scalar.
function Invoke-Section([string]$Name, [scriptblock]$Block) {
    try { $r = & $Block; return , $r }
    catch { Write-Warning "$Name failed: $($_.Exception.Message)"; return $null }
}

function To-Date($d) {
    if ($null -eq $d -or "$d" -eq '') { return $null }
    try { return ([datetime]$d).ToString('yyyy-MM-dd') } catch { return $null }
}

function To-Iso($d) {
    if ($null -eq $d) { return $null }
    try { return ([datetime]$d).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } catch { return $null }
}

function Get-Cim([string]$Class, [string]$Namespace = 'root/cimv2', [string]$Filter = $null) {
    if ($Filter) { return @(Get-CimInstance -Namespace $Namespace -ClassName $Class -Filter $Filter) }
    return @(Get-CimInstance -Namespace $Namespace -ClassName $Class)
}

$os   = Invoke-Section 'os'   { (Get-Cim Win32_OperatingSystem)[0] }
$cs   = Invoke-Section 'cs'   { (Get-Cim Win32_ComputerSystem)[0] }
$bios = Invoke-Section 'bios' { (Get-Cim Win32_BIOS)[0] }

# -- hardware ----------------------------------------------------------------
$hardware = Invoke-Section 'hardware' {
    $cpus  = Get-Cim Win32_Processor
    $board = (Get-Cim Win32_BaseBoard)[0]
    $csp   = (Get-Cim Win32_ComputerSystemProduct)[0]
    $disk  = (Get-Cim Win32_LogicalDisk -Filter 'DriveType=3' | Measure-Object -Property Size -Sum).Sum
    $chassis = switch ([int]$cs.PCSystemType) { 1 { 'desktop' } 2 { 'laptop' } 3 { 'desktop' } 4 { 'server' } 5 { 'server' } 7 { 'server' } default { $null } }
    $virtual = ($cs.Model -match 'Virtual|VMware|KVM|HVM domU|Parallels') -or ($cs.Manufacturer -match 'VMware|QEMU|Xen|innotek|Parallels')
    @{
        manufacturer  = $cs.Manufacturer
        model         = $cs.Model
        serial_number = $bios.SerialNumber
        hardware_uuid = $csp.UUID
        chassis_type  = $chassis
        is_virtual    = [bool]$virtual
        cpu           = "$($cpus[0].Name)".Trim()
        cpu_cores     = [int](($cpus | Measure-Object -Property NumberOfCores -Sum).Sum)
        cpu_logical   = [int]$cs.NumberOfLogicalProcessors
        ram_gb        = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        disk_gb       = [math]::Round($disk / 1GB, 1)
        bios_vendor   = $bios.Manufacturer
        bios_version  = $bios.SMBIOSBIOSVersion
        bios_date     = To-Date $bios.ReleaseDate
        motherboard   = ("{0} {1}" -f $board.Manufacturer, $board.Product).Trim()
    }
}

# -- software (machine-wide + loaded user hives) -----------------------------
$software = Invoke-Section 'software' {
    $paths = @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'Registry::HKEY_USERS\*\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $seen = @{}
    $items = foreach ($p in $paths) {
        Get-ItemProperty $p -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 -and $_.ReleaseType -notin @('Update', 'Hotfix', 'Security Update') } |
            ForEach-Object {
                $key = "$($_.DisplayName)|$($_.DisplayVersion)"
                if (-not $seen.ContainsKey($key)) {
                    $seen[$key] = $true
                    $installed = $null
                    if ("$($_.InstallDate)" -match '^\d{8}$') { $installed = "$($_.InstallDate)".Insert(6, '-').Insert(4, '-') }
                    @{ name = "$($_.DisplayName)".Trim(); version = "$($_.DisplayVersion)"; publisher = "$($_.Publisher)"; install_date = $installed }
                }
            }
    }
    , @($items)
}

# -- hotfixes ----------------------------------------------------------------
$patches = Invoke-Section 'patches' {
    , @(Get-HotFix | Where-Object { $_.HotFixID } | ForEach-Object {
        @{ id = $_.HotFixID; description = $_.Description; installed_on = To-Date $_.InstalledOn }
    })
}

# -- services ----------------------------------------------------------------
$services = Invoke-Section 'services' {
    , @(Get-Cim Win32_Service | ForEach-Object {
        @{ name = $_.Name; display_name = $_.DisplayName; state = "$($_.State)".ToLower(); start_mode = "$($_.StartMode)".ToLower(); account = $_.StartName }
    })
}

# -- local accounts + Administrators group -----------------------------------
$accounts = Invoke-Section 'local_accounts' {
    $adminSid = 'S-1-5-32-544'
    try {
        $members = @(Get-LocalGroupMember -SID $adminSid | ForEach-Object { "$($_.Name)" })
    } catch {
        # Orphaned SIDs make Get-LocalGroupMember throw; the ADSI provider still lists members.
        $groupName = (Get-LocalGroup -SID $adminSid).Name
        $group = [ADSI]"WinNT://$env:COMPUTERNAME/$groupName,group"
        $members = @($group.psbase.Invoke('Members') | ForEach-Object { $_.GetType().InvokeMember('Name', 'GetProperty', $null, $_, $null) })
    }
    $local = "$env:COMPUTERNAME\"
    $adminLocal = @{}
    foreach ($m in $members) { $adminLocal[($m -replace [regex]::Escape($local), '')] = $true }

    $list = New-Object System.Collections.ArrayList
    foreach ($u in @(Get-LocalUser)) {
        [void]$list.Add(@{ name = $u.Name; enabled = [bool]$u.Enabled; is_admin = [bool]$adminLocal[$u.Name]; last_logon = To-Iso $u.LastLogon })
        $adminLocal.Remove($u.Name)
    }
    # Remaining admin members are domain users/groups (e.g. CORP\Domain Admins).
    foreach ($name in $adminLocal.Keys) { [void]$list.Add(@{ name = $name; is_admin = $true }) }
    , @($list)
}

# -- security posture --------------------------------------------------------
$security = Invoke-Section 'security' {
    $sec = @{}

    $av = $null
    try {
        # Workstations: Security Center knows every registered product.
        $av = @(Get-Cim AntiVirusProduct -Namespace 'root/SecurityCenter2' | ForEach-Object {
            $hex = '{0:X6}' -f [int]$_.productState
            @{ name = $_.displayName; enabled = ($hex.Substring(2, 2) -in @('10', '11')); up_to_date = ($hex.Substring(4, 2) -eq '00') }
        })
    } catch {
        try {
            # Servers have no Security Center; ask Defender directly.
            $mp = Get-MpComputerStatus
            $av = @(@{ name = 'Microsoft Defender Antivirus'; enabled = [bool]$mp.AntivirusEnabled
                       up_to_date = ([int]$mp.AntivirusSignatureAge -le 7); definitions_date = To-Date $mp.AntivirusSignatureLastUpdated })
        } catch { $av = $null }
    }
    if ($null -ne $av) { $sec.antivirus = @($av) }

    try {
        $sec.firewall = @(Get-NetFirewallProfile | ForEach-Object { @{ profile = "$($_.Name)"; enabled = ("$($_.Enabled)" -eq 'True') } })
    } catch { }

    try {
        $sec.encryption = @(Get-BitLockerVolume | Where-Object { "$($_.VolumeType)" -in @('OperatingSystem', 'FixedData') } | ForEach-Object {
            @{ volume = $_.MountPoint; method = 'BitLocker'; protected = ("$($_.ProtectionStatus)" -eq 'On'); status = "$($_.VolumeStatus)" }
        })
    } catch {
        try {
            $sec.encryption = @(Get-Cim Win32_EncryptableVolume -Namespace 'root/cimv2/Security/MicrosoftVolumeEncryption' | ForEach-Object {
                @{ volume = $_.DriveLetter; method = 'BitLocker'; protected = ([int]$_.ProtectionStatus -eq 1) }
            })
        } catch { }
    }

    try { $tpm = Get-Tpm; $sec.tpm_present = [bool]$tpm.TpmPresent; $sec.tpm_ready = [bool]$tpm.TpmReady } catch { }
    try { $sec.secure_boot = [bool](Confirm-SecureBootUEFI) }
    catch [System.PlatformNotSupportedException] { $sec.secure_boot = $false }   # legacy BIOS boot
    catch { }                                                                     # not elevated: unknown
    $sec
}

# -- disks, network, monitors, printers --------------------------------------
$disks = Invoke-Section 'disks' {
    , @(Get-Cim Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
        @{ name = $_.DeviceID; filesystem = $_.FileSystem; size_gb = [math]::Round($_.Size / 1GB, 1); free_gb = [math]::Round($_.FreeSpace / 1GB, 1) }
    })
}

$nics = Invoke-Section 'network_adapters' {
    $speeds = @{}
    foreach ($a in Get-Cim Win32_NetworkAdapter) { if ($a.Speed) { $speeds[[int]$a.Index] = [int]([int64]$a.Speed / 1000000) } }
    , @(Get-Cim Win32_NetworkAdapterConfiguration -Filter 'IPEnabled = TRUE' | ForEach-Object {
        $gw = @($_.DefaultIPGateway | Where-Object { $_ -match '^\d+\.' })
        @{
            name         = $_.Description
            mac          = $_.MACAddress
            ip_addresses = @($_.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })
            speed_mbps   = $speeds[[int]$_.Index]
            dhcp         = [bool]$_.DHCPEnabled
            gateway      = $(if ($gw.Count) { $gw[0] } else { $null })
            dns_servers  = @($_.DNSServerSearchOrder)
        }
    })
}

$pnpVendors = @{ DEL = 'Dell'; SAM = 'Samsung'; LEN = 'Lenovo'; HWP = 'HP'; HPN = 'HP'; ACR = 'Acer'; AUS = 'ASUS'; GSM = 'LG'; LGD = 'LG Display'
                 BNQ = 'BenQ'; PHL = 'Philips'; VSC = 'ViewSonic'; AOC = 'AOC'; SNY = 'Sony'; APP = 'Apple'; BOE = 'BOE'; AUO = 'AU Optronics'
                 CMN = 'Innolux'; SHP = 'Sharp'; MSI = 'MSI'; IVM = 'Iiyama'; NEC = 'NEC'; EIZ = 'EIZO'; FUS = 'Fujitsu' }
function Decode-Edid($codes) { (($codes | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ }) -join '').Trim() }

$monitors = Invoke-Section 'monitors' {
    , @(Get-Cim WmiMonitorID -Namespace 'root/wmi' | ForEach-Object {
        $code = Decode-Edid $_.ManufacturerName
        $vendor = $pnpVendors[$code]
        if (-not $vendor) { $vendor = $code }
        @{ manufacturer = $vendor; model = Decode-Edid $_.UserFriendlyName; serial_number = Decode-Edid $_.SerialNumberID }
    })
}

$printers = Invoke-Section 'printers' {
    , @(Get-Cim Win32_Printer | ForEach-Object {
        @{ name = $_.Name; driver = $_.DriverName; port = $_.PortName; is_network = [bool]$_.Network; is_default = [bool]$_.Default }
    })
}

$pendingReboot = Invoke-Section 'pending_reboot' {
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
    ($null -ne (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue))
}

# -- assemble ----------------------------------------------------------------
$build = $null
if ($os) {
    $build = "$($os.BuildNumber)"
    $ubr = Invoke-Section 'ubr' { (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR }
    if ($ubr) { $build = "$build.$ubr" }    # e.g. 22631.4317 - the cumulative-update level
}

$fqdn = $env:COMPUTERNAME
try { $fqdn = [System.Net.Dns]::GetHostEntry('').HostName } catch { }

$domain = $null
if ($cs -and $cs.PartOfDomain) { $domain = $cs.Domain }

$ipList = @()
$macList = @()
if ($nics) {
    $ipList = @($nics | ForEach-Object { $_.ip_addresses } | Where-Object { $_ -and $_ -notmatch '^(127\.|169\.254\.)' } | Sort-Object -Unique)
    $macList = @($nics | ForEach-Object { $_.mac } | Where-Object { $_ } | Sort-Object -Unique)
}

$report = [ordered]@{
    schema_version    = 2
    collector_version = $AgentVersion
    hostname          = $env:COMPUTERNAME
    fqdn              = $fqdn
    domain            = $domain
    os_name           = $(if ($os) { "$($os.Caption)".Trim() } else { $null })
    os_version        = $(if ($os) { $os.Version } else { $null })
    os_build          = $build
    architecture      = $(if ($os) { $os.OSArchitecture } else { $null })
    last_boot         = $(if ($os) { To-Iso $os.LastBootUpTime } else { $null })
    logged_in_user    = $(if ($cs) { $cs.UserName } else { $null })
    pending_reboot    = $pendingReboot
    ip_addresses      = $ipList
    mac_addresses     = $macList
    hardware          = $hardware
    software          = $software
    patches           = $patches
    services          = $services
    local_accounts    = $accounts
    security          = $security
    disks             = $disks
    network_adapters  = $nics
    monitors          = $monitors
    printers          = $printers
}

$json = $report | ConvertTo-Json -Depth 6 -Compress

if ($DryRun) {
    $report | ConvertTo-Json -Depth 6
    exit 0
}
if (-not $Server -or -not $Token) {
    Write-Error 'Server and Token are required (or set ITAM_SERVER / ITAM_TOKEN).'
    exit 2
}

try {
    # Windows PowerShell 5.1 defaults to TLS 1.0; HTTPS servers need 1.2.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $body = [System.Text.Encoding]::UTF8.GetBytes($json)
    $r = Invoke-RestMethod -Uri ($Server.TrimEnd('/') + '/api/ingest/agent') -Method Post `
        -Headers @{ 'X-Agent-Token' = $Token } -ContentType 'application/json; charset=utf-8' -Body $body
    Write-Host 'Reported OK:' ($r | ConvertTo-Json -Compress -Depth 4)
} catch {
    Write-Error "Report failed: $($_.Exception.Message)"
    exit 1
}
