"""
main.py — CinemaForge
═══════════════════════════════════════════════════════════════════

FastAPI web platform for CinemaForge.
Separate from ReelForge — runs on a different port (8001).
Same Google VM, same nginx reverse proxy with /cinema prefix.

Routes:
  GET  /           → React portal (SPA)
  POST /submit     → Parse + queue a project
  GET  /projects   → List all projects
  GET  /projects/{id} → Project detail + asset manifest
  POST /projects/{id}/upload/{scene} → Upload AI asset for a scene
  POST /projects/{id}/fetch_stock    → Trigger Pexels auto-fetch
  POST /projects/{id}/render         → Start render (blocks until assets ready)
  GET  /projects/{id}/status         → Render status + output paths
  POST /projects/{id}/upload_yt      → Upload to YouTube
  GET  /health     → Health check
═══════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import uuid
import logging
import threading
import subprocess
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv

load_dotenv() # Load from .env if it exists

from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File, Depends, Body
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
import secrets

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .models import init_db, Session, CinemaProject, ProjectStatus
from .parser import parse_script, fetch_all_stock, register_uploaded_asset, manifest_to_checklist, fetch_pexels_asset
from .tts    import generate_project_audio, VOICES_FOLDER
from .alignment import get_word_timestamps
from .renderer import render_project
from .uploader import upload_video, build_yt_metadata

log = logging.getLogger("main")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)

# ── Auth ──────────────────────────────────────────────────────────
_security    = HTTPBasic()
_PORTAL_USER = os.environ.get("CINEMA_USER",     "admin")
_PORTAL_PASS = os.environ.get("CINEMA_PASSWORD", "cinemaforge")

def require_auth(creds: HTTPBasicCredentials = Depends(_security)):
    ok_u = secrets.compare_digest(creds.username.encode(), _PORTAL_USER.encode())
    ok_p = secrets.compare_digest(creds.password.encode(), _PORTAL_PASS.encode())
    if not (ok_u and ok_p):
        raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return creds.username


# ── Lifespan ──────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app     = FastAPI(title="CinemaForge", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import pathlib
_DIST = pathlib.Path(__file__).parent.parent / "portal" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

UPLOAD_FOLDER = os.environ.get("ASSETS_FOLDER", "/app/assets")
OUTPUT_FOLDER = os.environ.get("OUTPUT_FOLDER", "/app/output_cinema")
VOICES_FOLDER = os.environ.get("VOICES_FOLDER", "/app/voices")
SFX_FOLDER    = os.environ.get("SFX_FOLDER",    "/app/sfx")

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, VOICES_FOLDER, SFX_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Mount static files with proper permissions
app.mount("/output", StaticFiles(directory=OUTPUT_FOLDER), name="output")
app.mount("/assets", StaticFiles(directory=UPLOAD_FOLDER), name="assets")
app.mount("/voices", StaticFiles(directory=VOICES_FOLDER), name="voices")
app.mount("/sfx",    StaticFiles(directory=SFX_FOLDER),    name="sfx")


# ── Scan trap ─────────────────────────────────────────────────────
@app.middleware("http")
async def scan_trap(request: Request, call_next):
    path = request.url.path.lower()
    BAD  = {"/.env", "/.git/config", "/wp-config.php", "/credentials.json"}
    if path in BAD or "../" in path:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return await call_next(request)


# ═══════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def index(request: Request, _user: str = Depends(require_auth)):
    from fastapi.responses import FileResponse
    if _DIST.exists():
        return FileResponse(str(_DIST / "index.html"))
    return HTMLResponse("<h2>CinemaForge — portal/dist not built yet. Run npm run build.</h2>")


@app.post("/projects/{project_id}/upload_yt")
@limiter.limit("5/minute")
async def upload_to_youtube(
    request: Request,
    project_id: int,
    format: str = "longform", # "longform" or "short"
    _user: str = Depends(require_auth)
):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if not p:
        db.close()
        raise HTTPException(404, "Project not found")
    
    video_path = p.output_path if format == "longform" else p.short_path
    if not video_path or not os.path.exists(video_path):
        db.close()
        raise HTTPException(400, f"Rendered video ({format}) not found. Please render first.")

    p.status = ProjectStatus.uploading
    db.commit()
    script_md = p.script_md
    project_name = p.name
    db.close()

    def _upload():
        try:
            is_short = (format == "short")
            title, desc, tags = build_yt_metadata(project_name, script_md, is_short=is_short)
            video_id = upload_video(video_path, title, desc, tags)
            
            db2 = Session()
            p2 = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
            if p2:
                p2.status = ProjectStatus.done
                p2.yt_video_id_en = video_id # Assuming English for now
                db2.commit()
            db2.close()
            log.info(f"[upload] ✓ Project #{project_id} uploaded to YT: {video_id}")
        except Exception as e:
            log.error(f"[upload] ✗ Project #{project_id} failed: {e}")
            db3 = Session()
            p3 = db3.query(CinemaProject).filter(CinemaProject.id == project_id).first()
            if p3:
                p3.status = ProjectStatus.failed
                p3.error_msg = f"YouTube upload failed: {e}"
                db3.commit()
            db3.close()

    threading.Thread(target=_upload, daemon=True).start()
    return {"ok": True, "message": "YouTube upload started"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "CinemaForge", "time": datetime.utcnow().isoformat()}


# ── Submit project ────────────────────────────────────────────────

@app.post("/submit")
@limiter.limit("10/minute")
async def submit_project(
    request:    Request,
    script_md:  str = Form(...),
    _user: str  = Depends(require_auth),
):
    try:
        # 1. Parse to get metadata and scenes
        meta, scenes, manifest = parse_script(script_md)
        
        # 2. Check if a project with this name already exists
        db = Session()
        existing = db.query(CinemaProject).filter(CinemaProject.name == meta.name).first()
        
        if existing:
            # Update existing project script and metadata
            existing.script_md = script_md
            existing.meta_json = json.dumps(meta.__dict__)
            # get_live_manifest will sync with disk
            existing.manifest_json = json.dumps(get_live_manifest(existing))
            pid = existing.id
            db.commit()
            log.info(f"[submit] Updated existing project: {meta.name} (ID: {pid})")
        else:
            # Create new project
            project = CinemaProject(
                project_id    = str(uuid.uuid4())[:8],
                name          = meta.name,
                script_md     = script_md,
                meta_json     = json.dumps(meta.__dict__),
                manifest_json = json.dumps(manifest.to_dict()),
                status        = ProjectStatus.pending,
            )
            db.add(project)
            db.commit()
            pid = project.id
            log.info(f"[submit] Created new project: {meta.name} (ID: {pid})")
        
        db.close()

        # 3. Trigger stock fetching in background
        def _fetch():
            _meta, _scenes, _manifest = parse_script(script_md)
            results = fetch_all_stock(_manifest)
            log.info(f"[stock] Project #{pid}: {results}")
            db2 = Session()
            p2 = db2.query(CinemaProject).filter(CinemaProject.id == pid).first()
            if p2:
                p2.manifest_json = json.dumps(get_live_manifest(p2))
                db2.commit()
            db2.close()

        threading.Thread(target=_fetch, daemon=True).start()

        return {"ok": True, "project_id": pid}
    except Exception as e:
        log.error(f"Submit failed: {e}")
        raise HTTPException(500, f"Submission failed: {str(e)}")


# ── List projects ─────────────────────────────────────────────────

@app.get("/projects", response_class=JSONResponse)
@limiter.limit("60/minute")
async def list_projects(request: Request, _user: str = Depends(require_auth)):
    db       = Session()
    projects = db.query(CinemaProject).order_by(CinemaProject.created_at.desc()).limit(100).all()
    db.close()
    return [p.as_dict() for p in projects]


def get_live_manifest(project: CinemaProject):
    """
    Returns a manifest dictionary that is synced with disk.
    If no manifest exists in DB, it creates one from the script.
    """
    try:
        # 1. Start with what's in DB or a fresh one from script
        if project.manifest_json:
            manifest_dict = json.loads(project.manifest_json)
        else:
            _, _, manifest = parse_script(project.script_md)
            manifest_dict = manifest.to_dict()

        # 2. Sync with disk
        # Check stock assets
        for item in manifest_dict.get("auto_fetch", []):
            if item.get("local_path") and os.path.exists(item["local_path"]):
                item["status"] = "ready"
            elif item.get("status") == "ready": # Path missing but status ready? reset
                item["status"] = "pending"

        # Check user uploads
        for item in manifest_dict.get("user_upload", []):
            if item.get("local_path") and os.path.exists(item["local_path"]):
                item["status"] = "ready"
            else:
                item["status"] = "pending"

        # Check SFX
        SFX_FOLDER = os.environ.get("SFX_FOLDER", "/app/sfx")
        available_sfx = []
        if os.path.exists(SFX_FOLDER):
            available_sfx = [os.path.splitext(f)[0].lower() for f in os.listdir(SFX_FOLDER)]
        
        manifest_dict["sfx_ready"] = []
        for sfx in manifest_dict.get("sfx_needed", []):
            if sfx.lower() in available_sfx:
                manifest_dict["sfx_ready"].append(sfx)

        # 3. Calculate overall readiness
        all_ready = True
        for item in manifest_dict.get("auto_fetch", []) + manifest_dict.get("user_upload", []):
            if item.get("status") != "ready":
                all_ready = False
                break
        
        if all_ready:
            for sfx in manifest_dict.get("sfx_needed", []):
                if sfx not in manifest_dict["sfx_ready"]:
                    all_ready = False
                    break
        
        manifest_dict["is_ready"] = all_ready
        return manifest_dict
    except Exception as e:
        log.error(f"Error syncing manifest: {e}")
        return {}

@app.get("/projects/{project_id}", response_class=JSONResponse)
@limiter.limit("60/minute")
async def get_project(request: Request, project_id: int, _user: str = Depends(require_auth)):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if not p:
        db.close()
        raise HTTPException(404, "Project not found")
    
    data = p.as_dict()
    data["voice_mapping"] = json.loads(p.voice_mapping_json) if p.voice_mapping_json else {}
    
    # Get synced manifest
    manifest = get_live_manifest(p)
    data["manifest"] = manifest
    data["is_ready"] = manifest.get("is_ready", False)
    data["checklist"] = "Ready" if data["is_ready"] else "Pending assets"
    
    # Save back the synced manifest only if it was missing or changed
    new_manifest_json = json.dumps(manifest)
    if p.manifest_json != new_manifest_json:
        p.manifest_json = new_manifest_json
        db.commit()
    
    db.close()
    return data


# ── Stock fetching ────────────────────────────────────────────────

@app.post("/projects/{project_id}/fetch_stock")
@limiter.limit("10/minute")
async def fetch_stock_scene(
    request: Request, 
    project_id: int, 
    payload: dict = Body(...),
    _user: str = Depends(require_auth)
):
    scene_name = payload.get("scene")
    index      = payload.get("index", 0)
    
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    db.close()
    if not p:
        raise HTTPException(404, "Project not found")

    meta, scenes, manifest = parse_script(p.script_md)
    
    # Find the asset item in the manifest
    item = next((a for a in manifest.auto_fetch if a.scene_name == scene_name), None)
    if not item:
        raise HTTPException(400, f"Scene '{scene_name}' is not a STOCK asset.")

    ok = fetch_pexels_asset(item, meta.name, index=index)
    
    if ok:
        # Re-sync manifest with DB
        db2 = Session()
        p2 = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
        if p2:
            # We don't need to manually update JSON here because get_project
            # or subsequent calls will use get_live_manifest which checks disk.
            # But let's trigger a sync just in case.
            p2.manifest_json = json.dumps(get_live_manifest(p2))
            db2.commit()
        db2.close()
        return {"ok": True, "pexels_url": item.pexels_url}
    
    raise HTTPException(500, "Failed to fetch stock image.")


# ── Voice management ──────────────────────────────────────────────

@app.post("/voices/upload/{speaker_name}")
async def upload_voice_ref(
    speaker_name: str,
    file: UploadFile = File(...),
    _user: str = Depends(require_auth)
):
    VOICES_FOLDER = os.environ.get("VOICES_FOLDER", "/app/voices")
    os.makedirs(VOICES_FOLDER, exist_ok=True)
    # Don't lower/safe the name if it's a custom display name from the prompt
    ext = os.path.splitext(file.filename)[1] or ".wav"
    out_path = os.path.join(VOICES_FOLDER, f"{speaker_name}{ext}")
    
    content = await file.read()
    with open(out_path, "wb") as f:
        f.write(content)
    
    return {"ok": True, "speaker": speaker_name, "path": out_path}


@app.post("/projects/{project_id}/voice_map")
async def update_voice_mapping(
    project_id: int,
    mapping: dict = Body(...),
    _user: str = Depends(require_auth)
):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if not p:
        db.close()
        raise HTTPException(404, "Project not found")
    
    p.voice_mapping_json = json.dumps(mapping)
    db.commit()
    db.close()
    return {"ok": True}


@app.get("/voices")
async def list_voices(_user: str = Depends(require_auth)):
    if not os.path.exists(VOICES_FOLDER):
        return []
    
    voices = []
    for f in os.listdir(VOICES_FOLDER):
        if f.lower().endswith((".wav", ".mp3")):
            voices.append({
                "name": os.path.splitext(f)[0],
                "filename": f
            })
    return voices


@app.get("/sfx")
async def list_sfx(_user: str = Depends(require_auth)):
    SFX_FOLDER = os.environ.get("SFX_FOLDER", "sfx")
    if not os.path.exists(SFX_FOLDER):
        return []
    
    sfx = []
    for f in os.listdir(SFX_FOLDER):
        if f.lower().endswith((".wav", ".mp3")):
            sfx.append({
                "name": os.path.splitext(f)[0],
                "filename": f
            })
    return sfx


@app.post("/sfx/upload/{sfx_name}")
async def upload_sfx(
    sfx_name: str,
    file: UploadFile = File(...),
    _user: str = Depends(require_auth)
):
    SFX_FOLDER = os.environ.get("SFX_FOLDER", "/app/sfx")
    os.makedirs(SFX_FOLDER, exist_ok=True)
    ext = os.path.splitext(file.filename)[1] or ".mp3"
    out_path = os.path.join(SFX_FOLDER, f"{sfx_name}{ext}")
    
    content = await file.read()
    with open(out_path, "wb") as f:
        f.write(content)
    
    return {"ok": True, "name": sfx_name, "path": out_path}


@app.get("/voices/play/{speaker_name}")
async def play_voice_ref(speaker_name: str, _user: str = Depends(require_auth)):
    from fastapi.responses import FileResponse
    # Try direct name first, then safe name
    names_to_try = [speaker_name, re.sub(r"[^\w]", "_", speaker_name.lower())]
    for name in names_to_try:
        for ext in (".wav", ".mp3"):
            path = os.path.join(VOICES_FOLDER, f"{name}{ext}")
            if os.path.exists(path):
                return FileResponse(path)
    raise HTTPException(404, "Voice reference not found")


@app.delete("/voices/{speaker_name}")
async def delete_voice_ref(speaker_name: str, _user: str = Depends(require_auth)):
    safe_name = re.sub(r"[^\w]", "_", speaker_name.lower())
    deleted = False
    for ext in (".wav", ".mp3"):
        path = os.path.join(VOICES_FOLDER, f"{safe_name}{ext}")
        if os.path.exists(path):
            os.remove(path)
            deleted = True
    if deleted:
        return {"ok": True}
    raise HTTPException(404, "Voice reference not found")


# ── Upload AI asset ───────────────────────────────────────────────

@app.post("/projects/{project_id}/upload/{scene_name}")
@limiter.limit("30/minute")
async def upload_asset(
    request:    Request,
    project_id: int,
    scene_name: str,
    file:       UploadFile = File(...),
    _user: str  = Depends(require_auth),
):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    db.close()
    if not p:
        raise HTTPException(404, "Project not found")

    safe_proj  = re.sub(r"[^\w]", "_", p.name).lower()
    safe_scene = re.sub(r"[^\w]", "_", scene_name).lower()
    ext        = os.path.splitext(file.filename)[1] or ".jpg"
    out_dir    = os.path.join(UPLOAD_FOLDER, safe_proj)
    os.makedirs(out_dir, exist_ok=True)
    out_path   = os.path.join(out_dir, f"{safe_scene}{ext}")

    content = await file.read()
    with open(out_path, "wb") as f:
        f.write(content)

    # Re-sync manifest with DB
    db2 = Session()
    p2  = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if p2:
        # get_live_manifest will see the new file on disk and update status
        p2.manifest_json = json.dumps(get_live_manifest(p2))
        db2.commit()
    db2.close()

    log.info(f"[upload] Project #{project_id} scene '{scene_name}': {out_path}")
    return {"ok": True, "scene": scene_name, "path": out_path}


# ── Start render ──────────────────────────────────────────────────

def _do_render(project_id: int):
    """Background render thread."""
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if not p:
        db.close()
        return

    p.status     = ProjectStatus.rendering
    p.updated_at = datetime.utcnow()
    db.commit()
    script_md = p.script_md
    voice_mapping = json.loads(p.voice_mapping_json) if p.voice_mapping_json else {}
    db.close()

    try:
        meta, scenes, manifest = parse_script(script_md)

        if not manifest.is_ready():
            missing = [f"{a.scene_name} ({a.asset_type})" for a in manifest.missing()]
            raise RuntimeError(f"Assets missing: {', '.join(missing)}")

        # TTS
        tmp_audio = os.path.join(OUTPUT_FOLDER, f"_audio_{project_id}")
        os.makedirs(tmp_audio, exist_ok=True)
        scene_audios = generate_project_audio(scenes, tmp_audio, meta.name, voice_mapping=voice_mapping)

        # Alignment
        stamps_map = {}
        for scene, audio in zip(scenes, scene_audios):
            transcript = " ".join(scene.lines)
            stamps     = get_word_timestamps(audio.wav_path, transcript)
            stamps_map[scene.name] = stamps

        # Render
        project_out = os.path.join(OUTPUT_FOLDER, f"project_{project_id}")
        os.makedirs(project_out, exist_ok=True)
        results = render_project(
            meta            = meta,
            scenes          = scenes,
            scene_audios    = scene_audios,
            stamps_map      = stamps_map,
            output_dir      = project_out,
            generate_short  = True,
        )

        # Save output paths
        db2 = Session()
        p2  = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
        if p2:
            p2.status       = ProjectStatus.rendered
            p2.output_path  = results.get("longform")
            p2.short_path   = results.get("short")
            p2.error_msg    = None
            p2.updated_at   = datetime.utcnow()
            db2.commit()
        db2.close()
        log.info(f"[render] ✓ Project #{project_id} complete.")

    except Exception as e:
        log.error(f"[render] ✗ Project #{project_id} failed: {e}")
        db3 = Session()
        p3  = db3.query(CinemaProject).filter(CinemaProject.id == project_id).first()
        if p3:
            p3.status    = ProjectStatus.failed
            p3.error_msg = str(e)
            p3.updated_at = datetime.utcnow()
            db3.commit()
        db3.close()


@app.post("/projects/{project_id}/render")
@limiter.limit("5/minute")
async def start_render(request: Request, project_id: int, _user: str = Depends(require_auth)):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if not p:
        db.close()
        raise HTTPException(404, "Project not found")
    if p.status == ProjectStatus.rendering:
        db.close()
        raise HTTPException(400, "Already rendering")
    db.close()

    t = threading.Thread(target=_do_render, args=(project_id,), daemon=True)
    t.start()
    return {"ok": True, "project_id": project_id, "message": "Render started"}


@app.get("/projects/{project_id}/status")
@limiter.limit("120/minute")
async def project_status(request: Request, project_id: int, _user: str = Depends(require_auth)):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    db.close()
    if not p:
        raise HTTPException(404, "Project not found")
    return {
        "id":          p.id,
        "status":      p.status.value,
        "output_path": p.output_path,
        "short_path":  p.short_path,
        "error_msg":   p.error_msg,
        "updated_at":  p.updated_at.isoformat() if p.updated_at else None,
    }
