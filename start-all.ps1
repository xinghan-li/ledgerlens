# 启动 LedgerLens 前端和后端
Write-Host "Starting LedgerLens..." -ForegroundColor Yellow

# 检查并清理残留进程
Write-Host "`n[0] Checking for existing processes..." -ForegroundColor Cyan
$nodeCount = (Get-Process -Name node -ErrorAction SilentlyContinue | Measure-Object).Count
$pythonCount = (Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmd -like "*uvicorn*" -or $cmd -like "*run_backend*"
} | Measure-Object).Count

if ($nodeCount -gt 0 -or $pythonCount -gt 0) {
    Write-Host "  Found existing processes. Running cleanup..." -ForegroundColor Yellow
    & "$PSScriptRoot\stop-all.ps1"
    Start-Sleep -Seconds 2
}

# 启动后端
Write-Host "`n[1/2] Starting backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend'; python run_backend.py"
Write-Host "  Backend starting (check new window)" -ForegroundColor Green

# 等待后端写入端口配置
Write-Host "  Waiting for backend to write port config..." -ForegroundColor Gray
Start-Sleep -Seconds 5

# 检查端口配置文件
$portConfigFile = Join-Path $PSScriptRoot "backend-port.json"
if (Test-Path $portConfigFile) {
    $portConfig = Get-Content $portConfigFile | ConvertFrom-Json
    Write-Host "  Backend port detected: $($portConfig.port)" -ForegroundColor Green
} else {
    Write-Host "  Warning: Port config file not found, using default" -ForegroundColor Yellow
}

# 启动前端（会自动读取端口配置）
Write-Host "`n[2/2] Starting frontend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev"
Write-Host "  Frontend starting (will auto-detect backend URL)" -ForegroundColor Green

Write-Host "`nAll services started!" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend: Will auto-select available port (8000-8084)" -ForegroundColor Cyan
Write-Host "`nPress Ctrl+C in each window to stop services" -ForegroundColor Gray
