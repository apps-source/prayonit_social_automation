"""Weekly Rhythm content engine (additive content-selection layer).

This module does NOT touch the existing production pipeline. It simply
loads `creative/weekly_rhythm.json`, determines today's weekday and
morning/evening slot, and returns that slot's content configuration so it
can be prepended to the existing Gemini prompt in prompt_builder.py.

Nothing here replaces campaign_engine.py's campaign/formula/persona/
background selection, nor Gemini generation, image rendering, video
rendering, uploads, or Buffer scheduling.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_CREATIVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "creative",
)

_WEEKLY_RHYTHM_PATH = os.path.join(_CREATIVE_DIR, "weekly_rhythm.json")
_HOOK_STYLES_PATH = os.path.join(_CREATIVE_DIR, "hook_styles.json")
_LIFE_MOMENTS_PATH = os.path.join(_CREATIVE_DIR, "life_moments.json")
_ENGAGEMENT_PROMPTS_PATH = os.path.join(_CREATIVE_DIR, "engagement_prompts.json")
_SOFT_PROMOTIONS_PATH = os.path.join(_CREATIVE_DIR, "soft_promotions.json")
_CONTENT_RULES_PATH = os.path.join(_CREATIVE_DIR, "content_rules.json")

_WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_PRESENTATION_FIELDS = (
    "content_type",
    "video_template",
    "video_library",
    "duration_seconds",
    "marketing_enabled",
    "show_logo",
    "show_badges",
    "show_cta",
    "show_link_in_bio",
    "show_app_benefit",
    "engagement_prompt_enabled",
    "engagement_prompt_type",
    "cta_text",
)

_VALID_VIDEO_TEMPLATES = {
    "long_prayer",
    "short_promo",
    "long_devotional",
    "short_engagement",
    "long_encouragement",
}

_VALID_VIDEO_LIBRARIES = {"short", "long"}

_VALID_ENGAGEMENT_PROMPT_TYPES = {
    "none",
    "save_or_share",
    "comment_or_send",
    "share_or_prayer_request",
    "save_or_comment",
    "share_or_amen",
}

_SHORT_PROMO_PRESENTATION_DEFAULTS: Dict[str, Any] = {
    "content_type": "app_feature",
    "video_template": "short_promo",
    "video_library": "short",
    "duration_seconds": 8,
    "marketing_enabled": True,
    "show_logo": True,
    "show_badges": True,
    "show_cta": True,
    "show_link_in_bio": True,
    "show_app_benefit": True,
    "engagement_prompt_enabled": False,
    "engagement_prompt_type": "none",
    "cta_text": "Come pray with me.",
}

# Cached in-memory copies of the parsed JSON contents, keyed by file path.
_json_cache: Dict[str, Any] = {}
_weekly_rhythm_cache: Optional[Dict[str, Any]] = None


def _load_json_file(path: str, use_cache: bool = True) -> Any:
    """Load and return the parsed contents of a JSON file, optionally
    caching the result in-memory for subsequent calls with the default
    path.
    """
    if use_cache and path in _json_cache:
        return _json_cache[path]

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if use_cache:
        _json_cache[path] = data

    return data



def load_weekly_rhythm(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and return the full weekly_rhythm.json contents.

    Results are cached in-memory (per path) after the first successful
    load. Pass an explicit `path` to bypass the default location (used by
    tests).
    """
    global _weekly_rhythm_cache
    target_path = path or _WEEKLY_RHYTHM_PATH

    if path is None and _weekly_rhythm_cache is not None:
        return _weekly_rhythm_cache

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if path is None:
        _weekly_rhythm_cache = data

    return data


def get_current_weekday(now: Optional[datetime] = None) -> str:
    """Return the lowercase weekday name (e.g. 'monday') for `now`
    (defaults to current UTC time).
    """
    dt = now or datetime.now(timezone.utc)
    return _WEEKDAY_NAMES[dt.weekday()]


def get_current_slot(now: Optional[datetime] = None) -> str:
    """Return 'morning' or 'evening' based on the current UTC hour.

    Hours 0-11 are treated as morning, 12-23 as evening. This is a simple,
    deterministic default; callers that already know the slot (e.g. the
    existing --slot CLI argument) should pass it in explicitly to
    get_todays_content() instead of relying on this clock-based guess.
    """
    dt = now or datetime.now(timezone.utc)
    return "morning" if dt.hour < 12 else "evening"


def get_todays_content(
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
    weekly_rhythm: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return today's content configuration.

    Args:
        slot: "morning" or "evening". If omitted, it is inferred from the
            current UTC hour via get_current_slot(). Callers in the
            existing pipeline already know the slot (from the --slot CLI
            argument) and should pass it explicitly for consistency with
            the rest of the run.
        now: Optional datetime override, used for deterministic testing.
        weekly_rhythm: Optional pre-loaded weekly rhythm dict, used for
            deterministic testing without touching the on-disk cache.

    Returns:
        A dict with the existing weekly-rhythm keys (content_type, theme,
        emotion, hook_style, objective) plus validated presentation
        controls. Missing or invalid presentation fields fail safely to
        the existing short-promo defaults.
    """
    rhythm = weekly_rhythm if weekly_rhythm is not None else load_weekly_rhythm()
    weekday = get_current_weekday(now=now)
    resolved_slot = slot if slot in ("morning", "evening") else get_current_slot(now=now)

    day_config = rhythm.get(weekday, {})
    slot_config = day_config.get(resolved_slot, {})

    if not slot_config:
        raise KeyError(
            "No weekly_rhythm.json entry found for weekday={0!r} slot={1!r}".format(
                weekday, resolved_slot
            )
        )

    todays_content = {
        "content_type": slot_config.get("content_type", ""),
        "theme": slot_config.get("theme", ""),
        "emotion": slot_config.get("emotion", ""),
        "hook_style": slot_config.get("hook_style", ""),
        "objective": slot_config.get("objective", ""),
        "prayer_category_id": slot_config.get("prayer_category_id", ""),
    }
    todays_content.update(get_presentation_config(slot_config))
    return todays_content


def get_presentation_config(slot_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a validated presentation config for a weekly-rhythm slot.

    The result is additive metadata only: callers can consume it now or
    ignore it, and missing/invalid fields safely fall back to the
    established short-promo defaults.
    """
    slot_config = slot_config or {}

    video_template = slot_config.get("video_template")
    if video_template not in _VALID_VIDEO_TEMPLATES:
        video_template = _SHORT_PROMO_PRESENTATION_DEFAULTS["video_template"]

    video_library = slot_config.get("video_library")
    if video_library not in _VALID_VIDEO_LIBRARIES:
        video_library = _SHORT_PROMO_PRESENTATION_DEFAULTS["video_library"]

    duration_seconds = slot_config.get("duration_seconds")
    if not isinstance(duration_seconds, int) or not (8 <= duration_seconds <= 35):
        duration_seconds = _SHORT_PROMO_PRESENTATION_DEFAULTS["duration_seconds"]

    engagement_prompt_type = slot_config.get("engagement_prompt_type")
    if engagement_prompt_type not in _VALID_ENGAGEMENT_PROMPT_TYPES:
        engagement_prompt_type = _SHORT_PROMO_PRESENTATION_DEFAULTS["engagement_prompt_type"]

    presentation = {
        "content_type": slot_config.get(
            "content_type", _SHORT_PROMO_PRESENTATION_DEFAULTS["content_type"]
        ),
        "video_template": video_template,
        "video_library": video_library,
        "duration_seconds": duration_seconds,
        "engagement_prompt_type": engagement_prompt_type,
        "cta_text": slot_config.get("cta_text", _SHORT_PROMO_PRESENTATION_DEFAULTS["cta_text"]),
    }

    for key in (
        "marketing_enabled",
        "show_logo",
        "show_badges",
        "show_cta",
        "show_link_in_bio",
        "show_app_benefit",
        "engagement_prompt_enabled",
    ):
        value = slot_config.get(key)
        presentation[key] = (
            value
            if isinstance(value, bool)
            else _SHORT_PROMO_PRESENTATION_DEFAULTS[key]
        )

    return presentation


# ---------------------------------------------------------------------------
# Creative library helpers (Playbook-derived JSON files).
#
# These helpers load version-controlled creative data. Canonical brief
# resolution consumes selected libraries before prompt construction; the
# helpers themselves do not perform rendering, publishing, or remote calls.
# ---------------------------------------------------------------------------


def load_hook_styles(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load and return the full contents of hook_styles.json."""
    return _load_json_file(path or _HOOK_STYLES_PATH, use_cache=path is None)


def load_life_moments(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load and return the full contents of life_moments.json."""
    return _load_json_file(path or _LIFE_MOMENTS_PATH, use_cache=path is None)


def load_engagement_prompts(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load and return the full contents of engagement_prompts.json."""
    return _load_json_file(path or _ENGAGEMENT_PROMPTS_PATH, use_cache=path is None)


def load_soft_promotions(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load and return the full contents of soft_promotions.json."""
    return _load_json_file(path or _SOFT_PROMOTIONS_PATH, use_cache=path is None)


def load_content_rules(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and return the full contents of content_rules.json."""
    return _load_json_file(path or _CONTENT_RULES_PATH, use_cache=path is None)


def get_random_hook(
    style: Optional[str] = None, hook_styles: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """Return a random hook style entry, optionally filtered by `style`
    (case-insensitive match against the "name" field). Returns None if no
    entries match.
    """
    styles = hook_styles if hook_styles is not None else load_hook_styles()
    if style:
        candidates = [s for s in styles if s.get("name", "").lower() == style.lower()]
    else:
        candidates = list(styles)

    if not candidates:
        return None
    return random.choice(candidates)


def get_random_emotional_moment(
    category: Optional[str] = None, life_moments: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """Return a random life-moment entry, optionally filtered by
    `category` (case-insensitive match against the "category" field).
    Returns None if no entries match.
    """
    moments = life_moments if life_moments is not None else load_life_moments()
    if category:
        candidates = [m for m in moments if m.get("category", "").lower() == category.lower()]
    else:
        candidates = list(moments)

    if not candidates:
        return None
    return random.choice(candidates)


def get_random_engagement_prompt(
    category: Optional[str] = None, engagement_prompts: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """Return a random engagement prompt entry, optionally filtered by
    `category` (case-insensitive match against the "category" field).
    Returns None if no entries match.
    """
    prompts = engagement_prompts if engagement_prompts is not None else load_engagement_prompts()
    if category:
        candidates = [p for p in prompts if p.get("category", "").lower() == category.lower()]
    else:
        candidates = list(prompts)

    if not candidates:
        return None
    return random.choice(candidates)


def get_random_soft_promotion(
    style: Optional[str] = None, soft_promotions: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """Return a random soft-promotion entry, optionally filtered by
    `style` (case-insensitive match against the "style" field). Returns
    None if no entries match.
    """
    promos = soft_promotions if soft_promotions is not None else load_soft_promotions()
    if style:
        candidates = [p for p in promos if p.get("style", "").lower() == style.lower()]
    else:
        candidates = list(promos)

    if not candidates:
        return None
    return random.choice(candidates)
