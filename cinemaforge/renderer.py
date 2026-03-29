"""
renderer.py — CinemaForge
═══════════════════════════════════════════════════════════════════

Extends ReelForge BEAST MODE renderer with:
  ✓ Scene-by-scene rendering (each scene = own background + audio)
  ✓ AI_IMAGE motion effects: zoom_in | zoom_out | pan_left | pan_right | ken_burns
  ✓ AI_VIDEO clip support (VideoFileClip instead of ImageClip)
  ✓ Multi-speaker subtitle support (speaker name tag above line)
  ✓ Dynamic music crossfade between scenes
  ✓ Per-scene SFX with offset timing
  ✓ Auto Short clip generation from the highest-impact scene
  ✓ Long-form stitching: all scenes → final .mp4
  ✓ All ReelForge BEAST MODE features preserved
═══════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import logging
import subprocess
import textwrap
import random
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import numpy as np
from moviepy import (
    ImageClip, VideoFileClip, AudioFileClip, TextClip,
    CompositeVideoClip, CompositeAudioClip,
    ColorClip, VideoClip, concatenate_videoclips,
    vfx, afx,
)

from .parser import Scene, ProjectMeta, AssetManifest
from .tts    import SceneAudio

log = logging.getLogger("renderer")

# ═══════════════════════════════════════════════════════════════════
# CONFIG — inherits ReelForge values, adds CinemaForge extensions
# ═══════════════════════════════════════════════════════════════════

MUSIC_FOLDER  = os.environ.get("MUSIC_FOLDER",  "music")
SFX_FOLDER    = os.environ.get("SFX_FOLDER",    "sfx")
OUTPUT_FOLDER = os.environ.get("OUTPUT_FOLDER", "output")
FONT_PATH     = os.environ.get("FONT_PATH",     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_GEORGIA  = os.environ.get("FONT_GEORGIA",  "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf")
FONT_GEORGIA_I = os.environ.get("FONT_GEORGIA_I", "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf")

# ── Dimensions ──────────────────────────────────────────────────────
VIDEO_W_VERTICAL   = 1080
VIDEO_H_VERTICAL   = 1920
VIDEO_W_HORIZONTAL = 1920
VIDEO_H_HORIZONTAL = 1080

# ── Safe margins ────────────────────────────────────────────────────
SAFE_MARGIN = 80

# ── Font sizes ──────────────────────────────────────────────────────
FONT_SIZE_NORMAL   = 72
FONT_SIZE_HOOK     = 96
FONT_SIZE_PUNCH    = 108
FONT_SIZE_SPEAKER  = 52    # speaker name tag above dialogue line
FONT_SIZE_ENGAGE   = 82

WRAP_WIDTH_NORMAL  = 22
WRAP_WIDTH_PUNCH   = 18

# ── Colors ──────────────────────────────────────────────────────────
COLOR_WHITE  = (255, 255, 255)
COLOR_YELLOW = (255, 225, 0)
COLOR_GOLD   = (255, 200, 0)
COLOR_GRAY   = (210, 210, 210)
COLOR_BLACK  = (0, 0, 0)
COLOR_RED    = (220, 50, 50)     # for speaker name tag

# ── Timing ──────────────────────────────────────────────────────────
SILENCE_BUFFER     = 0.3         # gap between scenes
OUTRO_HOLD         = 2.5
OUTRO_FADE_IN      = 0.7
OUTRO_FADE_OUT     = 0.8
SCENE_CROSSFADE    = 0.5         # video crossfade between scenes
HOOK_WORD_DURATION = 0.18

# ── Music volumes ────────────────────────────────────────────────────
MUSIC_VOL_BASE  = 0.08
MUSIC_VOL_SWELL = 0.22
MUSIC_VOL_OUTRO = 0.10

# ── Overlay opacities ────────────────────────────────────────────────
OVERLAY_DEFAULT = 0.52
OVERLAY_HOOK    = 0.62
OVERLAY_PUNCH   = 0.65
OVERLAY_SHIFT   = 0.44

POWER_WORDS = {
    "silence", "power", "powerful", "never", "always", "truth", "lies",
    "fear", "dangerous", "strength", "control", "dominate", "real", "fake",
    "unstoppable", "chosen", "purpose", "obsession", "free", "trap",
}


# ═══════════════════════════════════════════════════════════════════
# DIMENSIONS HELPER
# ═══════════════════════════════════════════════════════════════════

def get_dimensions(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16x9":
        return VIDEO_W_HORIZONTAL, VIDEO_H_HORIZONTAL
    return VIDEO_W_VERTICAL, VIDEO_H_VERTICAL


# ═══════════════════════════════════════════════════════════════════
# BACKGROUND CLIP BUILDER
# Handles: STOCK (image), AI_IMAGE (image+motion), AI_VIDEO, USER_VIDEO
# ═══════════════════════════════════════════════════════════════════

def build_scene_background(
    scene:    Scene,
    duration: float,
    video_w:  int,
    video_h:  int,
) -> list:
    """
    Returns a list of clips for this scene's background layer.
    Motion effects applied based on scene.background.motion.
    """
    bg   = scene.background
    path = bg.resolved_path

    if not path or not os.path.exists(path):
        # Fallback: black background
        log.warning(f"[render] No asset for scene '{scene.name}' — using black background.")
        return [ColorClip((video_w, video_h), color=COLOR_BLACK, duration=duration)]

    is_video = path.lower().endswith((".mp4", ".mov", ".avi", ".webm"))

    if is_video:
        clip = (
            VideoFileClip(path)
            .resized(height=video_h)
            .cropped(x_center=None, width=video_w, height=video_h)
        )
        # Loop if shorter than needed
        if clip.duration < duration:
            clip = clip.loop(duration=duration)
        else:
            clip = clip.subclipped(0, duration)
        return [clip]

    # Image-based: apply motion effect
    motion = bg.motion.lower()

    def zoom_in(t):
        return 1.0 + 0.025 * (t / max(duration, 1))

    def zoom_out(t):
        return 1.025 - 0.025 * (t / max(duration, 1))

    def ken_burns(t):
        # Gentle slow zoom — same as ReelForge default
        return 1.0 + 0.008 * t

    def still(t):
        return 1.0

    zoom_funcs = {
        "zoom_in":   zoom_in,
        "zoom_out":  zoom_out,
        "ken_burns": ken_burns,
        "still":     still,
        "pan_left":  ken_burns,   # pan via position offset (handled below)
        "pan_right": ken_burns,
    }
    zoom_func = zoom_funcs.get(motion, ken_burns)

    img = (
        ImageClip(path)
        .with_duration(duration)
        .resized(height=video_h)
    )
    img = img.cropped(x_center=img.w / 2, width=video_w, height=video_h)
    img = img.with_effects([vfx.Resize(zoom_func)])

    # Pan effects: shift x position over time
    if motion == "pan_left":
        def pan_pos(t):
            offset = int(40 * (t / max(duration, 1)))
            return (-offset, 0)
        img = img.with_position(pan_pos)

    elif motion == "pan_right":
        def pan_pos(t):
            offset = int(40 * (t / max(duration, 1)))
            return (offset, 0)
        img = img.with_position(pan_pos)

    return [img]


# ═══════════════════════════════════════════════════════════════════
# OVERLAY BUILDER
# ═══════════════════════════════════════════════════════════════════

def build_overlay(style: str, duration: float, video_w: int, video_h: int) -> ColorClip:
    opacity_map = {
        "hook":   OVERLAY_HOOK,
        "punch":  OVERLAY_PUNCH,
        "shift":  OVERLAY_SHIFT,
        "normal": OVERLAY_DEFAULT,
        "none":   0.0,
    }
    opacity = opacity_map.get(style, OVERLAY_DEFAULT)
    return (
        ColorClip((video_w, video_h), color=COLOR_BLACK, duration=duration)
        .with_opacity(opacity)
    )


def build_vignette(duration: float, video_w: int, video_h: int) -> list:
    VIGNETTE_H = 280
    top = (
        ColorClip((video_w, VIGNETTE_H), color=COLOR_BLACK, duration=duration)
        .with_opacity(0.55)
        .with_position((0, 0))
    )
    bot = (
        ColorClip((video_w, VIGNETTE_H), color=COLOR_BLACK, duration=duration)
        .with_opacity(0.60)
        .with_position((0, video_h - VIGNETTE_H))
    )
    return [top, bot]


# ═══════════════════════════════════════════════════════════════════
# SUBTITLE BUILDER
# ═══════════════════════════════════════════════════════════════════

def make_text_clip(text, font, font_size, color, method="caption",
                   stroke_color=None, stroke_width=0, text_width=None):
    if text_width is None:
        text_width = VIDEO_W_VERTICAL - SAFE_MARGIN * 2
    padded = text + "\n\n"
    kwargs = dict(
        text=padded, font=font, font_size=font_size, color=color,
        stroke_color=stroke_color, stroke_width=stroke_width,
        method=method, size=(text_width, None),
    )
    return TextClip(**kwargs)


def contains_power_word(line: str) -> bool:
    return any(w in POWER_WORDS for w in re.findall(r"\w+", line.lower()))


def build_scene_subtitles(
    scene:      Scene,
    audio:      SceneAudio,
    stamps:     list,          # list[WordStamp] from alignment
    video_w:    int,
    video_h:    int,
) -> list:
    """
    Build subtitle clips for a single scene.
    Supports: hook flash | punch centered | speaker tag | power words | normal
    """
    from .alignment import get_word_timestamps, proportional_timings, line_timings_from_stamps

    text_width  = video_w - SAFE_MARGIN * 2
    text_bottom = video_h - 420
    hook_y      = 380
    punch_y     = video_h // 2

    lines = [l.strip() for l in scene.lines if l.strip()]
    if not lines:
        return []

    # Get timings
    timings = None
    if stamps:
        timings = line_timings_from_stamps(lines, stamps, audio.duration)
    if not timings:
        timings = proportional_timings(lines, audio.duration)

    style    = scene.style.lower()
    clips    = []

    for i, line in enumerate(lines):
        start_t, dur = timings[i]
        has_power    = contains_power_word(line)

        # ── HOOK: word-by-word flash ──────────────────────────────
        if style == "hook":
            words      = line.split()
            actual_dur = min(HOOK_WORD_DURATION, dur / max(len(words), 1))
            for wi, word in enumerate(words):
                w_start = start_t + wi * actual_dur
                if w_start >= start_t + dur:
                    break
                wc = (
                    make_text_clip(word.upper(), FONT_PATH, FONT_SIZE_HOOK,
                                   COLOR_WHITE, stroke_color="black", stroke_width=8,
                                   text_width=text_width)
                    .with_position(("center", hook_y))
                    .with_start(w_start)
                    .with_duration(actual_dur)
                    .with_effects([vfx.FadeIn(0.04), vfx.FadeOut(0.06)])
                )
                clips.append(wc)
            continue

        # ── PUNCH: full screen centered yellow ────────────────────
        if style == "punch":
            wrapped = textwrap.fill(line, width=WRAP_WIDTH_PUNCH)
            tc = make_text_clip(wrapped, FONT_PATH, FONT_SIZE_PUNCH, COLOR_YELLOW,
                                stroke_color="black", stroke_width=9, text_width=text_width)
            y  = max(punch_y - tc.h // 2, 200)
            tc = (
                tc
                .with_position(("center", y))
                .with_start(start_t)
                .with_duration(dur)
                .with_effects([vfx.FadeIn(0.08)])
            )
            clips.append(tc)
            continue

        # ── SPEAKER TAG: show name above dialogue line ────────────
        if scene.speaker_name and scene.type != "narration":
            name_clip = (
                make_text_clip(
                    scene.speaker_name.upper(),
                    FONT_GEORGIA, FONT_SIZE_SPEAKER, COLOR_RED,
                    method="label", text_width=text_width,
                )
                .with_position(("center", text_bottom - 80))
                .with_start(start_t)
                .with_duration(dur)
                .with_effects([vfx.FadeIn(0.2), vfx.FadeOut(0.2)])
            )
            clips.append(name_clip)

        # ── POWER WORD: yellow + pill ─────────────────────────────
        if has_power:
            wrapped = textwrap.fill(line, width=WRAP_WIDTH_NORMAL)
            tc = make_text_clip(wrapped, FONT_PATH, FONT_SIZE_NORMAL, COLOR_YELLOW,
                                stroke_color="black", stroke_width=6, text_width=text_width)
            y  = max(text_bottom - tc.h, 200)
            pill = (
                ColorClip((tc.w + 48, tc.h + 24), color=COLOR_BLACK, duration=dur)
                .with_opacity(0.50)
                .with_position(("center", y - 12))
                .with_start(start_t)
                .with_effects([vfx.FadeIn(0.25), vfx.FadeOut(0.3)])
            )
            tc = (
                tc
                .with_position(("center", y))
                .with_start(start_t)
                .with_duration(dur)
                .with_effects([vfx.FadeIn(0.25), vfx.FadeOut(0.3)])
            )
            clips.extend([pill, tc])
            continue

        # ── NORMAL ────────────────────────────────────────────────
        wrapped = textwrap.fill(line, width=WRAP_WIDTH_NORMAL)
        tc = make_text_clip(wrapped, FONT_PATH, FONT_SIZE_NORMAL, COLOR_WHITE,
                            stroke_color="black", stroke_width=5, text_width=text_width)
        y  = max(text_bottom - tc.h, 200)
        tc = (
            tc
            .with_position(("center", y))
            .with_start(start_t)
            .with_duration(dur)
            .with_effects([vfx.FadeIn(0.35), vfx.FadeOut(0.3)])
        )
        clips.append(tc)

    return clips


# ═══════════════════════════════════════════════════════════════════
# AUDIO BUILDER PER SCENE
# ═══════════════════════════════════════════════════════════════════

def build_scene_audio(
    scene:         Scene,
    audio:         SceneAudio,
    total_dur:     float,
    current_music: str | None,
) -> tuple[CompositeAudioClip, str]:
    """
    Build the composite audio for a single scene.
    Returns (CompositeAudioClip, new_current_music_track_name)
    """
    voice = AudioFileClip(audio.mp3_path).with_effects([afx.AudioFadeOut(0.4)])
    layers = [voice]

    # Music
    music_name = scene.music.strip().lower()
    if music_name == "continue":
        music_name = current_music
    if music_name and music_name != "none":
        music_path = os.path.join(MUSIC_FOLDER, f"{music_name}.mp3")
        if os.path.exists(music_path):
            is_swell   = "swell" in music_name
            vol        = MUSIC_VOL_SWELL if is_swell else MUSIC_VOL_BASE
            music_clip = (
                AudioFileClip(music_path)
                .subclipped(0, min(total_dur, AudioFileClip(music_path).duration))
                .with_volume_scaled(vol)
                .with_effects([afx.AudioFadeIn(0.5), afx.AudioFadeOut(0.8)])
            )
            layers.append(music_clip)
        else:
            log.warning(f"[audio] Music not found: {music_path}")

    # SFX
    for sfx_decl in scene.sfx:
        # Try direct name, then safe name, for .wav and .mp3
        sfx_path = None
        names = [sfx_decl.name, re.sub(r"[^\w]", "_", sfx_decl.name.lower())]
        for n in names:
            for ext in (".wav", ".mp3"):
                path = os.path.join(SFX_FOLDER, f"{n}{ext}")
                if os.path.exists(path):
                    sfx_path = path
                    break
            if sfx_path: break

        if sfx_path:
            try:
                from moviepy.audio.fx.AudioFadeOut import AudioFadeOut
                sfx = (
                    AudioFileClip(sfx_path)
                    .with_start(sfx_decl.offset)
                    .with_volume_scaled(0.6)
                    .with_effects([AudioFadeOut(0.1)])
                )
                layers.append(sfx)
            except Exception as e:
                log.warning(f"[audio] SFX load failed ({sfx_decl.name}): {e}")
        else:
            log.warning(f"[audio] SFX not found: {sfx_decl.name}")

    return CompositeAudioClip(layers), music_name


# ═══════════════════════════════════════════════════════════════════
# WATERMARK + OUTRO (shared across scenes)
# ═══════════════════════════════════════════════════════════════════

def build_watermark(page_name: str, total_dur: float, video_w: int) -> TextClip:
    text_width = video_w - SAFE_MARGIN * 2
    wm = TextClip(
        text=page_name.upper() + "\n\n",
        font=FONT_GEORGIA, font_size=28,
        color=(255, 255, 255), method="label",
        size=(text_width, None),
    )
    return wm.with_opacity(0.28).with_position(("center", 52)).with_duration(total_dur)


def build_outro(
    voice_end:   float,
    total_dur:   float,
    page_name:   str,
    tagline:     str,
    video_w:     int,
    video_h:     int,
) -> list:
    text_width  = video_w - SAFE_MARGIN * 2
    outro_start = voice_end + SILENCE_BUFFER
    outro_dur   = total_dur - outro_start
    if outro_dur <= 0:
        return []

    clips    = []
    anchor_y = video_h // 2

    bg = (
        ColorClip((video_w, video_h), color=COLOR_BLACK, duration=outro_dur)
        .with_opacity(0.72).with_start(outro_start)
        .with_effects([vfx.FadeIn(OUTRO_FADE_IN), vfx.FadeOut(OUTRO_FADE_OUT)])
    )
    clips.append(bg)

    for y in [anchor_y - 70, anchor_y + 30]:
        clips.append(
            ColorClip((380, 2), color=COLOR_WHITE, duration=outro_dur)
            .with_position(("center", y)).with_start(outro_start)
            .with_effects([vfx.FadeIn(OUTRO_FADE_IN), vfx.FadeOut(OUTRO_FADE_OUT)])
        )

    name_clip = (
        TextClip(text="  ".join(page_name.upper()) + "\n\n", font=FONT_GEORGIA,
                 font_size=74, color=(255, 255, 255), method="label",
                 size=(text_width, None))
        .with_position(("center", anchor_y - 50)).with_start(outro_start)
        .with_duration(outro_dur)
        .with_effects([vfx.FadeIn(OUTRO_FADE_IN), vfx.FadeOut(OUTRO_FADE_OUT)])
    )
    clips.append(name_clip)

    if tagline:
        tag_clip = (
            TextClip(text=tagline + "\n\n", font=FONT_GEORGIA_I,
                     font_size=32, color=COLOR_GRAY, method="label",
                     size=(text_width, None))
            .with_position(("center", anchor_y + 50)).with_start(outro_start)
            .with_duration(outro_dur)
            .with_effects([vfx.FadeIn(OUTRO_FADE_IN + 0.35), vfx.FadeOut(OUTRO_FADE_OUT)])
        )
        clips.append(tag_clip)

    return clips


# ═══════════════════════════════════════════════════════════════════
# SCENE RENDERER — one scene → one CompositeVideoClip
# ═══════════════════════════════════════════════════════════════════

def render_scene(
    scene:     Scene,
    audio:     SceneAudio,
    stamps:    list,
    meta:      ProjectMeta,
    video_w:   int,
    video_h:   int,
    current_music: str | None,
) -> tuple:
    """
    Renders a single scene. Returns (CompositeVideoClip, new_current_music).
    """
    duration   = audio.duration + SILENCE_BUFFER
    text_width = video_w - SAFE_MARGIN * 2

    # Background
    bg_clips = build_scene_background(scene, duration, video_w, video_h)

    # Overlay
    overlay = build_overlay(scene.style, duration, video_w, video_h)

    # Vignette
    vig_clips = build_vignette(duration, video_w, video_h)

    # Subtitles
    sub_clips = [] if scene.style == "none" else build_scene_subtitles(
        scene, audio, stamps, video_w, video_h
    )

    # Watermark
    wm = build_watermark(meta.page_name, duration, video_w)

    # Audio
    scene_audio, new_music = build_scene_audio(
        scene, audio, duration, current_music
    )

    all_clips = bg_clips + [overlay] + vig_clips + [wm] + sub_clips
    composed  = (
        CompositeVideoClip(all_clips, size=(video_w, video_h))
        .with_audio(scene_audio)
        .with_duration(duration)
        .with_effects([vfx.FadeIn(SCENE_CROSSFADE), vfx.FadeOut(SCENE_CROSSFADE)])
    )

    return composed, new_music


# ═══════════════════════════════════════════════════════════════════
# AUTO SHORT GENERATOR
# Picks the highest-impact scene and clips it to 45s
# ═══════════════════════════════════════════════════════════════════

def _impact_score(scene: Scene) -> int:
    score = 0
    if scene.style == "punch":   score += 10
    if scene.style == "hook":    score += 6
    if scene.sfx:                score += 3
    if "swell" in scene.music:   score += 3
    score += sum(1 for l in scene.lines if contains_power_word(l))
    return score


def generate_short_from_best_scene(
    final_mp4:    str,
    scenes:       list[Scene],
    scene_audios: list[SceneAudio],
    output_dir:   str,
    project_name: str,
) -> str | None:
    """
    Finds the highest-impact scene in the project and clips it to 45s.
    Saves as <project_name>_short.mp4.
    Returns the output path or None on failure.
    """
    if not scenes:
        return None

    # Score each scene and pick the best
    scored = sorted(
        zip(scenes, scene_audios),
        key=lambda x: _impact_score(x[0]),
        reverse=True,
    )
    best_scene, best_audio = scored[0]
    log.info(f"[short] Best scene for Short: '{best_scene.name}' (score={_impact_score(best_scene)})")

    # Find start time of this scene in the full video
    start_time = 0.0
    for scene, audio in zip(scenes, scene_audios):
        if scene.name == best_scene.name:
            break
        start_time += audio.duration + SILENCE_BUFFER

    clip_dur = min(45.0, best_audio.duration + SILENCE_BUFFER)
    safe_proj = re.sub(r"[^\w]", "_", project_name).lower()
    out_path  = os.path.join(output_dir, f"{safe_proj}_short.mp4")

    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-ss", str(start_time),
             "-i", final_mp4,
             "-t", str(clip_dur),
             "-c:v", "libx264", "-c:a", "aac",
             "-preset", "fast",
             out_path],
            check=True, capture_output=True,
        )
        log.info(f"[short] ✓ Short saved: {out_path}")
        return out_path
    except subprocess.CalledProcessError as e:
        log.error(f"[short] Failed to generate short: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# MAIN RENDER FUNCTION
# Orchestrates full project render: scenes → stitch → outro → short
# ═══════════════════════════════════════════════════════════════════

def render_project(
    meta:         ProjectMeta,
    scenes:       list[Scene],
    scene_audios: list[SceneAudio],
    stamps_map:   dict[str, list],   # {scene_name: [WordStamp,...]}
    output_dir:   str,
    generate_short: bool = True,
) -> dict[str, str]:
    """
    Full project render.
    Returns dict with keys: 'longform', 'short' (if generated).
    """
    os.makedirs(output_dir, exist_ok=True)
    safe_name   = re.sub(r"[^\w]", "_", meta.name).lower()
    video_w, video_h = get_dimensions(meta.aspect_ratio)

    log.info(f"[render] ══ Project: {meta.name} | {meta.format} | {meta.aspect_ratio} ══")

    # ── Render each scene ─────────────────────────────────────────
    scene_clips    = []
    current_music  = None

    for scene, audio in zip(scenes, scene_audios):
        stamps = stamps_map.get(scene.name, [])
        log.info(f"[render] Scene: {scene.name} ({audio.duration:.1f}s)")

        composed, current_music = render_scene(
            scene, audio, stamps, meta, video_w, video_h, current_music
        )
        scene_clips.append(composed)

    # ── Stitch scenes ─────────────────────────────────────────────
    log.info(f"[render] Stitching {len(scene_clips)} scenes...")
    total_voice_dur = sum(a.duration for a in scene_audios)
    main_video      = concatenate_videoclips(scene_clips, method="compose")

    # ── Outro ─────────────────────────────────────────────────────
    outro_total = main_video.duration + OUTRO_HOLD
    outro_clips = build_outro(
        voice_end  = main_video.duration,
        total_dur  = outro_total,
        page_name  = meta.page_name,
        tagline    = meta.tagline,
        video_w    = video_w,
        video_h    = video_h,
    )

    if outro_clips:
        # Extend main with black + outro
        black_ext = ColorClip((video_w, video_h), color=COLOR_BLACK, duration=OUTRO_HOLD)
        final     = concatenate_videoclips([main_video, black_ext], method="compose")
        final     = CompositeVideoClip([final] + outro_clips, size=(video_w, video_h))
    else:
        final = main_video

    # ── Write longform ────────────────────────────────────────────
    longform_path = os.path.join(output_dir, f"{safe_name}.mp4")
    log.info(f"[render] Writing longform: {longform_path}")
    final.write_videofile(
        longform_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=4,
    )
    log.info(f"[render] ✓ Longform done: {longform_path}")

    result = {"longform": longform_path}

    # ── Auto short ────────────────────────────────────────────────
    if generate_short and meta.format in ("short", "both"):
        short_path = generate_short_from_best_scene(
            final_mp4    = longform_path,
            scenes       = scenes,
            scene_audios = scene_audios,
            output_dir   = output_dir,
            project_name = meta.name,
        )
        if short_path:
            result["short"] = short_path

    return result
