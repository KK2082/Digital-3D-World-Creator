# Digital-3D-World-Creator — Real-Time Video to 3D Reconstruction

Using your phone camera to capture the reality, then the 3D representation is created in the digital world.

> Point your phone at a room. Walk around it. Watch it become a 3D model.

---

## What it does

Digital-3D-World-Creator takes a short phone video (or live camera stream) of an indoor space and reconstructs a geometrically coherent, semantically labelled 3D point cloud. It runs entirely on your own machine — no cloud, no GPU required.

**Pipeline at a glance:**

```
Phone camera  →  Frame extraction  →  Feature matching  →  3D triangulation
     ↓                                                            ↓
  Live UI    ←  Three.js viewer   ←  Semantic labels   ←  Point cloud cleanup
```

---

## Features

| Feature | Description |
|---|---|
| 📱 Live camera capture | Streams frames directly from phone browser |
| 🎬 Video file upload | Drop a `.mp4` / `.mov` video instead |
| ⚡ Dual SfM engine | Uses COLMAP (if installed) or built-in ORB-based triangulation |
| 🧊 Dense point cloud | Statistical outlier removal + voxel downsampling |
| 🏠 Semantic labels | Floor / wall / ceiling / furniture via normal + height analysis |
| 🌐 3D viewer | Interactive Three.js viewer with orbit, pinch-zoom, touch |
| 💾 Export | Download `.ply` point cloud for Blender / MeshLab / CloudCompare |
| 🔌 Offline demo | Works without backend to show example scene |

---

## Folder structure

```
Digital-3D-World-Creator/
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html
├── start.ps1            ← Windows start script
├── start.sh             ← Mac/Linux start script
└── docker-compose.yml
```

---

## Requirements

- **Python 3.10–3.11** (Python 3.12+ not supported due to Open3D)
- **COLMAP** *(optional but recommended for higher quality)*

### Python packages
```
fastapi  uvicorn  opencv-python-headless  open3d  numpy  scipy
```

---

## Quick start

### Option A — One command (Mac / Linux)
```bash
git clone https://github.com/KK2082/Digital-3D-World-Creator.git
cd Digital-3D-World-Creator
chmod +x start.sh
./start.sh
```

### Option B — Windows PowerShell
```powershell
git clone https://github.com/KK2082/Digital-3D-World-Creator.git
cd Digital-3D-World-Creator
.\start.ps1
```

### Option C — Docker Compose
```bash
docker compose up --build
```

### Option D — Manual (recommended for first-time setup)
```powershell
# Create and activate virtual environment (Python 3.11 required)
py -3.11 -m venv venv
venv\Scripts\activate

# Terminal 1 — backend
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend (open a new PowerShell window)
cd Digital-3D-World-Creator
python -m http.server 3000 --directory frontend
```

Then open **http://localhost:3000** in your browser.

---

## Using on your phone

The easiest and most reliable method is to **record a video and upload it**:

1. Record a slow 30–60 second video on your phone panning around the room
2. Send it to your laptop (WhatsApp, Google Drive, email, USB)
3. Open `http://localhost:3000` on your laptop
4. Click the **upload area** at the bottom and select your video
5. Click **Reconstruct 3D Scene**
6. Switch to the **3D Viewer** tab

### Live camera from phone (advanced)
If you want to use your phone as a live camera:

1. Make sure your phone and laptop are on the **same WiFi** (note: university/managed networks may block this — use your phone's hotspot instead)
2. Find your laptop's IP: run `ipconfig` and look for the IPv4 address under Wi-Fi
3. Open `http://LAPTOP_IP:3000` on your phone
4. If camera access is blocked (Chrome requires https for camera), use [ngrok](https://ngrok.com) to create a secure tunnel:
   ```powershell
   ngrok http 3000
   ```
   Then open the `https://` URL ngrok provides on your phone

### Tips for best results
- Move **slowly and steadily** — fast motion = blurry frames = fewer matches
- Ensure **good lighting** — reconstruction needs visible texture
- Aim for **30–120 frames** (15–60 seconds of slow panning)
- Overlap adjacent views by ~60% for robust feature matching
- Avoid **featureless surfaces** (plain white walls) — add some objects for texture

---

## Architecture & Design Choices

### Why dual-engine SfM?

**COLMAP** (when installed) gives production-quality sparse reconstruction via:
- SIFT feature extraction with GPU-optional matching
- Sequential matcher (ideal for video, exploits temporal ordering)
- Bundle adjustment to minimise reprojection error

**Built-in ORB triangulation** (fallback, no install needed):
- ORB feature matching between consecutive frame pairs
- Essential matrix estimation via RANSAC
- Pose recovery + linear triangulation
- Less accurate but fully self-contained — works out of the box

The system auto-detects COLMAP and falls back gracefully.

### Why Open3D for post-processing?
Open3D provides battle-tested implementations of:
- Statistical outlier removal (protects against noisy points)
- Voxel downsampling (keeps viewer responsive)
- Poisson surface reconstruction (optional mesh from normals)
- Normal estimation + consistent orientation

### Why height-based semantics?
Monocular video doesn't carry enough information to run SAM/Mask2Former in real time without a GPU. The lightweight normal + height heuristic correctly classifies floor/ceiling/wall/furniture in most indoor scenes without requiring any model download. Labels align with the point cloud by construction, satisfying geometric coherence.

For richer semantics, the architecture is designed to swap in SAM2 + point projection with a single function replacement.

### Frontend API connection
The frontend automatically connects to the backend using `window.location.hostname`, so it works on any machine without configuration changes:
```javascript
const API = `http://${window.location.hostname}:8000`;
```

---

## Output files

After reconstruction, files are saved to `sessions/<id>/outputs/`:

| File | Description |
|---|---|
| `pointcloud.json` | Points + colours + semantic labels (Three.js format) |
| `pointcloud.ply` | Standard PLY — open in Blender, MeshLab, CloudCompare |
| `mesh.obj` | Poisson mesh (if ≥ 500 points and normals available) |

---

## Example output

```
Session: a3f7b2c1
Frames captured: 87
Deduplicated: 87 → 52 unique frames
COLMAP SfM: 4,213 sparse points
After cleaning: 3,891 points
Semantic labels: floor×892 wall×1204 ceiling×621 furniture×1174
Poisson mesh: 8,442 triangles
```

---

## Extending

| What | Where |
|---|---|
| Swap in SAM2 semantics | `assign_semantic_labels()` in `backend/main.py` |
| Add depth estimation (MiDaS) | After `dense_reconstruction_fallback()` in `backend/main.py` |
| WebRTC for lower latency | Replace fetch-frame loop in `frontend/index.html` |
| NeRF export | Add `export_nerf_transforms()` using COLMAP camera poses |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `open3d` install fails | Use Python 3.11 — `py -3.11 -m venv venv` |
| Backend offline in browser | Run uvicorn from inside the `backend/` folder |
| Phone can't reach laptop | Use phone hotspot instead of university WiFi |
| Camera blocked on phone | Use video upload instead, or use ngrok for https |
| `.\start.ps1` not recognised | Run PowerShell from the project root folder |

---

## License

MIT — do whatever you want with it.

---

*Built for the internship challenge. Questions? Open an issue.*
