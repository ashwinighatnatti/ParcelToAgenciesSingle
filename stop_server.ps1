<#
Stops the Django UI and cleans up what it leaves behind.
  .\stop_server.ps1            stop the server (and its reloader child), orphaned pipeline runs and Playwright browsers;
                               delete __pycache__ folders and *.log / *.err files
  .\stop_server.ps1 -Deep      also delete generated results: output\, downloads\, django_ui\db.sqlite3 (search history). Asks first.
  .\stop_server.ps1 -Port 8000 the port to free (default 8000)
Never touches .env, .env_typesafe or source files.
#>
param([int]$Port = 8000, [switch]$Deep)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:killed = 0

function Stop-Tree($procId, $why) {
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        & taskkill /F /T /PID $procId *> $null
        Write-Host "  stopped PID $procId ($why)"
        $script:killed++
    }
}

Write-Host "Stopping Django UI..."
# 1. whatever is listening on the port
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Tree $_.OwningProcess "listening on port $Port" }

# 2. runserver reloader parents and background pipeline runs started from this project
$pattern = 'django_ui[\\/]manage\.py runserver|single_collector\.(run|portals|triage)'
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $pattern } |
    ForEach-Object { Stop-Tree $_.ProcessId "project python process" }

# 3. headless browsers left behind by the portal scripts (only those launched by Playwright)
Get-CimInstance Win32_Process -Filter "Name like 'chrome%' or Name like 'headless_shell%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ms-playwright' } |
    ForEach-Object { Stop-Tree $_.ProcessId "Playwright browser" }

if ($script:killed -eq 0) { Write-Host "  nothing was running" }

Write-Host "Cleaning up..."
Get-ChildItem $root -Recurse -Directory -Filter __pycache__ -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.venv\\' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $root -File -Include *.log, *.err -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Write-Host "  removed __pycache__ folders and server logs"

if ($Deep) {
    $targets = @("output", "downloads", "django_ui\db.sqlite3") |
        ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ }
    if ($targets) {
        Write-Host "Deep clean will DELETE:"
        $targets | ForEach-Object { Write-Host "  $_" }
        if ((Read-Host "Type yes to continue") -eq "yes") {
            $targets | ForEach-Object { Remove-Item $_ -Recurse -Force }
            Write-Host "  deleted. Run 'python django_ui/manage.py migrate' before the next start."
        } else { Write-Host "  skipped" }
    }
}

$still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($still) { Write-Host "Port $Port is STILL in use (PID $($still.OwningProcess))."; exit 1 }
Write-Host "Done. Port $Port is free."
