"""Resolve one canonical content identity before generation or rendering."""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import config
from engines import content_engine


_ALIASES_PATH = Path(__file__).resolve().parent / "creative" / "pain_point_aliases.json"
_ENGAGEMENT_PROMPTS_PATH = Path(__file__).resolve().parent / "creative" / "engagement_prompt_profiles.json"
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
    results = []
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
    )
