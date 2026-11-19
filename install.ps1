# ember installer for Windows 10 and 11.
# NOT TESTED on a real Windows computer as of writing. See README.md, "Honest limits".
# What it does: installs uv if missing, makes the data folder and the secret,
# and sets the mind to start by itself every time you log in.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# 1. uv looks after Python so you don't have to.
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path $uv)) {
    Write-Host "Installing uv..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
}
if (-not (Test-Path $uv)) { throw "uv did not install. Install it from https://docs.astral.sh/uv/ and run this again." }

# 2. Get the mind ready, make the data folder and the secret, and show the address.
Write-Host "Getting the mind ready (the first time takes a minute)..."
& $uv sync --no-dev --quiet
if ($LASTEXITCODE -ne 0) { throw "Could not get the mind ready (uv sync failed)." }
& $uv run --no-dev ember --setup
if ($LASTEXITCODE -ne 0) { throw "Could not set up the mind." }

# 3. Start at logon, hidden. First choice: a Scheduled Task. If Windows refuses, a Startup shortcut.
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$uv' run --project '$here' --no-dev ember`""
try {
    Stop-ScheduledTask -TaskName "ember" -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $here
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName "ember" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName "ember"
    $how = "a Scheduled Task called 'ember'"
} catch {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "ember.lnk"
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $here
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden
    $how = "a shortcut in your Startup folder ($shortcutPath)"
}

Start-Sleep -Seconds 5
Write-Host ""
Write-Host "Done. The mind is running, and it will start by itself when you log in ($how)."
Write-Host ""
Write-Host "What to do next:"
Write-Host "  1. Your look page is opening in your browser: http://127.0.0.1:8971/"
Write-Host "     If it does not open, wait a minute and open that address yourself."
Write-Host "  2. Open GUIDE-HUMAN.md and carry on from step 3 (getting an https address)."
Write-Host "  3. Do not move or rename this folder. The mind runs from here."
Start-Process "http://127.0.0.1:8971/"
