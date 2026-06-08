#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# SCENE.3D — Quick start (no Docker required)
# Starts the Python backend + opens the frontend in your browser
# ──────────────────────────────────────────────────────────────────
set -e

PYTHON=${PYTHON:-python3}

echo ""
echo "  ███████╗ ██████╗███████╗███╗   ██╗███████╗    ██████╗ ██████╗ "
echo "  ██╔════╝██╔════╝██╔════╝████╗  ██║██╔════╝    ╚════██╗██╔══██╗"
echo "  ███████╗██║     █████╗  ██╔██╗ ██║█████╗       █████╔╝██║  ██║"
echo "  ╚════██║██║     ██╔══╝  ██║╚██╗██║██╔══╝       ╚═══██╗██║  ██║"
echo "  ███████║╚██████╗███████╗██║ ╚████║███████╗    ██████╔╝██████╔╝"
echo "  ╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═══╝╚══════╝    ╚═════╝ ╚═════╝ "
echo ""
echo "  Video-to-3D Reconstruction System"
echo "  ──────────────────────────────────"
echo ""

# ── Check Python ────────────────────────────────────────────────
if ! command -v $PYTHON &>/dev/null; then
  echo "  ✗ Python 3 not found. Install from https://python.org"
  exit 1
fi
echo "  ✓ Python: $($PYTHON --version)"

# ── Install dependencies ─────────────────────────────────────────
echo ""
echo "  Installing Python dependencies..."
$PYTHON -m pip install -q -r backend/requirements.txt
echo "  ✓ Dependencies installed"

# ── Check COLMAP ─────────────────────────────────────────────────
if command -v colmap &>/dev/null; then
  echo "  ✓ COLMAP found: $(colmap --version 2>&1 | head -1)"
else
  echo "  ⚠ COLMAP not found — will use built-in ORB-based SfM (still works!)"
  echo "    To install COLMAP: https://colmap.github.io/install.html"
fi

# ── Create sessions dir ──────────────────────────────────────────
mkdir -p sessions

# ── Start backend ────────────────────────────────────────────────
echo ""
echo "  Starting backend on http://localhost:8000 ..."
cd backend
$PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# Wait for backend to be ready
echo "  Waiting for backend..."
for i in {1..20}; do
  if curl -s http://localhost:8000/docs &>/dev/null; then
    echo "  ✓ Backend ready"
    break
  fi
  sleep 0.5
done

# ── Serve frontend ────────────────────────────────────────────────
echo ""
echo "  Starting frontend on http://localhost:3000 ..."
$PYTHON -m http.server 3000 --directory frontend &
FRONTEND_PID=$!

# ── Open browser ─────────────────────────────────────────────────
FRONTEND_URL="http://localhost:3000"
echo ""
echo "  ═══════════════════════════════════════════"
echo "  🎥  Open on your phone / browser:"
echo ""
# Try to get local IP
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$LOCAL_IP" ]; then
  echo "      http://${LOCAL_IP}:3000"
  echo "      (both this machine and your phone on the same WiFi)"
fi
echo "      http://localhost:3000   (this machine only)"
echo "  ═══════════════════════════════════════════"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# Open in browser
if command -v xdg-open &>/dev/null; then
  xdg-open $FRONTEND_URL &
elif command -v open &>/dev/null; then
  open $FRONTEND_URL &
fi

# Wait
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo '  Stopped.'" EXIT
wait
