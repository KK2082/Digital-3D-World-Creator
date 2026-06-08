# SCENE.3D — Quick Start for Windows (PowerShell)
# Run: .\start.ps1 from the repo root

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  SCENE.3D — Video-to-3D Reconstruction" -ForegroundColor Cyan
Write-Host "  ──────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# Check Python
try {
    $pyver = python --version 2>&1
    Write-Host "  OK  Python: $pyver" -ForegroundColor Green
} catch {
    Write-Host "  ERR  Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# Install dependencies
Write-Host ""
Write-Host "  Installing Python dependencies..."
python -m pip install -q -r backend\requirements.txt
Write-Host "  OK  Dependencies ready" -ForegroundColor Green

# Check COLMAP
if (Get-Command colmap -ErrorAction SilentlyContinue) {
    Write-Host "  OK  COLMAP found" -ForegroundColor Green
} else {
    Write-Host "  --  COLMAP not found (built-in ORB-SfM will be used)" -ForegroundColor Yellow
    Write-Host "      Download COLMAP: https://colmap.github.io/install.html" -ForegroundColor DarkGray
}

# Create sessions dir
New-Item -ItemType Directory -Force -Path sessions | Out-Null

# Start backend
Write-Host ""
Write-Host "  Starting backend..."
$backend = Start-Process -FilePath python -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8000" -WorkingDirectory backend -PassThru -NoNewWindow

# Wait for backend to be ready
Start-Sleep -Seconds 2

# Start frontend
Write-Host "  Starting frontend..."
$frontend = Start-Process -FilePath python -ArgumentList "-m","http.server","3000","--directory","frontend" -PassThru -NoNewWindow

# Get local IP
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*" } | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "   Open in your browser / phone:" -ForegroundColor White
Write-Host ""
Write-Host "     http://localhost:3000        (this machine)" -ForegroundColor Yellow
if ($ip) {
    Write-Host "     http://${ip}:3000   (phone on same WiFi)" -ForegroundColor Yellow
}
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray

# Open browser
Start-Process "http://localhost:3000"

# Keep running until Ctrl+C
try {
    while ($true) { Start-Sleep -Seconds 1 }
} finally {
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
    Write-Host "  Stopped." -ForegroundColor DarkGray
}
