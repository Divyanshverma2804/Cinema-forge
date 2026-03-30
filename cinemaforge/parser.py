"""
parser.py — CinemaForge
═══════════════════════════════════════════════════════════════════

Reads a CinemaForge content.md script and produces:
  1. ProjectMeta   — header fields (name, type, format, channels…)
  2. List[Scene]   — ordered scene objects with all declarations
  3. AssetManifest — what needs to be fetched vs uploaded by user

Asset types:
  STOCK     → auto-fetched from Pexels API (no user action needed)
  AI_IMAGE  → user must generate (Seedance/Leonardo) and upload
  AI_VIDEO  → user must generate (Seedance) and upload
  USER_VIDEO → user uploads their own footage directly

The manifest drives the UI: the platform shows the user exactly
which assets are missing and blocks rendering until all are present.
═══════════════════════════════════════════════════════════════════
"""

import re
import os
import json
import logging
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("parser")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
ASSETS_FOLDER  = os.environ.get("ASSETS_FOLDER", "assets")


# ═══════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SFXDeclaration:
    name:   str             # sfx name (matches sfx/<name>.mp3)
    offset: float = 0.0    # seconds into the scene to play


@dataclass
class BackgroundDeclaration:
    type:   str             # STOCK | AI_IMAGE | AI_VIDEO | USER_VIDEO
    prompt: str             # search query or generation prompt
    motion: str = "ken_burns"  # zoom_in | zoom_out | pan_left | pan_right | still | ken_burns
    resolved_path: Optional[str] = None   # filled in after asset is available


@dataclass
class Scene:
    name:       str
    background: BackgroundDeclaration
    music:      str                    # dark_ambient | continue | none | tension_swell
    sfx:        list[SFXDeclaration]
    style:      str                    # hook | punch | normal | none
    speaker:    Optional[str]          # None for narration, "Detective [gruff]" for dialogue
    lines:      list[str]              # the actual narration/dialogue lines
    # Derived
    speaker_name:   Optional[str] = None
    speaker_emotion: Optional[str] = None


@dataclass
class ProjectMeta:
    name:         str
    type:         str        # narration | dialogue | short | film
    format:       str        # longform | short | both
    channels:     list[str]  # ["EN"] | ["HI"] | ["EN", "HI"]
    aspect_ratio: str        # 9x16 | 16x9
    page_name:    str
    tagline:      str


@dataclass
class AssetItem:
    scene_name: str
    asset_type: str          # STOCK | AI_IMAGE | AI_VIDEO | USER_VIDEO
    prompt:     str
    motion:     str
    status:     str = "pending"    # pending | fetching | ready | failed
    local_path: Optional[str] = None
    pexels_url: Optional[str] = None


@dataclass
class AssetManifest:
    project_name:  str
    auto_fetch:    list[AssetItem]   # STOCK → Pexels auto-fetch
    user_upload:   list[AssetItem]   # AI_IMAGE | AI_VIDEO | USER_VIDEO → user provides
    music_needed:  list[str]         # unique music track names needed
    sfx_needed:    list[str]         # unique SFX names needed

    def is_ready(self) -> bool:
        """True when all assets have a local_path."""
        all_assets = self.auto_fetch + self.user_upload
        return all(a.local_path and os.path.exists(a.local_path) for a in all_assets)

    def missing(self) -> list[AssetItem]:
        all_assets = self.auto_fetch + self.user_upload
        return [a for a in all_assets if not (a.local_path and os.path.exists(a.local_path))]

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "auto_fetch":  [asdict(a) for a in self.auto_fetch],
            "user_upload": [asdict(a) for a in self.user_upload],
            "music_needed": self.music_needed,
            "sfx_needed":   self.sfx_needed,
            "is_ready":     self.is_ready(),
            "missing_count": len(self.missing()),
        }


# ═══════════════════════════════════════════════════════════════════
# PARSER
# ═══════════════════════════════════════════════════════════════════

_HEADER_RE = re.compile(r"^#\s*(\w[\w\s]*):\s*(.+)$")
_SCENE_RE  = re.compile(r"^##\s*Scene:\s*(.+)$", re.IGNORECASE)
_META_RE   = re.compile(r"^#\s*(Background|Music|SFX|Style|Speaker|Duration):\s*(.+)$", re.IGNORECASE)
_BG_RE     = re.compile(r"^\[(STOCK|AI_IMAGE|AI_VIDEO|USER_VIDEO)\]\s*(.+?)(?:\s*\|\s*(\w+))?$", re.IGNORECASE)
_SFX_RE    = re.compile(r"^(\w+)(?:\s*\|\s*([\d.]+))?$")
_SPEAKER_RE = re.compile(r"^(.+?)\s*\[(.+?)\]$")


def parse_script(raw: str) -> tuple[ProjectMeta, list[Scene], AssetManifest]:
    """
    Main entry point. Returns (meta, scenes, manifest).
    Raises ValueError on malformed scripts.
    """
    lines = raw.splitlines()
    meta, scenes = _parse_structure(lines)
    manifest     = _build_manifest(meta, scenes)
    return meta, scenes, manifest


def _parse_structure(lines: list[str]) -> tuple[ProjectMeta, list[Scene]]:
    # ── Pass 1: extract project header ────────────────────────────
    header = {}
    for line in lines:
        line = line.strip()
        if line.startswith("##"):
            break   # scene block started
        m = _HEADER_RE.match(line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            val = m.group(2).strip()
            header[key] = val

    meta = ProjectMeta(
        name         = header.get("projectname", "untitled"),
        type         = header.get("type",         "narration"),
        format       = header.get("format",       "longform"),
        channels     = [c.strip() for c in header.get("channels", "EN").split(",")],
        aspect_ratio = header.get("aspectratio",  "9x16"),
        page_name    = header.get("pagename",     "CinemaForge"),
        tagline      = header.get("tagline",      ""),
    )

    # ── Pass 2: extract scenes ─────────────────────────────────────
    scenes    = []
    cur_scene = None
    cur_meta  = {}
    cur_lines = []

    def _flush_scene():
        nonlocal cur_scene, cur_meta, cur_lines
        if cur_scene is None:
            return
        bg    = _parse_background(cur_meta.get("background", "[STOCK] dark background"))
        sfx   = _parse_sfx(cur_meta.get("sfx", "none"))
        spkr  = cur_meta.get("speaker", "").strip()
        spkr_name, spkr_emo = _parse_speaker(spkr) if spkr else (None, None)
        scenes.append(Scene(
            name            = cur_scene,
            background      = bg,
            music           = cur_meta.get("music",  "continue").strip(),
            sfx             = sfx,
            style           = cur_meta.get("style",  "normal").strip().lower(),
            speaker         = spkr if spkr else None,
            speaker_name    = spkr_name,
            speaker_emotion = spkr_emo,
            lines           = [l for l in cur_lines if l.strip()],
        ))
        cur_scene = None
        cur_meta  = {}
        cur_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip pure comment/separator lines that aren't directives
        if stripped.startswith("---"):
            _flush_scene()
            continue

        # Scene header
        sm = _SCENE_RE.match(stripped)
        if sm:
            _flush_scene()
            cur_scene = sm.group(1).strip()
            continue

        if cur_scene is None:
            continue  # still in project header, skip

        # Scene-level meta directives
        mm = _META_RE.match(stripped)
        if mm:
            key = mm.group(1).strip().lower()
            val = mm.group(2).strip()
            cur_meta[key] = val
            continue

        # Skip comment lines that are not directives
        if stripped.startswith("#"):
            continue

        # Dialogue/narration line
        if stripped:
            cur_lines.append(stripped)

    _flush_scene()

    if not scenes:
        raise ValueError("No scenes found. Check your ## Scene: declarations.")

    return meta, scenes


def _parse_background(raw: str) -> BackgroundDeclaration:
    m = _BG_RE.match(raw.strip())
    if not m:
        # Fallback: treat as stock search
        return BackgroundDeclaration(type="STOCK", prompt=raw.strip(), motion="ken_burns")
    bg_type = m.group(1).upper()
    prompt  = m.group(2).strip()
    motion  = (m.group(3) or "ken_burns").strip().lower()
    return BackgroundDeclaration(type=bg_type, prompt=prompt, motion=motion)


def _parse_sfx(raw: str) -> list[SFXDeclaration]:
    if not raw or raw.strip().lower() == "none":
        return []
    result = []
    for part in raw.split(";"):
        part = part.strip()
        m = _SFX_RE.match(part)
        if m:
            name   = m.group(1).strip()
            offset = float(m.group(2)) if m.group(2) else 0.0
            result.append(SFXDeclaration(name=name, offset=offset))
    return result


def _parse_speaker(raw: str) -> tuple[str, str]:
    """Returns (speaker_name, emotion_string). E.g. 'Detective [gruff, direct]'"""
    m = _SPEAKER_RE.match(raw.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return raw.strip(), "default"


# ═══════════════════════════════════════════════════════════════════
# ASSET MANIFEST BUILDER
# ═══════════════════════════════════════════════════════════════════

def _build_manifest(meta: ProjectMeta, scenes: list[Scene]) -> AssetManifest:
    auto_fetch   = []
    user_upload  = []
    music_needed = []
    sfx_needed   = []

    seen_music = set()
    seen_sfx   = set()

    for scene in scenes:
        bg = scene.background
        item = AssetItem(
            scene_name = scene.name,
            asset_type = bg.type,
            prompt     = bg.prompt,
            motion     = bg.motion,
        )
        # Check if already resolved (asset file exists in assets/<project>/<scene>/)
        expected_path = _expected_asset_path(meta.name, scene.name, bg.type)
        if expected_path and os.path.exists(expected_path):
            item.local_path = expected_path
            item.status     = "ready"
            bg.resolved_path = expected_path

        if bg.type == "STOCK":
            auto_fetch.append(item)
        else:
            user_upload.append(item)

        # Music tracking
        music = scene.music.strip().lower()
        if music not in ("continue", "none", "") and music not in seen_music:
            seen_music.add(music)
            music_needed.append(music)

        # SFX tracking
        for sfx in scene.sfx:
            if sfx.name not in seen_sfx:
                seen_sfx.add(sfx.name)
                sfx_needed.append(sfx.name)

    return AssetManifest(
        project_name = meta.name,
        auto_fetch   = auto_fetch,
        user_upload  = user_upload,
        music_needed = music_needed,
        sfx_needed   = sfx_needed,
    )


def _expected_asset_path(project: str, scene: str, asset_type: str) -> Optional[str]:
    """Returns the expected local path for a pre-uploaded asset, or None."""
    safe_project = re.sub(r"[^\w]", "_", project).lower()
    safe_scene   = re.sub(r"[^\w]", "_", scene).lower()
    ext_map = {"STOCK": ".jpg", "AI_IMAGE": ".jpg", "AI_VIDEO": ".mp4", "USER_VIDEO": ".mp4"}
    ext = ext_map.get(asset_type, ".jpg")
    return os.path.join(ASSETS_FOLDER, safe_project, f"{safe_scene}{ext}")


# ═══════════════════════════════════════════════════════════════════
# PEXELS AUTO-FETCH
# ═══════════════════════════════════════════════════════════════════

def fetch_pexels_asset(item: AssetItem, project_name: str, index: int = 0) -> bool:
    """
    Fetches a stock image from Pexels for the given AssetItem.
    Saves to assets/<project>/<scene>.jpg
    Returns True on success.
    """
    if not PEXELS_API_KEY:
        log.warning("[pexels] No API key set — set PEXELS_API_KEY env var.")
        return False

    safe_project = re.sub(r"[^\w]", "_", project_name).lower()
    safe_scene   = re.sub(r"[^\w]", "_", item.scene_name).lower()
    out_dir      = os.path.join(ASSETS_FOLDER, safe_project)
    os.makedirs(out_dir, exist_ok=True)
    out_path     = os.path.join(out_dir, f"{safe_scene}.jpg")

    # If index is 0 and file exists, we're already ready
    if index == 0 and os.path.exists(out_path):
        item.local_path = out_path
        item.status     = "ready"
        return True

    log.info(f"[pexels] Fetching (idx={index}): '{item.prompt}' for scene '{item.scene_name}'")
    try:
        # Clear existing file to force re-download for "Try Another"
        if os.path.exists(out_path):
            os.remove(out_path)

        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": item.prompt, "per_page": 10, "orientation": "portrait"},
            timeout=10,
        )
        resp.raise_for_status()
        data   = resp.json()
        photos = data.get("photos", [])
        if not photos or index >= len(photos):
            log.warning(f"[pexels] No results (or index out of range) for '{item.prompt}'")
            item.status = "failed"
            return False

        # Pick the image at the specified index
        url = photos[index]["src"]["large2x"]
        img_resp = requests.get(url, timeout=20)
        img_resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(img_resp.content)

        item.local_path  = out_path
        item.pexels_url  = url
        item.status      = "ready"
        log.info(f"[pexels] ✓ Saved (idx={index}): {out_path}")
        return True

    except Exception as e:
        log.error(f"[pexels] Failed for '{item.prompt}': {e}")
        item.status = "failed"
        return False


def fetch_all_stock(manifest: AssetManifest) -> dict:
    """Fetch all STOCK assets in the manifest. Returns status summary."""
    results = {"fetched": 0, "failed": 0, "already_ready": 0}
    for item in manifest.auto_fetch:
        if item.status == "ready":
            results["already_ready"] += 1
            continue
        ok = fetch_pexels_asset(item, manifest.project_name)
        if ok:
            results["fetched"] += 1
        else:
            results["failed"] += 1
    return results


# ═══════════════════════════════════════════════════════════════════
# REGISTER UPLOADED ASSET
# Called by the API when user uploads an AI image/video
# ═══════════════════════════════════════════════════════════════════

def register_uploaded_asset(
    manifest:   AssetManifest,
    scene_name: str,
    file_path:  str,
) -> bool:
    """
    Mark a user-uploaded asset as ready in the manifest.
    Returns True if the scene was found and updated.
    """
    for item in manifest.user_upload:
        if item.scene_name == scene_name:
            item.local_path = file_path
            item.status     = "ready"
            log.info(f"[asset] Registered upload for scene '{scene_name}': {file_path}")
            return True
    log.warning(f"[asset] Scene '{scene_name}' not found in user_upload manifest.")
    return False


# ═══════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════

def manifest_to_checklist(manifest: AssetManifest) -> str:
    """Human-readable asset checklist for display in the UI."""
    lines = [f"📋 Asset checklist for: {manifest.project_name}", ""]

    if manifest.auto_fetch:
        lines.append("✅ Auto-fetched from Pexels (no action needed):")
        for item in manifest.auto_fetch:
            status = "✓ ready" if item.status == "ready" else "⏳ pending"
            lines.append(f"   [{status}] Scene '{item.scene_name}': {item.prompt}")
        lines.append("")

    if manifest.user_upload:
        lines.append("⬆️  Upload required (generate with Seedance/Leonardo AI):")
        for item in manifest.user_upload:
            status  = "✓ ready" if item.status == "ready" else "❌ MISSING"
            asset_type = getattr(item, "type", None) or getattr(item, "asset_type", "UNKNOWN")

            type_lbl = {
                "AI_IMAGE": "🖼 AI Image",
                "AI_VIDEO": "🎬 AI Video",
                "USER_VIDEO": "📹 Your footage",
                "STOCK": "📦 Stock"
            }.get(asset_type, asset_type)
            # type_lbl = {"AI_IMAGE": "🖼 AI Image", "AI_VIDEO": "🎬 AI Video", "USER_VIDEO": "📹 Your footage"}.get(item.type, item.type)
            lines.append(f"   [{status}] {type_lbl} — Scene '{item.scene_name}'")
            lines.append(f"            Prompt: {item.prompt}")
            if item.motion != "ken_burns":
                lines.append(f"            Motion: {item.motion}")
        lines.append("")

    if manifest.music_needed:
        lines.append("🎵 Music files needed in music/ folder:")
        for m in manifest.music_needed:
            path   = f"music/{m}.mp3"
            exists = os.path.exists(path)
            lines.append(f"   {'✓' if exists else '❌'} {path}")
        lines.append("")

    if manifest.sfx_needed:
        lines.append("🔊 SFX files needed in sfx/ folder:")
        for s in manifest.sfx_needed:
            path   = f"sfx/{s}.mp3"
            exists = os.path.exists(path)
            lines.append(f"   {'✓' if exists else '❌'} {path}")
        lines.append("")

    missing = manifest.missing()
    if missing:
        lines.append(f"⚠️  {len(missing)} asset(s) still missing — rendering blocked until ready.")
    else:
        lines.append("🟢 All assets ready — rendering can begin.")

    return "\n".join(lines)
