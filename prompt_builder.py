"""Gemini prompt construction and platform-specific caption assembly (Part 12)."""
import json
import random
import re
import time
from typing import Any, Dict, Optional

import creative_engine_v3
from google import genai
from google.genai import types

import config
import resolved_content_brief
from engines import content_engine

_gemini_clients_by_key: Dict[str, genai.Client] = {}
_TEMPORARY_GEMINI_ERROR_CODES = ("429", "500", "502", "503", "504")
_CONTENT_503_RETRY_DELAYS_SECONDS = (2.0, 5.0)


def _get_gemini_client(api_key: Optional[str] = None) -> genai.Client:
    resolved_api_key = api_key or config.get_gemini_primary_api_key()
    client = _gemini_clients_by_key.get(resolved_api_key)
    if client is None:
        client = genai.Client(api_key=resolved_api_key)
        _gemini_clients_by_key[resolved_api_key] = client
    return client


def _gemini_error_status(exc: Exception) -> Optional[str]:
    code = getattr(exc, "code", None)
    if code is not None and str(code) in _TEMPORARY_GEMINI_ERROR_CODES:
        return str(code)
    match = re.search(r"\b(429|500|502|503|504)\b", str(exc))
    return match.group(1) if match else None


def _is_temporary_gemini_error(exc: Exception) -> bool:
    return _gemini_error_status(exc) is not None


def _get_configured_content_models() -> list[str]:
    models = []
    for model in (
        config.CONTENT_MODEL_PRIMARY,
        config.CONTENT_MODEL_SECONDARY,
        config.CONTENT_MODEL_TERTIARY,
    ):
        if model and model not in models:
            models.append(model)
    return models or [config.GEMINI_MODEL]


def _get_content_model_attempt_plan() -> list[tuple[str, str, str]]:
    models = _get_configured_content_models()
    primary_key = config.get_gemini_primary_api_key()
    secondary_key = config.get_gemini_secondary_api_key()
    attempts = []
    for index, model_name in enumerate(models):
        key_label = "primary" if index == 0 or secondary_key == primary_key else "secondary"
        api_key = primary_key if key_label == "primary" else secondary_key
        attempts.append((model_name, key_label, api_key))
    return attempts


PRODUCT_FLOW_DESCRIPTION = """
Prayonit's actual product flow:
- The user selects how they feel.
- They receive a relevant KJV Scripture passage.
- They receive an uplifting devotion.
- They can share what is on their heart.
- They receive a personalized, AI-generated prayer.
- They can journal the experience afterward.
"""


def build_brand_brain_preamble(brand_rules: Dict[str, Any]) -> str:
    """Build the mandatory Brand Brain preamble injected at the start of
    every Gemini prompt. brand_rules should be config.BRAND_RULES (loaded
    from brand/brand_rules.json).
    """
    core_features = brand_rules.get("core_features", [])
    approved_ctas = brand_rules.get("approved_ctas", [])
    preferred_cta = brand_rules.get("preferred_cta", "")
    tone = brand_rules.get("voice", {}).get("tone", [])
    voice_avoid = brand_rules.get("voice", {}).get("avoid", [])
    approved_language = brand_rules.get("approved_language", [])
    never_claim = brand_rules.get("never_claim", [])
    never_say = brand_rules.get("never_say", [])

    return f"""
You MUST follow every rule contained in brand_rules.json.
Never violate these rules.
Never invent features.
Never invent pricing.
Never invent URLs.
Never promise outcomes.
Never claim God is speaking through the app.
Always use the preferred CTA unless instructed otherwise.

Brand: {brand_rules.get('brand_name', 'Prayonit')} - {brand_rules.get('tagline', '')}
Mission: {brand_rules.get('mission', '')}
Only these features actually exist, do not invent any others: {', '.join(core_features)}
Preferred CTA (use this unless a specific alternate is requested): {preferred_cta}
Other approved CTAs you may use instead: {', '.join(approved_ctas)}
Preferred tone: {', '.join(tone)}
Never use this tone/approach: {', '.join(voice_avoid)}
Approved language/phrases to draw from: {', '.join(approved_language)}
Never claim any of the following: {', '.join(never_claim)}
Never say any of the following phrases: {', '.join(never_say)}
"""


def build_time_guidance(slot: str) -> str:
    if slot == "evening":
        return """
Time-of-day guidance: this ad will publish this evening, around 7:00 PM.
- Language may reference tonight, winding down, reflecting on the day,
  releasing worries, or praying before sleep.
- Never say "start your day," "this morning," or similar morning language.
"""
    return """
Time-of-day guidance: this ad will publish this morning, around 8:00 AM.
- Language may reference starting the day, this morning, today, or
  beginning with prayer.
- Avoid bedtime or end-of-day language.
"""


def build_weekly_rhythm_preamble(
    slot: str, resolved_brief: Optional[Any] = None
) -> str:
    """Build the "Today's Schedule" block from the Weekly Rhythm content
    engine and log the resolved theme for verification.

    This is an ADDITIVE content-selection layer only: it does not alter,
    remove, or replace any existing prompt instructions. If the weekly
    rhythm config cannot be loaded for any reason, an empty string is
    returned so prompt generation continues to work exactly as before.
    """
    if resolved_brief is not None:
        content_type = resolved_brief.content_type
        theme = resolved_brief.weekly_theme
        emotion = resolved_brief.pain_point_label
        hook_style = resolved_brief.hook_style_label or ""
        objective = resolved_brief.objective
    else:
        try:
            todays_content = content_engine.get_todays_content(slot=slot)
        except Exception as exc:  # pragma: no cover - defensive fallback only
            print("Weekly Theme: unavailable ({0})".format(exc))
            return ""

        content_type = todays_content.get("content_type", "")
        theme = todays_content.get("theme", "")
        emotion = todays_content.get("emotion", "")
        hook_style = todays_content.get("hook_style", "")
        objective = todays_content.get("objective", "")

    print("Weekly Theme:")
    print(content_type.replace("_", " ").title())
    print(theme.title())
    print(hook_style.title())

    return """
Today's Schedule

Content Type:
{content_type}

Theme:
{theme}

Emotion:
{emotion}

Hook Style:
{hook_style}

Objective:
{objective}
""".format(
        content_type=content_type.replace("_", " ").title(),
        theme=theme.title(),
        emotion=emotion.title(),
        hook_style=hook_style.title(),
        objective=objective,
    )


# ---------------------------------------------------------------------------
# Creative Brief (Weekly Rhythm + Creative Library)
#
# This is an ADDITIVE content-selection layer that runs before the existing
# Gemini prompt. It selects a Life Moment, a Hook Style, and (only when
# today's rules allow it) an Engagement Prompt or Soft Promotion from the
# creative library (creative/*.json), then renders a structured "Creative
# Brief" block that is prepended to the unchanged existing prompt. Nothing
# below alters the renderer, uploader, Buffer integration, Supabase,
# image generation, or video generation, and it never replaces or removes
# any existing prompt instructions — build_prompt() below still appends
# the full existing prompt unchanged.
# ---------------------------------------------------------------------------

# Content types (from creative/weekly_rhythm.json) on which it is
# appropriate to surface an Engagement Prompt or a Soft Promotion.
_ENGAGEMENT_PROMPT_CONTENT_TYPES = (
    "prayer_read",
    "devotional_read",
    "recognition_engagement",
    "hope_encouragement",
    "gratitude_reflection",
    "night_prayer_or_rest",
)
_SOFT_PROMOTION_CONTENT_TYPES = ("app_feature",)

_MORNING_TONE = "Warm and encouraging"
_EVENING_TONE = "Calm and reflective"

_PRAYER_GUIDANCE_TYPES = {"prayer_read", "night_prayer_or_rest"}
_DEVOTIONAL_GUIDANCE_TYPES = {"devotional_read", "gratitude_reflection"}
_ENCOURAGEMENT_GUIDANCE_TYPES = {"hope_encouragement"}

LONG_FORM_OPTIONAL_KEYS = (
    "long_form_type",
    "opening_hook",
    "bridge_line",
    "script_segments",
    "closing_line",
    "engagement_line",
    "estimated_spoken_seconds",
)

_LONG_FORM_TYPES = {"prayer", "devotional", "encouragement", "none"}


def build_format_specific_guidance(content_type: str) -> str:
    """Return additive writing guidance for the resolved content type."""
    if content_type in _PRAYER_GUIDANCE_TYPES:
        return """
Format Guidance:
- Generate an actual complete prayer suitable for approximately 25 to 35 seconds of spoken delivery.
- Include a short recognition hook.
- The prayer should feel natural, compassionate, and specific to the Life Moment.
- Do not turn it into app marketing.
- End the prayer naturally, such as with "Amen," when appropriate.
"""
    if content_type in _DEVOTIONAL_GUIDANCE_TYPES:
        return """
Format Guidance:
- Generate a meaningful devotional reflection suitable for approximately 20 to 30 seconds.
- Include recognition, comfort, hope, and one clear takeaway.
- Avoid hard app promotion.
"""
    if content_type in _ENCOURAGEMENT_GUIDANCE_TYPES:
        return """
Format Guidance:
- Generate a hope-filled encouragement suitable for approximately 20 to 30 seconds.
- Focus on reassurance, emotional resolution, and a clear sense of hope.
- Avoid hard app promotion.
"""
    if content_type == "app_feature":
        return """
Format Guidance:
- Preserve the current concise promotional behavior.
"""
    if content_type == "recognition_engagement":
        return """
Format Guidance:
- Generate a short relatable recognition message and one natural engagement invitation.
"""
    return ""


def expected_long_form_type(content_type: str, video_template: str) -> str:
    """Return the expected long-form type for the resolved content format."""
    if content_type in _PRAYER_GUIDANCE_TYPES or video_template == "long_prayer":
        return "prayer"
    if content_type in _ENCOURAGEMENT_GUIDANCE_TYPES or video_template == "long_encouragement":
        return "encouragement"
    if content_type in _DEVOTIONAL_GUIDANCE_TYPES or video_template == "long_devotional":
        return "devotional"
    return "none"


def build_long_form_defaults(
    *,
    content_type: str,
    video_template: str,
    duration_seconds: int,
) -> Dict[str, Any]:
    """Return safe long-form defaults for the resolved weekly format."""
    long_form_type = expected_long_form_type(content_type, video_template)
    estimated_spoken_seconds = duration_seconds if long_form_type != "none" else 8
    return {
        "long_form_type": long_form_type,
        "opening_hook": "",
        "bridge_line": "",
        "script_segments": [],
        "closing_line": "",
        "engagement_line": "",
        "estimated_spoken_seconds": estimated_spoken_seconds,
    }


def _looks_like_complete_thought(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return stripped[-1] in ".?!"


def normalize_long_form_fields(
    raw_data: Dict[str, Any],
    *,
    content_type: str,
    video_template: str,
    duration_seconds: int,
    engagement_prompt_enabled: bool,
) -> Dict[str, Any]:
    """Normalize optional long-form fields without breaking old callers."""
    normalized = build_long_form_defaults(
        content_type=content_type,
        video_template=video_template,
        duration_seconds=duration_seconds,
    )

    long_form_type = str(raw_data.get("long_form_type", normalized["long_form_type"])).strip().lower()
    if long_form_type not in _LONG_FORM_TYPES:
        long_form_type = normalized["long_form_type"]
    if normalized["long_form_type"] == "none":
        long_form_type = "none"
    elif long_form_type == "none":
        long_form_type = normalized["long_form_type"]
    normalized["long_form_type"] = long_form_type

    for key in ("opening_hook", "bridge_line", "closing_line", "engagement_line"):
        value = raw_data.get(key, normalized[key])
        normalized[key] = str(value).strip() if value is not None else ""

    raw_segments = raw_data.get("script_segments", [])
    if not isinstance(raw_segments, list):
        raw_segments = []
    script_segments = []
    for segment in raw_segments:
        text = str(segment).strip()
        if not text:
            continue
        if not _looks_like_complete_thought(text):
            continue
        script_segments.append(text)

    expected_segment_count = normalized["long_form_type"] in {"prayer", "devotional", "encouragement"}
    if normalized["long_form_type"] == "none":
        script_segments = []
    elif expected_segment_count and not (2 <= len(script_segments) <= 5):
        script_segments = []
    normalized["script_segments"] = script_segments

    estimated = raw_data.get("estimated_spoken_seconds", normalized["estimated_spoken_seconds"])
    if not isinstance(estimated, int) or not (8 <= estimated <= 35):
        estimated = normalized["estimated_spoken_seconds"]
    normalized["estimated_spoken_seconds"] = estimated

    if not engagement_prompt_enabled:
        normalized["engagement_line"] = ""

    if normalized["long_form_type"] == "prayer" and not normalized["closing_line"]:
        normalized["closing_line"] = "Amen."

    return normalized


def select_life_moment_for_emotion(
    emotion: str, life_moments: Optional[list] = None
) -> Optional[Dict[str, Any]]:
    """Select one Life Moment whose emotions list includes `emotion`
    (case-insensitive). Falls back to a random moment from the full list
    if no exact match is found, and to None if the library is empty.
    """
    moments = life_moments if life_moments is not None else content_engine.load_life_moments()
    if not moments:
        return None

    candidates = [
        m
        for m in moments
        if emotion and emotion.lower() in [e.lower() for e in m.get("emotions", [])]
    ]
    if not candidates:
        candidates = moments

    return random.choice(candidates)


def select_hook_for_style(
    hook_style: str, hook_styles: Optional[list] = None
) -> Optional[Dict[str, Any]]:
    """Select the Hook Style entry matching today's rhythm `hook_style`
    (case-insensitive match against the "name" field). Falls back to a
    random hook style if no exact match is found, and to None if the
    library is empty.
    """
    hook = content_engine.get_random_hook(style=hook_style, hook_styles=hook_styles)
    if hook is not None:
        return hook
    return content_engine.get_random_hook(hook_styles=hook_styles)


def creative_brief_allows_engagement_prompt(content_type: str) -> bool:
    """Return True when today's content_type permits an Engagement
    Prompt, per the Weekly Rhythm content rules."""
    return content_type in _ENGAGEMENT_PROMPT_CONTENT_TYPES


def creative_brief_allows_soft_promotion(content_type: str) -> bool:
    """Return True when today's content_type permits a Soft Promotion,
    per the Weekly Rhythm content rules."""
    return content_type in _SOFT_PROMOTION_CONTENT_TYPES


def build_creative_brief_data(
    slot: str, resolved_brief: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """Assemble the structured Creative Brief data for today's rhythm.

    Returns None if the Weekly Rhythm config cannot be loaded, so callers
    can fail safe without breaking prompt generation.
    """
    if resolved_brief is not None:
        return {
            "weekly_theme": resolved_brief.weekly_theme,
            "content_type": resolved_brief.content_type,
            "prayer_category_id": resolved_brief.prayer_category_id,
            "hook_profile_id": resolved_brief.hook_profile_id,
            "voice_profile_id": resolved_brief.voice_profile_id,
            "body_profile_id": getattr(
                resolved_brief, "body_profile_id", "current_default"
            ),
            "caption_profile_id": resolved_brief.caption_profile_id,
            "scene_profile_id": resolved_brief.scene_profile_id,
            "cta_profile_id": resolved_brief.cta_profile_id,
            "hashtag_profile_id": resolved_brief.hashtag_profile_id,
            "creative_policy_version": resolved_brief.creative_policy_version,
            "objective": resolved_brief.objective,
            "tone": resolved_brief.tone,
            "emotional_goal": resolved_brief.emotional_goal,
            "video_template": resolved_brief.video_template,
            "target_duration": resolved_brief.duration_seconds,
            "marketing_enabled": resolved_brief.marketing_enabled,
            "engagement_prompt_enabled": bool(resolved_brief.engagement_prompt),
            "engagement_prompt_type": resolved_brief.engagement_prompt_type,
            "format_guidance": build_format_specific_guidance(resolved_brief.content_type),
            "expected_long_form_type": resolved_brief.long_form_type,
            "life_moment": {
                "category": resolved_brief.life_moment_category,
                "moment": resolved_brief.life_moment_text,
                "emotions": [resolved_brief.normalized_emotion_id],
            },
            "hook": {"name": resolved_brief.hook_style_label},
            "engagement_prompt": (
                {"prompt": resolved_brief.engagement_prompt}
                if resolved_brief.engagement_prompt
                else None
            ),
            "soft_promotion": None,
        }
    try:
        todays_content = content_engine.get_todays_content(slot=slot)
    except Exception as exc:  # pragma: no cover - defensive fallback only
        print("Creative Brief: unavailable ({0})".format(exc))
        return None

    content_type = todays_content.get("content_type", "")
    theme = todays_content.get("theme", "")
    emotion = todays_content.get("emotion", "")
    hook_style_name = todays_content.get("hook_style", "")
    objective = todays_content.get("objective", "")
    presentation = content_engine.get_presentation_config(todays_content)

    life_moment = select_life_moment_for_emotion(emotion)
    hook = select_hook_for_style(hook_style_name)

    engagement_prompt = None
    if presentation.get("engagement_prompt_enabled"):
        engagement_prompt = content_engine.get_random_engagement_prompt()

    soft_promotion = None
    if presentation.get("marketing_enabled"):
        soft_promotion = content_engine.get_random_soft_promotion()

    tone = _MORNING_TONE if slot != "evening" else _EVENING_TONE
    emotional_goal = "Help the reader move from feeling {0} toward hope and peace.".format(
        emotion.lower() if emotion else "burdened"
    )

    return {
        "weekly_theme": theme,
        "content_type": content_type,
        "objective": objective,
        "tone": tone,
        "emotional_goal": emotional_goal,
        "video_template": presentation["video_template"],
        "target_duration": presentation["duration_seconds"],
        "marketing_enabled": presentation["marketing_enabled"],
        "engagement_prompt_enabled": presentation["engagement_prompt_enabled"],
        "engagement_prompt_type": presentation["engagement_prompt_type"],
        "format_guidance": build_format_specific_guidance(content_type),
        "expected_long_form_type": expected_long_form_type(
            content_type, presentation["video_template"]
        ),
        "life_moment": life_moment,
        "hook": hook,
        "engagement_prompt": engagement_prompt,
        "soft_promotion": soft_promotion,
    }


def build_creative_brief_preamble(slot: str, resolved_brief: Optional[Any] = None) -> str:
    """Build the structured "Creative Brief" text block and log the
    resolved selections for verification.

    This does not replace build_weekly_rhythm_preamble() or any existing
    prompt content; it is an additional block prepended before the
    existing Gemini prompt.
    """
    brief = build_creative_brief_data(slot, resolved_brief=resolved_brief)
    if brief is None:
        return ""

    life_moment = brief.get("life_moment") or {}
    hook = brief.get("hook") or {}
    engagement_prompt = brief.get("engagement_prompt")
    soft_promotion = brief.get("soft_promotion")

    print("Creative Brief:")
    print(brief.get("weekly_theme", "").title())
    print(life_moment.get("moment", ""))
    print(hook.get("name", ""))

    lines = [
        "",
        "Creative Brief",
        "",
        "Weekly Theme:",
        brief.get("weekly_theme", ""),
        "",
        "Content Type:",
        brief.get("content_type", "").replace("_", " ").title(),
        "",
        "Video Template:",
        brief.get("video_template", "").replace("_", " ").title(),
        "",
        "Target Duration:",
        "{0} seconds".format(brief.get("target_duration", "")),
        "",
        "Marketing Enabled:",
        str(brief.get("marketing_enabled", False)).lower(),
        "",
        "Expected Long-Form Type:",
        brief.get("expected_long_form_type", "none"),
        "",
        "Engagement Prompt Enabled:",
        str(brief.get("engagement_prompt_enabled", False)).lower(),
        "",
        "Engagement Prompt Type:",
        brief.get("engagement_prompt_type", ""),
        "",
        "Life Moment:",
        life_moment.get("moment", ""),
        "",
        "Hook Style:",
        hook.get("name", ""),
        "",
        "Objective:",
        brief.get("objective", ""),
        "",
        "Tone:",
        brief.get("tone", ""),
        "",
        "Emotional Goal:",
        brief.get("emotional_goal", ""),
    ]

    if engagement_prompt:
        lines += [
            "",
            "Engagement Prompt:",
            engagement_prompt.get("prompt", ""),
            "",
            "Engagement Line Requirement:",
            "Use the resolved Engagement Prompt above verbatim as engagement_line. Do not replace it with a different question or invitation.",
        ]

    if soft_promotion:
        lines += [
            "",
            "Soft Promotion:",
            soft_promotion.get("text", ""),
        ]

    format_guidance = brief.get("format_guidance", "")
    if format_guidance:
        lines += [
            "",
            format_guidance.strip(),
        ]

    lines.append("")
    return "\n".join(lines)


def _profile_list(values: Any) -> str:
    normalized = [str(value).strip() for value in (values or []) if str(value).strip()]
    return ", ".join(normalized) if normalized else "none"


def build_resolved_profile_guidance(resolved_brief: Optional[Any]) -> str:
    """Render resolver-owned writing guidance without selecting any profile."""
    if resolved_brief is None:
        return ""

    hook_profile = resolved_content_brief.get_hook_profile_definition(
        resolved_brief.hook_profile_id,
        creative_policy_version=resolved_brief.creative_policy_version,
    )
    writing_profile = resolved_content_brief.get_writing_profile_definition(
        resolved_brief.voice_profile_id,
        creative_policy_version=resolved_brief.creative_policy_version,
    )
    body_profile = resolved_content_brief.get_body_profile_definition(
        getattr(resolved_brief, "body_profile_id", "current_default"),
        creative_policy_version=resolved_brief.creative_policy_version,
    )
    body_guidance_enabled = body_profile.get("inject_guidance", True)
    if (
        not hook_profile.get("inject_guidance", True)
        and not writing_profile.get("inject_guidance", True)
        and not body_guidance_enabled
    ):
        return ""

    word_range = hook_profile.get("preferred_word_range") or []
    preferred_words = (
        f"{word_range[0]} to {word_range[1]} words"
        if len(word_range) == 2
        else "preserve the existing hook length guidance"
    )
    reading_seconds = hook_profile.get("preferred_reading_seconds")
    preferred_reading = (
        f"approximately {float(reading_seconds):g} seconds"
        if isinstance(reading_seconds, (int, float))
        else "preserve the existing reading-time guidance"
    )

    profile_scope = (
        "Apply the Hook Profile only to opening_hook. Apply the Writing Profile "
        "to how opening_hook, bridge_line, script_segments, and closing_line sound. "
        "Apply the Body Profile to what bridge_line, script_segments, reassurance, "
        "and closing_line emphasize. Do not use these profiles to change platform "
        "captions, CTA language, hashtags, engagement prompts, publishing fields, "
        "or output schema."
        if body_guidance_enabled
        else (
            "Apply the Hook Profile only to opening_hook. Apply the\n"
            "Writing Profile only to opening_hook, bridge_line, script_segments, and\n"
            "closing_line. Do not use either profile to change platform captions, CTA\n"
            "language, engagement prompts, publishing fields, or output schema."
        )
    )
    body_guidance = ""
    if body_guidance_enabled:
        body_guidance = """

Resolved Body Profile:
- ID: {body_id}
- Recognition focus: {recognition_focus}
- Petition focus: {petition_focus}
- Reassurance focus: {reassurance_focus}
- Emotional movement: {emotional_movement}
- Closing focus: {closing_focus}
- Avoid: {body_avoid}
- Use the existing universal emotional arc flexibly; this profile refines its
  emphasis rather than replacing it.
- Preserve natural variety. Do not turn these stages into a rigid or repeated
  prayer template.
""".format(
            body_id=body_profile["id"],
            recognition_focus=_profile_list(body_profile.get("recognition_focus")),
            petition_focus=_profile_list(body_profile.get("petition_focus")),
            reassurance_focus=_profile_list(body_profile.get("reassurance_focus")),
            emotional_movement=_profile_list(body_profile.get("emotional_movement")),
            closing_focus=_profile_list(body_profile.get("closing_focus")),
            body_avoid=_profile_list(body_profile.get("avoid")),
        )

    return """
Resolved Creative Profile Guidance

These profile IDs were already selected by ResolvedContentBrief. Consume
their guidance exactly as written. Do not choose, replace, or infer a
different profile. {profile_scope}

Resolved Hook Profile:
- ID: {hook_id}
- Emotional tone: {hook_tone}
- Opening style: {opening_style}
- Preferred length: {preferred_words}
- Preferred reading time: {preferred_reading}
- Behavioral guidance: {hook_guidance}
- Preferred verbs: {preferred_verbs}
- Avoid: {hook_avoid}
- Curiosity level: {curiosity_level}
- Urgency level: {urgency_level}
- First person allowed: {allow_first_person}
- Rhetorical questions: {rhetorical_questions}

Resolved Writing Profile:
- ID: {writing_id}
- Purpose: content writing only; never use this profile to control TTS
- Sentence rhythm: {sentence_rhythm}
- Diction: {diction}
- Emotional tone: {writing_tone}
- Transitions: {transitions}
- Behavioral guidance: {writing_guidance}
- Avoid: {writing_avoid}
{body_guidance}""".format(
        profile_scope=profile_scope,
        hook_id=hook_profile["id"],
        hook_tone=hook_profile.get("emotional_tone", "preserve current behavior"),
        opening_style=hook_profile.get("opening_style", "preserve current behavior"),
        preferred_words=preferred_words,
        preferred_reading=preferred_reading,
        hook_guidance=hook_profile.get("writing_guidance", "Preserve current hook behavior."),
        preferred_verbs=_profile_list(hook_profile.get("preferred_verbs")),
        hook_avoid=_profile_list(hook_profile.get("avoid")),
        curiosity_level=hook_profile.get("curiosity_level", "preserve current behavior"),
        urgency_level=hook_profile.get("urgency_level", "preserve current behavior"),
        allow_first_person=str(hook_profile.get("allow_first_person", "preserve current behavior")).lower(),
        rhetorical_questions=hook_profile.get("rhetorical_questions", "preserve current behavior"),
        writing_id=writing_profile["id"],
        sentence_rhythm=writing_profile.get("sentence_rhythm", "preserve current behavior"),
        diction=writing_profile.get("diction", "preserve current behavior"),
        writing_tone=writing_profile.get("emotional_tone", "preserve current behavior"),
        transitions=writing_profile.get("transitions", "preserve current behavior"),
        writing_guidance=writing_profile.get(
            "writing_guidance", "Preserve current natural conversational writing behavior."
        ),
        writing_avoid=_profile_list(writing_profile.get("avoid")),
        body_guidance=body_guidance,
    )


def validate_opening_hook(
    opening_hook: str,
    hook_profile: Dict[str, Any],
) -> list[str]:
    """Return advisory hook warnings without rewriting or rejecting copy."""
    text = str(opening_hook or "").strip()
    if not text:
        return ["hook_blank"]

    warnings = []
    words = text.split()
    word_count = len(words)
    preferred_range = hook_profile.get("preferred_word_range") or []
    if len(preferred_range) == 2:
        minimum_words, maximum_words = (int(value) for value in preferred_range)
        if word_count < minimum_words:
            warnings.append("hook_below_preferred_word_range")
        if word_count > maximum_words:
            warnings.append("hook_exceeds_preferred_word_range")
        if word_count > max(10, maximum_words + 3):
            warnings.append("hook_excessively_long")

    if text[-1] not in ".?!…":
        warnings.append("hook_incomplete_thought")

    preferred_seconds = hook_profile.get("preferred_reading_seconds")
    if isinstance(preferred_seconds, (int, float)):
        estimated_seconds = word_count / 3.0
        if estimated_seconds > float(preferred_seconds) + 0.1:
            warnings.append("hook_exceeds_preferred_reading_duration")
    return warnings


def log_resolved_hook_warnings(
    ad_copy: Dict[str, Any],
    resolved_brief: Optional[Any],
) -> list[str]:
    if resolved_brief is None or resolved_brief.long_form_type == "none":
        return []
    profile = resolved_content_brief.get_hook_profile_definition(
        resolved_brief.hook_profile_id,
        creative_policy_version=resolved_brief.creative_policy_version,
    )
    warnings = validate_opening_hook(ad_copy.get("opening_hook", ""), profile)
    for warning in warnings:
        print(f"Opening hook validation warning: {warning}")
    return warnings


def validate_body_profile_output(
    ad_copy: Dict[str, Any],
    resolved_brief: Optional[Any],
) -> list[str]:
    """Return advisory category-body diagnostics without rewriting copy."""
    if resolved_brief is None or resolved_brief.long_form_type == "none":
        return []

    profile = resolved_content_brief.get_body_profile_definition(
        getattr(resolved_brief, "body_profile_id", "current_default"),
        creative_policy_version=resolved_brief.creative_policy_version,
    )
    if not profile.get("inject_guidance", True):
        return []

    body_units = [str(ad_copy.get("bridge_line", "")).strip()]
    raw_segments = ad_copy.get("script_segments", [])
    if isinstance(raw_segments, list):
        body_units.extend(str(segment).strip() for segment in raw_segments)
    body_units.append(str(ad_copy.get("closing_line", "")).strip())
    body_units = [unit for unit in body_units if unit]
    if not body_units:
        return ["body_blank"]

    body_text = "\n".join(body_units)
    normalized_body = " ".join(
        re.sub(r"[^a-z0-9]+", " ", body_text.lower()).split()
    )
    warnings: list[str] = []

    diagnostic_terms = [
        " ".join(re.sub(r"[^a-z0-9]+", " ", str(term).lower()).split())
        for term in profile.get("diagnostic_terms", [])
    ]
    if diagnostic_terms and not any(term in normalized_body for term in diagnostic_terms):
        warnings.append("body_may_be_overly_generic_for_category")

    normalized_hook = " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            str(ad_copy.get("opening_hook", "")).lower(),
        ).split()
    )
    if normalized_hook and normalized_hook in normalized_body:
        warnings.append("body_duplicates_opening_hook")

    normalized_sentences = [
        " ".join(re.sub(r"[^a-z0-9]+", " ", sentence.lower()).split())
        for sentence in re.split(r"(?<=[.!?])\s+", body_text)
    ]
    substantial_sentences = [
        sentence for sentence in normalized_sentences if len(sentence.split()) >= 4
    ]
    if len(substantial_sentences) != len(set(substantial_sentences)):
        warnings.append("body_repeats_petition")

    unsupported_promise_patterns = (
        r"\bguaranteed\b",
        r"\bimmediate(?:ly)? relief\b",
        r"\bnothing bad will happen\b",
        r"\byou will be healed\b",
        r"\byour anxiety will (?:leave|disappear|be gone)\b",
    )
    if any(re.search(pattern, normalized_body) for pattern in unsupported_promise_patterns):
        warnings.append("body_contains_unsupported_promise")

    avoided_phrases = [
        " ".join(re.sub(r"[^a-z0-9]+", " ", str(term).lower()).split())
        for term in profile.get("avoid", [])
    ]
    if any(term and term in normalized_body for term in avoided_phrases):
        warnings.append("body_contains_avoided_category_language")

    inappropriate_time_terms = [
        " ".join(re.sub(r"[^a-z0-9]+", " ", str(term).lower()).split())
        for term in profile.get("inappropriate_time_terms", [])
    ]
    if any(term and term in normalized_body for term in inappropriate_time_terms):
        warnings.append("body_contains_inappropriate_time_language")

    if (
        resolved_brief.prayer_category_id == "bible_verse"
        and not any(term in normalized_body for term in diagnostic_terms)
        and not re.search(r"\b(?:[1-3]\s+)?[a-z]+\s+\d+(?::\d+)?\b", body_text.lower())
    ):
        warnings.append("body_scripture_relevance_unclear")

    return warnings


def log_body_profile_warnings(
    ad_copy: Dict[str, Any],
    resolved_brief: Optional[Any],
) -> list[str]:
    warnings = validate_body_profile_output(ad_copy, resolved_brief)
    for warning in warnings:
        print(f"Prayer body validation warning: {warning}")
    return warnings


def build_prompt(
    *,
    post_type: str,
    selection: Dict[str, Any],
    slot: str,
    tracked_url: str,
    resolved_brief: Optional[Any] = None,
) -> str:
    """Build the full Gemini prompt.

    Creative decisions (what the ad emotionally says and why) now come
    ONLY from: Weekly Rhythm, Creative Brief (Life Moment, Hook Style,
    Tone, Objective, Emotional Goal), Brand Brain, and Seasonal Context.

    Legacy Campaign/Persona/Formula/Marketing-Hook/Marketing-CTA fields on
    `selection` are intentionally NOT read here anymore -- they no longer
    steer Gemini generation. They are preserved elsewhere in `selection`
    unchanged (campaign_engine.py, prayonit_social.py, history_store.py,
    build_platform_captions()'s hashtag selection, and background
    matching) purely for analytics, QA, reporting, and hashtag/background
    selection, none of which this function touches.
    """
    seasonal_context = selection.get("seasonal_context")
    spiritual_action = selection.get("spiritual_action", "Give today's burdens to God in prayer.")

    seasonal_block = f"\nSeasonal context to weave in naturally, if relevant: {seasonal_context}\n" if seasonal_context else ""

    brand_preamble = build_brand_brain_preamble(config.BRAND_RULES)
    weekly_rhythm_preamble = build_weekly_rhythm_preamble(
        slot, resolved_brief=resolved_brief
    )
    creative_brief_preamble = build_creative_brief_preamble(slot, resolved_brief=resolved_brief)
    profile_guidance = build_resolved_profile_guidance(resolved_brief)

    # ---- Emotional flow: Life Moment -> Recognition Hook -> Comfort ->
    # Hope -> Invitation -> Brand Rules -> App Features -> Constraints ----
    return f"""
{creative_brief_preamble}
{weekly_rhythm_preamble}{profile_guidance}
The Life Moment, Hook Style, Objective, Tone, and Emotional Goal above are
the single source of truth for this ad's emotional content. Do not invent
a different pain point, hook, or angle -- build directly on what is given
above.

The primary goal is NOT to advertise the app. The primary goal is to help
someone feel understood. If mentioning the app improves the message, do so
naturally. If it does not, allow the invitation to appear only near the
end.

Existing short-form fields still power the current Feed and Story outputs.
The optional long-form fields below are for future long video templates
only. Keep both layers aligned to the same Life Moment, Hook Style,
Objective, Tone, Emotional Goal, content type, and target duration. Do
not let the long-form script suddenly introduce a different topic.

Write toward this emotional arc, in this order: first help the reader feel
recognized in the Life Moment above (using the given Hook Style). Then
offer comfort. Then offer hope. Only after comfort and hope have been
established, offer a gentle invitation to pray together.

Comfort and hope should offer a short, concrete spiritual action (praying
to God, giving/bringing/laying something before God, seeking God's
guidance, thanking God, or similar) that speaks directly to the Life
Moment above. Write this spiritual action yourself so it stays specific to
the Life Moment — do not drift onto a different topic. Use the line below
only as a tone/style example, not as a script to copy if it does not fit
the Life Moment above:
"{spiritual_action}"
{seasonal_block}{build_time_guidance(slot)}
{brand_preamble}
You are the direct-response social media copywriter for Prayonit, a Christian
mobile app that helps people choose how they feel, receive relevant Scripture
and a devotion, share what is on their heart, and receive a personalized prayer.
{PRODUCT_FLOW_DESCRIPTION}
Do not say prayers are "crafted by a human." Do not imply divine authority.
Do not say the app knows God's will. Do not imply God is praying to the
user, that God is speaking through the app, that Prayonit speaks on God's
behalf, or that the AI knows God's will. Never promise guaranteed healing,
sleep, peace, or relief.

Create ONE {post_type} acquisition ad intended to invite the reader into a
moment of prayer with God, following this exact message hierarchy:
Pain or emotional need -> Spiritual action -> How Prayonit helps -> Invitation
to pray together -> Visit prayonit.app (or "Link in bio" on Instagram).

This is advertising, not a sermon and not a verse-of-the-day post.

A real destination link will be appended automatically after you respond, so:
- Do NOT include any URL, link, or web address in facebook_caption
  or instagram_caption.
- Do NOT invent, guess, shorten, rewrite, or substitute any domain or URL
  (for example, do not output "prayonit.com" or any other made-up link).
- Prayonit does not lead with a free trial or a direct "download the app"
  instruction. Never mention a 14-day trial, "start your free trial," "try
  Prayonit free," "download Prayonit," "install the app," or "get the app"
  anywhere in this ad — those phrases are strictly forbidden. Prayonit
  invites people into a moment with God and points them to the website
  first (an app download or trial may only be offered later, on the
  website itself). If you need to reference how someone gets started, say
  things like "come pray with me" or "join me in prayer" — never "download
  Prayonit," "install Prayonit," "get the app," or "download the app." The
  real link/CTA is inserted by the system, not by you.

Requirements:
- brand_header: 1 to 3 short words, normally "PRAYONIT".
- pain_headline: powerful scroll-stopping question or statement naming the
  pain/emotional need, maximum 9 words, short enough for mobile.
- spiritual_action: a short spiritual action sentence written specifically
  for the Life Moment above (not copied from any unrelated example). Must
  still describe the user praying to God (giving/bringing/laying
  something before God, seeking God's guidance, thanking God, or similar)
  — never God acting toward the user, and never a new theological claim.
- app_benefit: must directly answer pain_headline. Always include "guided"
  or "personalized prayer" and a connection to the user's current mood,
  feelings, worries, gratitude, or situation. Example matching pain_headline
  "Need rest tonight?": "Get a guided, personalized prayer to help you end
  your day in peace."
- download_cta: must be exactly "{config.PRIMARY_CTA}" (Prayonit invites
  people into a moment with God rather than leading with a download
  instruction; this is an invitation, not a store-download button label).
- trial_support: must be exactly "Start your prayer at\\nprayonit.app" (this
  field name is kept for backward compatibility only; its value is now
  website-first destination text, not a free-trial pitch). Never mention a
  free trial, download, or install instruction here.
- facebook_caption: 35 to 70 words, natural and persuasive, following the
  pain -> spiritual action -> benefit -> invitation flow, ending with an
  invitation to pray (for example "come pray with me"), never a download
  or free-trial instruction. No hashtags. Never mention a free trial,
  download, or app-install instruction anywhere in this caption.
- instagram_caption: shorter and punchier than facebook_caption, 20 to 45
  words, no hashtags (hashtags are added separately). Never mention a free
  trial, download, or app-install instruction anywhere in this caption.
- story_headline: very short, maximum 6 words, for a vertical Story image.
- story_spiritual_action: very short version of spiritual_action, maximum 8 words.
- story_app_benefit: very short version of app_benefit, maximum 12 words,
  readable in at most three lines.
- story_download_cta: must be exactly "{config.PRIMARY_CTA}".
- story_trial_support: compact website-first destination phrase, maximum 6
  words, must reference prayonit.app or "link in bio" — never a free-trial
  or download phrase (for example: "Start your prayer at prayonit.app.").
- long_form_type: optional. Must be one of prayer, devotional,
  encouragement, or none. Use the Expected Long-Form Type in the Creative
  Brief unless the content format clearly requires none.
- opening_hook: optional. A short recognition hook, approximately 3 to 10
  words, complete thought. It should align with pain_headline but does
  not need to be identical.
- bridge_line: optional. One natural sentence connecting the hook to the
  prayer or devotional without changing topics.
- script_segments: optional. JSON array of 2 to 5 complete text segments
  for long-form formats, or [] for short formats. Never leave a sentence
  truncated. Keep the segments in logical order.
- closing_line: optional. A natural ending such as "Amen." for prayer
  content, or a concise takeaway for devotional content.
- engagement_line: optional. One soft engagement invitation only when
  Engagement Prompt Enabled is true. Leave it empty when engagement is
  not enabled.
- estimated_spoken_seconds: optional. Integer between 8 and 35. Match the
  target duration closely.
- For prayer long-form output: long_form_type must be prayer. Write a real
  complete prayer specific to the Life Moment. Keep script_segments to
  approximately 55 to 90 spoken words total and target about 25 to 35
  seconds. Do not include app marketing inside the prayer. opening_hook
  and bridge_line are not part of the prayer word count. closing_line
  should normally be "Amen."
- For devotional long-form output: long_form_type must be devotional.
  Write a meaningful reflection with recognition, comfort, hope, and one
  takeaway. Keep script_segments to approximately 45 to 80 spoken words
  total. Avoid hard app promotion. closing_line should be a concise
  takeaway, not necessarily "Amen."
- For encouragement long-form output: long_form_type must be encouragement.
  Keep script_segments to approximately 40 to 70 words total and focus on
  hope, reassurance, and emotional resolution.
- For short_promo and short_engagement formats: long_form_type must be
  none, script_segments must be [], and short-form behavior must remain
  the focus.
- Do not make unverifiable claims.
- Do not promise divine outcomes.
- Do not say the app replaces God, church, clergy, therapy, or medical care.
- Do not use fake statistics, fake testimonials, or fake user counts.
- Avoid repeating the exact phrase "Scripture-inspired prayers" every time.
- Output valid JSON only with keys: brand_header, pain_headline,
  spiritual_action, app_benefit, download_cta, trial_support,
  facebook_caption, instagram_caption, story_headline,
  story_spiritual_action, story_app_benefit, story_download_cta,
  story_trial_support, long_form_type, opening_hook, bridge_line,
  script_segments, closing_line, engagement_line,
  estimated_spoken_seconds.
"""



REQUIRED_AD_COPY_KEYS = (
    "brand_header",
    "pain_headline",
    "spiritual_action",
    "app_benefit",
    "download_cta",
    "trial_support",
    "facebook_caption",
    "instagram_caption",
    "story_headline",
    "story_spiritual_action",
    "story_app_benefit",
    "story_download_cta",
    "story_trial_support",
)
_LEGACY_REQUIRED_AD_COPY_KEYS = REQUIRED_AD_COPY_KEYS + ("threads_caption",)

# Text fields where caption-level enforcement (forbidden phrases, unknown
# feature claims) should be applied. "download_cta" and
# "story_download_cta" are handled separately (enforce_download_cta())
# since they must exactly equal "DOWNLOAD PRAYONIT".
_CAPTION_ENFORCEMENT_FIELDS = (
    "brand_header",
    "pain_headline",
    "spiritual_action",
    "app_benefit",
    "facebook_caption",
    "instagram_caption",
    "story_headline",
    "story_spiritual_action",
    "story_app_benefit",
)

# Fields that must never contain free-trial wording omitting the 14-day
# duration (checked with enforce_trial_duration after other enforcement).
_TRIAL_DURATION_ENFORCED_FIELDS = (
    "trial_support",
    "facebook_caption",
    "instagram_caption",
)

# Phrases describing features Prayonit does not have. If Gemini mentions one
# of these despite instructions not to invent features, the sentence
# containing it is removed. This list is intentionally conservative; any
# phrase that also appears in core_features is never treated as forbidden.
KNOWN_NONEXISTENT_FEATURE_PHRASES = [
    "live video chat",
    "video chat with a pastor",
    "video call with a pastor",
    "live pastor",
    "community forum",
    "social feed",
    "live streaming",
    "group prayer call",
    "in-app purchases",
    "live counselor",
    "licensed counselor",
    "therapist chat",
    "meditation timer",
    "sleep sounds",
    "worship music library",
    "bible study groups",
    "chat with a real pastor",
]


def _contains_14_day_duration(text: str) -> bool:
    lower = text.lower()
    return "14-day" in lower or "14 day" in lower


def _mentions_trial_or_free(text: str) -> bool:
    lower = text.lower()
    return "trial" in lower or "free" in lower


# Explicit forbidden trial-first / download-first phrases. Prayonit's
# funnel is now invitation-first ("Come pray with me") -> prayonit.app ->
# an app download or trial may only be offered later, on the website
# itself -- never as the lead of a social caption. These overlap with
# brand_rules['never_say'] but are kept here too so functions that don't
# take the generic never_say -> preferred_cta substitution path (e.g.
# story_cta, trial_support) are still protected.
TRIAL_WORDING_VIOLATIONS = [
    "try it free today",
    "download for free",
    "free app",
    "try prayonit free",
    "100% free",
    "always free",
    "unlimited free",
    "free forever",
    "14-day free trial",
    "14 day free trial",
    "start your free trial",
    "download prayonit",
    "install prayonit",
    "install the app",
    "get the app",
]


def enforce_trial_duration(text: str, brand_rules: Dict[str, Any]) -> str:
    """Ensure a caption never contains trial-first or download-first
    wording. Prayonit's funnel is now invitation-first ("Come pray with
    me") -> prayonit.app -> an app download or trial may only be offered
    later, on the website itself -- so no caption should lead with, or
    contain at all, trial or direct-download language. If any forbidden
    phrase is found, the entire field is replaced with the brand's
    preferred (invitation-first) CTA.
    """
    preferred_cta = brand_rules.get("preferred_cta", "Come pray with me.")
    lower = text.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return preferred_cta
    return text


def enforce_story_cta_trial_wording(story_cta: str, brand_rules: Dict[str, Any]) -> str:
    """Ensure story_cta never contains trial-first or download-first
    wording, replacing it with the compact, website-first destination
    phrase instead (e.g. "Start your prayer at prayonit.app").
    """
    compact_phrase = brand_rules.get("compact_trial_phrase", "Start your prayer at prayonit.app")
    lower = story_cta.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return compact_phrase
    return story_cta


def enforce_cta(cta: str, brand_rules: Dict[str, Any]) -> str:
    """Return cta unchanged if it exactly matches an approved CTA, otherwise
    replace it with the brand's preferred CTA."""
    approved_ctas = brand_rules.get("approved_ctas", [])
    preferred_cta = brand_rules.get("preferred_cta", "Start your 14-day free trial.")
    if cta.strip() in approved_ctas:
        return cta.strip()
    return preferred_cta


# ---------- Creative Engine v2 enforcement ----------

# Phase 1B: locked invitation-first CTA, loaded from brand configuration
# (brands/<brand>/brand.yaml -> copy.primary_cta). PRIMARY_DOWNLOAD_CTA is
# kept as a backward-compatible alias name for any other call sites.
PRIMARY_DOWNLOAD_CTA = config.PRIMARY_CTA


def enforce_download_cta(_text: str) -> str:
    """The primary visual CTA button must always read exactly the brand's
    approved invitation-first CTA (config.PRIMARY_CTA, e.g. "COME PRAY WITH
    ME") for both Feed and Story, since Prayonit invites people into a
    moment with God rather than leading with a direct download instruction.
    """
    return PRIMARY_DOWNLOAD_CTA


def enforce_trial_support(text: str, brand_rules: Dict[str, Any], *, compact: bool = False) -> str:
    """Ensure trial_support/story_trial_support contain website-first
    destination text ("Start your prayer at\\nprayonit.app") rather than
    trial-first or download-first language.

    These field names ("trial_support" / "story_trial_support") are kept
    for backward compatibility only (per task scope, not broadly renamed);
    their content is now the website destination, not a free-trial pitch.
    """
    fallback = config.VISUAL_DESTINATION_TEXT
    text = (text or "").strip()
    if not text:
        return fallback
    lower = text.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return fallback
    if _mentions_trial_or_free(text):
        return fallback
    return text


_MOOD_KEYWORDS = (
    "mood",
    "feel",
    "feeling",
    "feelings",
    "worry",
    "worries",
    "worried",
    "anxious",
    "anxiety",
    "grateful",
    "gratitude",
    "situation",
    "heart",
    "burden",
    "stress",
    "peace",
    "rest",
    "hope",
)


def app_benefit_matches_pain(app_benefit: str) -> bool:
    """Return True if app_benefit mentions a guided/personalized prayer and
    connects it to the user's mood, feelings, worries, gratitude, or
    situation (a generic, non-connected benefit is rejected).
    """
    lower = (app_benefit or "").lower()
    mentions_prayer = "guided" in lower or "personalized prayer" in lower or "personalized, guided prayer" in lower
    mentions_mood = any(keyword in lower for keyword in _MOOD_KEYWORDS)
    return mentions_prayer and mentions_mood


def enforce_app_benefit_matches_pain(app_benefit: str) -> str:
    """If app_benefit does not clearly answer the pain headline (missing a
    guided/personalized-prayer + mood/feeling connection), replace it with
    the brand's approved fallback benefit sentence.
    """
    if app_benefit_matches_pain(app_benefit):
        return app_benefit.strip()
    return "Get a guided, personalized prayer based on your mood right now."


def enforce_headline_quality(headline: str, *, max_chars: int = 45) -> str:
    """Deterministic quality gate for pain/story headlines."""
    report = creative_engine_v3.validate_headline_quality(headline, max_chars=max_chars)
    text = report["shortened"] or (headline or "").strip()
    if text.count("?") > 1:
        first = text.split("?", 1)[0].strip()
        text = f"{first}?" if first else "Need Prayer Support Today?"
    norm = creative_engine_v3.normalize_text(text)
    if "is a prayer app for you" in norm:
        return "Struggling to Pray Today?"
    if not text:
        return "Need Prayer Support Today?"
    return text.strip()


# Wording that would imply God acts toward the user, that the app speaks
# for God, or that guarantees a spiritual/emotional outcome. Any sentence
# containing one of these is removed from spiritual_action/app_benefit
# fields; if nothing remains, an approved fallback is used instead.
FORBIDDEN_THEOLOGY_PHRASES = [
    "god is praying",
    "god is speaking through",
    "god speaks through the app",
    "let god meet you with a personalized prayer",
    "receive god's message",
    "hear what god wants to tell you",
    "prayonit speaks for god",
    "prayonit speaks on god's behalf",
    "guaranteed healing",
    "guaranteed peace",
    "guaranteed sleep",
    "guaranteed relief",
    "guarantees peace",
    "guarantees healing",
]


def enforce_theology_safety(text: str, fallback: str) -> str:
    """Remove any sentence containing a forbidden theological claim. If the
    entire field is emptied as a result, use the provided approved fallback
    sentence instead.
    """
    cleaned = text
    for phrase in FORBIDDEN_THEOLOGY_PHRASES:
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        if pattern.search(cleaned):
            cleaned = _remove_sentences_matching(cleaned, pattern)
    cleaned = cleaned.strip()
    return cleaned if cleaned else fallback


def enforce_forbidden_phrases(text: str, brand_rules: Dict[str, Any]) -> str:
    """Replace any brand_rules 'never_say' phrase with the preferred CTA."""
    preferred_cta = brand_rules.get("preferred_cta", "Start your 14-day free trial.")
    for phrase in brand_rules.get("never_say", []):
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        text = pattern.sub(preferred_cta, text)
    return text


def _remove_sentences_matching(text: str, pattern: "re.Pattern") -> str:
    """Remove any sentence (split on ./!/?) that matches pattern."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not pattern.search(s)]
    return " ".join(s.strip() for s in kept).strip()


def enforce_feature_claims(text: str, brand_rules: Dict[str, Any]) -> str:
    """Remove any sentence referencing a feature that does not exist.

    Only phrases in KNOWN_NONEXISTENT_FEATURE_PHRASES are checked, and any
    phrase also present in brand_rules['core_features'] is skipped (treated
    as a real, allowed feature).
    """
    core_features_lower = {f.lower() for f in brand_rules.get("core_features", [])}
    for phrase in KNOWN_NONEXISTENT_FEATURE_PHRASES:
        if phrase.lower() in core_features_lower:
            continue
        pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
        if pattern.search(text):
            text = _remove_sentences_matching(text, pattern)
    return text


def apply_brand_enforcement(ad_copy: Dict[str, str], brand_rules: Dict[str, Any]) -> Dict[str, str]:
    """Apply all Brand Brain enforcement rules to a raw ad_copy dict:
    CTA enforcement, forbidden-phrase replacement, feature-claim removal,
    and free-trial-duration enforcement (main cta, story_cta, and every
    feed caption).
    """
    enforced = dict(ad_copy)

    if "cta" in enforced:
        enforced["cta"] = enforce_cta(enforced["cta"], brand_rules)

    for field in _CAPTION_ENFORCEMENT_FIELDS:
        if field in enforced:
            value = enforce_forbidden_phrases(enforced[field], brand_rules)
            value = enforce_feature_claims(value, brand_rules)
            enforced[field] = value.strip()

    if "story_cta" in enforced:
        enforced["story_cta"] = enforce_story_cta_trial_wording(
            enforced["story_cta"].strip(), brand_rules
        )

    for field in _TRIAL_DURATION_ENFORCED_FIELDS:
        if field in enforced:
            enforced[field] = enforce_trial_duration(enforced[field], brand_rules).strip()

    # ---------- Creative Engine v2 fields ----------
    if "spiritual_action" in enforced:
        enforced["spiritual_action"] = enforce_theology_safety(
            enforced["spiritual_action"], "Give today's burdens to God in prayer."
        )
    if "story_spiritual_action" in enforced:
        enforced["story_spiritual_action"] = enforce_theology_safety(
            enforced["story_spiritual_action"], "Bring it to God in prayer."
        )

    if "app_benefit" in enforced:
        enforced["app_benefit"] = enforce_theology_safety(
            enforced["app_benefit"],
            "Get a guided, personalized prayer based on your mood right now.",
        )
        # Ensure forbidden benefit variants are replaced with the locked
        # canonical phrase for consistency and legal safety.
        enforced["app_benefit"] = enforce_locked_benefit_phrase(enforced["app_benefit"], LOCKED_APP_BENEFIT)
        enforced["app_benefit"] = enforce_app_benefit_matches_pain(enforced["app_benefit"])
    if "story_app_benefit" in enforced:
        enforced["story_app_benefit"] = enforce_theology_safety(
            enforced["story_app_benefit"],
            "Get a guided, personalized prayer based on your mood right now.",
        )
        enforced["story_app_benefit"] = enforce_locked_benefit_phrase(enforced["story_app_benefit"], LOCKED_STORY_APP_BENEFIT)
        enforced["story_app_benefit"] = LOCKED_STORY_APP_BENEFIT

    if "pain_headline" in enforced:
        enforced["pain_headline"] = enforce_headline_quality(enforced["pain_headline"], max_chars=45)
    if "story_headline" in enforced:
        enforced["story_headline"] = enforce_headline_quality(enforced["story_headline"], max_chars=45)

    if "download_cta" in enforced:
        enforced["download_cta"] = enforce_download_cta(enforced["download_cta"])
    if "story_download_cta" in enforced:
        enforced["story_download_cta"] = enforce_download_cta(enforced["story_download_cta"])

    if "trial_support" in enforced:
        enforced["trial_support"] = enforce_trial_support(enforced["trial_support"], brand_rules)
    if "story_trial_support" in enforced:
        enforced["story_trial_support"] = enforce_trial_support(
            enforced["story_trial_support"], brand_rules, compact=True
        )

    return enforced


def parse_ad_copy_response(
    raw: str,
    *,
    slot: str,
    resolved_brief: Optional[Any] = None,
) -> Dict[str, Any]:
    """Parse Gemini JSON and normalize optional long-form fields."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"Gemini did not return valid JSON:\n{raw}")
        data = json.loads(match.group(0))

    for key in REQUIRED_AD_COPY_KEYS:
        if not str(data.get(key, "")).strip():
            raise RuntimeError(f"Gemini response is missing '{key}': {data}")

    ad_copy: Dict[str, Any] = {key: str(data[key]).strip() for key in REQUIRED_AD_COPY_KEYS}
    if "tiktok_caption" in data and str(data.get("tiktok_caption", "")).strip():
        ad_copy["tiktok_caption"] = str(data["tiktok_caption"]).strip()
    if "threads_caption" in data and str(data.get("threads_caption", "")).strip():
        ad_copy["threads_caption"] = str(data["threads_caption"]).strip()

    if resolved_brief is not None:
        todays_content = {"content_type": resolved_brief.content_type}
        presentation = {
            "video_template": resolved_brief.video_template,
            "duration_seconds": resolved_brief.duration_seconds,
            "engagement_prompt_enabled": bool(resolved_brief.engagement_prompt),
        }
    else:
        todays_content = content_engine.get_todays_content(slot=slot)
        presentation = content_engine.get_presentation_config(todays_content)
    ad_copy.update(
        normalize_long_form_fields(
            data,
            content_type=todays_content.get("content_type", ""),
            video_template=presentation["video_template"],
            duration_seconds=presentation["duration_seconds"],
            engagement_prompt_enabled=presentation["engagement_prompt_enabled"],
        )
    )
    return ad_copy


def enforce_resolved_engagement_line(
    ad_copy: Dict[str, Any], resolved_brief: Optional[Any]
) -> Dict[str, Any]:
    """Keep Gemini's optional line identical to the canonical brief selection."""
    if resolved_brief is None or not resolved_brief.engagement_prompt:
        return ad_copy
    enforced = dict(ad_copy)
    expected = resolved_brief.engagement_prompt
    actual = str(enforced.get("engagement_line", "")).strip()
    if actual != expected:
        print("Gemini engagement_line corrected to the resolved engagement prompt.")
        enforced["engagement_line"] = expected
    return enforced


def generate_ad_copy(
    *,
    post_type: str,
    selection: Dict[str, Any],
    slot: str,
    tracked_url: str,
    resolved_brief: Optional[Any] = None,
) -> Dict[str, Any]:
    prompt = build_prompt(
        post_type=post_type,
        selection=selection,
        slot=slot,
        tracked_url=tracked_url,
        resolved_brief=resolved_brief,
    )

    # TEMPORARY DEBUG LOGGING: verify the Creative Brief is actually part
    # of the prompt Gemini receives. Safe to remove once verified.
    print("======== GEMINI PROMPT ========")
    print(prompt[:1000])
    print("===============================")

    response = None
    attempts = _get_content_model_attempt_plan()
    max_attempts = len(attempts)
    for attempt, (model_name, key_label, api_key) in enumerate(attempts, start=1):
        print(
            f"Gemini content model attempt {attempt}/{max_attempts}: {model_name} "
            f"using {key_label} key"
        )
        client = _get_gemini_client(api_key)
        model_call_limit = len(_CONTENT_503_RETRY_DELAYS_SECONDS) + 1
        for model_call in range(1, model_call_limit + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=1.0,
                        response_mime_type="application/json",
                    ),
                )
                break
            except Exception as exc:  # noqa: BLE001
                status = _gemini_error_status(exc)
                if status is None:
                    raise
                print(
                    f"Gemini content model temporary failure: {model_name} — {status}"
                )
                if status == "503" and model_call < model_call_limit:
                    delay = _CONTENT_503_RETRY_DELAYS_SECONDS[model_call - 1]
                    print(
                        f"Retrying Gemini content model {model_name} after "
                        f"{delay:g}s (attempt {model_call + 1}/{model_call_limit})"
                    )
                    time.sleep(delay)
                    continue
                if attempt >= max_attempts:
                    raise
                print(f"Switching Gemini content model to: {attempts[attempt][0]}")
                break
        if response is not None:
            break

    if response is None:  # pragma: no cover - defensive
        raise RuntimeError("Gemini response was unavailable after content-model failover.")

    raw = (response.text or "").strip()
    ad_copy = parse_ad_copy_response(
        raw, slot=slot, resolved_brief=resolved_brief
    )
    log_resolved_hook_warnings(ad_copy, resolved_brief)
    log_body_profile_warnings(ad_copy, resolved_brief)
    return enforce_resolved_engagement_line(
        apply_brand_enforcement(ad_copy, config.BRAND_RULES), resolved_brief
    )


def generate_local_ad_copy(
    *, selection: Dict[str, Any], slot: str, resolved_brief: Optional[Any] = None
) -> Dict[str, Any]:
    """Deterministic local copy generator used for TEST_MODE preview runs."""
    campaign = selection["campaign"]
    territory = selection.get("emotional_territory") or creative_engine_v3.classify_emotional_territory(
        campaign_name=campaign.get("name", ""),
        pain_point=campaign.get("pain_point", ""),
        goal=campaign.get("goal", ""),
    )
    headline_map = {
        "insomnia": "Mind Racing at Bedtime?",
        "financial_stress": "Anxious About Money Today?",
        "burnout": "Running on Empty?",
        "prayer_difficulty": "Struggling to Pray?",
        "confidence": "Feeling Unsteady Today?",
        "purpose": "Need Direction Tonight?",
        "loneliness": "Feeling Alone Tonight?",
        "guilt": "Carrying Guilt Right Now?",
        "identity": "Questioning Your Worth Today?",
        "gratitude": "Want to Thank God Today?",
    }
    pain_headline = headline_map.get(territory, "Need Prayer Support Today?")
    if resolved_brief is not None and resolved_brief.pain_point_label:
        pain_headline = "Feeling {0}?".format(resolved_brief.pain_point_label.rstrip("?"))
    spiritual_action = selection.get("spiritual_action", "Give your worries to God.")
    ad_copy = {
        "brand_header": "PRAYONIT",
        "pain_headline": pain_headline,
        "spiritual_action": spiritual_action,
        "app_benefit": LOCKED_APP_BENEFIT,
        "download_cta": config.PRIMARY_CTA,
        "trial_support": config.VISUAL_DESTINATION_TEXT,
        "facebook_caption": (
            f"{pain_headline} {spiritual_action} {LOCKED_APP_BENEFIT}"
        ),
        "instagram_caption": f"{pain_headline} {spiritual_action} {LOCKED_APP_BENEFIT}",
        "story_headline": pain_headline,
        "story_spiritual_action": spiritual_action,
        "story_app_benefit": LOCKED_STORY_APP_BENEFIT,
        "story_download_cta": config.PRIMARY_CTA,
        "story_trial_support": config.VISUAL_DESTINATION_TEXT,
    }
    todays_content = content_engine.get_todays_content(slot=slot)
    presentation = content_engine.get_presentation_config(todays_content)
    if resolved_brief is not None:
        todays_content = {"content_type": resolved_brief.content_type}
        presentation = {
            **presentation,
            "video_template": resolved_brief.video_template,
            "duration_seconds": resolved_brief.duration_seconds,
            "engagement_prompt_enabled": bool(resolved_brief.engagement_prompt),
        }
    long_form = build_long_form_defaults(
        content_type=todays_content.get("content_type", ""),
        video_template=presentation["video_template"],
        duration_seconds=presentation["duration_seconds"],
    )
    if long_form["long_form_type"] == "prayer":
        long_form.update(
            {
                "opening_hook": "God sees your burden.",
                "bridge_line": "Let this prayer meet you right where you are.",
                "script_segments": [
                    "Lord, meet me in this moment and calm the worries I have been carrying.",
                    "Give me strength to trust You with what feels heavy and wisdom for the next step in front of me.",
                    "Cover this day with Your peace and help me remember that I do not walk through it alone.",
                ],
                "closing_line": "Amen.",
                "engagement_line": "Save this prayer for later today." if presentation["engagement_prompt_enabled"] else "",
                "estimated_spoken_seconds": presentation["duration_seconds"],
            }
        )
    elif long_form["long_form_type"] == "devotional":
        long_form.update(
            {
                "opening_hook": "You are not forgotten.",
                "bridge_line": "Take this reflection with you for a moment.",
                "script_segments": [
                    "When the middle of the week feels heavy, God still meets you with steady compassion and patient strength.",
                    "Even if you feel worn down, hope is not gone, and small faithfulness still matters today.",
                    "Take the next step in peace, trusting that God is present with you in it.",
                ],
                "closing_line": "Take the next faithful step today.",
                "engagement_line": "Share this with someone who needs hope today." if presentation["engagement_prompt_enabled"] else "",
                "estimated_spoken_seconds": presentation["duration_seconds"],
            }
        )
    elif long_form["long_form_type"] == "encouragement":
        long_form.update(
            {
                "opening_hook": "Hope is still here.",
                "bridge_line": "Hold onto this encouragement for a moment.",
                "script_segments": [
                    "You may be tired, but God has not left you, and this hard moment will not have the final word.",
                    "Take a breath, receive His peace, and keep moving with steady hope today.",
                ],
                "closing_line": "You can keep going.",
                "engagement_line": "Send this to someone who needs encouragement." if presentation["engagement_prompt_enabled"] else "",
                "estimated_spoken_seconds": presentation["duration_seconds"],
            }
        )
    ad_copy.update(long_form)
    log_resolved_hook_warnings(ad_copy, resolved_brief)
    return enforce_resolved_engagement_line(
        apply_brand_enforcement(ad_copy, config.BRAND_RULES), resolved_brief
    )


_URL_PATTERN = re.compile(r"https?://\S+", flags=re.IGNORECASE)


def _strip_invented_urls(text: str) -> str:
    """Remove any URL Gemini may have included despite instructions not to.

    This is a defense-in-depth step: the caption's real download link is
    always appended programmatically afterward, so nothing here relies on
    Gemini having formatted (or even included) a URL correctly.
    """
    cleaned = _URL_PATTERN.sub("", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


# Sentences/phrases that contain trial-first or download-first CTA
# wording. Prayonit's funnel is now invitation-first ("Come pray with me")
# -> prayonit.app / Link in bio -> an app download or trial may only be
# offered later, on the website itself -- so social captions must never
# contain this wording at all (not just deduplicated).
_FORBIDDEN_TRIAL_OR_DOWNLOAD_SENTENCE_PATTERN = re.compile(
    r"\b(start|begin|try)\b.{0,80}?\b14-?\s*day\b.{0,40}?\b(free\s+)?trial\b"
    r"|\bstart\s+your\s+free\s+trial\b"
    r"|\btry\s+prayonit\s+free\b"
    r"|\bdownload\s+prayonit\b"
    r"|\binstall\s+(the\s+app|prayonit)\b"
    r"|\bget\s+the\s+app\b",
    flags=re.IGNORECASE,
)


def _strip_forbidden_trial_and_download_sentences(text: str) -> str:
    """Remove every sentence containing trial-first or download-first CTA
    wording (not just duplicates), so social captions never lead with, or
    contain at all, a free-trial pitch or a direct app-download/install
    instruction. The invitation-first CTA and prayonit.app/Link-in-bio
    destination text are appended separately by build_platform_captions.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s.strip() and not _FORBIDDEN_TRIAL_OR_DOWNLOAD_SENTENCE_PATTERN.search(s)]
    return " ".join(kept).strip()


# Locked canonical benefit phrases. If Gemini uses certain alternate
# variants we consider forbidden for legal/brand reasons, replace the
# entire field with the locked phrase to ensure consistent messaging.
LOCKED_APP_BENEFIT = "Get a guided, personalized prayer based on your mood right now."
LOCKED_STORY_APP_BENEFIT = "Get a guided, personalized prayer based on your mood right now."


# Variants that should be replaced with the locked benefit phrase if
# they appear in Gemini output. The matching is intentionally broad to
# catch common rewordings that are still undesirable.
_FORBIDDEN_BENEFIT_VARIANTS = [
    "receive personalized, guided prayer",
    "receive personalized prayer",
    "receive a guided prayer",
    "receive personalized, guided prayer",
    "receive a guided, personalized prayer",
    "personalized scripture and a devotion",
]


def _contains_forbidden_benefit_variant(text: str) -> bool:
    lower = (text or "").lower()
    return any(variant in lower for variant in _FORBIDDEN_BENEFIT_VARIANTS)


def enforce_locked_benefit_phrase(text: str, locked_phrase: str) -> str:
    """If the text contains any forbidden benefit variant, return the
    locked canonical phrase; otherwise return the original text.
    """
    if _contains_forbidden_benefit_variant(text):
        return locked_phrase
    return text


# Download-CTA duplicate sentence removal: remove any Gemini-written
# sentence that is merely a legacy direct-download CTA (e.g. "Download
# Prayonit today.", "Install Prayonit now.", "Get the app.") before the
# system appends the exact required invitation-first CTA + URL.
_DUPLICATE_DOWNLOAD_CTA_PATTERN = re.compile(
    r"\bdownload\b.{0,40}?\bprayonit\b"
    r"|\binstall\b.{0,40}?\bprayonit\b"
    r"|\bdownload\s+the\s+app\b"
    r"|\bget\s+the\s+app\b",
    flags=re.IGNORECASE,
)


def _strip_duplicate_download_cta_sentences(text: str) -> str:
    """Remove any sentence that appears to be a simple download CTA so
    the caption builder can append the exact required CTA/URL once.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s.strip() and not _DUPLICATE_DOWNLOAD_CTA_PATTERN.search(s)]
    return " ".join(kept).strip()


def _normalize_cta_text(text: str) -> str:
    normalized = (text or "").replace("’", "'").replace("‘", "'")
    normalized = re.sub(r"\s+", " ", normalized.strip().lower())
    return normalized.rstrip(".! ")


def contains_normalized_cta(text: str, cta: str) -> bool:
    normalized_cta = _normalize_cta_text(cta)
    if not normalized_cta:
        return False
    normalized_text = _normalize_cta_text(text)
    return normalized_text.endswith(normalized_cta)


def build_platform_captions(
    ad_copy: Dict[str, str],
    selection: Dict[str, Any],
    platform_urls: Dict[str, str],
) -> Dict[str, str]:
    """Build final per-platform captions with hashtags and the exact,
    programmatically-appended website destination for each platform.

    Gemini is never trusted to insert URLs: any URL it produced is stripped
    from each caption, and the exact URL supplied in platform_urls (either
    the tracked URL when TRACKING_ENABLED=true, or DEFAULT_DESTINATION_URL
    when tracking is disabled) is appended afterward, verbatim. Every
    caption body also has any trial-first or download-first sentence
    removed, since Prayonit's funnel is invitation-first ("Come pray with
    me") -> prayonit.app / Link in bio -> an app download or trial may only
    be offered later, on the website itself.
    """
    campaign = selection["campaign"]

    facebook_url = platform_urls["facebook"]
    _instagram_url = platform_urls["instagram"]

    facebook_body = _strip_invented_urls(ad_copy["facebook_caption"])
    # Remove any Gemini-generated download or trial CTA sentences so the
    # system can append the exact required invitation-first CTA/URL
    # consistently, with no trial-first or download-first language at all.
    facebook_body = _strip_duplicate_download_cta_sentences(facebook_body)
    facebook_body = _strip_forbidden_trial_and_download_sentences(facebook_body)
    facebook_cta_block = "" if contains_normalized_cta(facebook_body, config.FACEBOOK_CTA) else f"\n\n{config.FACEBOOK_CTA}"
    facebook_caption = f"{facebook_body}{facebook_cta_block}\n{facebook_url}"

    ig_hashtag_pool = [h for h in campaign.get("instagram_hashtags", []) if h.lower() != "#prayonit"]
    ig_count = min(len(ig_hashtag_pool), random.randint(4, 7)) if ig_hashtag_pool else 0
    ig_hashtags = ["#Prayonit"] + (random.sample(ig_hashtag_pool, k=ig_count) if ig_count else [])
    instagram_body = _strip_invented_urls(ad_copy["instagram_caption"])
    # Remove any Gemini-generated trial-first or download-first sentence so
    # the caption never leads with (or contains at all) that language.
    instagram_body = _strip_forbidden_trial_and_download_sentences(instagram_body)
    instagram_body = _strip_duplicate_download_cta_sentences(instagram_body)
    # Instagram feed captions do not make raw URLs clickable, so the
    # destination URL is never appended here. The exact same URL
    # (instagram_url) is instead placed in metadata.instagram.link on the
    # Buffer post (see buffer_client.buffer_create_post). No trial-first
    # line is appended -- the invitation-first CTA (which includes "Link in
    # bio") is the only thing appended after the body.
    instagram_cta_block = "\n\nLink in bio." if contains_normalized_cta(instagram_body, config.FACEBOOK_CTA) else f"\n\n{config.INSTAGRAM_CTA}"
    instagram_caption = f"{instagram_body}{instagram_cta_block}"
    if ig_hashtags:
        instagram_caption = f"{instagram_caption}\n\n{' '.join(ig_hashtags)}"

    return {
        "facebook": facebook_caption,
        "instagram": instagram_caption,
    }
