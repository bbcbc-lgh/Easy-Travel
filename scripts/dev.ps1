# 一键启动开发环境（Windows / PowerShell 5.1+）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "[setup] creating virtualenv ..." -ForegroundColor Cyan
    python -m venv (Join-Path $backend ".venv")
}

Write-Host "[setup] installing backend dependencies ..." -ForegroundColor Cyan
& $python -m pip install -q -r (Join-Path $backend "requirements.txt")

if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Host "[setup] created .env — fill in LLM_API_KEY / AMAP_WEB_KEY, then restart." -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[setup] installing frontend dependencies ..." -ForegroundColor Cyan
    Push-Location $frontend
    npm install
    Pop-Location
}

Write-Host "[run] backend  http://127.0.0.1:8000  (docs: /docs)" -ForegroundColor Green
$backendProcess = Start-Process -PassThru -WindowStyle Hidden `
    -FilePath $python `
    -ArgumentList "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory $backend

try {
    Write-Host "[run] frontend http://127.0.0.1:5173" -ForegroundColor Green
    Push-Location $frontend
    npm run dev
}
finally {
    Pop-Location
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[stop] services stopped." -ForegroundColor DarkGray
}
