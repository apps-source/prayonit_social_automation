"""Long-form vertical video renderer for prayer, devotional, and encouragement.

This renderer is intentionally separate from motion_renderer.py so the
existing 8-second short-form path remains unchanged.
"""
from __future__ import annotations

import random
import re
import subprocess
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, VideoFileClip
from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos

import config
import motion_renderer
import resolved_content_brief

LONG_FORM_OUTPUT_DIR = config.OUTPUT_VIDEOS_LONG_DIR
LONG_FORM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
TARGET_CANVAS_SIZE = (720, 1280)

SAFE_ZONE_TOP_FRAC = 0.12
SAFE_ZONE_BOTTOM_FRAC = 0.20
SAFE_ZONE_RIGHT_FRAC = 0.15
SAFE_ZONE_MAX_TEXT_WIDTH_FRAC = 1.0 - (2 * SAFE_ZONE_RIGHT_FRAC)

OPENING_HOOK_DURATION = 2.5
OPENING_NARRATION_DELAY_SECONDS = 0.2
BRIDGE_LINE_DURATION = 2.0
FINAL_BRAND_DURATION = 4.0
MIN_TOTAL_DURATION = 20.0
MAX_TOTAL_DURATION = 35.0
PREFERRED_MAX_TOTAL_DURATION = 45.0
MIN_CARD_DURATION = 2.8
MAX_CARD_DURATION = 7.5
CROSSFADE_SECONDS = config.LONG_FORM_CROSSFADE_SECONDS
TEXT_BACKDROP_FILL = (0, 0, 0, 110)
TEXT_BACKDROP_PADDING = 26
TEXT_BACKDROP_RADIUS = 26
WHITE = (255, 255, 255, 255)
GOLD = (255, 226, 164, 255)
AUDIO_SAMPLE_RATE = 48000
AUDIO_BITRATE = "192k"
NARRATION_SYNC_DELAY_SECONDS = 0.65
CAPTION_LEAD_SECONDS = 0.35
CAPTION_TRANSITION_LEAD_SECONDS = 0.30
CAPTION_FADE_IN_SECONDS = 0.18
CAPTION_FADE_OUT_SECONDS = 0.18
LEADING_SILENCE_THRESHOLD_RATIO = 0.015
LEADING_SILENCE_FLOOR_SECONDS = 0.08
LEADING_SILENCE_PRESERVE_SECONDS = 0.03
PAUSE_DETECTION_THRESHOLD_RATIO = 0.012
PAUSE_DETECTION_MIN_SECONDS = 0.20
PAUSE_DETECTION_SEARCH_WINDOW_SECONDS = 1.5


@dataclass(frozen=True)
class VideoAssetSpec:
    path: Path
    start_ratio: float = 0.0
    reverse: bool = False


@dataclass(frozen=True)
class ClipPlan:
    path: Path
    clip_start: float
    clip_end: float
    source_start: float
    source_end: float
    reverse: bool
    crossfade_in: float
    crossfade_out: float


@dataclass(frozen=True)
class TextCard:
    text: str
    start: float
    end: float
    kind: str


_CAPTION_CONJUNCTIONS = {"and", "but", "or", "because", "so", "yet"}
_SCRIPTURE_BOOK_WORDS = {
    "acts",
    "chronicles",
    "corinthians",
    "daniel",
    "deuteronomy",
    "ecclesiastes",
    "ephesians",
    "exodus",
    "ezekiel",
    "galatians",
    "genesis",
    "hebrews",
    "isaiah",
    "jeremiah",
    "job",
    "john",
    "joshua",
    "judges",
    "kings",
    "luke",
    "mark",
    "matthew",
    "peter",
    "philippians",
    "proverbs",
    "psalm",
    "psalms",
    "revelation",
    "romans",
    "samuel",
    "solomon",
    "songs",
    "thessalonians",
    "timothy",
}
_SCRIPTURE_REFERENCE_PATTERN = re.compile(r"^\d+:\d+(?:[-–—]\d+)?(?:,\d+)?$")


def _clean_caption_token(token: str) -> str:
    return token.strip(" \t\r\n\"'“”‘’()[]{}.,;:!?").lower()


def _caption_word_count(tokens: Sequence[str]) -> int:
    return sum(1 for token in tokens if any(character.isalnum() for character in token))


def _scripture_protected_boundaries(tokens: Sequence[str]) -> set[int]:
    protected: set[int] = set()
    for index, token in enumerate(tokens):
        reference = token.strip("\"'“”‘’()[]{}.,;!?")
        if not _SCRIPTURE_REFERENCE_PATTERN.match(reference) or index == 0:
            continue
        previous = _clean_caption_token(tokens[index - 1])
        if previous not in _SCRIPTURE_BOOK_WORDS:
            continue
        protected.add(index)
        if index >= 2 and _clean_caption_token(tokens[index - 2]) in {"1", "2", "3"}:
            protected.add(index - 1)
    return protected


def _phrase_boundary_score(
    phrase_tokens: Sequence[str],
    next_token: Optional[str],
    *,
    preferred_minimum_words: int,
    preferred_maximum_words: int,
    minimum_words: int,
    maximum_words: int,
    soft_maximum_characters: int,
) -> float:
    word_count = _caption_word_count(phrase_tokens)
    if preferred_minimum_words <= word_count <= preferred_maximum_words:
        score = 0.0
    elif minimum_words <= word_count <= maximum_words:
        score = 1.5
    else:
        score = 12.0

    phrase = " ".join(phrase_tokens)
    punctuation_text = phrase.rstrip("\"'”’)]}")
    if punctuation_text.endswith((".", "!", "?")):
        score -= 5.0
    elif punctuation_text.endswith((";", ":", "—", "–")):
        score -= 3.0
    elif punctuation_text.endswith(","):
        score -= 2.5

    if _clean_caption_token(phrase_tokens[-1]) in _CAPTION_CONJUNCTIONS:
        score += 8.0
    if next_token and _clean_caption_token(next_token) in _CAPTION_CONJUNCTIONS:
        score -= 1.0
    if len(phrase) > soft_maximum_characters:
        score += (len(phrase) - soft_maximum_characters) * 0.25
    return score


def group_caption_phrases(text: str, profile: Dict[str, Any]) -> List[str]:
    """Split caption text deterministically while preserving every token."""
    tokens = [token for token in str(text).split() if token]
    if not tokens:
        return []

    minimum_words = max(1, int(profile.get("minimum_words", 3)))
    preferred_minimum_words = max(
        minimum_words, int(profile.get("preferred_minimum_words", 4))
    )
    preferred_maximum_words = max(
        preferred_minimum_words, int(profile.get("preferred_maximum_words", 5))
    )
    maximum_words = max(
        preferred_maximum_words, int(profile.get("maximum_words", 6))
    )
    soft_maximum_characters = max(
        1, int(profile.get("soft_maximum_characters", 44))
    )
    total_words = _caption_word_count(tokens)
    if total_words <= 2:
        return [" ".join(tokens)]

    protected_boundaries = _scripture_protected_boundaries(tokens)

    @lru_cache(maxsize=None)
    def best_from(start: int) -> Tuple[float, Tuple[str, ...]]:
        if start >= len(tokens):
            return 0.0, ()

        best_score = float("inf")
        best_groups: Tuple[str, ...] = ()
        for end in range(start + 1, len(tokens) + 1):
            phrase_tokens = tokens[start:end]
            word_count = _caption_word_count(phrase_tokens)
            if word_count > maximum_words:
                break
            if end < len(tokens) and end in protected_boundaries:
                continue
            if word_count == 0:
                continue

            remaining_words = _caption_word_count(tokens[end:])
            boundary_score = _phrase_boundary_score(
                phrase_tokens,
                tokens[end] if end < len(tokens) else None,
                preferred_minimum_words=preferred_minimum_words,
                preferred_maximum_words=preferred_maximum_words,
                minimum_words=minimum_words,
                maximum_words=maximum_words,
                soft_maximum_characters=soft_maximum_characters,
            )
            if 0 < remaining_words < minimum_words:
                boundary_score += 15.0

            future_score, future_groups = best_from(end)
            score = boundary_score + future_score
            if score < best_score:
                best_score = score
                best_groups = (" ".join(phrase_tokens),) + future_groups
        return best_score, best_groups

    _score, groups = best_from(0)
    return list(groups) if groups else [" ".join(tokens)]


def _phrase_timing_weight(phrase: str) -> float:
    weight = float(max(1, _caption_word_count(phrase.split())))
    punctuation_text = phrase.rstrip("\"'”’)]}")
    if punctuation_text.endswith((".", "!", "?")):
        return weight + 0.60
    if punctuation_text.endswith((";", ":", "—", "–")):
        return weight + 0.45
    if punctuation_text.endswith(","):
        return weight + 0.30
    return weight


def _bounded_weighted_durations(
    weights: Sequence[float],
    total_duration: float,
    minimum_duration: float,
    maximum_duration: float,
) -> List[float]:
    if not weights:
        return []
    if total_duration <= 0:
        return [0.0 for _weight in weights]

    count = len(weights)
    lower = minimum_duration if total_duration >= count * minimum_duration else 0.0
    upper = maximum_duration if total_duration <= count * maximum_duration else total_duration
    positive_weights = [max(0.001, float(weight)) for weight in weights]

    low = 0.0
    high = total_duration / min(positive_weights)
    for _iteration in range(80):
        scale = (low + high) / 2.0
        allocated = sum(
            min(upper, max(lower, scale * weight))
            for weight in positive_weights
        )
        if allocated < total_duration:
            low = scale
        else:
            high = scale

    scale = (low + high) / 2.0
    durations = [
        min(upper, max(lower, scale * weight))
        for weight in positive_weights
    ]
    durations[-1] += total_duration - sum(durations)
    return durations


def allocate_phrase_timing(
    parent_card: TextCard,
    phrases: Sequence[str],
    profile: Dict[str, Any],
) -> List[TextCard]:
    """Allocate contiguous phrase cards inside one immutable parent window."""
    normalized_phrases = [str(phrase) for phrase in phrases if str(phrase).strip()]
    if not normalized_phrases:
        return []

    total_duration = max(0.0, parent_card.end - parent_card.start)
    durations = _bounded_weighted_durations(
        [_phrase_timing_weight(phrase) for phrase in normalized_phrases],
        total_duration,
        max(0.0, float(profile.get("minimum_dwell_seconds", 0.85))),
        max(0.0, float(profile.get("maximum_dwell_seconds", 3.0))),
    )

    cards: List[TextCard] = []
    phrase_start = parent_card.start
    for index, (phrase, phrase_duration) in enumerate(
        zip(normalized_phrases, durations)
    ):
        phrase_end = (
            parent_card.end
            if index == len(normalized_phrases) - 1
            else phrase_start + phrase_duration
        )
        cards.append(
            TextCard(
                text=phrase,
                start=phrase_start,
                end=phrase_end,
                kind=parent_card.kind,
            )
        )
        phrase_start = phrase_end
    return cards


def apply_rolling_timing_offsets(
    cards: Sequence[TextCard], caption_profile: Dict[str, Any]
) -> List[TextCard]:
    """Shift rolling body cards later while keeping every card non-overlapping."""
    start_delay = max(
        0.0, float(caption_profile.get("start_delay_seconds", 0.0))
    )
    end_extension = max(
        0.0, float(caption_profile.get("end_extension_seconds", 0.0))
    )
    if start_delay == 0.0 and end_extension == 0.0:
        return cards if isinstance(cards, list) else list(cards)

    applicable_kinds = set(caption_profile.get("applicable_kinds", []))
    adjusted: List[TextCard] = []
    for index, card in enumerate(cards):
        if card.kind not in applicable_kinds:
            adjusted.append(card)
            continue

        start = min(card.end, card.start + start_delay)
        end = card.end + end_extension
        if index + 1 < len(cards):
            next_card = cards[index + 1]
            next_start = next_card.start
            if next_card.kind in applicable_kinds:
                next_start += start_delay
            end = min(end, next_start)
        else:
            # The final caption must not intrude into the brand frame.
            end = min(end, card.end)
        adjusted.append(
            TextCard(card.text, start, max(start, end), card.kind)
        )
    return adjusted


def apply_caption_profile(
    cards: Sequence[TextCard], caption_profile: Dict[str, Any]
) -> List[TextCard]:
    """Apply one resolved caption profile in a single planning stage."""
    mode = str(caption_profile.get("mode", "current_default")).strip()
    if mode in {"", "current_default"}:
        return cards if isinstance(cards, list) else list(cards)
    if mode != "rolling_phrase":
        raise RuntimeError(f"Unsupported caption profile mode: {mode}")

    applicable_kinds = set(caption_profile.get("applicable_kinds", []))
    transformed: List[TextCard] = []
    opening_hook_seen = False
    for card in cards:
        if card.kind == "opening_hook":
            if not opening_hook_seen:
                transformed.append(card)
                opening_hook_seen = True
            continue
        if card.kind not in applicable_kinds:
            transformed.append(card)
            continue
        phrases = group_caption_phrases(card.text, caption_profile)
        transformed.extend(allocate_phrase_timing(card, phrases, caption_profile))
    return apply_rolling_timing_offsets(transformed, caption_profile)


@dataclass
class OverlayLayer:
    image: Image.Image
    position: Tuple[int, int]
    start: float
    end: float
    fade_in: float = 0.35
    fade_out: float = 0.35
    label: str = ""

    def __post_init__(self) -> None:
        self.array = np.array(self.image)
        self.base_alpha = self.array[:, :, 3].astype(np.float32)

    def alpha_at(self, t: float) -> float:
        if t < self.start or t > self.end:
            return 0.0
        alpha = 1.0
        if self.fade_in > 0 and t < self.start + self.fade_in:
            alpha = min(alpha, max(0.0, (t - self.start) / self.fade_in))
        if self.fade_out > 0 and t > self.end - self.fade_out:
            alpha = min(alpha, max(0.0, (self.end - t) / self.fade_out))
        return max(0.0, min(1.0, alpha))


def _get_ffmpeg_executable() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _safe_filename(path: Path) -> str:
    return Path(path).name


def _measure_wav_duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
    if frame_rate <= 0:
        return 0.0
    return frame_count / float(frame_rate)


def _read_wav_amplitudes(audio_path: Path) -> Tuple[int, np.ndarray]:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            raw_frames = wav_file.readframes(frame_count)
    except (wave.Error, EOFError, FileNotFoundError, OSError):
        return 0, np.array([], dtype=np.int32)

    if frame_rate <= 0 or frame_count <= 0 or not raw_frames:
        return frame_rate, np.array([], dtype=np.int32)

    if sample_width == 1:
        samples = np.frombuffer(raw_frames, dtype=np.uint8).astype(np.int16) - 128
    elif sample_width == 2:
        samples = np.frombuffer(raw_frames, dtype=np.int16)
    elif sample_width == 4:
        samples = np.frombuffer(raw_frames, dtype=np.int32)
    else:
        return frame_rate, np.array([], dtype=np.int32)

    if channels > 1:
        samples = samples.reshape(-1, channels)
        amplitudes = np.max(np.abs(samples), axis=1)
    else:
        amplitudes = np.abs(samples)
    return frame_rate, amplitudes.astype(np.int32)


def _detect_wav_leading_silence(audio_path: Path) -> float:
    frame_rate, amplitudes = _read_wav_amplitudes(audio_path)
    if frame_rate <= 0 or amplitudes.size == 0:
        return 0.0

    max_amplitude = max(127, int(np.max(amplitudes)))
    threshold = max(64, int(max_amplitude * LEADING_SILENCE_THRESHOLD_RATIO))
    non_silent = np.flatnonzero(amplitudes > threshold)
    if len(non_silent) == 0:
        return amplitudes.size / float(frame_rate)
    return float(non_silent[0]) / float(frame_rate)


def _resolve_narration_start_time(
    copy: Dict[str, Any],
    narration_segment_timeline: Optional[Sequence[Dict[str, Any]]],
) -> float:
    if narration_segment_timeline:
        starts = [
            float(item.get("start", 0.0))
            for item in narration_segment_timeline
            if str(item.get("text", "")).strip()
        ]
        if starts:
            return max(0.0, starts[0])
    return OPENING_HOOK_DURATION if str(copy.get("opening_hook", "")).strip() else 0.0


def _extract_narration_units(
    copy: Dict[str, Any],
    narration_segment_timeline: Optional[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    if narration_segment_timeline:
        return [
            {
                "text": str(item.get("text", "")).strip(),
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "kind": str(item.get("kind", "script_segment")),
            }
            for item in narration_segment_timeline
            if str(item.get("text", "")).strip()
        ]

    units: List[Dict[str, Any]] = []
    bridge_line = str(copy.get("bridge_line", "")).strip()
    if bridge_line:
        units.append({"text": bridge_line, "start": 0.0, "end": 0.0, "kind": "bridge_line"})
    for segment in _normalize_script_segments(copy):
        units.append({"text": segment, "start": 0.0, "end": 0.0, "kind": "script_segment"})
    closing_line = str(copy.get("closing_line", "")).strip()
    if closing_line:
        units.append({"text": closing_line, "start": 0.0, "end": 0.0, "kind": "closing_line"})
    return units


def _estimated_relative_starts(narration_units: Sequence[Dict[str, Any]]) -> List[float]:
    if not narration_units:
        return []
    first_start = float(narration_units[0].get("start", 0.0))
    return [max(0.0, float(unit.get("start", 0.0)) - first_start) for unit in narration_units]


def _detect_pause_regions(
    audio_path: Path,
    *,
    trim_seconds: float = 0.0,
) -> List[Tuple[float, float]]:
    frame_rate, amplitudes = _read_wav_amplitudes(audio_path)
    if frame_rate <= 0 or amplitudes.size == 0:
        return []

    trim_frames = min(amplitudes.size, max(0, int(round(trim_seconds * frame_rate))))
    trimmed = amplitudes[trim_frames:]
    if trimmed.size == 0:
        return []

    max_amplitude = max(127, int(np.max(trimmed)))
    noise_floor = int(np.percentile(trimmed, 20)) if trimmed.size else 0
    threshold = max(64, int(max_amplitude * PAUSE_DETECTION_THRESHOLD_RATIO), noise_floor * 3)
    silence_mask = trimmed <= threshold
    min_pause_frames = max(1, int(round(PAUSE_DETECTION_MIN_SECONDS * frame_rate)))
    regions: List[Tuple[float, float]] = []
    run_start: Optional[int] = None

    for index, is_silent in enumerate(silence_mask):
        if is_silent and run_start is None:
            run_start = index
        elif not is_silent and run_start is not None:
            if index - run_start >= min_pause_frames:
                regions.append((run_start / frame_rate, index / frame_rate))
            run_start = None
    if run_start is not None and silence_mask.size - run_start >= min_pause_frames:
        regions.append((run_start / frame_rate, silence_mask.size / frame_rate))
    return regions


def _match_pause_boundaries(
    pause_regions: Sequence[Tuple[float, float]],
    estimated_next_starts: Sequence[float],
) -> List[float]:
    detected: List[float] = []
    for estimated in estimated_next_starts:
        candidates = [
            region for region in pause_regions
            if abs(region[1] - estimated) <= PAUSE_DETECTION_SEARCH_WINDOW_SECONDS
        ]
        if not candidates:
            return []
        best = min(candidates, key=lambda region: abs(region[1] - estimated))
        detected.append(best[1])
    return detected


def _select_caption_transition_boundary(
    *,
    transition_index: int,
    hook_window: float,
    estimated_speech_boundary: float,
    detected_pause_boundary: Optional[float],
) -> Tuple[float, str]:
    safe_visual_boundary = max(hook_window, estimated_speech_boundary - CAPTION_TRANSITION_LEAD_SECONDS)
    selected_boundary = safe_visual_boundary
    reason = "proportional_fallback"

    if detected_pause_boundary is not None:
        if detected_pause_boundary > safe_visual_boundary:
            selected_boundary = safe_visual_boundary
            reason = "pause_boundary_too_late"
        else:
            selected_boundary = max(hook_window, detected_pause_boundary)
            reason = "audio_pause_detection"

    print(f"[long_form_renderer] Caption transition {transition_index}:")
    print(f"[long_form_renderer] estimated speech boundary: {estimated_speech_boundary:.2f}s")
    print(f"[long_form_renderer] safe visual boundary: {safe_visual_boundary:.2f}s")
    print(
        "[long_form_renderer] detected pause boundary: {0}".format(
            "none" if detected_pause_boundary is None else f"{detected_pause_boundary:.2f}s"
        )
    )
    print(f"[long_form_renderer] selected boundary: {selected_boundary:.2f}s")
    print(f"[long_form_renderer] reason: {reason}")
    return selected_boundary, reason


def _build_audio_timed_script_cards(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    duration_seconds: float,
    *,
    narration_units: Sequence[Dict[str, Any]],
    narration_audio_path: Path,
    trim_seconds: float,
    actual_speech_start_time: float,
    audio_offset_seconds: float,
    remaining_lead_seconds: float,
    brand_start: float,
) -> Tuple[List[TextCard], str, List[float]]:
    cards: List[TextCard] = []
    opening_hook = str(copy.get("opening_hook", "")).strip()
    hook_window = OPENING_HOOK_DURATION if opening_hook else 0.0
    if opening_hook:
        cards.append(TextCard(opening_hook, 0.0, hook_window, "opening_hook"))

    if not narration_units:
        return cards, "proportional_fallback", []

    relative_starts = _estimated_relative_starts(narration_units)
    estimated_next_audio_starts = [
        remaining_lead_seconds + relative_start
        for relative_start in relative_starts[1:]
    ]
    pause_regions = _detect_pause_regions(narration_audio_path, trim_seconds=trim_seconds)
    detected_next_audio_starts = _match_pause_boundaries(pause_regions, estimated_next_audio_starts)
    boundary_source = "audio_pause_detection" if len(detected_next_audio_starts) == len(estimated_next_audio_starts) else "proportional_fallback"
    estimated_speech_starts = [actual_speech_start_time + relative_start for relative_start in relative_starts[1:]]
    detected_speech_starts = (
        [audio_offset_seconds + region_end for region_end in detected_next_audio_starts]
        if boundary_source == "audio_pause_detection"
        else []
    )

    first_caption_start = max(hook_window, actual_speech_start_time - CAPTION_LEAD_SECONDS)
    caption_boundaries = [first_caption_start]
    selected_speech_starts: List[float] = []
    reasons: List[str] = []

    for index, estimated_speech_start in enumerate(estimated_speech_starts, start=1):
        detected_speech_start = detected_speech_starts[index - 1] if index - 1 < len(detected_speech_starts) else None
        transition_time, reason = _select_caption_transition_boundary(
            transition_index=index,
            hook_window=hook_window,
            estimated_speech_boundary=estimated_speech_start,
            detected_pause_boundary=detected_speech_start,
        )
        caption_boundaries.append(transition_time)
        selected_speech_starts.append(transition_time + CAPTION_TRANSITION_LEAD_SECONDS)
        reasons.append(reason)

    if boundary_source == "audio_pause_detection" and any(reason != "audio_pause_detection" for reason in reasons):
        boundary_source = "clamped_audio_pause_detection"

    for index, unit in enumerate(narration_units):
        start = caption_boundaries[index]
        if index + 1 < len(caption_boundaries):
            end = caption_boundaries[index + 1]
        else:
            end = brand_start
        cards.append(TextCard(unit["text"], start, max(start, end), unit["kind"]))

    return cards, boundary_source, detected_speech_starts if detected_speech_starts else estimated_speech_starts


def _verify_exported_mp4(video_path: Path) -> Dict[str, Any]:
    info = ffmpeg_parse_infos(str(video_path), check_duration=True)
    audio_duration = 0.0
    audio_streams = [
        stream
        for input_info in info.get("inputs", [])
        for stream in input_info.get("streams", [])
        if stream.get("stream_type") == "audio"
    ]
    if audio_streams:
        stream_duration = audio_streams[0].get("duration")
        if isinstance(stream_duration, (int, float)):
            audio_duration = float(stream_duration)
        elif info.get("audio_found"):
            audio_duration = float(info.get("duration") or 0.0)
    return {
        "video_found": bool(info.get("video_found")),
        "audio_found": bool(info.get("audio_found")),
        "audio_duration": audio_duration,
        "duration": float(info.get("duration") or 0.0),
    }


def _mux_narration_audio(
    *,
    silent_video_path: Path,
    narration_audio_path: Path,
    output_path: Path,
    video_duration: float,
    audio_trim_seconds: float,
    audio_offset_seconds: float,
) -> None:
    ffmpeg_exe = _get_ffmpeg_executable()
    command = [ffmpeg_exe, "-y", "-i", str(silent_video_path)]
    if audio_trim_seconds > 0:
        command.extend(["-ss", f"{audio_trim_seconds:.3f}"])
    command.extend(
        [
            "-i",
            str(narration_audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-af",
            f"adelay={int(round(audio_offset_seconds * 1000))}:all=1,apad",
            "-t",
            f"{video_duration:.3f}",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    subprocess.run(command, check=True, capture_output=True, text=True)


def _clamp_duration(presentation_config: Dict[str, Any], copy: Dict[str, Any]) -> float:
    duration = presentation_config.get("duration_seconds")
    if not isinstance(duration, int):
        duration = copy.get("estimated_spoken_seconds")
    if not isinstance(duration, int):
        duration = 30
    return float(max(MIN_TOTAL_DURATION, min(MAX_TOTAL_DURATION, duration)))


def resolve_long_form_duration(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    narration_duration: Optional[float] = None,
) -> Tuple[float, float, float]:
    """Return total duration, hook window, and brand start time."""
    hook_window = OPENING_HOOK_DURATION if str(copy.get("opening_hook", "")).strip() else 0.0
    if narration_duration is None:
        total_duration = _clamp_duration(presentation_config, copy)
        brand_start = max(0.0, total_duration - FINAL_BRAND_DURATION)
        return total_duration, hook_window, brand_start

    total_duration = hook_window + narration_duration + FINAL_BRAND_DURATION
    if total_duration < MIN_TOTAL_DURATION:
        total_duration = MIN_TOTAL_DURATION
    elif total_duration > PREFERRED_MAX_TOTAL_DURATION:
        print(
            "[long_form_renderer] WARNING: narration exceeds preferred maximum; "
            "preserving full audio with total duration {0:.2f}s.".format(total_duration)
        )
    brand_start = hook_window + narration_duration
    return total_duration, hook_window, brand_start


def _content_label(presentation_config: Dict[str, Any]) -> str:
    content_type = str(presentation_config.get("content_type", "")).strip()
    slot = str(presentation_config.get("slot", "")).strip().lower()
    if content_type in {"prayer_read", "night_prayer_or_rest"}:
        return "PRAYER BEFORE BED" if slot == "evening" else "MORNING PRAYER"
    if content_type in {"devotional_read", "gratitude_reflection"}:
        return "EVENING REFLECTION" if slot == "evening" else "TODAY'S WORD"
    if content_type == "hope_encouragement":
        return "TODAY'S ENCOURAGEMENT"
    return "MORNING PRAYER"


def list_long_form_video_candidates(
    long_video_dir: Optional[Path] = None,
    fallback_dir: Optional[Path] = None,
) -> List[Path]:
    """Return available long-form scenic video candidates."""
    primary_dir = Path(long_video_dir or config.LONG_FORM_VIDEO_DIR)
    fallback = Path(fallback_dir or config.MOTION_BACKGROUNDS_DIR)
    directories = [primary_dir]
    if primary_dir != fallback:
        directories.append(fallback)

    for directory in directories:
        if not directory.exists():
            continue
        candidates = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        )
        if candidates:
            return candidates
    return []


def select_long_form_video_assets(
    *,
    target_count: int = 5,
    long_video_dir: Optional[Path] = None,
    fallback_dir: Optional[Path] = None,
) -> List[VideoAssetSpec]:
    """Select 4-6 scenic clips, reusing only when the library is small."""
    candidates = list_long_form_video_candidates(long_video_dir, fallback_dir)
    if not candidates:
        raise FileNotFoundError("No eligible scenic video assets found for long-form rendering.")

    bounded_target = max(4, min(6, target_count))
    unique_count = min(len(candidates), bounded_target)
    chosen_paths = random.sample(candidates, unique_count)
    selected = [VideoAssetSpec(path=path) for path in chosen_paths]

    while len(selected) < 4:
        reused = chosen_paths[len(selected) % len(chosen_paths)]
        start_ratio = (len(selected) % 4) * 0.18
        reverse = len(selected) % 2 == 1
        selected.append(VideoAssetSpec(path=reused, start_ratio=start_ratio, reverse=reverse))

    print("[long_form_renderer] Selected scenic clips:")
    for spec in selected:
        print(
            "[long_form_renderer] - {0} start_ratio={1:.2f} reverse={2}".format(
                spec.path.name, spec.start_ratio, spec.reverse
            )
        )
    return selected


def _normalize_video_assets(video_assets: Sequence[Any]) -> List[VideoAssetSpec]:
    normalized: List[VideoAssetSpec] = []
    for asset in video_assets:
        if isinstance(asset, VideoAssetSpec):
            normalized.append(asset)
        else:
            normalized.append(VideoAssetSpec(path=Path(asset)))
    return normalized


def _split_segment_preserving_sentences(text: str) -> List[str]:
    stripped = (text or "").strip()
    if not stripped:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", stripped)
    pieces: List[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        word_count = len(candidate.split())
        if current and word_count > 35:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    if not pieces:
        return [stripped]
    return pieces


def _normalize_script_segments(copy: Dict[str, Any]) -> List[str]:
    raw_segments = copy.get("script_segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        fallback = str(copy.get("spiritual_action", "")).strip()
        return [fallback] if fallback else []

    normalized: List[str] = []
    for segment in raw_segments:
        text = str(segment).strip()
        if not text:
            continue
        normalized.extend(_split_segment_preserving_sentences(text))
    return [segment for segment in normalized if segment]


def build_script_cards(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    duration_seconds: float,
    narration_segment_timeline: Optional[Sequence[Dict[str, Any]]] = None,
    narration_duration: Optional[float] = None,
) -> List[TextCard]:
    """Build the ordered text-card timeline for the long-form script."""
    if narration_segment_timeline is not None:
        return [
            TextCard(
                text=str(item.get("text", "")).strip(),
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                kind=str(item.get("kind", "script_segment")),
            )
            for item in narration_segment_timeline
            if str(item.get("text", "")).strip()
        ]

    cards: List[TextCard] = []
    opening_hook = str(copy.get("opening_hook", "")).strip()
    bridge_line = str(copy.get("bridge_line", "")).strip()
    closing_line = str(copy.get("closing_line", "")).strip()
    script_segments = _normalize_script_segments(copy)
    hook_window = OPENING_HOOK_DURATION if opening_hook else 0.0
    brand_start = max(hook_window, duration_seconds - FINAL_BRAND_DURATION)

    current_time = hook_window
    if opening_hook:
        cards.append(TextCard(opening_hook, 0.0, OPENING_HOOK_DURATION, "opening_hook"))
        current_time = hook_window
        if bridge_line:
            cards.append(
                TextCard(bridge_line, current_time, current_time + BRIDGE_LINE_DURATION, "bridge_line")
            )
            current_time += BRIDGE_LINE_DURATION

    closing_duration = 1.5 if closing_line else 0.0
    script_end = max(current_time + MIN_CARD_DURATION, brand_start - closing_duration)
    available_for_segments = max(0.0, script_end - current_time)

    if not script_segments:
        script_segments = [str(copy.get("spiritual_action", "")).strip() or "Come pray with me."]

    word_counts = [max(1, len(segment.split())) for segment in script_segments]
    total_words = sum(word_counts)
    remaining_time = available_for_segments
    segment_start = current_time

    for index, segment in enumerate(script_segments):
        words = word_counts[index]
        slots_left = len(script_segments) - index
        if slots_left == 1:
            card_duration = remaining_time
        else:
            proportional = available_for_segments * (words / total_words)
            min_required_for_rest = MIN_CARD_DURATION * (slots_left - 1)
            card_duration = max(MIN_CARD_DURATION, min(MAX_CARD_DURATION, proportional))
            card_duration = min(card_duration, max(MIN_CARD_DURATION, remaining_time - min_required_for_rest))
        segment_end = segment_start + max(MIN_CARD_DURATION, card_duration)
        cards.append(TextCard(segment, segment_start, segment_end, "script_segment"))
        remaining_time = max(0.0, brand_start - closing_duration - segment_end)
        segment_start = segment_end

    if closing_line:
        cards.append(TextCard(closing_line, segment_start, min(brand_start, segment_start + closing_duration), "closing_line"))

    return cards


def build_clip_plan(
    video_assets: Sequence[VideoAssetSpec],
    clip_durations: Dict[Path, float],
    duration_seconds: float,
) -> List[ClipPlan]:
    """Build the scenic clip timeline with soft crossfades."""
    overlap = CROSSFADE_SECONDS if len(video_assets) > 1 else 0.0
    segment_duration = (duration_seconds + overlap * (len(video_assets) - 1)) / len(video_assets)
    plans: List[ClipPlan] = []
    clip_start = 0.0

    for index, spec in enumerate(video_assets):
        source_duration = max(0.1, clip_durations.get(spec.path, segment_duration))
        max_start = max(0.0, source_duration - segment_duration)
        source_start = min(max_start, max(0.0, spec.start_ratio) * max_start)
        source_end = min(source_duration, source_start + segment_duration)
        clip_end = min(duration_seconds, clip_start + segment_duration)
        plans.append(
            ClipPlan(
                path=spec.path,
                clip_start=clip_start,
                clip_end=clip_end,
                source_start=source_start,
                source_end=max(source_start + 0.1, source_end),
                reverse=spec.reverse,
                crossfade_in=overlap if index > 0 else 0.0,
                crossfade_out=overlap if index < len(video_assets) - 1 else 0.0,
            )
        )
        clip_start = clip_end - overlap
    if plans:
        last = plans[-1]
        plans[-1] = ClipPlan(
            path=last.path,
            clip_start=last.clip_start,
            clip_end=duration_seconds,
            source_start=last.source_start,
            source_end=last.source_end,
            reverse=last.reverse,
            crossfade_in=last.crossfade_in,
            crossfade_out=0.0,
        )
    return plans


def _get_text_box(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int, int],
    stroke_width: int,
    stroke_fill: Tuple[int, int, int, int],
    max_width: int,
) -> Image.Image:
    wrapped = motion_renderer._wrap_text(text, font, max_width)
    return motion_renderer._make_text_layer(
        wrapped,
        font,
        fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
        backdrop_fill=TEXT_BACKDROP_FILL,
        backdrop_padding=TEXT_BACKDROP_PADDING,
        backdrop_radius=TEXT_BACKDROP_RADIUS,
    )[0]


def _fit_card_text(
    text: str,
    canvas_size: Tuple[int, int],
    kind: str,
    caption_profile: Optional[Dict[str, Any]] = None,
) -> Tuple[ImageFont.FreeTypeFont, str]:
    width, _height = canvas_size
    bold_path, _regular_path = motion_renderer._get_fonts()
    max_width = int(width * SAFE_ZONE_MAX_TEXT_WIDTH_FRAC)
    base_size = 64 if kind in {"script_segment", "bridge_line"} else 72
    min_size = 36
    max_lines = 4 if kind == "script_segment" else 2
    if (
        caption_profile
        and caption_profile.get("mode") == "rolling_phrase"
        and kind in set(caption_profile.get("applicable_kinds", []))
    ):
        max_lines = max(1, int(caption_profile.get("maximum_lines", 2)))
    return motion_renderer._fit_text_to_max_lines(
        text,
        bold_path,
        base_size,
        max_width,
        max_lines=max_lines,
        min_font_size=min_size,
    )


def _fit_card_layer(
    text: str,
    canvas_size: Tuple[int, int],
    kind: str,
    caption_profile: Optional[Dict[str, Any]] = None,
) -> Image.Image:
    font, wrapped = _fit_card_text(
        text,
        canvas_size,
        kind,
        caption_profile=caption_profile,
    )
    return motion_renderer._make_text_layer(
        wrapped,
        font,
        GOLD if kind == "closing_line" else WHITE,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 170),
        backdrop_fill=TEXT_BACKDROP_FILL,
        backdrop_padding=TEXT_BACKDROP_PADDING,
        backdrop_radius=TEXT_BACKDROP_RADIUS,
    )[0]


def build_script_layers(
    cards: Sequence[TextCard],
    canvas_size: Tuple[int, int],
    caption_profile: Optional[Dict[str, Any]] = None,
) -> List[OverlayLayer]:
    width, height = canvas_size
    layers: List[OverlayLayer] = []
    center_y = int(height * 0.42)
    max_top = int(height * SAFE_ZONE_TOP_FRAC)
    max_bottom = height - int(height * SAFE_ZONE_BOTTOM_FRAC)

    for card in cards:
        image = _fit_card_layer(
            card.text,
            canvas_size,
            card.kind,
            caption_profile=caption_profile,
        )
        x = int((width - image.width) / 2)
        y = int(center_y - image.height / 2)
        y = max(max_top, min(y, max_bottom - image.height))
        rolling_card = (
            caption_profile
            and caption_profile.get("mode") == "rolling_phrase"
            and card.kind in set(caption_profile.get("applicable_kinds", []))
        )
        fade_in = (
            float(caption_profile.get("fade_in_seconds", CAPTION_FADE_IN_SECONDS))
            if rolling_card
            else CAPTION_FADE_IN_SECONDS
        )
        fade_out = (
            float(caption_profile.get("fade_out_seconds", CAPTION_FADE_OUT_SECONDS))
            if rolling_card
            else CAPTION_FADE_OUT_SECONDS
        )
        layers.append(
            OverlayLayer(
                image=image,
                position=(x, y),
                start=card.start,
                end=card.end,
                fade_in=0.0 if card.kind == "opening_hook" else fade_in,
                fade_out=0.3 if card.kind == "opening_hook" else fade_out,
                label=card.kind,
            )
        )
    return layers


def build_title_layers(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    canvas_size: Tuple[int, int],
) -> List[OverlayLayer]:
    title = _content_label(presentation_config)
    if not title:
        return []
    width, height = canvas_size
    title_img = _fit_card_layer(title, canvas_size, "title")
    x = int((width - title_img.width) / 2)
    y = max(int(height * SAFE_ZONE_TOP_FRAC), int(height * 0.22) - int(title_img.height / 2))
    return [
        OverlayLayer(
            image=title_img,
            position=(x, y),
            start=0.0,
            end=OPENING_HOOK_DURATION if str(copy.get("opening_hook", "")).strip() else 2.0,
            fade_in=0.0,
            fade_out=0.3,
            label="title",
        )
    ]


def build_final_brand_layers(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    canvas_size: Tuple[int, int],
    duration_seconds: float,
    *,
    brand_start: Optional[float] = None,
) -> List[OverlayLayer]:
    width, height = canvas_size
    start = duration_seconds - FINAL_BRAND_DURATION if brand_start is None else brand_start
    max_text_width = int(width * SAFE_ZONE_MAX_TEXT_WIDTH_FRAC)
    bold_path, _regular_path = motion_renderer._get_fonts()
    wordmark_font = ImageFont.truetype(bold_path, 38)
    cta_font = ImageFont.truetype(bold_path, 34)
    small_font = ImageFont.truetype(bold_path, 28)

    layers: List[OverlayLayer] = []
    top_safe = int(height * SAFE_ZONE_TOP_FRAC)
    bottom_safe = height - int(height * SAFE_ZONE_BOTTOM_FRAC)
    current_y = max(top_safe, int(height * 0.50))

    if presentation_config.get("show_logo", False):
        logo_asset = motion_renderer._load_brand_asset(config.LOGO_PATH)
        if logo_asset is not None:
            logo_canvas = Image.new("RGBA", (220, 72), (0, 0, 0, 0))
            motion_renderer._paste_scaled(
                logo_canvas,
                logo_asset,
                center_x=logo_canvas.width // 2,
                top_y=0,
                target_height=60,
            )
            x = int((width - logo_canvas.width) / 2)
            y = current_y
            layers.append(OverlayLayer(logo_canvas, (x, y), start, duration_seconds, label="logo"))
            current_y = y + logo_canvas.height + 10

    wordmark_img = _get_text_box(
        "PRAYONIT",
        font=wordmark_font,
        fill=GOLD,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 160),
        max_width=max_text_width,
    )
    wordmark_x = int((width - wordmark_img.width) / 2)
    layers.append(OverlayLayer(wordmark_img, (wordmark_x, current_y), start, duration_seconds, label="wordmark"))
    current_y += wordmark_img.height + 8

    if presentation_config.get("show_cta", False):
        cta_text = str(presentation_config.get("cta_text", "")).strip() or "Come pray with me."
        cta_img = _get_text_box(
            cta_text,
            font=cta_font,
            fill=WHITE,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 150),
            max_width=max_text_width,
        )
        cta_x = int((width - cta_img.width) / 2)
        layers.append(OverlayLayer(cta_img, (cta_x, current_y), start, duration_seconds, label="cta"))
        current_y += cta_img.height + 8

    if presentation_config.get("show_link_in_bio", False):
        link_img = _get_text_box(
            "Link in bio.",
            font=small_font,
            fill=WHITE,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 120),
            max_width=max_text_width,
        )
        link_x = int((width - link_img.width) / 2)
        layers.append(OverlayLayer(link_img, (link_x, current_y), start, duration_seconds, label="link_in_bio"))
        current_y += link_img.height + 8

    if presentation_config.get("engagement_prompt_enabled", False):
        engagement_line = str(copy.get("engagement_line", "")).strip()
        if engagement_line and len(engagement_line.split()) <= 10:
            engagement_img = _get_text_box(
                engagement_line,
                font=small_font,
                fill=GOLD,
                stroke_width=1,
                stroke_fill=(0, 0, 0, 120),
                max_width=max_text_width,
            )
            engagement_x = int((width - engagement_img.width) / 2)
            layers.append(OverlayLayer(engagement_img, (engagement_x, current_y), start, duration_seconds, label="engagement"))
            current_y += engagement_img.height + 8

    if presentation_config.get("show_app_benefit", False):
        benefit_text = str(copy.get("app_benefit", "")).strip()
        if benefit_text:
            benefit_img = _get_text_box(
                benefit_text,
                font=small_font,
                fill=WHITE,
                stroke_width=1,
                stroke_fill=(0, 0, 0, 120),
                max_width=max_text_width,
            )
            benefit_x = int((width - benefit_img.width) / 2)
            layers.append(OverlayLayer(benefit_img, (benefit_x, current_y), start, duration_seconds, label="app_benefit"))
            current_y += benefit_img.height + 8

    if presentation_config.get("show_badges", False):
        badge_y = min(current_y, bottom_safe - 60)
        for badge_path, x_offset in ((config.APP_STORE_BADGE_PATH, -90), (config.GOOGLE_PLAY_BADGE_PATH, 10)):
            badge = motion_renderer._load_brand_asset(badge_path)
            if badge is None:
                continue
            badge_canvas = Image.new("RGBA", (160, 48), (0, 0, 0, 0))
            motion_renderer._paste_scaled(
                badge_canvas,
                badge,
                center_x=badge_canvas.width // 2,
                top_y=0,
                target_height=40,
            )
            layers.append(
                OverlayLayer(
                    badge_canvas,
                    (int(width / 2 + x_offset), badge_y),
                    start,
                    duration_seconds,
                    label="badge",
                )
            )

    return [
        layer
        for layer in layers
        if layer.position[1] + layer.image.height <= bottom_safe + 2
    ]


def _crop_to_vertical(frame: np.ndarray, canvas_size: Tuple[int, int]) -> np.ndarray:
    canvas_width, canvas_height = canvas_size
    src_h, src_w = frame.shape[0], frame.shape[1]
    src_ratio = src_w / src_h
    target_ratio = canvas_width / canvas_height

    if src_ratio > target_ratio:
        new_height = canvas_height
        new_width = int(new_height * src_ratio)
    else:
        new_width = canvas_width
        new_height = int(new_width / src_ratio)

    resized = Image.fromarray(frame).resize((new_width, new_height), Image.Resampling.LANCZOS)
    left = max(0, int((new_width - canvas_width) / 2))
    top = max(0, int((new_height - canvas_height) / 2))
    return np.array(resized.crop((left, top, left + canvas_width, top + canvas_height)))


def _clip_frame_at(plan: ClipPlan, clip: VideoFileClip, t: float) -> np.ndarray:
    plan_duration = max(0.1, plan.clip_end - plan.clip_start)
    source_span = max(0.1, plan.source_end - plan.source_start)
    progress = max(0.0, min(1.0, (t - plan.clip_start) / plan_duration))
    source_t = plan.source_start + (1.0 - progress if plan.reverse else progress) * source_span
    source_t = max(0.0, min(source_t, max(0.0, clip.duration - 0.001)))
    return clip.get_frame(source_t)


def _blend_frames(base: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
    if alpha <= 0.0:
        return base
    if alpha >= 1.0:
        return overlay
    return (base.astype(np.float32) * (1.0 - alpha) + overlay.astype(np.float32) * alpha).astype(np.uint8)


def render_long_form_video(
    copy: Dict[str, Any],
    presentation_config: Dict[str, Any],
    video_assets: Optional[Sequence[VideoAssetSpec]] = None,
    output_path: Optional[Path] = None,
    narration_audio_path: Optional[Path] = None,
    narration_duration: Optional[float] = None,
    narration_segment_timeline: Optional[Sequence[Dict[str, Any]]] = None,
    caption_profile_id: str = "current_default",
    creative_policy_version: Optional[str] = None,
) -> Path:
    """Render one finished long-form 9:16 MP4."""
    caption_profile = resolved_content_brief.get_caption_profile_definition(
        caption_profile_id,
        creative_policy_version=creative_policy_version,
    )
    duration_seconds, hook_window, brand_start = resolve_long_form_duration(
        copy,
        presentation_config,
        narration_duration=narration_duration,
    )
    has_audio = narration_audio_path is not None and Path(narration_audio_path).exists()
    audio_timing: Dict[str, Any] = {}
    narration_units = _extract_narration_units(copy, narration_segment_timeline)
    if has_audio:
        narration_audio_path = Path(narration_audio_path)
        wav_duration = _measure_wav_duration(narration_audio_path)
        if wav_duration <= 0:
            raise RuntimeError(f"Narration WAV has no usable audio duration: {narration_audio_path}")

        intended_narration_start_time = _resolve_narration_start_time(copy, narration_segment_timeline)
        detected_leading_silence = _detect_wav_leading_silence(narration_audio_path)
        trim_seconds = 0.0
        if detected_leading_silence > LEADING_SILENCE_FLOOR_SECONDS:
            trim_seconds = max(0.0, detected_leading_silence - LEADING_SILENCE_PRESERVE_SECONDS)
        remaining_lead = max(0.0, detected_leading_silence - trim_seconds)
        actual_speech_start_time = intended_narration_start_time + (
            OPENING_NARRATION_DELAY_SECONDS if str(copy.get("opening_hook", "")).strip() else 0.0
        )
        audio_offset_seconds = max(0.0, actual_speech_start_time - remaining_lead)
        effective_audio_duration = max(0.0, wav_duration - trim_seconds)
        brand_start = max(brand_start, audio_offset_seconds + effective_audio_duration)
        duration_seconds = max(duration_seconds, brand_start + FINAL_BRAND_DURATION, MIN_TOTAL_DURATION)
        audio_timing = {
            "wav_duration": wav_duration,
            "intended_narration_start_time": intended_narration_start_time,
            "detected_leading_silence": detected_leading_silence,
            "trim_seconds": trim_seconds,
            "remaining_lead": remaining_lead,
            "actual_speech_start_time": actual_speech_start_time,
            "audio_offset_seconds": audio_offset_seconds,
        }

    selected_assets = (
        _normalize_video_assets(video_assets)
        if video_assets is not None
        else select_long_form_video_assets()
    )
    output_dir = LONG_FORM_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(output_path) if output_path is not None else output_dir / "video_test.mp4"
    silent_out_path = out_path.with_name(f"{out_path.stem}.silent{out_path.suffix}")

    unique_paths = {spec.path for spec in selected_assets}
    clips = {path: VideoFileClip(str(path)) for path in unique_paths}
    try:
        clip_durations = {path: clip.duration for path, clip in clips.items()}
        clip_plan = build_clip_plan(selected_assets, clip_durations, duration_seconds)
        if has_audio:
            script_cards, boundary_source, detected_boundaries = _build_audio_timed_script_cards(
                copy,
                presentation_config,
                duration_seconds,
                narration_units=narration_units,
                narration_audio_path=narration_audio_path,
                trim_seconds=audio_timing["trim_seconds"],
                actual_speech_start_time=audio_timing["actual_speech_start_time"],
                audio_offset_seconds=audio_timing["audio_offset_seconds"],
                remaining_lead_seconds=audio_timing["remaining_lead"],
                brand_start=brand_start,
            )
        else:
            script_cards = build_script_cards(
                copy,
                presentation_config,
                duration_seconds,
                narration_segment_timeline=narration_segment_timeline,
                narration_duration=narration_duration,
            )
            boundary_source = "proportional_fallback"
            detected_boundaries = []
        script_cards = apply_caption_profile(script_cards, caption_profile)
        script_layers = build_script_layers(
            script_cards,
            TARGET_CANVAS_SIZE,
            caption_profile=caption_profile,
        )
        title_layers = build_title_layers(copy, presentation_config, TARGET_CANVAS_SIZE)
        brand_layers = build_final_brand_layers(
            copy,
            presentation_config,
            TARGET_CANVAS_SIZE,
            duration_seconds,
            brand_start=brand_start,
        )
        all_layers = title_layers + script_layers + brand_layers
        fps = 30

        def make_frame(t: float) -> np.ndarray:
            active_plan = None
            for plan in clip_plan:
                if plan.clip_start <= t <= plan.clip_end:
                    active_plan = plan
                    break
            if active_plan is None:
                active_plan = clip_plan[-1]

            base_frame = _crop_to_vertical(_clip_frame_at(active_plan, clips[active_plan.path], t), TARGET_CANVAS_SIZE)
            active_index = clip_plan.index(active_plan)
            if active_plan.crossfade_out > 0 and t > active_plan.clip_end - active_plan.crossfade_out and active_index < len(clip_plan) - 1:
                next_plan = clip_plan[active_index + 1]
                next_frame = _crop_to_vertical(_clip_frame_at(next_plan, clips[next_plan.path], t), TARGET_CANVAS_SIZE)
                alpha = (t - (active_plan.clip_end - active_plan.crossfade_out)) / active_plan.crossfade_out
                base_frame = _blend_frames(base_frame, next_frame, alpha)

            canvas = Image.fromarray(base_frame).convert("RGBA")
            for layer in all_layers:
                alpha = layer.alpha_at(t)
                if alpha <= 0.0:
                    continue
                if alpha >= 1.0:
                    array = layer.array
                else:
                    array = layer.array.copy()
                    array[:, :, 3] = (layer.base_alpha * alpha).astype(np.uint8)
                canvas.alpha_composite(Image.fromarray(array), dest=layer.position)
            return np.array(canvas.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration_seconds).with_fps(fps)
        if has_audio:
            print(f"Long-form narration source: {_safe_filename(narration_audio_path)}")
            print(f"Narration duration: {audio_timing['wav_duration']:.2f}s")
            print(
                f"[long_form_renderer] Narration sync delay: "
                f"{OPENING_NARRATION_DELAY_SECONDS if str(copy.get('opening_hook', '')).strip() else 0.0:.2f}s"
            )
            print(f"[long_form_renderer] Caption lead: {CAPTION_LEAD_SECONDS:.2f}s")
            print(f"[long_form_renderer] Intended narration start time: {audio_timing['intended_narration_start_time']:.2f}s")
            print(f"[long_form_renderer] Detected WAV leading silence: {audio_timing['detected_leading_silence']:.2f}s")
            print(f"[long_form_renderer] Applied audio offset: {audio_timing['audio_offset_seconds']:.2f}s")
            print(f"[long_form_renderer] Detected narration pause boundaries: {[round(boundary, 2) for boundary in detected_boundaries]}")
            print(f"[long_form_renderer] Caption boundary source: {boundary_source}")
            narrated_cards = [card for card in script_cards if card.kind != "opening_hook"]
            for index, card in enumerate(narrated_cards, start=1):
                print(f"[long_form_renderer] Caption {index}: {card.start:.2f}s-{card.end:.2f}s")
            first_caption_start = audio_timing["actual_speech_start_time"]
            if narrated_cards:
                first_caption_start = narrated_cards[0].start
            print(f"[long_form_renderer] First caption start time: {first_caption_start:.2f}s")

        print(
            "[long_form_renderer] Writing silent visual base {0} ...".format(
                silent_out_path if has_audio else out_path,
            )
        )
        clip.write_videofile(
            str(silent_out_path if has_audio else out_path),
            fps=fps,
            codec="libx264",
            audio=False,
            logger=None,
        )
        clip.close()

        if has_audio:
            _mux_narration_audio(
                silent_video_path=silent_out_path,
                narration_audio_path=narration_audio_path,
                output_path=out_path,
                video_duration=duration_seconds,
                audio_trim_seconds=audio_timing["trim_seconds"],
                audio_offset_seconds=audio_timing["audio_offset_seconds"],
            )
            verification = _verify_exported_mp4(out_path)
            print(f"Final MP4 audio stream detected: {verification['audio_found']}")
            print(f"Final MP4 audio duration: {verification['audio_duration']:.2f}s")
            if not verification["video_found"] or not verification["audio_found"] or verification["audio_duration"] <= 0:
                raise RuntimeError(f"Long-form narration mux verification failed for {out_path}")
            if silent_out_path.exists():
                silent_out_path.unlink()

        print(f"[long_form_renderer] Done: {out_path}")
        return out_path
    finally:
        for clip in clips.values():
            clip.close()
