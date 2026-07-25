"""Creative Engine V3 deterministic quality and matching utilities.

This module is intentionally pure/side-effect free so tests can validate
behavior without network or external service dependencies.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

LOCKED_BENEFIT_WORDING = "Get a guided, personalized prayer based on your mood right now."

# Contrast calculations and reporting remain active at all times. This toggle
# controls whether a contrast threshold failure is blocking (critical) or
# non-blocking (warning-only).
CONTRAST_BLOCKING_ENABLED = False

_HEADLINE_GENERIC_PATTERNS = (
    "is a prayer app for you",
    "prayer app",
    "discover prayonit",
    "download prayonit",
)

_TERRITORY_KEYWORDS = {
    "insomnia": ("sleep", "bedtime", "awake", "racing", "night", "insomnia"),
    "financial_stress": ("money", "financial", "bills", "debt"),
    "burnout": ("burnout", "exhaust", "empty", "overwhelmed", "drained"),
    "prayer_difficulty": ("find words", "struggling to pray", "hard to pray", "pray"),
    "confidence": ("confidence", "unsteady", "unsure", "self-doubt"),
    "purpose": ("purpose", "direction", "lost"),
    "loneliness": ("lonely", "alone", "isolated"),
    "guilt": ("guilt", "ashamed", "forgive", "forgiveness"),
    "identity": ("identity", "worth", "self-worth"),
    "gratitude": ("gratitude", "thankful", "thanks", "praise"),
    "family_stress": ("family", "children", "marriage", "parent"),
    "work_stress": ("work", "job", "career"),
}

_TIER_MULTIPLIER = {
    "insomnia": 1.35,
    "financial_stress": 1.30,
    "burnout": 1.30,
    "prayer_difficulty": 1.25,
    "confidence": 1.20,
    "purpose": 1.15,
    "loneliness": 1.12,
    "guilt": 1.12,
    "identity": 1.10,
    "gratitude": 1.08,
    "family_stress": 1.08,
    "work_stress": 1.08,
    "general_encouragement": 0.92,
    "app_discovery": 0.78,
}


# Deterministic, approved fallback pools for one-attempt production headline
# recovery. Avoid generic product language and app-name mentions.
_FALLBACK_HEADLINES_BY_SLOT: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "morning": {
        "insomnia": (
            "Woke Up Restless Today?",
            "Heavy Restless Thoughts This Morning?",
            "Need Rest to Start Today?",
        ),
        "financial_stress": (
            "Bills Weighing on You Today?",
            "Money Pressure This Morning?",
            "Need Peace Over Finances Today?",
        ),
        "burnout": (
            "Running on Empty This Morning?",
            "Feeling Drained Before Noon?",
            "Need Strength for Today?",
        ),
        "prayer_difficulty": (
            "Lost for Prayer Words Today?",
            "Not Sure How to Pray Today?",
            "Prayer Feels Hard This Morning?",
        ),
        "confidence": (
            "Feeling Unsteady This Morning?",
            "Need Courage for Today?",
            "Want to Start Grounded Today?",
        ),
        "purpose": (
            "Need Direction This Morning?",
            "Feeling Stuck About Next Steps?",
            "Looking for Clarity Today?",
        ),
        "loneliness": (
            "Feeling Alone This Morning?",
            "Need Comfort at Daybreak?",
            "Longing for Connection Today?",
        ),
        "guilt": (
            "Carrying Regret This Morning?",
            "Need Mercy to Begin Today?",
            "Still Holding Yesterday's Guilt?",
        ),
        "identity": (
            "Questioning Your Worth Today?",
            "Feeling Unseen This Morning?",
            "Need Truth About Who You Are?",
        ),
        "gratitude": (
            "Want to Begin with Gratitude?",
            "Ready to Thank God Today?",
            "Need a Thankful Start Today?",
        ),
        "general_encouragement": (
            "Carrying Something Heavy Today?",
            "Need Steady Peace This Morning?",
            "Need Strength for What Awaits?",
        ),
    },
    "evening": {
        "insomnia": (
            "Mind Racing at Bedtime?",
            "Still Restless Tonight?",
            "Need Calm Before Sleep Tonight?",
        ),
        "financial_stress": (
            "Money Worries Keeping You Up?",
            "Financial Pressure Tonight?",
            "Need Peace Over Bills Tonight?",
        ),
        "burnout": (
            "Running on Empty Tonight?",
            "Drained by the End of Today?",
            "Need Strength for This Evening?",
        ),
        "prayer_difficulty": (
            "Not Sure How to Pray Tonight?",
            "Prayer Feels Hard Tonight?",
            "Lost for Prayer Words Tonight?",
        ),
        "confidence": (
            "Feeling Unsteady Tonight?",
            "Need Courage This Evening?",
            "Need Steady Peace Before Tomorrow?",
        ),
        "purpose": (
            "Need Direction Tonight?",
            "Feeling Stuck This Evening?",
            "Looking for Clarity Tonight?",
        ),
        "loneliness": (
            "Feeling Alone Tonight?",
            "Need Comfort This Evening?",
            "Longing for Connection Tonight?",
        ),
        "guilt": (
            "Carrying Regret Tonight?",
            "Need Mercy This Evening?",
            "Still Holding Guilt Tonight?",
        ),
        "identity": (
            "Questioning Your Worth Tonight?",
            "Feeling Unseen This Evening?",
            "Need Truth About Your Worth Tonight?",
        ),
        "gratitude": (
            "Want to End with Gratitude?",
            "Ready to Thank God Tonight?",
            "Need a Thankful Ending Today?",
        ),
        "general_encouragement": (
            "Carrying Something Heavy Tonight?",
            "Need Peace Before Bed Tonight?",
            "Need Strength for This Night?",
        ),
    },
}


_FALLBACK_TERRITORY_REQUIRED_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "insomnia": ("sleep", "bed", "rest", "night", "tonight", "restless"),
    "financial_stress": ("money", "bill", "financial", "finance"),
    "burnout": ("empty", "drained", "burn", "strength"),
    "prayer_difficulty": ("prayer", "pray", "words"),
    "confidence": ("courage", "steady", "grounded", "unsteady"),
    "purpose": ("direction", "clarity", "stuck", "steps"),
    "loneliness": ("alone", "connection", "comfort"),
    "guilt": ("guilt", "regret", "mercy"),
    "identity": ("worth", "who you are", "unseen"),
    "gratitude": ("gratitude", "thank", "thankful"),
}


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s?]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_emotional_territory(*, campaign_name: str, pain_point: str = "", goal: str = "") -> str:
    haystack = normalize_text(" ".join([campaign_name, pain_point, goal]))
    for territory, keywords in _TERRITORY_KEYWORDS.items():
        if any(k in haystack for k in keywords):
            return territory
    if "app" in haystack and "download" in haystack:
        return "app_discovery"
    return "general_encouragement"


def territory_weight_multiplier(territory: str) -> float:
    return _TIER_MULTIPLIER.get(territory, 1.0)


def classify_background(path: str) -> Dict[str, Any]:
    name = normalize_text(path)

    time_bucket = "neutral"
    if any(k in name for k in ("night", "stars", "starfield", "moon", "bedtime", "evening")):
        time_bucket = "night"
    elif any(k in name for k in ("morning", "sunrise", "dawn")):
        time_bucket = "morning"
    elif any(k in name for k in ("sunset", "dusk")):
        time_bucket = "evening"
    elif any(k in name for k in ("day", "noon", "afternoon")):
        time_bucket = "daytime"

    visual_types = []
    visual_map = {
        "starfield": ("star", "stars", "starfield", "night"),
        "sunrise": ("sunrise", "dawn"),
        "sunset": ("sunset", "dusk"),
        "mountain": ("mountain", "peak", "ridge"),
        "valley": ("valley", "river", "canyon"),
        "desert": ("desert", "canyon", "sand"),
        "forest": ("forest", "trees", "woods"),
        "ocean": ("ocean", "sea", "beach"),
        "city": ("city", "urban", "street"),
        "clouds": ("cloud", "sky", "mist", "fog"),
    }
    for vtype, tokens in visual_map.items():
        if any(t in name for t in tokens):
            visual_types.append(vtype)
    if not visual_types:
        visual_types = ["other"]

    suitability = {"general encouragement"}
    if "starfield" in visual_types or time_bucket == "night":
        suitability.update({"anxiety", "insomnia", "prayer difficulty"})
    if "sunrise" in visual_types or "valley" in visual_types:
        suitability.update({"confidence", "gratitude", "general encouragement"})
    if "desert" in visual_types:
        suitability.update({"burnout", "purpose", "prayer difficulty"})
    if "mountain" in visual_types or "clouds" in visual_types:
        suitability.update({"purpose", "loneliness", "guilt"})

    return {
        "time": time_bucket,
        "visual_types": visual_types,
        "emotional_suitability": sorted(suitability),
    }


def background_match_score(
    *,
    background_meta: Dict[str, Any],
    territory: str,
    slot: str,
) -> float:
    score = 0.0
    time = background_meta.get("time", "neutral")
    visuals = set(background_meta.get("visual_types", []))
    suitability = set(background_meta.get("emotional_suitability", []))

    if slot == "evening" and time in ("evening", "night", "neutral"):
        score += 1.5
    elif slot == "morning" and time in ("morning", "daytime", "neutral"):
        score += 1.5

    territory_label = territory.replace("_", " ")
    if territory_label in suitability:
        score += 2.0

    if territory == "insomnia" and "starfield" in visuals:
        score += 1.5
    if territory == "confidence" and ("sunrise" in visuals or "valley" in visuals):
        score += 1.2
    if territory == "burnout" and ("desert" in visuals or "valley" in visuals):
        score += 1.2
    if territory == "purpose" and ("mountain" in visuals or "clouds" in visuals):
        score += 1.0

    return score


def deterministic_headline_shorten(headline: str, max_chars: int = 45) -> str:
    text = (headline or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("??", "?")
    if len(text) <= max_chars:
        return text

    # Keep first clause before punctuation/joiners when possible.
    split_candidates = re.split(r"[,:;]|\band\b|\bbut\b", text, maxsplit=1, flags=re.IGNORECASE)
    text = split_candidates[0].strip() if split_candidates else text

    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" ,.;:-")

    if "?" in headline and "?" not in text:
        text = text.rstrip(".!") + "?"
    return text


def validate_headline_quality(
    headline: str,
    *,
    max_chars: int = 45,
    recent_headlines: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    h = (headline or "").strip()
    norm = normalize_text(h)
    words = [w for w in norm.replace("?", "").split() if w]
    issues: List[str] = []

    if not h:
        issues.append("empty")
    if len(h) > max_chars:
        issues.append("too_long")
    q_count = h.count("?")
    if q_count > 1:
        issues.append("multiple_questions")
    if len(words) < 3 or len(words) > 8:
        issues.append("word_count_out_of_range")
    if any(p in norm for p in _HEADLINE_GENERIC_PATTERNS):
        issues.append("generic_product_language")
    if "prayonit" in norm:
        issues.append("includes_app_name")

    if recent_headlines:
        for rh in recent_headlines:
            ratio = SequenceMatcher(None, normalize_text(rh), norm).ratio()
            if ratio >= 0.86:
                issues.append("near_duplicate_recent")
                break

    shortened = deterministic_headline_shorten(h, max_chars=max_chars)
    return {
        "headline": h,
        "normalized": norm,
        "shortened": shortened,
        "accepted": len(issues) == 0,
        "issues": issues,
    }


def identify_headline_failure_reason(
    *,
    headline: str,
    issues: Iterable[str],
    territory: str,
) -> str:
    issue_set = set(issues or [])
    if "near_duplicate_recent" in issue_set:
        return "recent_duplicate"
    if "generic_product_language" in issue_set or "includes_app_name" in issue_set:
        return "generic_headline"
    if "too_long" in issue_set or "word_count_out_of_range" in issue_set:
        return "excessive_length"
    if "multiple_questions" in issue_set or "empty" in issue_set:
        return "invalid_formatting"

    required = _FALLBACK_TERRITORY_REQUIRED_KEYWORDS.get(territory, ())
    norm = normalize_text(headline)
    if required and not any(tok in norm for tok in required):
        return "territory_mismatch"
    return "other_headline_quality_failure"


def _rotated(items: Tuple[str, ...], offset: int) -> List[str]:
    if not items:
        return []
    n = len(items)
    k = offset % n
    return list(items[k:] + items[:k])


def deterministic_fallback_candidates(
    *,
    slot: str,
    territory: str,
    date_key: str,
    run_id: str,
) -> List[str]:
    slot_key = slot if slot in _FALLBACK_HEADLINES_BY_SLOT else "morning"
    slot_pool = _FALLBACK_HEADLINES_BY_SLOT[slot_key]
    territory_key = territory if territory in slot_pool else "general_encouragement"
    items = slot_pool[territory_key]
    seed = f"{slot_key}|{territory_key}|{date_key}|{run_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16)
    return _rotated(items, offset)


def select_recovered_headline(
    *,
    slot: str,
    territory: str,
    date_key: str,
    run_id: str,
    recent_headlines: Iterable[str],
    max_chars: int = 45,
    original_headline: Optional[str] = None,
) -> Optional[str]:
    """Recover a headline that failed quality validation.

    Recovery first tries to shorten `original_headline` (preserving its
    topic) via deterministic_headline_shorten(). Only if that shortened
    headline still fails quality validation (or no original_headline is
    given) does this fall back to the static, territory-keyed fallback
    pool below -- which is topic-generic (e.g. "purpose"/"loneliness") and
    may not match the original headline's specific subject (for example a
    friendship-related headline), so it is used only as a last resort.

    Candidates from the fallback pool are tried in deterministic rotated
    order; each candidate is validated with the existing headline-quality
    validator.
    """
    if original_headline:
        shortened = deterministic_headline_shorten(original_headline, max_chars=max_chars)
        report = validate_headline_quality(
            shortened,
            max_chars=max_chars,
            recent_headlines=recent_headlines,
        )
        if report.get("accepted"):
            return shortened

    for candidate in deterministic_fallback_candidates(
        slot=slot,
        territory=territory,
        date_key=date_key,
        run_id=run_id,
    ):
        report = validate_headline_quality(
            candidate,
            max_chars=max_chars,
            recent_headlines=recent_headlines,
        )
        if report.get("accepted"):
            return candidate
    return None


def validate_fallback_headline_pools() -> List[str]:
    """Validate static fallback pools for safety and quality.

    Returns a list of error strings; empty list means valid.
    """
    errors: List[str] = []
    for slot, by_territory in _FALLBACK_HEADLINES_BY_SLOT.items():
        for territory, pool in by_territory.items():
            if not pool:
                errors.append(f"empty_pool:{slot}:{territory}")
                continue
            required = _FALLBACK_TERRITORY_REQUIRED_KEYWORDS.get(territory, ())
            for idx, headline in enumerate(pool):
                key = f"{slot}:{territory}:{idx}"
                if not (headline or "").strip():
                    errors.append(f"empty_headline:{key}")
                    continue
                report = validate_headline_quality(headline, max_chars=45, recent_headlines=[])
                disallowed_issues = {
                    "too_long",
                    "word_count_out_of_range",
                    "multiple_questions",
                    "includes_app_name",
                    "generic_product_language",
                    "empty",
                }
                bad = [i for i in report.get("issues", []) if i in disallowed_issues]
                if bad:
                    errors.append(f"invalid_quality:{key}:{','.join(sorted(set(bad)))}")
                norm = normalize_text(headline)
                if required and not any(tok in norm for tok in required):
                    errors.append(f"territory_keyword_mismatch:{key}")
    return errors


def is_near_duplicate_headline(candidate: str, previous: str, threshold: float = 0.86) -> bool:
    return SequenceMatcher(None, normalize_text(candidate), normalize_text(previous)).ratio() >= threshold


def validate_locked_benefit(copy: Dict[str, str]) -> bool:
    return (copy.get("app_benefit", "").strip() == LOCKED_BENEFIT_WORDING and
            copy.get("story_app_benefit", "").strip() == LOCKED_BENEFIT_WORDING)


def build_prepublish_qa_report(
    *,
    ad_copy: Dict[str, str],
    slot: str,
    campaign_name: str,
    background_path: str,
    background_meta: Dict[str, Any],
    territory: str,
    recent_headlines: Iterable[str],
    has_badges: bool,
    contrast_metrics: Dict[str, Any],
    captions: Dict[str, str],
) -> Dict[str, Any]:
    warnings: List[str] = []
    critical: List[str] = []

    if not validate_locked_benefit(ad_copy):
        critical.append("locked_benefit_mismatch")

    hq = validate_headline_quality(ad_copy.get("pain_headline", ""), recent_headlines=recent_headlines)
    if not hq["accepted"]:
        critical.append("headline_quality_failed")

    if not has_badges:
        critical.append("missing_store_badges")

    if not contrast_metrics.get("overall_pass", False):
        if CONTRAST_BLOCKING_ENABLED:
            critical.append("contrast_threshold_failed")
        else:
            warnings.append("contrast_threshold_failed")

    match_score = background_match_score(background_meta=background_meta, territory=territory, slot=slot)
    if match_score < 1.5:
        warnings.append("background_message_mismatch")

    _LEGACY_DOWNLOAD_PHRASES = (
        "download prayonit",
        "download the app",
        "install prayonit",
        "get the app",
    )
    for platform, text in captions.items():
        lower = text.lower()
        if lower.count("download prayonit") > 1:
            warnings.append(f"duplicate_cta_{platform}")
        for phrase in _LEGACY_DOWNLOAD_PHRASES:
            if phrase in lower:
                critical.append(f"legacy_download_cta_{platform}")
                break
        if lower.count("14-day") > 1 and lower.count("trial") > 1:
            warnings.append(f"duplicate_trial_{platform}")

    score = 100
    score -= 20 * len(critical)
    score -= 6 * len(warnings)
    score = max(0, score)

    return {
        "campaign": campaign_name,
        "slot": slot,
        "background": background_path,
        "territory": territory,
        "background_meta": background_meta,
        "match_score": round(match_score, 2),
        "contrast_metrics": contrast_metrics,
        "warnings": warnings,
        "critical_failures": critical,
        "score": score,
        "pass": len(critical) == 0,
    }


def should_block_buffer(report: Dict[str, Any]) -> bool:
    return bool(report.get("critical_failures"))
