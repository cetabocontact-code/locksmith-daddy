# Register 3 Windows Task Scheduler tasks for the daily autopilot
# (Locksmith Daddy). Runs at user level (no admin needed). Subsequent
# changes can be done via Task Scheduler UI or by re-running this.
#
# Times: 8:00 / 14:00 / 20:00 local time (CST).
# Each task invokes scripts/autopilot.py with the appropriate session
# name. Output goes to data/runs/autopilot_{YYYY-MM-DD}_{session}.log.

$ErrorActionPreference = "Stop"

$RepoRoot = "C:\Users\rawes\Downloads\locksmith_brain_tool1"
$Python   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script   = Join-Path $RepoRoot "scripts\autopilot.py"
$LogDir   = Join-Path $RepoRoot "data\runs"

if (-not (Test-Path $Python)) { throw "Python venv not found at $Python" }
if (-not (Test-Path $Script)) { throw "autopilot.py not found at $Script" }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Register-Autopilot {
    param(
        [Parameter(Mandatory)][string]$Session,
        [Parameter(Mandatory)][string]$Time
    )
    $TaskName = "LocksmithDaddy_Autopilot_$Session"
    $LogPath  = Join-Path $LogDir "autopilot_$Session.log"
    # Use cmd /c so stdout+stderr both redirect to the log file
    $Cmd = "cmd"
    $Args = "/c `"`"$Python`" `"$Script`" $Session >> `"$LogPath`" 2>&1`""
    $Action  = New-ScheduledTaskAction -Execute $Cmd -Argument $Args -WorkingDirectory $RepoRoot
    $Trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action `
        -Trigger $Trigger -Settings $Settings `
        -Description "Locksmith Daddy autopilot $Session session" | Out-Null
    Write-Host "Registered: $TaskName at $Time"
}

Register-Autopilot -Session "morning"   -Time "08:00"
Register-Autopilot -Session "afternoon" -Time "14:00"
Register-Autopilot -Session "evening"   -Time "20:00"

Write-Host ""
Write-Host "Done. To remove later:"
Write-Host "  Unregister-ScheduledTask -TaskName 'LocksmithDaddy_Autopilot_morning'   -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName 'LocksmithDaddy_Autopilot_afternoon' -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName 'LocksmithDaddy_Autopilot_evening'   -Confirm:`$false"
