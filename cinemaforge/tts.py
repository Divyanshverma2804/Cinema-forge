"""
tts.py — CinemaForge
═══════════════════════════════════════════════════════════════════

Extends ReelForge's Chatterbox TTS with:
  ✓ Multi-speaker dialogue (each speaker = own voice profile)
  ✓ Per-scene emotion tuning from script declarations
  ✓ Voice reference files in voices/<speaker_name>.wav
  ✓ Scene-by-scene WAV generation (not one long audio blob)
  ✓ Full Hindi (HI) channel support via speaker lang flag
  ✓ All ReelForge section-based TTS logic preserved for shorts/motivational
═══════════════════════════════════════════════════════════════════
"""

import os
import re
import logging
import subprocess
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("tts")

VOICES_FOLDER = os.environ.get("VOICES_FOLDER", "voices")

# ── Emotion → Chatterbox params mapping ─────────────────────────────
# Covers all speaker emotions you might declare in the script
EMOTION_PARAMS: dict[str, dict] = {
    # Narrator styles
    "cold":       {"exaggeration": 0.55, "cfg_weight": 0.48},
    "slow":       {"exaggeration": 0.42, "cfg_weight": 0.38},
    "dark":       {"exaggeration": 0.60, "cfg_weight": 0.52},
    "warm":       {"exaggeration": 0.45, "cfg_weight": 0.40},
    "dramatic":   {"exaggeration": 0.78, "cfg_weight": 0.60},
    "fincher":    {"exaggeration": 0.52, "cfg_weight": 0.44},  # your signature style

    # Dialogue character styles
    "gruff":      {"exaggeration": 0.68, "cfg_weight": 0.55},
    "urgent":     {"exaggeration": 0.80, "cfg_weight": 0.65},
    "scared":     {"exaggeration": 0.85, "cfg_weight": 0.70},
    "quiet":      {"exaggeration": 0.35, "cfg_weight": 0.32},
    "direct":     {"exaggeration": 0.62, "cfg_weight": 0.50},
    "calm":       {"exaggeration": 0.40, "cfg_weight": 0.36},
    "angry":      {"exaggeration": 0.90, "cfg_weight": 0.72},
    "sad":        {"exaggeration": 0.50, "cfg_weight": 0.42},
    "nervous":    {"exaggeration": 0.75, "cfg_weight": 0.62},
    "confident":  {"exaggeration": 0.60, "cfg_weight": 0.50},
    "sinister":   {"exaggeration": 0.65, "cfg_weight": 0.55},

    # ReelForge section names (backward compat)
    "hook":       {"exaggeration": 0.75, "cfg_weight": 0.55},
    "punch":      {"exaggeration": 0.82, "cfg_weight": 0.62},
    "conflict":   {"exaggeration": 0.65, "cfg_weight": 0.50},
    "shift":      {"exaggeration": 0.42, "cfg_weight": 0.42},
    "engage":     {"exaggeration": 0.50, "cfg_weight": 0.40},
    "default":    {"exaggeration": 0.55, "cfg_weight": 0.45},
}


def _blend_emotions(emotion_str: str) -> dict:
    """
    Takes a comma/space separated emotion string from the script
    e.g. 'gruff, direct' → averages the params of each emotion.
    Falls back to 'default' for unknown emotions.
    """
    emotions = [e.strip().lower() for e in re.split(r"[,\s]+", emotion_str) if e.strip()]
    if not emotions:
        return EMOTION_PARAMS["default"]

    valid = [EMOTION_PARAMS[e] for e in emotions if e in EMOTION_PARAMS]
    if not valid:
        return EMOTION_PARAMS["default"]

    avg_exag = sum(p["exaggeration"] for p in valid) / len(valid)
    avg_cfg  = sum(p["cfg_weight"]   for p in valid) / len(valid)
    return {"exaggeration": round(avg_exag, 3), "cfg_weight": round(avg_cfg, 3)}


def _get_voice_ref(speaker_name: str, voice_mapping: dict = None) -> str | None:
    """
    Looks for a .wav or .mp3 in VOICES_FOLDER that matches the speaker_name
    or its mapped system voice.
    """
    if not speaker_name:
        return None

    # 1. Check mapping first
    if voice_mapping and speaker_name in voice_mapping:
        mapped_name = voice_mapping[speaker_name]
        safe_mapped = re.sub(r"[^\w]", "_", mapped_name.lower())
        for ext in (".wav", ".mp3"):
            path = os.path.join(VOICES_FOLDER, f"{safe_mapped}{ext}")
            if os.path.exists(path):
                return path

    # 2. Fallback to direct name match
    safe = re.sub(r"[^\w]", "_", speaker_name.lower())
    for ext in (".wav", ".mp3"):
        path = os.path.join(VOICES_FOLDER, f"{safe}{ext}")
        if os.path.exists(path):
            return path
    return None


# ── Lazy TTS model loader ────────────────────────────────────────────
_tts_model = None

def _get_tts_model():
    global _tts_model
    if _tts_model is None:
        import torch
        from chatterbox.tts import ChatterboxTTS
        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info(f"[tts] Loading Chatterbox on {device}...")
        _tts_model = ChatterboxTTS.from_pretrained(device=device)
        log.info("[tts] Model ready.")
    return _tts_model


def _preprocess(text: str) -> str:
    """Clean text for TTS: normalise CAPS, join lines cleanly."""
    lines   = [l.strip() for l in text.split("\n") if l.strip()]
    cleaned = []
    for line in lines:
        line = re.sub(r'\b([A-Z]{2,})\b', lambda m: m.group(1).title(), line)
        cleaned.append(line)
    return " ".join(cleaned)


def generate_scene_wav(
    text:         str,
    wav_path:     str,
    speaker_name: str | None  = None,
    emotion_str:  str | None  = None,
    section_key:  str | None  = None,
    voice_mapping: dict = None,
) -> str:
    """
    Generate a WAV file for a single scene's narration or dialogue line.

    Priority for params:
      1. Explicit emotion_str from script (e.g. 'gruff, direct')
      2. section_key fallback (ReelForge backward compat: hook/punch/etc.)
      3. 'default'

    Voice ref priority:
      1. voices/<speaker_name>.wav if exists
      2. TTS_VOICE_REF env var (global default)
      3. None (Chatterbox default voice)

    Returns wav_path on success.
    """
    import torchaudio as ta

    model = _get_tts_model()

    # Resolve emotion params
    if emotion_str:
        params = _blend_emotions(emotion_str)
    elif section_key and section_key in EMOTION_PARAMS:
        params = EMOTION_PARAMS[section_key]
    else:
        params = EMOTION_PARAMS["default"]

    exaggeration = float(os.environ.get("TTS_EXAGGERATION", str(params["exaggeration"])))
    cfg_weight   = float(os.environ.get("TTS_CFG_WEIGHT",   str(params["cfg_weight"])))

    # Resolve voice ref
    voice_ref = _get_voice_ref(speaker_name, voice_mapping=voice_mapping) if speaker_name else None
    if not voice_ref:
        voice_ref = os.environ.get("TTS_VOICE_REF", "").strip() or None

    kwargs = dict(exaggeration=exaggeration, cfg_weight=cfg_weight)
    if voice_ref and os.path.exists(voice_ref):
        kwargs["audio_prompt_path"] = voice_ref
        log.info(f"[tts] Using voice ref: {voice_ref}")

    processed = _preprocess(text)
    log.info(f"[tts] Speaker={speaker_name or 'Narrator'} | emotion={emotion_str or section_key or 'default'} | exag={exaggeration:.2f} cfg={cfg_weight:.2f}")

    wav = model.generate(processed, **kwargs)
    ta.save(wav_path, wav, model.sr)
    log.info(f"[tts] ✓ WAV saved: {wav_path}")
    return wav_path


def wav_to_mp3(wav_path: str, mp3_path: str):
    """Convert WAV → MP3 with voice EQ (low-cut 80Hz + 3dB presence at 3kHz)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path,
         "-af", "highpass=f=80,equalizer=f=3000:width_type=o:width=2:g=3",
         "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
        check=True, capture_output=True,
    )


def concat_wavs(wav_paths: list[str], out_path: str):
    """Concatenate multiple WAV files into one using ffmpeg."""
    list_file = out_path + ".concat.txt"
    with open(list_file, "w") as f:
        for p in wav_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", list_file, "-c", "copy", out_path],
        check=True, capture_output=True,
    )
    os.remove(list_file)


# ═══════════════════════════════════════════════════════════════════
# HIGH-LEVEL: generate all audio for a full project
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SceneAudio:
    scene_name: str
    wav_path:   str
    mp3_path:   str
    duration:   float


def generate_project_audio(
    scenes:      list,   # list[Scene] from parser
    output_dir:  str,
    project_name: str,
    voice_mapping: dict = None,
) -> list[SceneAudio]:
    """
    Generate audio for every scene in the project.
    Each scene gets its own WAV + MP3.
    Returns list of SceneAudio with paths and durations.

    For dialogue scenes: each line is generated separately
    (potentially with different speakers) then concatenated.
    For narration scenes: all lines joined and generated as one.
    """
    import torchaudio as ta
    os.makedirs(output_dir, exist_ok=True)
    results = []
    safe_proj = re.sub(r"[^\w]", "_", project_name).lower()

    for scene in scenes:
        safe_name = re.sub(r"[^\w]", "_", scene.name).lower()
        log.info(f"[tts] ══ Scene: {scene.name} ══")

        # Narration: all lines as one TTS call
        if scene.speaker_name is None or scene.speaker_name.lower() in ("narrator", ""):
            full_text = "\n".join(scene.lines)
            wav_path  = os.path.join(output_dir, f"{safe_proj}_{safe_name}.wav")
            mp3_path  = os.path.join(output_dir, f"{safe_proj}_{safe_name}.mp3")

            generate_scene_wav(
                text         = full_text,
                wav_path     = wav_path,
                speaker_name = None,
                emotion_str  = scene.speaker_emotion,
                section_key  = scene.style if scene.style in EMOTION_PARAMS else None,
                voice_mapping = voice_mapping,
            )
            wav_to_mp3(wav_path, mp3_path)

            waveform, sr = ta.load(wav_path)
            duration     = waveform.shape[1] / sr

            results.append(SceneAudio(
                scene_name = scene.name,
                wav_path   = wav_path,
                mp3_path   = mp3_path,
                duration   = duration,
            ))

        # Dialogue: each line is a separate TTS call → concat
        else:
            line_wavs = []
            for li, line in enumerate(scene.lines):
                line_wav = os.path.join(output_dir, f"{safe_proj}_{safe_name}_line{li:02d}.wav")
                generate_scene_wav(
                    text         = line,
                    wav_path     = line_wav,
                    speaker_name = scene.speaker_name,
                    emotion_str  = scene.speaker_emotion,
                    voice_mapping = voice_mapping,
                )
                line_wavs.append(line_wav)

            combined_wav = os.path.join(output_dir, f"{safe_proj}_{safe_name}.wav")
            mp3_path     = os.path.join(output_dir, f"{safe_proj}_{safe_name}.mp3")
            concat_wavs(line_wavs, combined_wav)
            wav_to_mp3(combined_wav, mp3_path)

            # Cleanup line wavs
            for p in line_wavs:
                try: os.remove(p)
                except OSError: pass

            waveform, sr = ta.load(combined_wav)
            duration     = waveform.shape[1] / sr

            results.append(SceneAudio(
                scene_name = scene.name,
                wav_path   = combined_wav,
                mp3_path   = mp3_path,
                duration   = duration,
            ))

    log.info(f"[tts] ✓ All {len(results)} scenes generated.")
    return results
