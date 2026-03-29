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

OUTPUT_FOLDER = os.environ.get("OUTPUT_FOLDER", "output_cinema")
UPLOAD_FOLDER = os.environ.get("ASSETS_FOLDER", "assets")
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Mount the output folder so the portal can access rendered videos
app.mount("/output", StaticFiles(directory=OUTPUT_FOLDER), name="output")


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
        meta, scenes, manifest = parse_script(script_md)
    except ValueError as e:
        raise HTTPException(400, f"Script parse error: {e}")

    db      = Session()
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
    db.close()

    # Auto-fetch stock assets in background
    def _fetch():
        _meta, _scenes, _manifest = parse_script(script_md)
        results = fetch_all_stock(_manifest)
        log.info(f"[stock] Project #{pid}: {results}")
        # Update manifest in DB
        db2 = Session()
        p   = db2.query(CinemaProject).filter(CinemaProject.id == pid).first()
        if p:
            p.manifest_json = json.dumps(_manifest.to_dict())
            db2.commit()
        db2.close()

    threading.Thread(target=_fetch, daemon=True).start()

    return JSONResponse({
        "ok":         True,
        "project_id": pid,
        "name":       meta.name,
        "scenes":     len(scenes),
        "checklist":  manifest_to_checklist(manifest),
    })


# ── List projects ─────────────────────────────────────────────────

@app.get("/projects", response_class=JSONResponse)
@limiter.limit("60/minute")
async def list_projects(request: Request, _user: str = Depends(require_auth)):
    db       = Session()
    projects = db.query(CinemaProject).order_by(CinemaProject.created_at.desc()).limit(100).all()
    db.close()
    return [p.as_dict() for p in projects]


@app.get("/projects/{project_id}", response_class=JSONResponse)
@limiter.limit("60/minute")
async def get_project(request: Request, project_id: int, _user: str = Depends(require_auth)):
    db = Session()
    p  = db.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    db.close()
    if not p:
        raise HTTPException(404, "Project not found")
    data = p.as_dict()
    data["voice_mapping"] = json.loads(p.voice_mapping_json) if p.voice_mapping_json else {}

    # Rebuild live checklist from saved manifest
    try:
        _, _, manifest = parse_script(p.script_md)
        data["checklist"] = manifest_to_checklist(manifest)
        data["manifest"]  = manifest.to_dict()
        data["is_ready"]  = manifest.is_ready()
    except Exception as e:
        log.error(f"Error rebuilding manifest: {e}")
        data["checklist"] = "Error reading manifest"
        data["is_ready"]  = False
    
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
        # Update manifest in DB
        db2 = Session()
        p2 = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
        if p2:
            p2.manifest_json = json.dumps(manifest.to_dict())
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
    SFX_FOLDER = os.environ.get("SFX_FOLDER", "sfx")
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

    # Update manifest in DB
    db2 = Session()
    p2  = db2.query(CinemaProject).filter(CinemaProject.id == project_id).first()
    if p2:
        # Load existing manifest
        try:
            _, _, manifest = parse_script(p2.script_md)
            # Find the item and update its local_path and status
            found = False
            for item in manifest.auto_fetch + manifest.user_upload:
                if item.scene_name == scene_name:
                    item.local_path = out_path
                    item.status = "ready"
                    found = True
                    break
            
            if found:
                p2.manifest_json = json.dumps(manifest.to_dict())
                db2.commit()
        except Exception as e:
            log.error(f"Error updating manifest after upload: {e}")
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
