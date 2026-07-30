"""Dedicated eight-second renderer for Prayonit's direct-marketing lane."""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, VideoFileClip

import config
import direct_marketing


CANVAS_SIZE = (720, 1280)
FPS = 24
NARRATION_END_GUARD_SECONDS = 0.15
NARRATION_LEADING_SILENCE_RESERVE_SECONDS = 0.08
NARRATION_TRAILING_SILENCE_RESERVE_SECONDS = 0.10
SCREEN_TYPES = (
    "mood_selection",
    "scripture_devotional",
    "guided_prayer_or_journal",
)


def _load_catalog(path: Path, collection_key: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Direct-marketing asset catalog is malformed: {path}") from exc
    entries = data.get(collection_key, [])
    if not isinstance(entries, list):
        raise RuntimeError(
            f"Direct-marketing asset catalog must contain a {collection_key} list."
        )
    return [entry for entry in entries if isinstance(entry, dict)]


def resolve_screenshot_sequence(
    *,
    catalog_path: Optional[Path] = None,
    asset_dir: Optional[Path] = None,
) -> List[Path]:
    """Return the three approved screens in controlled display order."""
    catalog = Path(catalog_path or config.DIRECT_MARKETING_SCREENSHOT_CATALOG)
    directory = Path(asset_dir or config.DIRECT_MARKETING_SCREENSHOT_DIR)
    active_entries = [
        entry
        for entry in _load_catalog(catalog, "screenshots")
        if entry.get("active") is True
    ]
    by_type = {
        str(entry.get("screen_type", "")).strip(): entry
        for entry in active_entries
    }
    resolved: List[Path] = []
    for expected_order, screen_type in enumerate(SCREEN_TYPES, start=1):
        entry = by_type.get(screen_type)
        if not entry or int(entry.get("display_order", 0) or 0) != expected_order:
            return []
        path = directory / str(entry.get("filename", "")).strip()
        if not path.is_file():
            return []
        resolved.append(path)
    return resolved


def select_audio_asset(
    *,
    profile_id: str,
    seed: str,
    catalog_path: Optional[Path] = None,
    asset_dir: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Select an active commercially approved local bed deterministically."""
    catalog = Path(catalog_path or config.DIRECT_MARKETING_AUDIO_CATALOG)
    directory = Path(asset_dir or config.DIRECT_MARKETING_AUDIO_DIR)
    eligible = []
    for entry in _load_catalog(catalog, "audio_assets"):
        if entry.get("active") is not True:
            continue
        if entry.get("commercial_use_allowed") is not True:
            continue
        if str(entry.get("audio_profile", "current_default")) != profile_id:
            continue
        path = directory / str(entry.get("filename", "")).strip()
        if path.is_file():
            eligible.append((path, entry))
    if not eligible:
        raise RuntimeError(
            f"No active commercially approved audio asset for profile {profile_id}."
        )

    oldest_marker = min(str(entry.get("last_used") or "") for _, entry in eligible)
    least_recent = [
        item for item in eligible if str(item[1].get("last_used") or "") == oldest_marker
    ]
    return random.Random(f"{seed}:{profile_id}").choice(least_recent)


def _font_paths() -> Tuple[str, str]:
    candidates = (
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
    )
    for bold, regular in candidates:
        if Path(bold).is_file() and Path(regular).is_file():
            return bold, regular
    raise RuntimeError("No supported system font is available.")


def _cover_image(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, int((resized.width - target_w) / 2))
    top = max(0, int((resized.height - target_h) / 2))
    return resized.crop((left, top, left + target_w, top + target_h))


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: int,
) -> str:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines: List[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _draw_card(
    base: Image.Image,
    *,
    text: str,
    final_card: bool,
    screenshot_mode: bool,
) -> None:
    bold_path, _ = _font_paths()
    font_size = 58 if final_card else 52
    font = ImageFont.truetype(bold_path, font_size)
    wrapped = _wrap_text(text, font, max_width=int(base.width * 0.78))
    draw = ImageDraw.Draw(base, "RGBA")
    box = draw.multiline_textbbox(
        (0, 0),
        wrapped,
        font=font,
        spacing=10,
        align="center",
        stroke_width=2,
    )
    text_w = box[2] - box[0]
    text_h = box[3] - box[1]
    center_y = int(base.height * (0.22 if screenshot_mode and not final_card else 0.46))
    x = int((base.width - text_w) / 2)
    y = int(center_y - text_h / 2)
    padding_x = 26
    padding_y = 20
    draw.rounded_rectangle(
        (
            x - padding_x,
            y - padding_y,
            x + text_w + padding_x,
            y + text_h + padding_y,
        ),
        radius=24,
        fill=(8, 16, 23, 184),
    )
    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=10,
        align="center",
        stroke_width=2,
        stroke_fill=(0, 0, 0, 190),
    )


def _draw_screenshot(
    base: Image.Image,
    screenshot: Image.Image,
    *,
    local_progress: float,
) -> None:
    zoom = 1.0 + 0.04 * max(0.0, min(1.0, local_progress))
    target_h = int(base.height * 0.57 * zoom)
    target_w = int(target_h * screenshot.width / screenshot.height)
    max_w = int(base.width * 0.76)
    if target_w > max_w:
        target_w = max_w
        target_h = int(target_w * screenshot.height / screenshot.width)
    rendered = screenshot.resize((target_w, target_h), Image.Resampling.LANCZOS)
    panel = Image.new(
        "RGBA",
        (target_w + 24, target_h + 24),
        (255, 255, 255, 235),
    )
    panel.alpha_composite(rendered.convert("RGBA"), (12, 12))
    x = int((base.width - panel.width) / 2)
    y = int(base.height * 0.34)
    shadow = Image.new("RGBA", panel.size, (0, 0, 0, 80))
    base.alpha_composite(shadow, (x + 10, y + 12))
    base.alpha_composite(panel, (x, y))


def _card_at(
    cards: Sequence[direct_marketing.MarketingCard], t: float
) -> direct_marketing.MarketingCard:
    return next(
        (card for card in cards if card.start <= t < card.end),
        cards[-1],
    )


def align_cards_to_narration(
    cards: Sequence[direct_marketing.MarketingCard],
    phrase_starts: Sequence[float],
) -> List[direct_marketing.MarketingCard]:
    if len(cards) != len(phrase_starts):
        raise RuntimeError(
            "Direct-marketing narration/card alignment count mismatch."
        )
    return [
        direct_marketing.MarketingCard(
            text=card.text,
            start=float(phrase_starts[index]),
            end=(
                float(phrase_starts[index + 1])
                if index + 1 < len(phrase_starts)
                else direct_marketing.DIRECT_MARKETING_DURATION_SECONDS
            ),
            source_field=card.source_field,
        )
        for index, card in enumerate(cards)
    ]


def inspect_wav_audio(audio_path: Path) -> Dict[str, float]:
    """Return signal diagnostics for the PCM WAV formats used by TTS and beds."""
    path = Path(audio_path)
    if not path.is_file():
        raise RuntimeError(f"Direct-marketing audio source is missing: {path.name}")
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)
    if channels <= 0 or frame_rate <= 0 or frame_count <= 0:
        raise RuntimeError(
            f"Direct-marketing audio source is empty or malformed: {path.name}"
        )
    if sample_width == 1:
        samples = (
            np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
        ) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise RuntimeError(
            "Direct-marketing audio QA supports 8-, 16-, or 32-bit PCM WAV."
        )
    frames = samples.reshape((-1, channels))
    frame_levels = np.max(np.abs(frames), axis=1)
    threshold = 0.003
    active = np.flatnonzero(frame_levels >= threshold)
    leading_silence = (
        float(active[0]) / frame_rate
        if active.size
        else float(frame_count) / frame_rate
    )
    trailing_silence = (
        float(frame_count - 1 - active[-1]) / frame_rate
        if active.size
        else float(frame_count) / frame_rate
    )
    return {
        "duration": float(frame_count) / frame_rate,
        "signal_peak": float(np.max(frame_levels)),
        "signal_rms": float(np.sqrt(np.mean(np.square(samples)))),
        "leading_silence": leading_silence,
        "trailing_silence": trailing_silence,
        "clipping_fraction": float(np.mean(frame_levels >= 0.999)),
    }


def _compress_internal_silence(
    frames: np.ndarray,
    *,
    frame_rate: int,
    threshold: float = 0.003,
    minimum_gap_seconds: float = 0.14,
    maximum_gap_seconds: float = 0.10,
) -> np.ndarray:
    levels = np.max(np.abs(frames.astype(np.float64) / 32768.0), axis=1)
    silent = levels < threshold
    minimum_gap = int(round(minimum_gap_seconds * frame_rate))
    maximum_gap = int(round(maximum_gap_seconds * frame_rate))
    chunks = []
    cursor = 0
    index = 0
    while index < len(frames):
        if not silent[index]:
            index += 1
            continue
        run_start = index
        while index < len(frames) and silent[index]:
            index += 1
        run_length = index - run_start
        if run_length >= minimum_gap:
            chunks.append(frames[cursor:run_start])
            chunks.append(frames[run_start : run_start + maximum_gap])
            cursor = index
    chunks.append(frames[cursor:])
    return np.concatenate(chunks, axis=0) if chunks else frames


def prepare_direct_marketing_narration(
    narration_path: Path,
    output_path: Path,
    *,
    target_starts: Sequence[float] = (0.0, 1.5, 3.0, 6.0),
) -> Dict[str, Any]:
    """Align four detected spoken phrases to the existing visual card regions."""
    source = Path(narration_path)
    with wave.open(str(source), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        raw = wav_file.readframes(frame_count)
    if sample_width != 2:
        raise RuntimeError(
            "Direct-marketing narration alignment requires 16-bit PCM WAV."
        )
    frames = np.frombuffer(raw, dtype="<i2").reshape((-1, channels))
    frame_levels = np.max(
        np.abs(frames.astype(np.float64) / 32768.0),
        axis=1,
    )
    active = frame_levels >= 0.003
    active_indexes = np.flatnonzero(active)
    if not active_indexes.size:
        raise RuntimeError(
            "Direct-marketing narration QA failed: narration is silent."
        )

    minimum_gap = int(round(0.20 * frame_rate))
    gaps = []
    index = int(active_indexes[0])
    last_active = int(active_indexes[-1])
    while index <= last_active:
        if active[index]:
            index += 1
            continue
        gap_start = index
        while index <= last_active and not active[index]:
            index += 1
        gap_end = index
        if gap_end - gap_start >= minimum_gap:
            gaps.append((gap_start, gap_end))
    if len(gaps) < 3:
        raise RuntimeError(
            "Direct-marketing narration QA failed: fewer than four reliable "
            "spoken phrase regions were detected."
        )

    boundary_gaps = gaps[:3]
    reserve_before = int(round(0.08 * frame_rate))
    reserve_after = int(round(0.10 * frame_rate))
    edge_reserve = int(round(0.02 * frame_rate))
    segment_starts = [
        max(0, int(active_indexes[0]) - reserve_before),
        *[
            max(0, gap_end - edge_reserve)
            for _, gap_end in boundary_gaps
        ],
    ]
    segment_ends = [
        *[
            min(len(frames), gap_start + edge_reserve)
            for gap_start, _ in boundary_gaps
        ],
        min(len(frames), int(active_indexes[-1]) + reserve_after),
    ]
    segments = [
        _compress_internal_silence(
            frames[start:end],
            frame_rate=frame_rate,
        )
        for start, end in zip(segment_starts, segment_ends)
    ]

    placed = []
    actual_starts = []
    cursor = 0
    minimum_separation = int(round(0.03 * frame_rate))
    for target_start, segment in zip(target_starts, segments):
        requested_start = int(round(float(target_start) * frame_rate))
        actual_start = max(requested_start, cursor + minimum_separation)
        if not placed:
            actual_start = requested_start
        if actual_start > cursor:
            placed.append(
                np.zeros((actual_start - cursor, channels), dtype=np.int16)
            )
        placed.append(segment.astype(np.int16))
        actual_starts.append(actual_start / float(frame_rate))
        cursor = actual_start + len(segment)
    aligned = np.concatenate(placed, axis=0)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(aligned.astype("<i2").tobytes())
    diagnostics = inspect_wav_audio(output)
    diagnostics.update(
        {
            "phrase_starts": actual_starts,
            "target_starts": [float(value) for value in target_starts],
            "boundary_gap_count": len(boundary_gaps),
        }
    )
    if diagnostics["duration"] > (
        direct_marketing.DIRECT_MARKETING_DURATION_SECONDS
        - NARRATION_END_GUARD_SECONDS
    ):
        raise RuntimeError(
            "Direct-marketing narration QA failed: aligned narration remains "
            "too long for the video."
        )
    return {
        "path": output,
        "diagnostics": diagnostics,
    }


def validate_direct_marketing_audio_sources(
    *,
    narration_path: Path,
    music_path: Optional[Path],
    music_db: float,
    narration_lead_seconds: float,
) -> Dict[str, Any]:
    narration = inspect_wav_audio(narration_path)
    failures = []
    narration_trim_start = max(
        0.0,
        narration["leading_silence"]
        - NARRATION_LEADING_SILENCE_RESERVE_SECONDS,
    )
    narration_trim_end = narration["duration"] - max(
        0.0,
        narration["trailing_silence"]
        - NARRATION_TRAILING_SILENCE_RESERVE_SECONDS,
    )
    effective_narration_duration = max(
        0.0,
        narration_trim_end - narration_trim_start,
    )
    if narration["signal_peak"] <= 0.00001:
        failures.append("narration_is_silent")
    if effective_narration_duration + narration_lead_seconds > (
        direct_marketing.DIRECT_MARKETING_DURATION_SECONDS
        - NARRATION_END_GUARD_SECONDS
    ):
        failures.append("narration_longer_than_video")
    if narration["leading_silence"] > 0.75:
        failures.append("narration_has_long_leading_silence")
    if narration["clipping_fraction"] > 0.005:
        failures.append("narration_is_clipped")

    music = None
    voice_to_bed_db = None
    music_gain_db = float(music_db)
    if music_path is not None:
        music = inspect_wav_audio(music_path)
        if music["signal_peak"] <= 0.00001:
            failures.append("music_bed_is_silent")
        target_bed_rms = narration["signal_rms"] * math.pow(
            10.0,
            music_db / 20.0,
        )
        if music["signal_rms"] > 0.0 and target_bed_rms > 0.0:
            music_gain_db = max(
                -30.0,
                min(
                    12.0,
                    20.0
                    * math.log10(target_bed_rms / music["signal_rms"]),
                ),
            )
        bed_rms_after_gain = music["signal_rms"] * math.pow(
            10.0,
            music_gain_db / 20.0,
        )
        if bed_rms_after_gain > 0.0 and narration["signal_rms"] > 0.0:
            voice_to_bed_db = 20.0 * math.log10(
                narration["signal_rms"] / bed_rms_after_gain
            )
            if voice_to_bed_db <= 0.0:
                failures.append("music_bed_not_below_voice")

    if failures:
        raise RuntimeError(
            "Direct-marketing narration QA failed: "
            + ", ".join(dict.fromkeys(failures))
        )
    return {
        "narration": narration,
        "music": music,
        "music_db": float(music_db),
        "music_gain_db": music_gain_db,
        "voice_to_bed_db": voice_to_bed_db,
        "narration_lead_seconds": float(narration_lead_seconds),
        "narration_trim_start": narration_trim_start,
        "narration_trim_end": narration_trim_end,
        "effective_narration_duration": effective_narration_duration,
    }


def _mux_audio(
    *,
    silent_path: Path,
    music_path: Optional[Path],
    narration_path: Optional[Path],
    output_path: Path,
    duration: float,
    music_db: float,
    narration_lead_seconds: float,
    narration_trim_start: float = 0.0,
    narration_trim_end: Optional[float] = None,
) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(silent_path),
    ]
    narration_input = None
    music_input = None
    next_input = 1
    if narration_path is not None:
        narration_input = next_input
        command.extend(["-i", str(narration_path)])
        next_input += 1
    if music_path is not None:
        music_input = next_input
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])

    filter_parts = []
    if narration_input is not None:
        voice_filters = []
        if narration_trim_start > 0.0 or narration_trim_end is not None:
            trim_parts = []
            if narration_trim_start > 0.0:
                trim_parts.append(f"start={narration_trim_start:.4f}")
            if narration_trim_end is not None:
                trim_parts.append(f"end={narration_trim_end:.4f}")
            voice_filters.extend(
                [
                    "atrim=" + ":".join(trim_parts),
                    "asetpts=PTS-STARTPTS",
                ]
            )
        voice_filters.extend(["aresample=48000", "volume=1.0"])
        if narration_lead_seconds > 0.0:
            delay_ms = int(round(narration_lead_seconds * 1000.0))
            voice_filters.append(f"adelay={delay_ms}:all=1")
        voice_filters.append(f"apad=whole_dur={duration:.2f}")
        filter_parts.append(
            f"[{narration_input}:a]{','.join(voice_filters)}[voice]"
        )
    if music_input is not None:
        filter_parts.append(
            f"[{music_input}:a]aresample=48000,volume={music_db:g}dB,"
            "afade=t=in:st=0:d=0.20,"
            "afade=t=out:st=7.50:d=0.50[music]"
        )
    if narration_input is not None and music_input is not None:
        filter_parts.append(
            "[voice][music]amix=inputs=2:duration=longest:"
            "dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95:level=false[aout]"
        )
    elif narration_input is not None:
        filter_parts.append(
            "[voice]alimiter=limit=0.95:level=false[aout]"
        )
    elif music_input is not None:
        filter_parts.append("[music]anull[aout]")
    else:
        raise RuntimeError("Direct-marketing audio mux has no audio sources.")

    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-t",
            f"{duration:.2f}",
            str(output_path),
        ]
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Direct-marketing audio mux failed: "
            + completed.stderr.strip().splitlines()[-1]
        )


def verify_direct_marketing_video(
    video_path: Path,
    *,
    audio_required: bool,
) -> Dict[str, Any]:
    clip = VideoFileClip(str(video_path))
    try:
        audio_present = clip.audio is not None
        audio_duration = float(clip.audio.duration or 0.0) if clip.audio else 0.0
        audio_signal_peak = 0.0
        if clip.audio and audio_duration > 0.0:
            last_sample = max(0.0, audio_duration - 0.05)
            sample_times = np.linspace(0.05, last_sample, num=24)
            audio_signal_peak = max(
                float(np.max(np.abs(clip.audio.get_frame(float(sample_time)))))
                for sample_time in sample_times
            )
        diagnostics = {
            "duration": float(clip.duration or 0.0),
            "fps": float(clip.fps or 0.0),
            "resolution": list(clip.size),
            "audio_stream_detected": audio_present,
            "audio_duration": audio_duration,
            "audio_signal_peak": audio_signal_peak,
        }
    finally:
        clip.close()
    if audio_required and (
        not diagnostics["audio_stream_detected"]
        or diagnostics["audio_duration"] <= 0.0
        or diagnostics["audio_signal_peak"] <= 0.00001
    ):
        raise RuntimeError(
            "Direct-marketing QA failed: required audio is missing or silent."
        )
    if diagnostics["duration"] < direct_marketing.DIRECT_MARKETING_DURATION_SECONDS - 0.1:
        raise RuntimeError("Direct-marketing QA failed: final video is too short.")
    if diagnostics["audio_signal_peak"] >= 0.999:
        raise RuntimeError("Direct-marketing QA failed: final audio may be clipped.")
    return diagnostics


def render_direct_marketing_short(
    *,
    ad_copy: Dict[str, Any],
    background_path: Optional[Path],
    output_path: Path,
    screenshot_mode: Optional[bool] = None,
    audio_enabled: Optional[bool] = None,
    narration_audio_path: Optional[Path] = None,
    narration_text: str = "",
    tts_enabled: Optional[bool] = None,
    tts_required: Optional[bool] = None,
    text_music_fallback_enabled: Optional[bool] = None,
    seed: str = "direct-marketing",
) -> Path:
    """Render one product-first master MP4 without publishing or remote I/O."""
    if not config.DIRECT_MARKETING_ENABLED:
        raise RuntimeError("Direct-marketing rendering is disabled by configuration.")

    use_screenshots = (
        config.DIRECT_MARKETING_SCREENSHOT_MODE
        if screenshot_mode is None
        else screenshot_mode
    )
    attach_audio = (
        config.DIRECT_MARKETING_AUDIO_ENABLED
        if audio_enabled is None
        else audio_enabled
    )
    use_tts = (
        config.DIRECT_MARKETING_TTS_ENABLED
        if tts_enabled is None
        else tts_enabled
    )
    require_tts = (
        config.DIRECT_MARKETING_TTS_REQUIRED
        if tts_required is None
        else tts_required
    )
    allow_text_music_fallback = (
        config.DIRECT_MARKETING_TEXT_MUSIC_FALLBACK_ENABLED
        if text_music_fallback_enabled is None
        else text_music_fallback_enabled
    )
    cards = direct_marketing.build_direct_marketing_cards(
        ad_copy,
        direct_cta=config.DIRECT_MARKETING_CTA,
    )
    copy_failures = direct_marketing.validate_direct_marketing_copy(
        ad_copy,
        cards=cards,
        expected_cta=config.DIRECT_MARKETING_CTA,
    )
    if copy_failures:
        raise RuntimeError(
            "Direct-marketing QA failed: " + ", ".join(copy_failures)
        )
    narration_segments = (
        direct_marketing.build_direct_marketing_narration_segments(
            ad_copy,
            word_limit=config.DIRECT_MARKETING_NARRATION_WORD_LIMIT,
        )
        if use_tts
        else []
    )
    narration_failures = (
        direct_marketing.validate_direct_marketing_narration(
            ad_copy,
            narration_text,
            narration_segments,
            word_limit=config.DIRECT_MARKETING_NARRATION_WORD_LIMIT,
            expected_cta=config.DIRECT_MARKETING_CTA,
        )
        if use_tts and narration_audio_path is not None
        else []
    )
    narration_source = (
        Path(narration_audio_path)
        if narration_audio_path is not None
        else None
    )
    narration_available = bool(
        narration_source is not None and narration_source.is_file()
    )
    if use_tts and require_tts and not narration_available:
        raise RuntimeError(
            "Direct-marketing narration QA failed: required narration is missing."
        )
    if (
        use_tts
        and not narration_available
        and not require_tts
        and not allow_text_music_fallback
    ):
        raise RuntimeError(
            "Direct-marketing narration QA failed: text-plus-music fallback "
            "is not explicitly enabled."
        )
    if narration_failures:
        raise RuntimeError(
            "Direct-marketing narration QA failed: "
            + ", ".join(narration_failures)
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    silent_path = output.with_name(f"{output.stem}.silent{output.suffix}")
    selected_audio = None
    audio_metadata: Dict[str, Any] = {}
    if attach_audio:
        selected_audio, audio_metadata = select_audio_asset(
            profile_id=str(ad_copy.get("audio_profile", "current_default")),
            seed=seed,
        )
    source_audio_diagnostics = None
    prepared_narration_path = None
    if use_tts and narration_available:
        prepared = prepare_direct_marketing_narration(
            narration_source,
            output.with_name(f"{output.stem}.narration.wav"),
        )
        prepared_narration_path = prepared["path"]
        narration_source = prepared_narration_path
        aligned_starts = prepared["diagnostics"]["phrase_starts"]
        cards = align_cards_to_narration(cards, aligned_starts)
        source_audio_diagnostics = validate_direct_marketing_audio_sources(
            narration_path=narration_source,
            music_path=selected_audio,
            music_db=config.DIRECT_MARKETING_MUSIC_DB,
            narration_lead_seconds=(
                config.DIRECT_MARKETING_NARRATION_LEAD_SECONDS
            ),
        )
        source_audio_diagnostics["phrase_alignment"] = prepared[
            "diagnostics"
        ]

    screenshot_paths = (
        resolve_screenshot_sequence() if use_screenshots else []
    )
    screenshot_images = [
        Image.open(path).convert("RGBA") for path in screenshot_paths
    ]
    screenshot_fallback_used = bool(use_screenshots and not screenshot_images)
    if screenshot_fallback_used:
        print(
            "[direct_marketing_renderer] Approved screenshots unavailable; "
            "using scenic/text fallback."
        )
    if not screenshot_images and (
        background_path is None or not Path(background_path).is_file()
    ):
        raise RuntimeError(
            "Direct-marketing screenshot mode has no approved sequence and "
            "no safe scenic fallback."
        )

    bg_clip = (
        VideoFileClip(str(background_path))
        if not screenshot_images and background_path is not None
        else None
    )

    def make_frame(t: float) -> np.ndarray:
        if bg_clip is not None:
            source_t = t % max(float(bg_clip.duration or 0.01), 0.01)
            frame = Image.fromarray(bg_clip.get_frame(source_t)).convert("RGB")
            base = _cover_image(frame, CANVAS_SIZE).convert("RGBA")
        else:
            base = Image.new("RGBA", CANVAS_SIZE, (15, 31, 42, 255))
            draw = ImageDraw.Draw(base, "RGBA")
            draw.ellipse((-180, -120, 520, 600), fill=(44, 103, 116, 95))
            draw.ellipse((260, 650, 960, 1400), fill=(210, 165, 78, 55))

        card = _card_at(cards, t)
        active_screenshot = None
        if screenshot_images and 1.5 <= t < 6.75:
            screenshot_index = min(
                2,
                int((t - 1.5) / 1.75),
            )
            active_screenshot = screenshot_images[screenshot_index]
            segment_start = 1.5 + screenshot_index * 1.75
            _draw_screenshot(
                base,
                active_screenshot,
                local_progress=(t - segment_start) / 1.75,
            )
        _draw_card(
            base,
            text=card.text,
            final_card=card.source_field == "direct_cta",
            screenshot_mode=active_screenshot is not None,
        )
        return np.array(base.convert("RGB"))

    visual = VideoClip(
        make_frame,
        duration=direct_marketing.DIRECT_MARKETING_DURATION_SECONDS,
    ).with_fps(FPS)
    try:
        visual.write_videofile(
            str(silent_path),
            fps=FPS,
            codec="libx264",
            audio=False,
            logger=None,
        )
    finally:
        visual.close()
        if bg_clip is not None:
            bg_clip.close()
        for screenshot in screenshot_images:
            screenshot.close()

    if selected_audio is not None or (use_tts and narration_available):
        _mux_audio(
            silent_path=silent_path,
            music_path=selected_audio,
            narration_path=(
                narration_source
                if use_tts and narration_available
                else None
            ),
            output_path=output,
            duration=direct_marketing.DIRECT_MARKETING_DURATION_SECONDS,
            music_db=(
                source_audio_diagnostics["music_gain_db"]
                if source_audio_diagnostics
                else config.DIRECT_MARKETING_MUSIC_DB
            ),
            narration_lead_seconds=(
                config.DIRECT_MARKETING_NARRATION_LEAD_SECONDS
            ),
            narration_trim_start=(
                source_audio_diagnostics["narration_trim_start"]
                if source_audio_diagnostics
                else 0.0
            ),
            narration_trim_end=(
                source_audio_diagnostics["narration_trim_end"]
                if source_audio_diagnostics
                else None
            ),
        )
        silent_path.unlink(missing_ok=True)
        if prepared_narration_path is not None:
            prepared_narration_path.unlink(missing_ok=True)
    else:
        os.replace(silent_path, output)

    media = verify_direct_marketing_video(
        output,
        audio_required=bool(
            selected_audio is not None or (use_tts and narration_available)
        ),
    )
    print(
        "[direct_marketing_renderer] Rendered family={0}, screenshots={1}, "
        "scenic_fallback={2}, audio={3}".format(
            ad_copy.get("marketing_family"),
            len(screenshot_paths),
            screenshot_fallback_used,
            selected_audio.name if selected_audio else "disabled",
        )
    )
    print(
        "[direct_marketing_renderer] Final MP4 audio stream detected: "
        f"{media['audio_stream_detected']}"
    )
    if audio_metadata:
        print(
            "[direct_marketing_renderer] Audio license source: "
            f"{audio_metadata.get('license_source', 'approved local asset')}"
        )
    if source_audio_diagnostics:
        print(
            "[direct_marketing_renderer] Narration duration: "
            f"{source_audio_diagnostics['effective_narration_duration']:.2f}s "
            "(after conservative silence trim)"
        )
        print(
            "[direct_marketing_renderer] Music target relative to voice: "
            f"{source_audio_diagnostics['music_db']:g}dB "
            "(applied source gain "
            f"{source_audio_diagnostics['music_gain_db']:.2f}dB)"
        )
    return output
