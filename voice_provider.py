"""Shared Gemini/macOS voice provider for validated narration audio."""
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
    "natural_conversational": {
        "style": "Steady, natural, conversational delivery with restrained emotion.",
        "pace": "Even, controlled pacing.",
        "scene": (
            "Speak in a steady, natural, conversational voice. "
            "Use an even pace and restrained emotion. "
            "Sound calm, clear, sincere, and grounded, as if speaking directly to one person. "
            "Keep the delivery mostly level and controlled.\n\n"
            "Do not sound theatrical, preachy, dramatic, excited, forceful, breathy, whispered, sleepy, or like a meditation narrator.\n"
            "Do not shout, yell, strain, build into a sermon cadence, or add dramatic crescendos.\n"
            "Use only slight emphasis on the most important words.\n"
            "Let the meaning of the words carry the emotion rather than performing the emotion.\n\n"
            "Read every sentence exactly once, in order. "
            "Do not skip, summarize, paraphrase, duplicate, or add words."
        ),
        "generic_context": "A grounded everyday devotional reflection spoken with warmth and clarity.",
    },
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

NATURAL_CONVERSATIONAL_STYLE_INSTRUCTION = STYLE_PROFILES["natural_conversational"]["scene"]
PRAYER_STYLE_INSTRUCTION = STYLE_PROFILES["charismatic_prayer"]["scene"]
DEVOTIONAL_STYLE_INSTRUCTION = STYLE_PROFILES["devotional_teacher"]["scene"]
ENCOURAGEMENT_STYLE_INSTRUCTION = STYLE_PROFILES["hopeful_encouragement"]["scene"]

VALID_STYLE_PROFILES = set(STYLE_PROFILES)

TTS_DELIVERY_PROFILES = {
    "current_default": {
        **STYLE_PROFILES["natural_conversational"],
        "base_style_profile": "natural_conversational",
        "temperature": None,
    },
    "morning_hopeful": {
        "style": "Warm, hopeful delivery with calm forward movement.",
        "pace": "Natural conversational pace with light forward momentum.",
        "scene": (
            "Speak in a warm, hopeful, conversational tone. Keep the delivery grounded and sincere, "
            "with gentle forward movement appropriate for beginning the day. Use light emphasis and "
            "natural pauses without sounding promotional, overly cheerful, urgent, or dramatic."
        ),
        "generic_context": "A grounded morning prayer or encouragement spoken with steady hope.",
        "base_style_profile": "natural_conversational",
        "temperature": None,
    },
    "evening_reflective": {
        "style": "Soft, warm, reflective delivery with restrained energy.",
        "pace": "Gentle pace with measured pauses.",
        "scene": (
            "Speak in a warm, calm, reflective tone. Use a gentle pace with measured pauses. "
            "Keep energy low and reassuring, as though guiding someone through a peaceful evening "
            "devotional. Avoid upbeat, promotional, urgent, sleepy, robotic, or overly dramatic delivery."
        ),
        "generic_context": "A peaceful evening devotional spoken with warmth and measured reflection.",
        "base_style_profile": "natural_conversational",
        "temperature": 0.8,
    },
    "anxiety_calming": {
        "style": "Calm, steady, emotionally safe delivery.",
        "pace": "Unhurried conversational pace with reassuring pauses.",
        "scene": (
            "Speak calmly and steadily, with a warm, reassuring presence. Use an unhurried pace and "
            "natural pauses that create room to breathe. Avoid diagnosing, intensifying fear, sounding "
            "sleepy, whispering, or promising immediate relief."
        ),
        "generic_context": "A calming prayer that acknowledges anxiety without escalating it.",
        "base_style_profile": "natural_conversational",
        "temperature": None,
    },
    "protection_confident": {
        "style": "Confident, caring, and controlled prayer delivery.",
        "pace": "Steady conversational pace with purposeful pauses.",
        "scene": (
            "Speak with calm confidence, warmth, and controlled conviction. Let protection language feel "
            "caring and prayerful rather than fearful or forceful. Use purposeful pauses and restrained "
            "emphasis. Avoid alarm, urgency, shouting, guarantees, or dramatic intensity."
        ),
        "generic_context": "A steady prayer for protection spoken with caring confidence.",
        "base_style_profile": "natural_conversational",
        "temperature": None,
    },
    "devotional_measured": {
        "style": "Measured, thoughtful devotional delivery with warm clarity.",
        "pace": "Even pace with deliberate pauses around key ideas.",
        "scene": (
            "Speak with warm clarity in a measured, thoughtful devotional tone. Use deliberate pauses "
            "around key spiritual ideas while remaining natural and conversational. Avoid preaching "
            "cadence, promotional energy, theatrical emphasis, or sounding robotic."
        ),
        "generic_context": "A thoughtful devotional reflection spoken with measured warmth.",
        "base_style_profile": "natural_conversational",
        "temperature": None,
    },
    "direct_marketing_clear": {
        "style": "Clear, warm, confident, conversational product delivery.",
        "pace": "Brisk but natural pacing for an eight-second product demo.",
        "scene": (
            "Speak in a clear, warm, confident, conversational tone. Keep the "
            "pace brisk but natural for a short product demo. Sound genuinely "
            "interested, not overly excited, salesy, dramatic, or devotional. "
            "Use clean emphasis on Prayonit and the concrete product benefit. "
            "Complete the full transcript naturally within about six and a "
            "half seconds, brisk but never rushed. Read each short phrase "
            "exactly once, in order, "
            "and move directly into the next phrase with only a very brief pause."
        ),
        "generic_context": (
            "A concise Prayonit product demonstration spoken with clear, "
            "restrained confidence."
        ),
        "base_style_profile": "natural_conversational",
        "temperature": 0.9,
    },
}

VALID_TTS_DELIVERY_PROFILES = set(TTS_DELIVERY_PROFILES)


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
    return select_style_profile_with_reason(copy)[0]


def select_style_profile_with_reason(copy: Dict[str, Any]) -> tuple[str, str]:
    override = str(copy.get("voice_style_profile", "")).strip().lower()
    if override:
        if override in VALID_STYLE_PROFILES:
            return override, "explicit manual override"
        print(f"[voice_provider] Invalid voice_style_profile override: {override}; falling back safely")

    return "natural_conversational", "unified production narration profile"


def select_tts_delivery_profile(
    copy: Dict[str, Any],
    delivery_context: Optional[Dict[str, Any]] = None,
) -> str:
    return select_tts_delivery_profile_with_reason(copy, delivery_context)[0]


def select_tts_delivery_profile_with_reason(
    copy: Dict[str, Any],
    delivery_context: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    context = delivery_context or {}
    override = str(
        context.get("tts_delivery_profile_id")
        or copy.get("tts_delivery_profile_id")
        or getattr(config, "TTS_DELIVERY_PROFILE_OVERRIDE", "")
    ).strip().lower()
    if override:
        if override in VALID_TTS_DELIVERY_PROFILES:
            return override, "explicit TTS delivery override"
        print(
            "[voice_provider] Invalid TTS delivery profile override: "
            f"{override}; falling back safely"
        )

    slot = str(context.get("slot", "")).strip().lower()
    content_type = str(context.get("content_type", "")).strip().lower()
    prayer_category_id = str(
        context.get("prayer_category_id", "")
    ).strip().lower()

    if content_type == "direct_marketing":
        configured_profile = str(
            getattr(
                config,
                "DIRECT_MARKETING_TTS_PROFILE",
                "direct_marketing_clear",
            )
        ).strip().lower()
        if configured_profile in VALID_TTS_DELIVERY_PROFILES:
            return configured_profile, "direct-marketing content type"
        print(
            "[voice_provider] Invalid direct-marketing TTS profile: "
            f"{configured_profile}; falling back safely"
        )
    if slot == "evening" and content_type == "devotional_read":
        return "evening_reflective", "evening devotional content"
    if content_type == "devotional_read":
        return "devotional_measured", "devotional content type"
    if prayer_category_id in {"anxiety", "fear"}:
        return "anxiety_calming", "anxiety prayer category"
    if prayer_category_id == "protection":
        return "protection_confident", "protection prayer category"
    if prayer_category_id in {"morning_prayer", "hope"} or (
        slot == "morning" and content_type == "hope_encouragement"
    ):
        return "morning_hopeful", "hopeful morning content"
    legacy_override = str(copy.get("voice_style_profile", "")).strip().lower()
    if legacy_override and legacy_override in VALID_STYLE_PROFILES:
        return legacy_override, "explicit manual override"
    return "current_default", "unified production narration profile"


def _style_profile_from_instruction(style_instruction: str) -> str:
    if style_instruction == NATURAL_CONVERSATIONAL_STYLE_INSTRUCTION:
        return "natural_conversational"
    if style_instruction == PRAYER_STYLE_INSTRUCTION:
        return "charismatic_prayer"
    if style_instruction == DEVOTIONAL_STYLE_INSTRUCTION:
        return "devotional_teacher"
    return "hopeful_encouragement"


def build_narration_segments(copy: Dict[str, Any]) -> List[str]:
    segments: List[str] = []
    opening_hook = str(copy.get("opening_hook", "")).strip()
    if opening_hook:
        segments.append(opening_hook)

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


def _resolve_voice_temperature(delivery_profile_id: Optional[str] = None) -> float:
    profile = TTS_DELIVERY_PROFILES.get(str(delivery_profile_id or ""))
    profile_temperature = profile.get("temperature") if profile else None
    if delivery_profile_id == "direct_marketing_clear":
        profile_temperature = getattr(
            config,
            "DIRECT_MARKETING_TTS_TEMPERATURE",
            0.9,
        )
    try:
        value = float(
            profile_temperature
            if profile_temperature is not None
            else getattr(config, "VOICE_TEMPERATURE", 1.0)
        )
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(2.0, value))


def build_tts_prompt(text: str, style_profile: str, copy: Optional[Dict[str, Any]] = None) -> str:
    profile = TTS_DELIVERY_PROFILES.get(style_profile) or STYLE_PROFILES[style_profile]
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
    current_time = 0.0
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
        kind = "script_segment"
        if index == 0 and str(copy.get("opening_hook", "")).strip():
            kind = "opening_hook"
        elif (
            index == (1 if str(copy.get("opening_hook", "")).strip() else 0)
            and str(copy.get("bridge_line", "")).strip()
        ):
            kind = "bridge_line"
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
        remaining_time = max(0.0, narration_duration - segment_end)
        current_time = segment_end

    if timeline:
        timeline[-1]["end"] = narration_duration
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
    delivery_context: Optional[Dict[str, Any]] = None,
) -> Path:
    if copy:
        delivery_profile, selection_reason = (
            select_tts_delivery_profile_with_reason(copy, delivery_context)
        )
    else:
        delivery_profile = _style_profile_from_instruction(style_instruction)
        selection_reason = "style instruction"
    if copy is not None:
        validate_narration_transcript(build_narration_segments(copy), text)
    prompt = build_tts_prompt(text, delivery_profile, copy)
    temperature = _resolve_voice_temperature(delivery_profile)
    profile = (
        TTS_DELIVERY_PROFILES.get(delivery_profile)
        or STYLE_PROFILES[delivery_profile]
    )
    print(f"Gemini TTS voice: {voice_name}")
    print(
        "Gemini TTS style profile: "
        f"{profile.get('base_style_profile', delivery_profile)}"
    )
    print(f"Gemini TTS delivery profile: {delivery_profile}")
    print(f"Style selection reason: {selection_reason}")
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
    delivery_context: Optional[Dict[str, Any]] = None,
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
                gemini_kwargs: Dict[str, Any] = {
                    "copy": copy,
                    "model_name": model_name,
                }
                if delivery_context is not None:
                    gemini_kwargs["delivery_context"] = delivery_context
                return _generate_with_gemini(
                    text,
                    voice_name,
                    style_instruction,
                    output_path,
                    **gemini_kwargs,
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
