"""Policy helpers for Prayonit's contained Tuesday/Thursday marketing lane."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence


DIRECT_MARKETING_CONTENT_TYPE = "direct_marketing"
DIRECT_MARKETING_VIDEO_TEMPLATE = "direct_marketing_short"
DIRECT_MARKETING_HASHTAG_PROFILE = "direct_marketing"
DIRECT_MARKETING_DURATION_SECONDS = 8.0
DIRECT_MARKETING_CTA = "Prayonit · Link in bio"
DIRECT_MARKETING_NARRATION_TARGET_MIN_WORDS = 16
DIRECT_MARKETING_NARRATION_TARGET_MAX_WORDS = 22
DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS = 24

TUESDAY_FAMILIES = (
    "product_demo",
    "product_announcement",
    "testimonial_curiosity",
)
THURSDAY_FAMILIES = (
    "pain_to_product",
    "feature_benefit",
    "testimonial_curiosity",
)
APPROVED_FAMILIES = frozenset((*TUESDAY_FAMILIES, *THURSDAY_FAMILIES))

_FAMILY_DEFAULTS = {
    "product_demo": {
        "opening_hook": "See what this prayer app does.",
        "follow_up_card": "Choose how you feel.",
    },
    "product_announcement": {
        "opening_hook": "Meet Prayonit: prayer for how you feel.",
        "follow_up_card": "Start with your real emotion.",
    },
    "testimonial_curiosity": {
        "opening_hook": "I didn't expect a prayer app to do this.",
        "follow_up_card": "See how Prayonit starts with your mood.",
    },
    "pain_to_product": {
        "opening_hook": "Don't know what to pray?",
        "follow_up_card": "Tell Prayonit how you feel.",
    },
    "feature_benefit": {
        "opening_hook": "Turn your mood into a prayer starting point.",
        "follow_up_card": "Start with how you feel.",
    },
}

_VAGUE_DEVOTIONAL_HOOKS = {
    "pause and bring your worry here",
    "facing a difficult choice",
    "feeling unsure of yourself today",
    "need steady peace this morning",
    "praying for provision",
}
_DIRECT_HOOK_TERMS = (
    "app",
    "prayonit",
    "guided prayer",
    "how you feel",
    "your mood",
    "what to pray",
    "words to pray",
    "praying feel",
    "prayer starting point",
)
_FABRICATED_TESTIMONIAL_PATTERNS = (
    re.compile(r"\b(?:customers?|users?)\s+(?:say|said|love|report)\b", re.I),
    re.compile(r"\b(?:five[- ]star|5[- ]star|rated\s+5)\b", re.I),
    re.compile(r"\b(?:thousands|millions)\s+of\s+(?:users|people)\b", re.I),
    re.compile(r"\bchanged\s+(?:my|their)\s+life\b", re.I),
    re.compile(r"\bverified\s+testimonial\b", re.I),
)

_SPOKEN_HOOKS = {
    "product_demo": "See Prayonit in action.",
    "product_announcement": "Meet Prayonit for real emotions.",
    "testimonial_curiosity": "This prayer app surprised me.",
    "pain_to_product": "Need words to pray?",
    "feature_benefit": "Turn your mood into prayer.",
}
_SPOKEN_ACTIONS = {
    "product_demo": "Choose how you feel.",
    "product_announcement": "Choose your feeling.",
    "testimonial_curiosity": "Choose your feeling.",
    "pain_to_product": "Tell Prayonit your feeling.",
    "feature_benefit": "Choose your feeling.",
}
_COMPACT_SPOKEN_ACTIONS = {
    "product_demo": "Choose your feeling.",
    "product_announcement": "Choose your feeling.",
    "testimonial_curiosity": "Choose your feeling.",
    "pain_to_product": "Tell Prayonit your feeling.",
    "feature_benefit": "Start with your mood.",
}
_COMPACT_SPOKEN_HOOKS = {
    **_SPOKEN_HOOKS,
    "pain_to_product": "Need words to pray?",
    "feature_benefit": "Mood to prayer.",
}


@dataclass(frozen=True)
class MarketingCard:
    text: str
    start: float
    end: float
    source_field: str


@dataclass(frozen=True)
class DirectMarketingNarrationSegment:
    text: str
    start: float
    end: float
    source_field: str


def resolve_marketing_family(
    *,
    post_date: str,
    slot: str,
    configured_families: Sequence[str],
    override: str = "",
) -> str:
    """Return a deterministic family without making the prompt choose one."""
    families = tuple(
        family for family in configured_families if family in APPROVED_FAMILIES
    )
    if not families:
        raise RuntimeError("Direct-marketing schedule has no approved hook families.")
    if override:
        if override not in APPROVED_FAMILIES:
            raise RuntimeError(f"Unknown direct-marketing profile override: {override}")
        if override not in families:
            raise RuntimeError(
                f"Direct-marketing profile override {override} is not approved for this day."
            )
        return override
    day_number = date.fromisoformat(post_date).toordinal()
    slot_offset = 1 if slot == "evening" else 0
    return families[(day_number + slot_offset) % len(families)]


def has_fabricated_testimonial_claim(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _FABRICATED_TESTIMONIAL_PATTERNS)


def normalize_direct_marketing_copy(
    ad_copy: Dict[str, Any],
    *,
    marketing_family: str,
    direct_cta: str = DIRECT_MARKETING_CTA,
    audio_profile: str = "current_default",
) -> Dict[str, Any]:
    """Populate direct-only fields without changing devotional copy contracts."""
    if marketing_family not in APPROVED_FAMILIES:
        raise RuntimeError(f"Unknown direct-marketing family: {marketing_family}")
    defaults = _FAMILY_DEFAULTS[marketing_family]
    normalized = dict(ad_copy)
    normalized["marketing_family"] = marketing_family
    normalized["opening_hook"] = (
        str(normalized.get("opening_hook", "")).strip()
        or defaults["opening_hook"]
    )
    normalized["follow_up_card"] = (
        str(normalized.get("follow_up_card", "")).strip()
        or str(normalized.get("product_action", "")).strip()
        or defaults["follow_up_card"]
    )
    normalized["product_action"] = (
        str(normalized.get("product_action", "")).strip()
        or normalized["follow_up_card"]
    )
    normalized["app_benefit"] = (
        str(normalized.get("app_benefit", "")).strip()
        or "Get a guided, personalized prayer based on your mood right now."
    )
    normalized["brand_card"] = (
        str(normalized.get("brand_card", "")).strip() or "Prayonit"
    )
    normalized["direct_cta"] = direct_cta
    raw_sequence = normalized.get("screenshot_sequence", [])
    normalized["screenshot_sequence"] = (
        [str(item).strip() for item in raw_sequence if str(item).strip()]
        if isinstance(raw_sequence, list)
        else []
    )
    normalized["audio_profile"] = (
        str(normalized.get("audio_profile", "")).strip() or audio_profile
    )
    return normalized


def _compact_benefit(app_benefit: str) -> str:
    lower = app_benefit.lower()
    if "scripture" in lower or "devotion" in lower or "journal" in lower:
        return "Prayonit gives you Scripture, devotion, and guided prayer."
    return "Prayonit gives you a guided prayer for your mood."


def _ensure_sentence(text: str) -> str:
    cleaned = " ".join(str(text).split()).strip()
    if cleaned and cleaned[-1] not in ".!?":
        return cleaned + "."
    return cleaned


def _spoken_hook(ad_copy: Dict[str, Any], family: str) -> str:
    # Family-specific equivalents preserve the generated hook's role while
    # keeping the first spoken phrase inside its 1.5-second visual region.
    _ = ad_copy
    return _SPOKEN_HOOKS[family]


def build_direct_marketing_narration_segments(
    ad_copy: Dict[str, Any],
    *,
    word_limit: int = DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS,
) -> List[DirectMarketingNarrationSegment]:
    """Build a concise spoken equivalent of the four visual cards."""
    family = str(ad_copy.get("marketing_family", "")).strip()
    if family not in APPROVED_FAMILIES:
        raise RuntimeError(
            "Cannot build direct-marketing narration for an unknown family."
        )
    effective_limit = max(
        DIRECT_MARKETING_NARRATION_TARGET_MIN_WORDS,
        min(DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS, int(word_limit)),
    )
    phrases = [
        _spoken_hook(ad_copy, family),
        _SPOKEN_ACTIONS[family],
        "Get Scripture and prayer.",
        "Prayonit. Link in bio.",
    ]
    if sum(len(phrase.split()) for phrase in phrases) > effective_limit:
        phrases[1] = _COMPACT_SPOKEN_ACTIONS[family]
        phrases[2] = "Get Scripture and prayer."
    if sum(len(phrase.split()) for phrase in phrases) > effective_limit:
        phrases[0] = _COMPACT_SPOKEN_HOOKS[family]
    word_count = sum(len(phrase.split()) for phrase in phrases)
    if word_count > effective_limit:
        raise RuntimeError(
            "Direct-marketing narration cannot fit the configured word limit "
            "without dropping a required message segment."
        )

    cards = build_direct_marketing_cards(ad_copy)
    return [
        DirectMarketingNarrationSegment(
            text=_ensure_sentence(phrase),
            start=card.start,
            end=card.end,
            source_field=card.source_field,
        )
        for phrase, card in zip(phrases, cards)
    ]


def build_direct_marketing_narration_text(
    ad_copy: Dict[str, Any],
    *,
    word_limit: int = DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS,
) -> str:
    return " ".join(
        segment.text
        for segment in build_direct_marketing_narration_segments(
            ad_copy,
            word_limit=word_limit,
        )
    )


def build_direct_marketing_tts_copy(
    ad_copy: Dict[str, Any],
    *,
    word_limit: int = DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS,
) -> Dict[str, Any]:
    """Map direct phrases into the voice provider's validated transcript shape."""
    segments = build_direct_marketing_narration_segments(
        ad_copy,
        word_limit=word_limit,
    )
    tts_copy = dict(ad_copy)
    tts_copy.update(
        {
            "opening_hook": segments[0].text,
            "bridge_line": segments[1].text,
            "script_segments": [segments[2].text],
            "closing_line": segments[3].text,
            "long_form_type": "none",
        }
    )
    return tts_copy


def validate_direct_marketing_narration(
    ad_copy: Dict[str, Any],
    narration_text: str,
    narration_segments: Sequence[DirectMarketingNarrationSegment],
    *,
    word_limit: int = DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS,
    expected_cta: str = DIRECT_MARKETING_CTA,
) -> List[str]:
    failures: List[str] = []
    transcript = str(narration_text).strip()
    expected_sources = (
        "opening_hook",
        "follow_up_card",
        "app_benefit",
        "direct_cta",
    )
    if not transcript:
        failures.append("narration_script_missing")
    if len(transcript.split()) > min(
        DIRECT_MARKETING_NARRATION_HARD_MAX_WORDS,
        int(word_limit),
    ):
        failures.append("narration_word_limit_exceeded")
    if tuple(segment.source_field for segment in narration_segments) != (
        expected_sources
    ):
        failures.append("narration_segment_order_invalid")

    search_start = 0
    for segment in narration_segments:
        found_at = transcript.find(segment.text, search_start)
        if found_at < 0:
            failures.append("narration_segment_text_misaligned")
            break
        search_start = found_at + len(segment.text)

    spoken_cta = (
        narration_segments[-1].text if narration_segments else ""
    ).lower()
    if "prayonit" not in spoken_cta:
        failures.append("spoken_cta_missing_prayonit")
    lowered = transcript.lower()
    if "come pray with me" in lowered or (
        "prayonit" not in lowered
        and "prayer app" not in lowered
    ):
        failures.append("narration_is_devotional_only")
    if has_fabricated_testimonial_claim(transcript):
        failures.append("fabricated_testimonial_claim")
    if validate_direct_marketing_copy(
        ad_copy,
        expected_cta=expected_cta,
    ):
        failures.append("narration_source_copy_failed_qa")
    return list(dict.fromkeys(failures))


def build_direct_marketing_cards(
    ad_copy: Dict[str, Any],
    *,
    direct_cta: str = DIRECT_MARKETING_CTA,
) -> List[MarketingCard]:
    """Build the fixed four-card product sequence for the dedicated renderer."""
    return [
        MarketingCard(
            str(ad_copy.get("opening_hook", "")).strip(),
            0.0,
            1.5,
            "opening_hook",
        ),
        MarketingCard(
            str(ad_copy.get("follow_up_card", "")).strip(),
            1.5,
            3.0,
            "follow_up_card",
        ),
        MarketingCard(
            _compact_benefit(str(ad_copy.get("app_benefit", "")).strip()),
            3.0,
            6.5,
            "app_benefit",
        ),
        MarketingCard(
            direct_cta,
            6.5,
            DIRECT_MARKETING_DURATION_SECONDS,
            "direct_cta",
        ),
    ]


def validate_direct_marketing_copy(
    ad_copy: Dict[str, Any],
    *,
    cards: Optional[Iterable[MarketingCard]] = None,
    expected_cta: str = DIRECT_MARKETING_CTA,
) -> List[str]:
    failures: List[str] = []
    family = str(ad_copy.get("marketing_family", "")).strip()
    hook = str(ad_copy.get("opening_hook", "")).strip()
    normalized_hook = " ".join(re.sub(r"[^a-z0-9]+", " ", hook.lower()).split())
    follow_up = str(ad_copy.get("follow_up_card", "")).strip()
    benefit = str(ad_copy.get("app_benefit", "")).strip()
    direct_cta = str(ad_copy.get("direct_cta", "")).strip()
    resolved_cards = list(
        cards
        or build_direct_marketing_cards(
            ad_copy,
            direct_cta=expected_cta,
        )
    )

    if family not in APPROVED_FAMILIES:
        failures.append("unknown_marketing_family")
    if not hook:
        failures.append("opening_hook_missing")
    elif len(hook.split()) > 12:
        failures.append("opening_hook_too_long")
    immediate_product_connection = (
        family == "pain_to_product" and "prayonit" in follow_up.lower()
    )
    if (
        normalized_hook in _VAGUE_DEVOTIONAL_HOOKS
        and not immediate_product_connection
    ):
        failures.append("opening_hook_is_devotional_only")
    if (
        hook
        and not any(term in normalized_hook for term in _DIRECT_HOOK_TERMS)
        and not immediate_product_connection
    ):
        failures.append("opening_hook_lacks_direct_marketing_signal")
    if family == "testimonial_curiosity" and has_fabricated_testimonial_claim(hook):
        failures.append("fabricated_testimonial_claim")
    if not follow_up:
        failures.append("follow_up_card_missing")
    if not benefit or not any(
        term in benefit.lower()
        for term in ("prayer", "scripture", "devotion", "journal", "mood", "feel")
    ):
        failures.append("app_benefit_missing_or_vague")
    if len(resolved_cards) not in {3, 4}:
        failures.append("invalid_primary_card_count")
    if any(card.end <= card.start or card.end - card.start < 1.25 for card in resolved_cards):
        failures.append("card_dwell_time_too_short")
    if any(
        left.end > right.start
        for left, right in zip(resolved_cards, resolved_cards[1:])
    ):
        failures.append("card_timing_overlap")
    if not any(card.source_field == "app_benefit" for card in resolved_cards[:-1]):
        failures.append("app_benefit_not_visible_before_cta")
    if not any("prayonit" in card.text.lower() for card in resolved_cards):
        failures.append("brand_name_missing")
    if direct_cta != expected_cta:
        failures.append("direct_cta_invalid")
    if "come pray with me" in direct_cta.lower():
        failures.append("devotional_cta_used")
    return list(dict.fromkeys(failures))


def build_direct_marketing_caption(ad_copy: Dict[str, Any], platform: str) -> str:
    """Return a product-first base caption; platform CTA/URL is added later."""
    hook = str(ad_copy.get("opening_hook", "")).strip()
    product_sentence = (
        "Tell Prayonit how you feel and receive Scripture, a devotional, "
        "and a guided prayer based on your mood."
    )
    if platform == "facebook":
        return f"{hook}\n\n{product_sentence}".strip()
    return product_sentence
