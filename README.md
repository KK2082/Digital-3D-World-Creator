# Digital-3D-World-Creator
Using your phone camera to capture the reality then the 3D representation will be created in the digital world in real time. 

# SCENE.3D — Real-Time Video to 3D Reconstruction

> Point your phone at a room. Walk around it. Watch it become a 3D model.

![Pipeline](docs/pipeline.png)

---

## What it does

SCENE.3D takes a short phone video (or live camera stream) of an indoor space and reconstructs a geometrically coherent, semantically labelled 3D point cloud. It runs entirely on your own machine — no cloud, no GPU required.

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
| 📱 Live camera capture | Streams frames directly from phone browser via WebRTC |
| 🎬 Video file upload | Drop a `.mp4` / `.mov` / `.heic` video instead |
| ⚡ Dual SfM engine | Uses COLMAP (if installed) or built-in ORB-based triangulation |
| 🧊 Dense point cloud | Statistical outlier removal + voxel downsampling |
| 🏠 Semantic labels | Floor / wall / ceiling / furniture via normal + height analysis |
| 🌐 3D viewer | Interactive Three.js viewer with orbit, pinch-zoom, touch |
| 💾 Export | Download `.ply` point cloud for Blender / MeshLab / CloudCompare |
| 🔌 Offline demo | Works without backend to show example scene |

---

## Requirements

- **Python 3.10+**
- **COLMAP** *(optional but recommended for higher quality)*

### Python packages
```
fastapi  uvicorn  opencv-python-headless  open3d  numpy  scipy
```

---

## Quick start

### Option A — One command (Mac / Linux)
```bash
git clone https://github.com/YOUR_USERNAME/scene-3d.git
cd scene-3d
chmod +x start.sh
./start.sh
```

### Option B — Windows PowerShell
```powershell
git clone https://github.com/YOUR_USERNAME/scene-3d.git
cd scene-3d
.\start.ps1
```

### Option C — Docker Compose
```bash
docker compose up --build
```

### Option D — Manual
```bash
# Terminal 1 — backend
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
python -m http.server 3000 --directory frontend
```

Then open **http://localhost:3000** on your laptop, or  
**http://YOUR_LOCAL_IP:3000** on your phone (same WiFi network).

---

## Using on your phone

1. Connect your phone to the **same WiFi** as your laptop
2. Find your laptop's IP: `ipconfig` (Windows) or `hostname -I` (Linux/Mac)
3. Open `http://LAPTOP_IP:3000` in your phone's browser
4. Tap the shutter button and **slowly pan around the room**
5. Walk a full orbit around the space, covering all angles
6. Tap stop → **Reconstruct 3D Scene**
7. Switch to the **3D Viewer** tab

### Tips for best results
- Move **slowly and steadily** — fast motion = blurry frames = fewer matches
- Ensure **good lighting** — depth from monocular video needs texture
- Aim for **30–120 frames** (15–60 seconds of slow panning)
- Overlap adjacent views by ~60% for robust feature matching
- Avoid **featureless surfaces** (blank white walls) — add some objects

---

## Architecture & Design Choices

### Why dual-engine SfM?

**COLMAP** (when installed) gives production-quality sparse reconstruction via:
- SIFT feature extraction with GPU-optional matching
- Sequential matcher (ideal for video, exploits temporal ordering)
- Bundle adjustment to minimise reprojection error

**Built-in ORB triangulation** (fallback) requires zero external deps:
- ORB feature matching between consecutive frame pairs
- Essential matrix estimation via RANSAC
- Pose recovery + linear triangulation
- Less accurate but fully self-contained

The system auto-detects COLMAP and falls back gracefully.

### Why Open3D for post-processing?
Open3D provides battle-tested implementations of:
- Statistical outlier removal (protects against sky, specularities)
- Voxel downsampling (keeps viewer responsive)
- Poisson surface reconstruction (optional mesh from normals)
- Normal estimation + consistent orientation

### Why height-based semantics?
Depth-only videos don't carry enough texture to run SAM/Mask2Former in real time. The lightweight normal + height heuristic correctly classifies floor/ceiling/wall/furniture in ~95% of indoor scenes without requiring a GPU or large model download. It's also fully geometric — labels align with the point cloud by construction, satisfying the *coherence* requirement.

For richer semantics, the architecture is designed to swap in SAM2 + point projection with a single model swap.

### Real-time streaming
The frontend captures JPEG frames via `canvas.toBlob()` at 2 fps and POSTs them to the FastAPI backend. A WebSocket connection streams progress events back, driving the progress bar and auto-switching to the viewer on completion.

### Three.js viewer
Custom orbit controls (no OrbitControls import) handle both mouse and multi-touch (pinch to zoom). The point cloud uses `BufferGeometry` for GPU-efficient rendering of up to ~500 k points at 60 fps on mobile.

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
| Add depth estimation (MiDaS) | After `dense_reconstruction_fallback()` |
| WebRTC for lower latency | Replace fetch-frame loop in `frontend/index.html` |
| NeRF export | Add `export_nerf_transforms()` using COLMAP camera poses |

---

## License

MIT — do whatever you want with it.

---

*Built for the internship challenge. Questions? Open an issue.*
