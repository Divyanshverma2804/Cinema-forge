"""
alignment.py — CinemaForge
Forced alignment module — extracted from ReelForge for clean reuse.
Unchanged logic, just modularised.
"""
import re
import logging
from dataclasses import dataclass

log = logging.getLogger("alignment")

ALIGN_BACKEND = __import__("os").environ.get("ALIGN_BACKEND", "wav2vec2")


@dataclass
class WordStamp:
    word:  str
    start: float
    end:   float


def get_word_timestamps(wav_path: str, transcript: str) -> list[WordStamp]:
    backend = ALIGN_BACKEND.lower()
    try:
        stamps = _align_wav2vec2(wav_path, transcript) if backend == "wav2vec2" \
            else _align_whisper(wav_path, transcript)  if backend == "whisper"  \
            else []
        if stamps:
            log.info(f"[align] {len(stamps)} word timestamps via {backend}.")
        else:
            log.warning("[align] No timestamps — proportional fallback.")
        return stamps
    except Exception as e:
        log.warning(f"[align] Error ({backend}): {e}")
        return []


def _align_wav2vec2(wav_path: str, transcript: str) -> list[WordStamp]:
    import torch, torchaudio
    device = "cuda" if torch.cuda.is_available() else "cpu"
    waveform, sample_rate = torchaudio.load(wav_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    bundle    = torchaudio.pipelines.MMS_300M
    model_    = bundle.get_model().to(device)
    tokenizer = bundle.get_tokenizer()
    aligner   = bundle.get_aligner()
    if sample_rate != bundle.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, bundle.sample_rate)
    with torch.inference_mode():
        emission, _ = model_(waveform.to(device))
    words = re.findall(r"[a-zA-Z']+", transcript.lower())
    if not words: return []
    try:
        token_spans = aligner(emission[0], tokenizer(words))
    except Exception as e:
        log.warning(f"[align] wav2vec2 failed: {e}")
        return []
    ratio = waveform.shape[1] / emission.shape[1] / bundle.sample_rate
    return [
        WordStamp(word=words[i], start=spans[0].start*ratio, end=spans[-1].end*ratio)
        for i, spans in enumerate(token_spans)
    ]


def _align_whisper(wav_path: str, transcript: str) -> list[WordStamp]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("[align] faster-whisper not installed.")
        return []
    model = WhisperModel("base", device="auto", compute_type="int8")
    segs, _ = model.transcribe(wav_path, word_timestamps=True, language="en")
    stamps = []
    for seg in segs:
        for w in (seg.words or []):
            clean = re.sub(r"[^a-zA-Z']", "", w.word).lower()
            if clean:
                stamps.append(WordStamp(word=clean, start=w.start, end=w.end))
    return stamps


def line_timings_from_stamps(
    lines: list[str], stamps: list[WordStamp], voice_dur: float
) -> list[tuple[float, float]]:
    line_words = []
    for i, line in enumerate(lines):
        for w in re.findall(r"[a-zA-Z']+", line.lower()):
            line_words.append((i, w))
    if not line_words or not stamps: return []

    stamp_idx   = 0
    line_starts: dict[int, float] = {}
    line_ends:   dict[int, float] = {}

    for (li, word) in line_words:
        for si in range(stamp_idx, len(stamps)):
            if stamps[si].word == word:
                if li not in line_starts:
                    line_starts[li] = stamps[si].start
                line_ends[li] = stamps[si].end
                stamp_idx = si + 1
                break

    if not line_starts: return []
    sorted_indices = sorted(line_starts.keys())
    timings = []
    for k, li in enumerate(sorted_indices):
        start   = line_starts[li]
        raw_end = line_ends.get(li, start + 0.5)
        end     = line_starts[sorted_indices[k+1]] if k+1 < len(sorted_indices) \
                  else max(raw_end, voice_dur)
        timings.append((start, max(end - start, 0.3)))

    if len(timings) != len(lines): return []
    return timings


def proportional_timings(lines: list[str], voice_dur: float) -> list[tuple[float, float]]:
    total_words = sum(max(len(l.split()), 1) for l in lines)
    raw         = [(max(len(l.split()), 1) / total_words) * voice_dur for l in lines]
    scale       = voice_dur / sum(raw)
    durations   = [d * scale for d in raw]
    timings, cur = [], 0.0
    for d in durations:
        timings.append((cur, d))
        cur += d
    return timings
