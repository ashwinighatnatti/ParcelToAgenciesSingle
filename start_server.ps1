# Starts the Django UI in the background on http://127.0.0.1:8000/ (stop it with .\stop_server.ps1)
param([int]$Port = 8000)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
if (-not (Test-Path ".env")) { Write-Host "Missing .env - copy .env.example to .env and fill it in."; exit 1 }
& $py django_ui/manage.py migrate --noinput
$p = Start-Process $py -ArgumentList "django_ui/manage.py","runserver",$Port -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "django_run.log" -RedirectStandardError "django_run.err"
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep 1
    try { if ((Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { Write-Host "Running: http://127.0.0.1:$Port/ (PID $($p.Id))"; exit 0 } } catch {}
}
Write-Host "Server did not respond; see django_run.err"; exit 1
