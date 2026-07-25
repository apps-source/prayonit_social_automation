"""Voice provider layer for long-form narration audio."""
from __future__ import annotations

import shutil
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

import config

_gemini_client: Optional[genai.Client] = None

TEMPORARY_TTS_ERROR_TOKENS = (
    "429",
    "503",
    "resource exhausted",
    "unavailable",
    "temporarily unavailable",
)

STYLE_PROFILES = {
    "charismatic_prayer": {
        "style": "High energy, punchy consonants, elongated vowels on excitement words.",
        "pace": "Natural conversational pace.",
        "scene": (
            "Speak like a charismatic Christian preacher delivering a powerful prayer to a congregation. "
            "Use a strong, full speaking voice with conviction, authority, and rising energy. Project clearly. "
            "Sound bold, faith-filled, and emotionally engaged.\n\n"
            "Do not whisper.\n"
            "Do not sound soft-spoken.\n"
            "Do not sound sleepy, meditative, breathy, restrained, or subdued.\n"
            "Do not use a commercial announcer voice.\n"
            "Do not overact or shout every line.\n\n"
            "Build intensity naturally. Emphasize declarations of faith, strength, trust, peace, courage, and God's guidance. "
            "Use brief, purposeful pauses. End with a confident, decisive \"Amen.\""
        ),
        "generic_context": "A bold spoken prayer that builds toward faith, trust, and a decisive Amen.",
    },
    "devotional_teacher": {
        "style": "Strong voice, steady emphasis, warm conviction.",
        "pace": "Natural conversational pace.",
        "scene": (
            "Speak like a confident Christian teacher delivering a powerful devotional message. "
            "Use a strong, full voice with conviction, warmth, and steady energy. "
            "Sound faith-filled and emotionally engaged. Do not whisper, sound sleepy, or use a commercial-announcer tone. "
            "Emphasize the core spiritual takeaway naturally."
        ),
        "generic_context": "A confident devotional message centered on one clear spiritual takeaway.",
    },
    "hopeful_encouragement": {
        "style": "Confident encouragement with clear emphasis and rising hope.",
        "pace": "Natural conversational pace.",
        "scene": (
            "Speak with confident Christian encouragement, full voice, conviction, and hopeful energy. "
            "Sound like someone who strongly believes the message. "
            "Do not whisper, sound breathy, subdued, meditative, or sleepy. "
            "Keep a natural conversational pace and build emphasis toward the closing declaration."
        ),
        "generic_context": "A hopeful Christian encouragement that grows stronger by the end.",
    },
}

PRAYER_STYLE_INSTRUCTION = STYLE_PROFILES["charismatic_prayer"]["scene"]
DEVOTIONAL_STYLE_INSTRUCTION = STYLE_PROFILES["devotional_teacher"]["scene"]
ENCOURAGEMENT_STYLE_INSTRUCTION = STYLE_PROFILES["hopeful_encouragement"]["scene"]


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.get_gemini_primary_api_key())
    return _gemini_client


def select_default_voice(copy: Dict[str, Any]) -> str:
    long_form_type = str(copy.get("long_form_type", "none")).strip().lower()
    if config.VOICE_NAME:
        return config.VOICE_NAME
    if long_form_type == "prayer":
        return config.VOICE_NAME_PRAYER
    if long_form_type == "devotional":
        return config.VOICE_NAME_DEVOTIONAL
    if long_form_type == "encouragement":
        return config.VOICE_NAME_ENCOURAGEMENT
    return config.VOICE_NAME_PRAYER


def select_style_instruction(copy: Dict[str, Any]) -> str:
    return STYLE_PROFILES[select_style_profile(copy)]["scene"]


def select_style_profile(copy: Dict[str, Any]) -> str:
    long_form_type = str(copy.get("long_form_type", "none")).strip().lower()
    if long_form_type == "prayer":
        return "charismatic_prayer"
    if long_form_type == "devotional":
        return "devotional_teacher"
    return "hopeful_encouragement"


def _style_profile_from_instruction(style_instruction: str) -> str:
    if style_instruction == PRAYER_STYLE_INSTRUCTION:
        return "charismatic_prayer"
    if style_instruction == DEVOTIONAL_STYLE_INSTRUCTION:
        return "devotional_teacher"
    return "hopeful_encouragement"


def build_narration_segments(copy: Dict[str, Any]) -> List[str]:
    segments: List[str] = []
    bridge_line = str(copy.get("bridge_line", "")).strip()
    if bridge_line:
        segments.append(bridge_line)

    raw_script_segments = copy.get("script_segments", [])
    if isinstance(raw_script_segments, list):
        for segment in raw_script_segments:
            text = str(segment).strip()
            if text:
                segments.append(text)

    closing_line = str(copy.get("closing_line", "")).strip()
    if closing_line:
        segments.append(closing_line)
    return segments


def build_narration_text(copy: Dict[str, Any]) -> str:
    return "\n\n".join(build_narration_segments(copy)).strip()


def _count_sentences(text: str) -> int:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    return len(parts)


def validate_narration_transcript(units: List[str], transcript: str) -> None:
    normalized_units = [str(unit).strip() for unit in units if str(unit).strip()]
    normalized_transcript = transcript.strip()
    search_start = 0
    for index, unit in enumerate(normalized_units):
        if normalized_transcript.count(unit) != 1:
            raise RuntimeError(
                "Narration transcript validation failed before TTS API call: "
                f"unit {index} was missing, duplicated, or altered."
            )
        found_at = normalized_transcript.find(unit, search_start)
        if found_at == -1:
            raise RuntimeError(
                "Narration transcript validation failed before TTS API call: "
                f"unit {index} was out of order or missing."
            )
        search_start = found_at + len(unit)


def build_sample_context(copy: Dict[str, Any]) -> str:
    opening_hook = str(copy.get("opening_hook", "")).strip()
    bridge_line = str(copy.get("bridge_line", "")).strip()
    script_segments = [str(segment).strip() for segment in copy.get("script_segments", []) if str(segment).strip()]

    context_parts: List[str] = []
    if opening_hook and bridge_line:
        context_parts = [opening_hook, bridge_line]
    elif bridge_line:
        context_parts = [bridge_line]
    elif script_segments:
        context_parts = [script_segments[0]]
    else:
        profile = STYLE_PROFILES[select_style_profile(copy)]
        context_parts = [profile["generic_context"]]
    return "\n".join(context_parts[:3]).strip()


def _resolve_voice_temperature() -> float:
    try:
        value = float(getattr(config, "VOICE_TEMPERATURE", 1.0))
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(2.0, value))


def build_tts_prompt(text: str, style_profile: str, copy: Optional[Dict[str, Any]] = None) -> str:
    profile = STYLE_PROFILES[style_profile]
    sample_context = build_sample_context(copy or {})
    transcript = text.strip()
    return (
        "Read the following transcript based on the director's note.\n\n"
        "# Director's note\n"
        f"Style: {profile['style']}\n"
        f"Pace: {profile['pace']}\n\n"
        "## Scene:\n"
        f"{profile['scene']}\n\n"
        "## Sample Context:\n"
        f"{sample_context}\n\n"
        "Read every sentence in the Transcript exactly once, in order. "
        "Do not skip, summarize, paraphrase, or omit any sentence.\n\n"
        "## Transcript:\n"
        f"{transcript}"
    )


def measure_audio_duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        if frame_rate <= 0:
            return 0.0
        return frames / float(frame_rate)


def create_silent_wav(output_path: Path, duration_seconds: float, rate: int = 24000) -> Path:
    frames = max(1, int(duration_seconds * rate))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return output_path


def build_narration_segment_timeline(
    copy: Dict[str, Any],
    narration_duration: float,
    *,
    hook_window: float = 0.0,
    min_segment_seconds: float = 1.8,
) -> List[Dict[str, Any]]:
    segments = build_narration_segments(copy)
    if not segments:
        return []

    total_words = sum(max(1, len(segment.split())) for segment in segments)
    timeline: List[Dict[str, Any]] = []
    current_time = hook_window
    remaining_time = narration_duration

    for index, segment in enumerate(segments):
        words = max(1, len(segment.split()))
        segments_left = len(segments) - index
        if segments_left == 1:
            segment_duration = remaining_time
        else:
            proportional = narration_duration * (words / total_words)
            min_required_for_rest = min_segment_seconds * (segments_left - 1)
            segment_duration = max(min_segment_seconds, proportional)
            segment_duration = min(segment_duration, max(min_segment_seconds, remaining_time - min_required_for_rest))

        segment_end = current_time + max(min_segment_seconds, segment_duration)
        kind = "bridge_line" if index == 0 and str(copy.get("bridge_line", "")).strip() else "script_segment"
        if segment == str(copy.get("closing_line", "")).strip() and str(copy.get("closing_line", "")).strip():
            kind = "closing_line"
        timeline.append(
            {
                "text": segment,
                "start": current_time,
                "end": segment_end,
                "kind": kind,
            }
        )
        remaining_time = max(0.0, hook_window + narration_duration - segment_end)
        current_time = segment_end

    if timeline:
        timeline[-1]["end"] = hook_window + narration_duration
    return timeline


def _wave_file(filename: Path, pcm: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> Path:
    filename.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(filename), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm)
    return filename


def _is_temporary_tts_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in TEMPORARY_TTS_ERROR_TOKENS)


def _generate_with_gemini(
    text: str,
    voice_name: str,
    style_instruction: str,
    output_path: Path,
    *,
    copy: Optional[Dict[str, Any]] = None,
    model_name: Optional[str] = None,
) -> Path:
    style_profile = select_style_profile(copy) if copy else _style_profile_from_instruction(style_instruction)
    if copy is not None:
        validate_narration_transcript(build_narration_segments(copy), text)
    prompt = build_tts_prompt(text, style_profile, copy)
    temperature = _resolve_voice_temperature()
    print(f"Gemini TTS voice: {voice_name}")
    print(f"Gemini TTS style profile: {style_profile}")
    print(f"Gemini TTS temperature: {temperature:g}")
    if config.PREVIEW_MODE:
        print(f"Final narration transcript character count: {len(text.strip())}")
        print(f"Final narration transcript sentence count: {_count_sentences(text)}")
        print(
            "Narration transcript integrity validated before TTS generation; "
            "spoken-word verification was not available."
        )
    client = _get_gemini_client()
    response = client.models.generate_content(
        model=model_name or config.VOICE_MODEL_PRIMARY or config.VOICE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )
    data = response.candidates[0].content.parts[0].inline_data.data
    return _wave_file(output_path, data)


def _generate_with_macos_say(text: str, output_path: Path, voice_name: str) -> Path:
    say_path = shutil.which("say")
    if say_path is None:
        raise RuntimeError("macOS 'say' command is unavailable.")
    afconvert_path = shutil.which("afconvert")
    if afconvert_path is None:
        raise RuntimeError("macOS 'afconvert' command is unavailable for WAV conversion.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as temp_file:
        temp_aiff = Path(temp_file.name)
    try:
        subprocess.run(
            [say_path, "-v", voice_name, "-o", str(temp_aiff), text],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [afconvert_path, "-f", "WAVE", "-d", "LEI16@24000", str(temp_aiff), str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if temp_aiff.exists():
            temp_aiff.unlink()
    return output_path


def generate_voiceover(
    text: str,
    voice_name: str,
    style_instruction: str,
    output_path: Path,
    *,
    copy: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    fallback_enabled: Optional[bool] = None,
) -> Optional[Path]:
    """Generate narration audio, retrying once for temporary Gemini failures."""
    chosen_provider = (provider or config.VOICE_PROVIDER or "gemini").strip().lower()
    allow_fallback = config.VOICE_FALLBACK_ENABLED if fallback_enabled is None else fallback_enabled
    output_path = Path(output_path)

    if not text.strip():
        return None

    def _fallback(exc: Exception) -> Optional[Path]:
        if allow_fallback:
            print(f"[voice_provider] Gemini TTS failed; trying macOS fallback: {exc}")
            try:
                return _generate_with_macos_say(text, output_path, voice_name)
            except Exception as fallback_exc:  # noqa: BLE001
                print(f"[voice_provider] macOS fallback failed: {fallback_exc}")
                return None
        print(f"[voice_provider] Voice generation failed and fallback is disabled: {exc}")
        return None

    if chosen_provider == "macos":
        try:
            return _generate_with_macos_say(text, output_path, voice_name)
        except Exception as exc:  # noqa: BLE001
            print(f"[voice_provider] macOS voice generation failed: {exc}")
            return None

    attempts = 2
    last_exc: Optional[Exception] = None
    model_sequence = []
    primary_model = config.VOICE_MODEL_PRIMARY or config.VOICE_MODEL
    secondary_model = config.VOICE_MODEL_SECONDARY
    if primary_model:
        model_sequence.append(primary_model)
    if secondary_model and secondary_model not in model_sequence:
        model_sequence.append(secondary_model)

    for model_name in model_sequence:
        for attempt in range(1, attempts + 1):
            try:
                return _generate_with_gemini(
                    text,
                    voice_name,
                    style_instruction,
                    output_path,
                    copy=copy,
                    model_name=model_name,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                temporary = _is_temporary_tts_error(exc)
                print(
                    "[voice_provider] Gemini TTS model {0} attempt {1} failed: {2}".format(
                        model_name,
                        attempt,
                        exc,
                    )
                )
                if attempt < attempts and temporary:
                    time.sleep(0.5)
                    continue
                break
    if last_exc is None:
        return None
    return _fallback(last_exc)
