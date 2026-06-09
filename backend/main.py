"""
Video-to-3D Reconstruction Backend
Handles frame ingestion, COLMAP-based SfM, dense reconstruction, and semantic labeling.
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import open3d as o3d
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Video-to-3D Reconstruction API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

sessions: dict[str, dict] = {}
websocket_connections: dict[str, list[WebSocket]] = {}


def session_dir(sid):
    d = SESSIONS_DIR / sid; d.mkdir(parents=True, exist_ok=True); return d

def frames_dir(sid):
    d = session_dir(sid) / "frames"; d.mkdir(exist_ok=True); return d

def colmap_dir(sid):
    d = session_dir(sid) / "colmap"; d.mkdir(exist_ok=True); return d

def outputs_dir(sid):
    d = session_dir(sid) / "outputs"; d.mkdir(exist_ok=True); return d


async def broadcast(sid, msg):
    conns = websocket_connections.get(sid, [])
    dead = []
    for ws in conns:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


def update_status(sid, stage, progress, message):
    if sid in sessions:
        sessions[sid].update({"stage": stage, "progress": progress, "message": message})
    logger.info(f"[{sid}] {stage} ({progress}%): {message}")


def extract_frames_from_video(video_path, out_dir, target_fps=2.0, max_frames=120):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(fps / target_fps))
    saved = []
    idx = 0
    frame_num = 0
    while True:
        ret, frame = cap.read()
        if not ret or len(saved) >= max_frames:
            break
        if frame_num % step == 0:
            h, w = frame.shape[:2]
            if w > 1280:
                scale = 1280 / w
                frame = cv2.resize(frame, (1280, int(h * scale)))
            path = str(out_dir / f"frame_{idx:05d}.jpg")
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            saved.append(path)
            idx += 1
        frame_num += 1
    cap.release()
    return saved


def deduplicate_frames(frame_paths, threshold=0.85):
    if len(frame_paths) <= 2:
        return frame_paths
    orb = cv2.ORB_create(500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    kept = [frame_paths[0]]
    prev_img = cv2.imread(frame_paths[0], cv2.IMREAD_GRAYSCALE)
    prev_kp, prev_des = orb.detectAndCompute(prev_img, None)
    for path in frame_paths[1:]:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        kp, des = orb.detectAndCompute(img, None)
        if des is None or prev_des is None:
            kept.append(path); prev_img, prev_kp, prev_des = img, kp, des; continue
        matches = bf.match(prev_des, des)
        score = len(matches) / max(len(prev_des), 1)
        if score < threshold:
            kept.append(path); prev_img, prev_kp, prev_des = img, kp, des
    return kept


def run_colmap(frames, colmap_path):
    img_dir = colmap_path / "images"; img_dir.mkdir(exist_ok=True)
    db_path = colmap_path / "database.db"
    sparse_dir = colmap_path / "sparse"; sparse_dir.mkdir(exist_ok=True)
    for i, fp in enumerate(frames):
        dst = img_dir / f"{i:05d}.jpg"
        if not dst.exists():
            shutil.copy2(fp, dst)

    # Find COLMAP executable
    colmap_exe = (shutil.which("colmap") or 
                  shutil.which("COLMAP") or 
                  r"C:\colmap\COLMAP.bat")
    
    logger.info(f"Using COLMAP at: {colmap_exe}")

    def run(cmd):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"COLMAP FAILED: {' '.join(cmd[:2])}", flush=True)
            print(f"STDERR: {result.stderr[:500]}", flush=True)
            return False
        print(f"COLMAP OK: {' '.join(cmd[:2])}", flush=True)
        return True

    if not run([colmap_exe, "feature_extractor",
                "--database_path", str(db_path),
                "--image_path", str(img_dir),
                "--ImageReader.single_camera", "1",
                "--SiftExtraction.max_num_features", "4096"]):
        return False

    if not run([colmap_exe, "sequential_matcher",
                "--database_path", str(db_path),
                "--SequentialMatching.overlap", "10"]):
        return False

    if not run([colmap_exe, "mapper",
                "--database_path", str(db_path),
                "--image_path", str(img_dir),
                "--output_path", str(sparse_dir),
                "--Mapper.min_num_matches", "15",
                "--Mapper.init_min_num_inliers", "50"]):
        return False

    return len(list(sparse_dir.iterdir())) > 0


def colmap_to_pointcloud(colmap_path):
    sparse_dirs = sorted((colmap_path / "sparse").iterdir())
    if not sparse_dirs:
        return None
    model_dir = sparse_dirs[0]
    pts, colors = [], []
    bin_file = model_dir / "points3D.bin"
    txt_file = model_dir / "points3D.txt"
    if bin_file.exists():
        try:
            import struct
            with open(bin_file, "rb") as f:
                n = struct.unpack("<Q", f.read(8))[0]
                for _ in range(n):
                    struct.unpack("<Q", f.read(8))
                    xyz = struct.unpack("<ddd", f.read(24))
                    rgb = struct.unpack("<BBB", f.read(3))
                    struct.unpack("<d", f.read(8))
                    tl = struct.unpack("<Q", f.read(8))[0]
                    f.read(8 * tl)
                    pts.append(xyz); colors.append(rgb)
        except Exception as e:
            logger.warning(f"bin read failed: {e}")
    if not pts and txt_file.exists():
        with open(txt_file) as f:
            for line in f:
                if line.startswith("#"): continue
                p = line.split()
                if len(p) >= 7:
                    pts.append([float(p[1]),float(p[2]),float(p[3])])
                    colors.append([int(p[4]),int(p[5]),int(p[6])])
    if not pts:
        return None
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.array(pts))
    if colors:
        pcd.colors = o3d.utility.Vector3dVector(np.array(colors) / 255.0)
    return pcd


def dense_reconstruction_fallback(frames):
    all_pts, all_colors = [], []
    orb = cv2.ORB_create(2000)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    for i in range(len(frames) - 1):
        img1 = cv2.imread(frames[i]); img2 = cv2.imread(frames[i+1])
        if img1 is None or img2 is None: continue
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        h, w = gray1.shape
        kp1, des1 = orb.detectAndCompute(gray1, None)
        kp2, des2 = orb.detectAndCompute(gray2, None)
        if des1 is None or des2 is None or len(des1) < 8: continue
        matches = sorted(bf.match(des1, des2), key=lambda x: x.distance)[:200]
        if len(matches) < 8: continue
        pts1 = np.float32([kp1[m.queryIdx].pt for m in matches])
        pts2 = np.float32([kp2[m.trainIdx].pt for m in matches])
        K = np.array([[w,0,w/2],[0,w,h/2],[0,0,1]], dtype=np.float64)
        E, mask = cv2.findEssentialMat(pts1, pts2, K, method=cv2.RANSAC, prob=0.999, threshold=1.0)
        if E is None or mask is None: continue
        _, R, t, mask2 = cv2.recoverPose(E, pts1, pts2, K, mask=mask)
        P1 = K @ np.hstack([np.eye(3), np.zeros((3,1))])
        P2 = K @ np.hstack([R, t])
        pts1_in = pts1[mask2.ravel() > 0].T
        pts2_in = pts2[mask2.ravel() > 0].T
        if pts1_in.shape[1] < 4: continue
        pts4d = cv2.triangulatePoints(P1, P2, pts1_in, pts2_in)
        pts3d = (pts4d[:3] / pts4d[3]).T
        valid = (pts3d[:,2] > 0.1) & (pts3d[:,2] < 20.0)
        pts3d = pts3d[valid]
        for pt, pt2d in zip(pts3d, pts1_in.T[valid]):
            x, y = int(pt2d[0]), int(pt2d[1])
            if 0 <= x < w and 0 <= y < h:
                b, g, r = img1[y, x]
                all_colors.append([r/255.0, g/255.0, b/255.0])
                all_pts.append(pt.tolist())
    if not all_pts:
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(np.random.randn(500, 3))
        return pcd
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.array(all_pts))
    pcd.colors = o3d.utility.Vector3dVector(np.array(all_colors))
    return pcd


def clean_pointcloud(pcd):
    if len(pcd.points) == 0: return pcd
    pcd, _ = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
    voxel_size = 0.01 if len(pcd.points) < 10000 else 0.02
    pcd = pcd.voxel_down_sample(voxel_size=voxel_size)
    pcd.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=30))
    pcd.orient_normals_consistent_tangent_plane(100)
    return pcd


def pointcloud_to_mesh(pcd):
    if len(pcd.points) < 100: return None
    try:
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8)
        mesh.remove_vertices_by_mask(densities < np.quantile(densities, 0.1))
        mesh.compute_vertex_normals()
        return mesh
    except Exception as e:
        logger.warning(f"Poisson failed: {e}"); return None


def assign_semantic_labels(pcd):
    if len(pcd.points) == 0: return {}
    pts = np.asarray(pcd.points)
    y = pts[:,1]
    y_min, y_max = y.min(), y.max()
    y_range = y_max - y_min if y_max != y_min else 1.0
    labels = {}
    for i, yn in enumerate(y):
        nh = (yn - y_min) / y_range
        if nh < 0.08:
            labels[i] = "floor"
        elif nh > 0.90:
            labels[i] = "ceiling"
        elif pcd.has_normals():
            n = np.asarray(pcd.normals)[i]
            if abs(n[1]) > 0.7:   labels[i] = "floor" if nh < 0.5 else "ceiling"
            elif abs(n[1]) < 0.3: labels[i] = "wall"
            else:                 labels[i] = "furniture"
        else:
            labels[i] = "furniture" if 0.1 < nh < 0.7 else "wall"
    return labels


def export_pointcloud_json(pcd, labels, path):
    pts = np.asarray(pcd.points).tolist()
    colors = np.asarray(pcd.colors).tolist() if pcd.has_colors() else [[0.5,0.5,0.5]]*len(pts)
    lc = {"floor":[0.45,0.38,0.30],"wall":[0.75,0.75,0.72],"ceiling":[0.92,0.92,0.88],
          "furniture":[0.55,0.38,0.22],"object":[0.28,0.48,0.68]}
    if labels:
        for i, label in labels.items():
            if i < len(colors): colors[i] = lc.get(label, colors[i])
    data = {"points":pts,"colors":colors,"labels":{str(k):v for k,v in labels.items()},
            "stats":{"num_points":len(pts),"bounds":{
                "min":np.min(pts,axis=0).tolist() if pts else [0,0,0],
                "max":np.max(pts,axis=0).tolist() if pts else [1,1,1]}}}
    with open(path,"w") as f: json.dump(data, f)


async def run_reconstruction(sid):
    fd = frames_dir(sid); cd = colmap_dir(sid); od = outputs_dir(sid)
    frame_paths = [str(f) for f in sorted(fd.glob("*.jpg")) + sorted(fd.glob("*.png"))]
    
    import os
    colmap_check = shutil.which("colmap") or shutil.which("COLMAP") or (r"C:\colmap\COLMAP.bat" if os.path.exists(r"C:\colmap\COLMAP.bat") else None)
    logger.info(f"DEBUG frames: {len(frame_paths)}, colmap: {colmap_check}")
    print(f"FRAMES: {len(frame_paths)}, COLMAP: {colmap_check}", flush=True)
    
    if len(frame_paths) < 5:
        await broadcast(sid, {"type":"error","message":"Not enough frames (need ≥ 5)"}); return

    await broadcast(sid, {"type":"status","stage":"dedup","progress":10,"message":f"Processing {len(frame_paths)} frames..."})
    frame_paths = deduplicate_frames(frame_paths, threshold=0.80)
    await broadcast(sid, {"type":"status","stage":"dedup","progress":20,"message":f"Using {len(frame_paths)} unique frames"})

    pcd = None; used_colmap = False
    colmap_exe = shutil.which("colmap") or shutil.which("COLMAP") or (r"C:\colmap\COLMAP.bat" if os.path.exists(r"C:\colmap\COLMAP.bat") else None)
    logger.info(f"COLMAP found at: {colmap_exe}")
    if colmap_exe and len(frame_paths) >= 10:
        await broadcast(sid, {"type":"status","stage":"sfm","progress":30,"message":"Running COLMAP SfM..."})
        try:
            ok = await asyncio.get_event_loop().run_in_executor(None, run_colmap, frame_paths, cd)
            print(f"COLMAP result: {ok}", flush=True)
        except Exception as e:
            print(f"COLMAP exception: {e}", flush=True)
            logger.warning(f"COLMAP error: {e}")
            if ok:
                pcd = colmap_to_pointcloud(cd)
                if pcd and len(pcd.points) > 10:
                    used_colmap = True
                    await broadcast(sid, {"type":"status","stage":"sfm","progress":55,"message":f"COLMAP: {len(pcd.points)} pts"})
        except Exception as e:
            logger.warning(f"COLMAP error: {e}")

    if pcd is None or len(pcd.points) < 50:
        await broadcast(sid, {"type":"status","stage":"triangulation","progress":35,"message":"Running ORB triangulation..."})
        pcd = await asyncio.get_event_loop().run_in_executor(None, dense_reconstruction_fallback, frame_paths)
        await broadcast(sid, {"type":"status","stage":"triangulation","progress":55,"message":f"Triangulated {len(pcd.points)} pts"})

    await broadcast(sid, {"type":"status","stage":"cleaning","progress":60,"message":"Cleaning point cloud..."})
    pcd = await asyncio.get_event_loop().run_in_executor(None, clean_pointcloud, pcd)
    await broadcast(sid, {"type":"status","stage":"cleaning","progress":70,"message":f"Clean: {len(pcd.points)} pts"})

    await broadcast(sid, {"type":"status","stage":"semantics","progress":75,"message":"Assigning semantic labels..."})
    labels = assign_semantic_labels(pcd)

    mesh = None
    if len(pcd.points) >= 500:
        await broadcast(sid, {"type":"status","stage":"meshing","progress":80,"message":"Building surface mesh..."})
        mesh = await asyncio.get_event_loop().run_in_executor(None, pointcloud_to_mesh, pcd)

    await broadcast(sid, {"type":"status","stage":"export","progress":90,"message":"Exporting..."})
    export_pointcloud_json(pcd, labels, str(od/"pointcloud.json"))
    o3d.io.write_point_cloud(str(od/"pointcloud.ply"), pcd)
    if mesh: o3d.io.write_triangle_mesh(str(od/"mesh.obj"), mesh)

    from collections import Counter
    label_counts = Counter(labels.values())
    sessions[sid].update({"stage":"complete","progress":100,"message":"Done",
        "results":{"num_points":len(pcd.points),"has_mesh":mesh is not None,
            "used_colmap":used_colmap,"labels":dict(label_counts),
            "files":{"pointcloud_json":f"/sessions/{sid}/outputs/pointcloud.json",
                     "pointcloud_ply":f"/sessions/{sid}/outputs/pointcloud.ply",
                     "mesh_obj":f"/sessions/{sid}/outputs/mesh.obj" if mesh else None}}})
    await broadcast(sid, {"type":"complete","session_id":sid,"results":sessions[sid]["results"]})

    


@app.post("/sessions/new")
async def new_session():
    sid = str(uuid.uuid4())[:8]
    sessions[sid] = {"stage":"idle","progress":0,"message":"Ready","frames":0}
    websocket_connections[sid] = []
    return {"session_id": sid}

@app.post("/sessions/{sid}/frames")
async def upload_frame(sid: str, frame: UploadFile = File(...)):
    if sid not in sessions: return JSONResponse({"error":"Unknown session"}, status_code=404)
    fd = frames_dir(sid); count = sessions[sid].get("frames", 0)
    data = await frame.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        cv2.imwrite(str(fd / f"frame_{count:05d}.jpg"), img)
        sessions[sid]["frames"] = count + 1
    return {"frame_index": count, "total": count + 1}

@app.post("/sessions/{sid}/upload-video")
async def upload_video(sid: str, video: UploadFile = File(...)):
    if sid not in sessions: return JSONResponse({"error":"Unknown session"}, status_code=404)
    vp = str(session_dir(sid) / "input.mp4")
    with open(vp, "wb") as f: f.write(await video.read())
    frames = extract_frames_from_video(vp, frames_dir(sid))
    sessions[sid]["frames"] = len(frames)
    return {"frames_extracted": len(frames)}

@app.post("/sessions/{sid}/reconstruct")
async def start_reconstruction(sid: str):
    if sid not in sessions: return JSONResponse({"error":"Unknown session"}, status_code=404)
    if sessions[sid].get("stage") in ("running","complete"):
        return JSONResponse({"error":"Already running"}, status_code=400)
    sessions[sid]["stage"] = "running"
    asyncio.create_task(run_reconstruction(sid))
    return {"status": "started", "session_id": sid}

@app.get("/sessions/{sid}/status")
async def get_status(sid: str):
    if sid not in sessions: return JSONResponse({"error":"Unknown session"}, status_code=404)
    return sessions[sid]

@app.websocket("/ws/{sid}")
async def websocket_endpoint(websocket: WebSocket, sid: str):
    await websocket.accept()
    if sid not in websocket_connections: websocket_connections[sid] = []
    websocket_connections[sid].append(websocket)
    try:
        if sid in sessions: await websocket.send_json({"type":"status",**sessions[sid]})
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if json.loads(data).get("type") == "ping":
                    await websocket.send_json({"type":"pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type":"ping"})
    except WebSocketDisconnect:
        if sid in websocket_connections and websocket in websocket_connections[sid]:
            websocket_connections[sid].remove(websocket)

app.mount("/sessions", StaticFiles(directory="sessions"), name="sessions")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
