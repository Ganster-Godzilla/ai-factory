#requires -Version 5.1
<#
.SYNOPSIS
    Dashboard 长驻化一键脚本(注册/卸载/启动/停止/状态)。
.DESCRIPTION
    默认用户级(启动文件夹快捷方式,登录后拉起);-Admin 用 Windows 计划任务(开机/无人登录)。
    日志由 cmd 追加,禁 PowerShell > 重定向写 jsonl(见 docs/dashboard-runbook.md)。
.PARAMETER Action
    register | unregister | start | stop | status
.PARAMETER Admin
    使用计划任务(需管理员)替代启动文件夹(默认用户级)。
.EXAMPLE
    powershell -NoProfile -File scripts/dashboard-service.ps1 status
#>
param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('register','unregister','start','stop','status')]
    [string]$Action,
    [switch]$Admin
)

$ErrorActionPreference = 'Stop'
$RepoRoot = 'D:\workspace\ai-factory'
$TaskName = 'OrcDashboard'
$Port = 8321
$PidLock = Join-Path $RepoRoot 'pool\.dashboard.pid'
$DashboardLog = Join-Path $RepoRoot 'pool\dashboard.log'
$StartupDir = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupDir 'OrcDashboard.lnk'

function Write-Log { param([string]$Msg) Write-Host $Msg }

function Get-DashboardPortListening {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $conn)
    } catch { return $false }
}

function Get-LockPid {
    if (-not (Test-Path $PidLock)) { return $null }
    try {
        $content = Get-Content $PidLock -Raw -Encoding UTF8 | ConvertFrom-Json
        return [int]$content.pid
    } catch { return $null }
}

function Test-ProcessAlive {
    param([int]$Pid)
    if ($Pid -le 0) { return $false }
    $proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    return ($null -ne $proc)
}

function Register-Dashboard {
    $cmd = "Set-Location '$RepoRoot'; py -3.11 -m orchestrator.daemon.cli dashboard *>> '$DashboardLog'"
    if ($Admin) {
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command $cmd"
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
        Write-Log "OK 计划任务已注册: $TaskName(AtLogOn,重启3次/1min)"
    } else {
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($ShortcutPath)
        $sc.TargetPath = 'powershell.exe'
        $sc.Arguments = "-NoProfile -WindowStyle Hidden -Command $cmd"
        $sc.WorkingDirectory = $RepoRoot
        $sc.Save()
        Write-Log "OK 启动文件夹快捷方式已创建: $ShortcutPath"
    }
}

function Unregister-Dashboard {
    if ($Admin) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Log "OK 计划任务已卸载: $TaskName"
    } else {
        if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force; Write-Log "OK 快捷方式已删除: $ShortcutPath" }
        else { Write-Log "OK 快捷方式不存在,无需删除" }
    }
}

function Start-Dashboard {
    if (Get-DashboardPortListening) {
        $pid = Get-LockPid
        Write-Log "OK Dashboard 已在运行(PID=$pid,端口 $Port)"
        return
    }
    # cmd 追加日志,避免 PowerShell *> 写 UTF-16
    $cmdLine = "/c cd /d `"$RepoRoot`" && py -3.11 -m orchestrator.daemon.cli dashboard >> `"$DashboardLog`" 2>&1"
    Start-Process -FilePath 'cmd.exe' -ArgumentList $cmdLine -WindowStyle Hidden
    Start-Sleep -Seconds 3
    if (Get-DashboardPortListening) { Write-Log "OK Dashboard 已启动,端口 $Port" }
    else { Write-Log "FAIL Dashboard 启动后端口 $Port 未监听"; exit 1 }
}

function Stop-Dashboard {
    $pid = Get-LockPid
    if ($null -eq $pid) { Write-Log "OK 无 PID 锁,Dashboard 未运行"; return }
    if (Test-ProcessAlive -Pid $pid) {
        Stop-Process -Id $pid -Force
        Start-Sleep -Seconds 2
        if (Test-Path $PidLock) { Remove-Item $PidLock -Force }
        Write-Log "OK Dashboard 已停止(PID=$pid)"
    } else {
        if (Test-Path $PidLock) { Remove-Item $PidLock -Force }
        Write-Log "OK PID 锁已回收(进程 $pid 不存在)"
    }
}

function Get-DashboardStatus {
    $listening = Get-DashboardPortListening
    $pid = Get-LockPid
    $alive = if ($pid) { Test-ProcessAlive -Pid $pid } else { $false }
    $current = ''
    $releaseDir = Join-Path $RepoRoot 'releases'
    if (Test-Path $releaseDir) {
        $cur = Join-Path $releaseDir 'current'
        if (Test-Path $cur) { $current = (Get-Item $cur).Target }
    }
    Write-Log ("端口 {0} 监听: {1}" -f $Port, $listening)
    Write-Log ("锁 PID: {0}  存活: {1}" -f $(if ($pid) { $pid } else { '无' }), $alive)
    if ($current) { Write-Log "current release: $current" }
    if ($listening -and $alive) { Write-Log 'OK 健康'; exit 0 }
    else { Write-Log 'FAIL 不健康'; exit 1 }
}

switch ($Action) {
    'register'   { Register-Dashboard }
    'unregister' { Unregister-Dashboard }
    'start'      { Start-Dashboard }
    'stop'       { Stop-Dashboard }
    'status'     { Get-DashboardStatus }
}
