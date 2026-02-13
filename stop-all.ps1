# 停止所有 LedgerLens 前端和后端进程
Write-Host "Stopping all LedgerLens processes..." -ForegroundColor Yellow

# 停止前端 (Node.js)
Write-Host "`n[1/2] Stopping frontend (Node.js)..." -ForegroundColor Cyan
Get-Process -Name node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  Frontend stopped" -ForegroundColor Green

# 停止后端 (Python/Uvicorn)
Write-Host "`n[2/2] Stopping backend (Python)..." -ForegroundColor Cyan
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmd -like "*uvicorn*" -or $cmd -like "*run_backend*"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  Backend stopped" -ForegroundColor Green

Write-Host "`nAll processes stopped successfully!" -ForegroundColor Green
Write-Host "(Zombie port occupations will be auto-released by Windows)" -ForegroundColor Gray
