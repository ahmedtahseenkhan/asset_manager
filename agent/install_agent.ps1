# IT Asset Manager - Windows agent installer
#
# Installs the inventory agent to %ProgramData%\ITAM and schedules it as SYSTEM:
# daily (with a random delay so a fleet doesn't report at the same second) and
# 10 minutes after every boot. Then runs it once and shows the result.
# Run from an elevated PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File install_agent.ps1 -Server "http://itam.corp.local:8080" -Token "<agent-token>"
#   powershell -ExecutionPolicy Bypass -File install_agent.ps1 -Uninstall
#
# If itam_agent.ps1 sits next to this script it is used as-is; otherwise it is
# downloaded from the server. For GPO/Intune rollout, deploy both files and run
# this script with the same arguments.

param(
    [string]$Server,
    [string]$Token,
    [string]$Time = '09:00',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'ITAM Inventory Agent'
$InstallDir = Join-Path $env:ProgramData 'ITAM'
$AgentPath = Join-Path $InstallDir 'itam_agent.ps1'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'Run this installer from an elevated (Administrator) PowerShell.'
    exit 1
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'ITAM agent removed.'
    exit 0
}

if (-not $Server -or -not $Token) {
    Write-Error 'Both -Server and -Token are required.'
    exit 2
}
$Server = $Server.TrimEnd('/')

# Folder readable only by SYSTEM and Administrators: the scheduled task's
# arguments carry the enrollment token.
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {   # SYSTEM, Administrators
    $id = New-Object Security.Principal.SecurityIdentifier($sid)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($id, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
}
Set-Acl -Path $InstallDir -AclObject $acl

$local = Join-Path $PSScriptRoot 'itam_agent.ps1'
if ($PSScriptRoot -and (Test-Path $local)) {
    Copy-Item $local $AgentPath -Force
    Write-Host "Using agent from $local"
} else {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri "$Server/api/agents/download/itam_agent.ps1" -OutFile $AgentPath
    Write-Host "Downloaded agent from $Server"
}
Unblock-File $AgentPath

$taskArgs = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AgentPath`" -Server `"$Server`" -Token `"$Token`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArgs
$daily = New-ScheduledTaskTrigger -Daily -At $Time -RandomDelay (New-TimeSpan -Minutes 30)
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = 'PT10M'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$taskPrincipal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily, $boot) -Settings $settings `
    -Principal $taskPrincipal -Description 'Reports hardware and software inventory to IT Asset Manager.' -Force | Out-Null
Write-Host "Scheduled task '$TaskName' registered (daily at $Time + 10 min after boot)."

Write-Host 'Running a first inventory now...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $AgentPath -Server $Server -Token $Token
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'The first report failed (see above). The scheduled task will retry; check the server address and token.'
}
