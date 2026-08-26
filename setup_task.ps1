# Register/update the DailyEmailBrief scheduled task
# Usage: powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
# Default runs daily at 09:05; edit $Time below to change.
$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$TaskName  = "DailyEmailBrief"
$Time      = "09:05"

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ProjectDir\run_daily.bat`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Daily email brief" -Force | Out-Null

Write-Host ""
Write-Host "Task registered: $TaskName (daily at $Time)"
Write-Host "  Run once:     schtasks /run /tn $TaskName"
Write-Host "  Check status: schtasks /query /tn $TaskName"
Write-Host ""
