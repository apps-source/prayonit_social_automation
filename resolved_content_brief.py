"""Resolve one canonical content identity before generation or rendering."""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import config
from engines import content_engine


_ALIASES_PATH = Path(__file__).resolve().parent / "creative" / "pain_point_aliases.json"
_ENGAGEMENT_PROMPTS_PATH = Path(__file__).resolve().parent / "creative" / "engagement_prompt_profiles.json"
_PRAYER_CATEGORIES_PATH = Path(__file__).resolve().parent / "creative" / "prayer_categories.json"
_RENDER_PROFILES_PATH = Path(__file__).resolve().parent / "creative" / "render_profiles.json"
_FALLBACK_PRAYER_CATEGORY_ID = "general_prayer"
_PROFILE_REGISTRY_KEYS = {
    "hook_profile_id": "hook_profiles",
    "voice_profile_id": "voice_profiles",
    "caption_profile_id": "caption_profiles",
    "scene_profile_id": "scene_profiles",
    "cta_profile_id": "cta_profiles",
    "hashtag_profile_id": "hashtag_profiles",
}
_CONTENT_TYPE_SAFE_CATEGORIES = {
    "app_feature": ("Faith & Spiritual Life",),
    "prayer_read": ("Faith & Spiritual Life",),
    "night_prayer_or_rest": ("Sleep & Nighttime", "Faith & Spiritual Life"),
    "devotional_read": ("Faith & Spiritual Life",),
    "gratitude_reflection": ("Faith & Spiritual Life",),
    "hope_encouragement": ("Faith & Spiritual Life",),
    "recognition_engagement": ("Faith & Spiritual Life",),
}


def _slugify(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _normalize_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def load_pain_point_config(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    with (path or _ALIASES_PATH).open("r", encoding="utf-8") as handle:
        return (json.load(handle).get("pain_points") or {})


def load_engagement_prompt_profiles(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load prompt metadata used to keep engagement aligned to the brief."""
    with (path or _ENGAGEMENT_PROMPTS_PATH).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_prayer_categories(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the controlled prayer-category taxonomy."""
    with (path or _PRAYER_CATEGORIES_PATH).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_creative_profile_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load profile IDs that preserve the current production behavior."""
    with (path or _RENDER_PROFILES_PATH).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_caption_profile_definition(
    profile_id: str, *, creative_policy_version: Optional[str] = None
) -> Dict[str, Any]:
    """Return one validated caption profile without selecting it."""
    registry = load_creative_profile_registry()
    active_version = str(registry.get("creative_policy_version", "")).strip()
    if creative_policy_version is not None and str(creative_policy_version) != active_version:
        raise RuntimeError(
            "Caption profile policy version does not match the active creative policy."
        )
    profile = registry.get("caption_profiles", {}).get(profile_id)
    if not isinstance(profile, dict):
        raise RuntimeError(f"Unknown caption profile ID: {profile_id}")
    return {"id": profile_id, **profile}


def normalize_pain_point(value: str, aliases: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """Return a controlled canonical ID, preserving unknown values for QA."""
    normalized = _normalize_text(value)
    for canonical_id, definition in (aliases or load_pain_point_config()).items():
        accepted = {_normalize_text(canonical_id)}
        accepted.update(_normalize_text(alias) for alias in definition.get("aliases", []))
        if normalized in accepted:
            return canonical_id
    return _slugify(normalized)


@dataclass(frozen=True)
class ResolvedContentBrief:
    run_id: str
    slot: str
    post_date: str
    platform_mode: str
    content_type: str
    video_template: str
    duration_seconds: int
    long_form_type: str
    weekly_theme: str
    pain_point_id: str
    pain_point_label: str
    normalized_emotion_id: str
    life_moment_id: Optional[str]
    life_moment_text: Optional[str]
    life_moment_category: Optional[str]
    life_moment_emotions: tuple[str, ...]
    hook_style_id: Optional[str]
    hook_style_label: Optional[str]
    objective: str
    tone: str
    emotional_goal: str
    scripture_theme: str
    engagement_prompt_type: str
    engagement_prompt_id: Optional[str]
    engagement_prompt: Optional[str]
    engagement_selection_reason: str
    marketing_enabled: bool
    campaign_compatible: bool
    campaign_id: Optional[str]
    campaign_name: Optional[str]
    creator_search_topic: Optional[str]
    asset_time_of_day: str
    asset_emotional_tone: str
    cta_id: str
    cta_text: str
    destination_url: str
    voice_style_profile: str
    organic_or_paid: str
    caption_version: str
    resolution_reason: str
    prayer_category_id: str = _FALLBACK_PRAYER_CATEGORY_ID
    hook_profile_id: str = "current_default"
    voice_profile_id: str = "natural_conversational"
    caption_profile_id: str = "current_default"
    scene_profile_id: str = "current_default"
    cta_profile_id: str = "current_default"
    hashtag_profile_id: str = "current_default"
    creative_policy_version: str = "1"
    prayer_category_resolution_reason: str = "backward_compatible_default"

    def to_history_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _life_moment_matches(moment: Dict[str, Any], canonical_id: str, aliases: Dict[str, Dict[str, Any]]) -> bool:
    return any(
        normalize_pain_point(emotion, aliases) == canonical_id
        for emotion in moment.get("emotions", [])
    )


def _life_moment_is_emotionally_compatible(
    moment: Dict[str, Any], canonical_id: str, aliases: Dict[str, Dict[str, Any]]
) -> bool:
    configured_terms = (aliases.get(canonical_id) or {}).get("fallback_emotions", [])
    compatible_terms = {_normalize_text(canonical_id)}
    compatible_terms.update(_normalize_text(term) for term in configured_terms)
    return any(_normalize_text(emotion) in compatible_terms for emotion in moment.get("emotions", []))


def _resolve_life_moment(
    canonical_id: str,
    *,
    aliases: Dict[str, Dict[str, Any]],
    life_moments: Iterable[Dict[str, Any]],
    content_type: str,
) -> tuple[Optional[Dict[str, Any]], str]:
    moments = list(life_moments)
    matches = [moment for moment in moments if _life_moment_matches(moment, canonical_id, aliases)]
    if matches:
        return sorted(matches, key=lambda moment: _slugify(moment.get("moment", "")))[0], "exact_or_alias_match"

    safe_categories = set((aliases.get(canonical_id) or {}).get("safe_categories", []))
    safe_categories.update(_CONTENT_TYPE_SAFE_CATEGORIES.get(content_type, ()))
    safe_candidates = [
        moment for moment in moments
        if moment.get("category") in safe_categories
        and _life_moment_is_emotionally_compatible(moment, canonical_id, aliases)
    ]
    if safe_candidates:
        return sorted(safe_candidates, key=lambda moment: _slugify(moment.get("moment", "")))[0], "safe_emotional_category_fallback"
    return None, "unresolved_no_emotionally_compatible_fallback"


def _campaign_text(campaign: Dict[str, Any]) -> str:
    return " ".join(str(campaign.get(field, "")) for field in ("_key", "name", "pain_point", "goal"))


def campaign_is_compatible(
    campaign: Optional[Dict[str, Any]],
    canonical_id: str,
    aliases: Optional[Dict[str, Dict[str, Any]]] = None,
) -> bool:
    if not campaign:
        return False
    configured_aliases = aliases or load_pain_point_config()
    terms = {_normalize_text(canonical_id)}
    terms.update(_normalize_text(alias) for alias in (configured_aliases.get(canonical_id) or {}).get("aliases", []))
    haystack = _normalize_text(_campaign_text(campaign))
    return any(term and term in haystack for term in terms)


def _select_compatible_campaign(
    campaigns: Iterable[Dict[str, Any]], canonical_id: str, aliases: Dict[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    compatible = [campaign for campaign in campaigns if campaign_is_compatible(campaign, canonical_id, aliases)]
    if not compatible:
        return None
    return sorted(compatible, key=lambda campaign: str(campaign.get("_key", campaign.get("name", ""))))[0]


def _creator_search_topic(canonical_id: str, life_moment_text: Optional[str]) -> Optional[str]:
    if not life_moment_text:
        return None
    normalized = _normalize_text(life_moment_text)
    if "grown" in normalized and "child" in normalized:
        return "prayer for parents missing grown children"
    subject = re.sub(r"^feeling\s+", "", life_moment_text.strip(), flags=re.IGNORECASE)
    return "prayer for " + subject.lower().rstrip(".?!")


def _topic_matches_life_moment(topic: Optional[str], life_moment_text: Optional[str]) -> bool:
    if not topic or not life_moment_text:
        return False
    topic_normalized = _normalize_text(topic)
    moment_normalized = _normalize_text(life_moment_text)
    if "grown child" in moment_normalized:
        return "grown children" in topic_normalized
    meaningful_words = [word for word in moment_normalized.split() if len(word) >= 5]
    return any(word in topic_normalized for word in meaningful_words)


def _validation(status: str, field: str, message: str) -> Dict[str, str]:
    return {"status": status, "field": field, "message": message}


def _category_supports_context(category: Dict[str, Any], *, slot: str, content_type: str) -> bool:
    allowed_slots = set(category.get("allowed_slots", []))
    allowed_content_types = set(category.get("allowed_content_types", []))
    slot_allowed = not allowed_slots or "anytime" in allowed_slots or slot in allowed_slots
    content_type_allowed = not allowed_content_types or content_type in allowed_content_types
    return slot_allowed and content_type_allowed


def _infer_prayer_category_id(
    *,
    slot: str,
    content_type: str,
    weekly_theme: str,
    video_template: str,
    long_form_type: str,
    categories: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[str], str]:
    normalized_theme = _slugify(weekly_theme)
    normalized_content_type = _slugify(content_type)

    if "bible_verse" in categories and (
        normalized_theme == "bible-verse"
        or normalized_content_type == "bible-verse"
        or video_template == "bible_verse"
    ):
        return "bible_verse", "inferred_from_explicit_bible_verse_format"
    if "devotional" in categories and (
        long_form_type == "devotional"
        or content_type in {"devotional_read", "gratitude_reflection"}
    ):
        return "devotional", "inferred_from_devotional_format"
    if long_form_type == "prayer":
        if slot == "morning" and "morning_prayer" in categories:
            return "morning_prayer", "inferred_from_morning_prayer_format"
        if slot == "evening" and "night_prayer" in categories:
            return "night_prayer", "inferred_from_evening_prayer_format"

    theme_category_id = normalized_theme.replace("-", "_")
    if theme_category_id in categories:
        return theme_category_id, "inferred_from_exact_weekly_theme"
    return None, "no_safe_category_inference"


def _resolve_prayer_category(
    *,
    explicit_category_id: str,
    slot: str,
    content_type: str,
    weekly_theme: str,
    video_template: str,
    long_form_type: str,
    category_definitions: Iterable[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    categories = {
        str(category.get("id", "")).strip(): category
        for category in category_definitions
        if str(category.get("id", "")).strip()
    }
    fallback = categories.get(_FALLBACK_PRAYER_CATEGORY_ID)
    if fallback is None:
        raise RuntimeError("Prayer category configuration is missing general_prayer.")

    requested_id = explicit_category_id.strip()
    if requested_id:
        requested = categories.get(requested_id)
        if requested is None:
            reason = f"fallback_unknown_explicit_category:{requested_id}"
            print(
                "[resolved_content_brief] Prayer category fallback to general_prayer: "
                f"unknown explicit category '{requested_id}'."
            )
            return fallback, reason
        if not _category_supports_context(requested, slot=slot, content_type=content_type):
            reason = f"fallback_incompatible_explicit_category:{requested_id}"
            print(
                "[resolved_content_brief] Prayer category fallback to general_prayer: "
                f"'{requested_id}' is incompatible with slot={slot}, content_type={content_type}."
            )
            return fallback, reason
        return requested, "explicit_weekly_category"

    inferred_id, inference_reason = _infer_prayer_category_id(
        slot=slot,
        content_type=content_type,
        weekly_theme=weekly_theme,
        video_template=video_template,
        long_form_type=long_form_type,
        categories=categories,
    )
    if inferred_id:
        inferred = categories[inferred_id]
        if _category_supports_context(inferred, slot=slot, content_type=content_type):
            return inferred, inference_reason
        print(
            "[resolved_content_brief] Prayer category fallback to general_prayer: "
            f"inferred category '{inferred_id}' is incompatible with "
            f"slot={slot}, content_type={content_type}."
        )
        return fallback, f"fallback_incompatible_inferred_category:{inferred_id}"

    print(
        "[resolved_content_brief] Prayer category fallback to general_prayer: "
        "no safe explicit or inferred category."
    )
    return fallback, "fallback_no_safe_category_inference"


def _resolve_creative_profile_ids(
    category: Dict[str, Any], registry: Dict[str, Any]
) -> Dict[str, str]:
    global_defaults = registry.get("global_defaults", {})
    category_defaults = category.get("default_profiles", {})
    return {
        field_name: str(
            category_defaults.get(field_name)
            or global_defaults.get(field_name)
            or ""
        ).strip()
        for field_name in _PROFILE_REGISTRY_KEYS
    }


def _validate_creative_resolution(brief: ResolvedContentBrief) -> List[Dict[str, str]]:
    categories = {
        str(category.get("id", "")).strip(): category
        for category in load_prayer_categories()
    }
    registry = load_creative_profile_registry()
    results: List[Dict[str, str]] = []
    category = categories.get(brief.prayer_category_id)

    if category is None:
        results.append(
            _validation(
                "critical failure",
                "prayer_category_id",
                "Resolved prayer category is not present in approved configuration.",
            )
        )
    elif not _category_supports_context(
        category, slot=brief.slot, content_type=brief.content_type
    ):
        results.append(
            _validation(
                "critical failure",
                "prayer_category_id",
                "Resolved prayer category conflicts with the slot or content type.",
            )
        )
    elif brief.prayer_category_resolution_reason.startswith("fallback_"):
        results.append(
            _validation(
                "warning",
                "prayer_category_id",
                "Prayer category used the documented general_prayer fallback.",
            )
        )
    else:
        results.append(
            _validation(
                "pass",
                "prayer_category_id",
                "Prayer category is approved and compatible.",
            )
        )

    if not brief.creative_policy_version:
        results.append(
            _validation(
                "critical failure",
                "creative_policy_version",
                "Creative policy version is missing.",
            )
        )
    elif brief.creative_policy_version != str(registry.get("creative_policy_version", "")).strip():
        results.append(
            _validation(
                "critical failure",
                "creative_policy_version",
                "Creative policy version is not present in the active registry.",
            )
        )
    else:
        results.append(
            _validation("pass", "creative_policy_version", "Creative policy version is valid.")
        )

    for field_name, registry_key in _PROFILE_REGISTRY_KEYS.items():
        profile_id = str(getattr(brief, field_name, "")).strip()
        if not profile_id or profile_id not in registry.get(registry_key, {}):
            results.append(
                _validation(
                    "critical failure",
                    field_name,
                    "Resolved creative profile is not present in approved configuration.",
                )
            )
        else:
            results.append(
                _validation("pass", field_name, "Resolved creative profile is valid.")
            )
    return results


def _profile_supports_slot(profile: Dict[str, Any], slot: str) -> bool:
    return slot in profile.get("slots", []) or "anytime" in profile.get("slots", [])


def _profile_supports_content_type(profile: Dict[str, Any], content_type: str) -> bool:
    supported = profile.get("content_types", [])
    return not supported or content_type in supported


def _profile_is_semantic_match(profile: Dict[str, Any], brief: Any) -> bool:
    return (
        brief.pain_point_id in profile.get("pain_point_ids", [])
        or (brief.life_moment_category or "") in profile.get("life_moment_categories", [])
    )


def _stable_profile_choice(profiles: List[Dict[str, Any]], brief: Any) -> Dict[str, Any]:
    ordered = sorted(profiles, key=lambda profile: profile["id"])
    seed = "|".join((brief.run_id, brief.pain_point_id, brief.life_moment_id or "", brief.engagement_prompt_type))
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(ordered)
    return ordered[index]


def _select_engagement_prompt(
    *,
    run_id: str,
    slot: str,
    content_type: str,
    pain_point_id: str,
    life_moment_id: Optional[str],
    life_moment_category: Optional[str],
    engagement_prompt_type: str,
    profiles: Iterable[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], str]:
    """Choose a slot- and type-compatible prompt without random topic drift."""
    context = type("EngagementContext", (), {
        "run_id": run_id,
        "slot": slot,
        "content_type": content_type,
        "pain_point_id": pain_point_id,
        "life_moment_id": life_moment_id,
        "life_moment_category": life_moment_category,
        "engagement_prompt_type": engagement_prompt_type,
    })()
    if context.engagement_prompt_type == "none":
        return None, "engagement_disabled"
    eligible = [
        profile for profile in profiles
        if context.engagement_prompt_type in profile.get("engagement_types", [])
        and _profile_supports_slot(profile, context.slot)
        and _profile_supports_content_type(profile, context.content_type)
    ]
    semantic = [
        profile for profile in eligible
        if not profile.get("fallback") and _profile_is_semantic_match(profile, context)
    ]
    if semantic:
        chosen = _stable_profile_choice(semantic, context)
        return chosen, "{0} + {1} semantic match".format(
            context.slot,
            context.life_moment_category or context.pain_point_id,
        )
    fallbacks = [profile for profile in eligible if profile.get("fallback")]
    if fallbacks:
        return _stable_profile_choice(fallbacks, context), "{0} + {1} neutral type-compatible fallback".format(
            context.slot, context.engagement_prompt_type
        )
    return None, "no slot- and type-compatible engagement prompt"


def validate_resolved_content_brief(brief: ResolvedContentBrief) -> List[Dict[str, str]]:
    approved_ctas = set(config.BRAND_RULES.get("approved_ctas", []))
    approved_ctas.add(config.BRAND_RULES.get("preferred_cta", ""))
    results = _validate_creative_resolution(brief)
    aliases = load_pain_point_config()
    if brief.pain_point_id in aliases or brief.resolution_reason.startswith("exact_or_alias_match"):
        results.append(_validation("pass", "pain_point", "Canonical pain point is represented by controlled data."))
    else:
        results.append(_validation("warning", "pain_point", "Pain point is using a category-aligned fallback and needs library review."))
    selected_moment = {
        "category": brief.life_moment_category,
        "moment": brief.life_moment_text,
        "emotions": brief.life_moment_emotions,
    }
    if brief.life_moment_id and brief.life_moment_text and _life_moment_is_emotionally_compatible(
        selected_moment, brief.pain_point_id, aliases
    ):
        results.append(_validation("pass", "life_moment", "Life Moment matches the canonical pain point's emotional meaning."))
    elif brief.life_moment_id and brief.life_moment_text:
        results.append(_validation("critical failure", "life_moment", "Life Moment is emotionally contradictory to the canonical pain point."))
    else:
        results.append(_validation("critical failure", "life_moment", "No emotionally compatible life moment was resolved."))
    if brief.campaign_id is None or brief.campaign_compatible:
        results.append(_validation("pass", "campaign", "Campaign is absent or semantically compatible."))
    else:
        results.append(_validation("critical failure", "campaign", "Campaign does not match the resolved pain point."))
    if _topic_matches_life_moment(brief.creator_search_topic, brief.life_moment_text):
        results.append(_validation("pass", "creator_search_topic", "Creator Search topic follows the resolved life moment."))
    else:
        results.append(_validation("critical failure", "creator_search_topic", "Creator Search topic does not match the resolved life moment."))
    if brief.asset_time_of_day == brief.slot:
        results.append(_validation("pass", "asset_time_of_day", "Asset time requirement matches the slot."))
    else:
        results.append(_validation("critical failure", "asset_time_of_day", "Asset time requirement conflicts with the slot."))
    if brief.cta_text in approved_ctas:
        results.append(_validation("pass", "cta", "CTA is approved."))
    else:
        results.append(_validation("critical failure", "cta", "CTA is not approved."))
    if brief.destination_url.strip() and brief.destination_url == config.DEFAULT_DESTINATION_URL:
        results.append(_validation("pass", "destination", "Destination URL is the configured approved destination."))
    else:
        results.append(_validation("critical failure", "destination", "Destination URL is missing or not approved."))
    if brief.engagement_prompt_type == "none" and not brief.engagement_prompt:
        results.append(_validation("pass", "engagement_prompt", "Engagement is disabled for this content type."))
    elif not brief.engagement_prompt or not brief.engagement_prompt_id:
        results.append(_validation("critical failure", "engagement_prompt", "No compatible engagement prompt was resolved."))
    else:
        profiles = {profile.get("id"): profile for profile in load_engagement_prompt_profiles()}
        profile = profiles.get(brief.engagement_prompt_id)
        if not profile or profile.get("prompt") != brief.engagement_prompt:
            results.append(_validation("critical failure", "engagement_prompt", "Resolved engagement prompt is not present in approved metadata."))
        elif brief.engagement_prompt_type not in profile.get("engagement_types", []):
            results.append(_validation("critical failure", "engagement_prompt", "Engagement prompt does not match the configured engagement type."))
        elif not _profile_supports_slot(profile, brief.slot):
            results.append(_validation("critical failure", "engagement_prompt", "Engagement prompt conflicts with the publishing slot."))
        elif not _profile_supports_content_type(profile, brief.content_type):
            results.append(_validation("critical failure", "engagement_prompt", "Engagement prompt conflicts with the content type."))
        elif profile.get("fallback"):
            results.append(_validation("warning", "engagement_prompt", "No specific semantic prompt was available; a neutral compatible fallback was selected."))
        elif _profile_is_semantic_match(profile, brief):
            results.append(_validation("pass", "engagement_prompt", "Engagement prompt matches the resolved pain point or Life Moment category."))
        else:
            results.append(_validation("critical failure", "engagement_prompt", "Engagement prompt is unrelated to the resolved Life Moment."))
    return results


def validate_asset_metadata(brief: ResolvedContentBrief, asset_metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    asset_time = str(asset_metadata.get("time", "neutral")).lower()
    allowed_times = {
        "morning": {"morning", "sunrise", "anytime", "neutral"},
        "evening": {"evening", "night", "anytime", "neutral"},
    }.get(brief.slot, {"anytime", "neutral"})
    if asset_time not in allowed_times:
        return [_validation("critical failure", "asset_time_of_day", f"{asset_time} asset conflicts with {brief.slot} slot.")]
    return [_validation("pass", "asset_time_of_day", "Asset metadata is slot-compatible.")]


def has_critical_failure(report: Iterable[Dict[str, str]]) -> bool:
    return any(item.get("status") == "critical failure" for item in report)


def log_resolved_content_brief(
    brief: ResolvedContentBrief, validation_report: Optional[Iterable[Dict[str, str]]] = None
) -> None:
    print("Resolved Content Brief:")
    print(f"- content type: {brief.content_type}")
    print(f"- prayer category: {brief.prayer_category_id}")
    print(
        "- creative profiles: hook={0}, voice={1}, caption={2}, scene={3}, "
        "cta={4}, hashtag={5}".format(
            brief.hook_profile_id,
            brief.voice_profile_id,
            brief.caption_profile_id,
            brief.scene_profile_id,
            brief.cta_profile_id,
            brief.hashtag_profile_id,
        )
    )
    print(f"- creative policy version: {brief.creative_policy_version}")
    print(f"- prayer category resolution: {brief.prayer_category_resolution_reason}")
    print(f"- pain point: {brief.pain_point_id}")
    print(f"- Life Moment: {brief.life_moment_text or 'unresolved'}")
    print(f"- campaign: {brief.campaign_name or 'none'}")
    print(f"- Creator Search topic: {brief.creator_search_topic or 'unresolved'}")
    print(f"- asset time: {brief.asset_time_of_day}")
    print(f"- CTA: {brief.cta_text}")
    print(f"- destination: {brief.destination_url}")
    print(f"- Resolved engagement prompt: {brief.engagement_prompt or 'none'}")
    print(f"- Resolved engagement type: {brief.engagement_prompt_type}")
    print(f"- Engagement selection reason: {brief.engagement_selection_reason}")
    if validation_report is not None:
        engagement_status = next(
            (item.get("status") for item in validation_report if item.get("field") == "engagement_prompt"),
            "not evaluated",
        )
        print(f"- Engagement validation status: {engagement_status}")
    print(f"- resolution reason: {brief.resolution_reason}")


def resolve_content_brief(
    *,
    run_id: str,
    slot: str,
    post_date: str,
    platform_mode: str,
    candidate_campaign: Optional[Dict[str, Any]],
    campaigns: Optional[Iterable[Dict[str, Any]]] = None,
    weekly_content: Optional[Dict[str, Any]] = None,
    life_moments: Optional[Iterable[Dict[str, Any]]] = None,
    hook_styles: Optional[Iterable[Dict[str, Any]]] = None,
    aliases: Optional[Dict[str, Dict[str, Any]]] = None,
    caption_profile_override: Optional[str] = None,
) -> ResolvedContentBrief:
    configured_aliases = aliases or load_pain_point_config()
    weekly = weekly_content or content_engine.get_todays_content(slot=slot)
    presentation = content_engine.get_presentation_config(weekly)
    requested_emotion = str(weekly.get("emotion", "")).strip()
    canonical_id = normalize_pain_point(requested_emotion, configured_aliases)
    resolved_moment, resolution_reason = _resolve_life_moment(
        canonical_id,
        aliases=configured_aliases,
        life_moments=life_moments if life_moments is not None else content_engine.load_life_moments(),
        content_type=str(weekly.get("content_type", "")),
    )
    hooks = list(hook_styles if hook_styles is not None else content_engine.load_hook_styles())
    requested_hook_style = str(weekly.get("hook_style", "")).strip()
    hook = next((item for item in hooks if _normalize_text(item.get("name", "")) == _normalize_text(requested_hook_style)), None)

    campaign_pool = list(campaigns if campaigns is not None else [])
    campaign = candidate_campaign if campaign_is_compatible(candidate_campaign, canonical_id, configured_aliases) else None
    if campaign is None:
        campaign = _select_compatible_campaign(campaign_pool, canonical_id, configured_aliases)
    if candidate_campaign and campaign is not candidate_campaign:
        resolution_reason += "; incompatible_campaign_replaced" if campaign else "; incompatible_campaign_dropped"

    life_moment_text = resolved_moment.get("moment") if resolved_moment else None
    long_form_type = "none"
    if presentation["video_template"] == "long_prayer":
        long_form_type = "prayer"
    elif presentation["video_template"] == "long_devotional":
        long_form_type = "devotional"
    elif presentation["video_template"] == "long_encouragement":
        long_form_type = "encouragement"

    prayer_category, prayer_category_resolution_reason = _resolve_prayer_category(
        explicit_category_id=str(weekly.get("prayer_category_id", "")),
        slot=slot,
        content_type=str(weekly.get("content_type", "")),
        weekly_theme=str(weekly.get("theme", "")),
        video_template=presentation["video_template"],
        long_form_type=long_form_type,
        category_definitions=load_prayer_categories(),
    )
    profile_registry = load_creative_profile_registry()
    profile_ids = _resolve_creative_profile_ids(prayer_category, profile_registry)
    if caption_profile_override:
        profile_ids["caption_profile_id"] = caption_profile_override.strip()

    engagement_type = presentation["engagement_prompt_type"]
    selected_prompt, engagement_selection_reason = _select_engagement_prompt(
        run_id=run_id,
        slot=slot,
        content_type=str(weekly.get("content_type", "")),
        pain_point_id=canonical_id,
        life_moment_id=("life-moment-" + _slugify(life_moment_text)) if life_moment_text else None,
        life_moment_category=resolved_moment.get("category") if resolved_moment else None,
        engagement_prompt_type=engagement_type if presentation["engagement_prompt_enabled"] else "none",
        profiles=load_engagement_prompt_profiles(),
    )

    return ResolvedContentBrief(
        run_id=run_id,
        slot=slot,
        post_date=post_date,
        platform_mode=platform_mode,
        content_type=str(weekly.get("content_type", "")),
        video_template=presentation["video_template"],
        duration_seconds=int(presentation["duration_seconds"]),
        long_form_type=long_form_type,
        weekly_theme=str(weekly.get("theme", "")),
        pain_point_id=canonical_id,
        pain_point_label=requested_emotion,
        normalized_emotion_id=canonical_id,
        life_moment_id=("life-moment-" + _slugify(life_moment_text)) if life_moment_text else None,
        life_moment_text=life_moment_text,
        life_moment_category=resolved_moment.get("category") if resolved_moment else None,
        life_moment_emotions=tuple(resolved_moment.get("emotions", ())) if resolved_moment else (),
        hook_style_id=_slugify(hook.get("name", "")) if hook else None,
        hook_style_label=hook.get("name") if hook else None,
        objective=str(weekly.get("objective", "")),
        tone="Warm and encouraging" if slot == "morning" else "Calm and reflective",
        emotional_goal=f"Help the reader move from feeling {requested_emotion or canonical_id} toward hope and peace.",
        scripture_theme=str(weekly.get("theme", "")),
        engagement_prompt_type=engagement_type,
        engagement_prompt_id=selected_prompt.get("id") if selected_prompt else None,
        engagement_prompt=selected_prompt.get("prompt") if selected_prompt else None,
        engagement_selection_reason=engagement_selection_reason,
        marketing_enabled=bool(presentation["marketing_enabled"]),
        campaign_compatible=campaign is not None,
        campaign_id=campaign.get("_key") if campaign else None,
        campaign_name=campaign.get("name") if campaign else None,
        creator_search_topic=_creator_search_topic(canonical_id, life_moment_text),
        asset_time_of_day=slot,
        asset_emotional_tone=canonical_id,
        cta_id="primary_invitation",
        cta_text=config.FACEBOOK_CTA,
        destination_url=config.DEFAULT_DESTINATION_URL,
        voice_style_profile="natural_conversational",
        organic_or_paid="organic",
        caption_version="v1",
        resolution_reason=resolution_reason,
        prayer_category_id=prayer_category["id"],
        creative_policy_version=str(
            profile_registry.get("creative_policy_version", "")
        ).strip(),
        prayer_category_resolution_reason=prayer_category_resolution_reason,
        **profile_ids,
    )
