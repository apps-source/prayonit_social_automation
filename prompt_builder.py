"""Gemini prompt construction and platform-specific caption assembly (Part 12)."""
import json
import random
import re
from typing import Any, Dict, Optional

import creative_engine_v3
from google import genai
from google.genai import types

import config

_gemini_client: Optional[genai.Client] = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


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


def build_prompt(
    *,
    post_type: str,
    selection: Dict[str, Any],
    slot: str,
    tracked_url: str,
) -> str:
    campaign = selection["campaign"]
    formula = selection.get("formula")
    persona = selection.get("persona")
    seasonal_context = selection.get("seasonal_context")
    spiritual_action = selection.get("spiritual_action", "Give today's burdens to God in prayer.")

    formula_block = ""
    if formula:
        formula_block = f"""
Use this proven advertising formula as the structural guide (do not label the
sections in the output, just follow the flow): {formula['name']} -
{formula['description']}
Structure: {' -> '.join(formula.get('structure', []))}
Avoid: {'; '.join(formula.get('avoid', []))}
"""

    persona_block = ""
    if persona:
        persona_block = f"""
Write with this audience in mind: {persona['name']} - {persona['description']}
Preferred tone: {persona['preferred_tone']}
Do not make assumptions about the reader's diagnosis or condition. Avoid: {'; '.join(persona.get('avoid', []))}
"""

    seasonal_block = f"\nSeasonal context to weave in naturally, if relevant: {seasonal_context}\n" if seasonal_context else ""

    brand_preamble = build_brand_brain_preamble(config.BRAND_RULES)

    return f"""
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

Create ONE {post_type} acquisition ad intended to drive app downloads,
following this exact message hierarchy:
Pain or emotional need -> Spiritual action -> How Prayonit helps -> Download
action -> 14-day free-trial support.

This is advertising, not a sermon and not a verse-of-the-day post.
Campaign: {campaign['name']} (goal: {campaign['goal']})
Pain point: {campaign.get('pain_point', '')}
Emotional promise: {campaign.get('emotional_promise', '')}
Hook inspiration: {selection['hook']}
Body angle inspiration: {selection['body_angle']}
CTA inspiration: {selection['cta']}

Approved spiritual action (use this exact sentence, or only light grammar
adaptation of it — never invent a new theological claim, and never replace
it with a different spiritual claim): "{spiritual_action}"
{formula_block}{persona_block}{seasonal_block}{build_time_guidance(slot)}
A real destination link will be appended automatically after you respond, so:
- Do NOT include any URL, link, or web address in facebook_caption,
  instagram_caption, or threads_caption.
- Do NOT invent, guess, shorten, rewrite, or substitute any domain or URL
  (for example, do not output "prayonit.com" or any other made-up link).
- Prayonit does not lead with a direct "download the app" instruction.
  Prayonit invites people into a moment with God. If you need to reference
  how someone gets started, say things like "come pray with me" or "join
  me in prayer" — never "download Prayonit," "install Prayonit," "get the
  app," or "download the app." The real link/CTA is inserted by the
  system, not by you.

Requirements:
- brand_header: 1 to 3 short words, normally "PRAYONIT".
- pain_headline: powerful scroll-stopping question or statement naming the
  pain/emotional need, maximum 9 words, short enough for mobile.
- spiritual_action: the approved spiritual action sentence above, adapted
  only in light grammar/phrasing if needed. Must still describe the user
  praying to God (giving/bringing/laying something before God, seeking
  God's guidance, thanking God, or similar) — never God acting toward the
  user.
- app_benefit: must directly answer pain_headline. Always include "guided"
  or "personalized prayer" and a connection to the user's current mood,
  feelings, worries, gratitude, or situation. Example matching pain_headline
  "Need rest tonight?": "Get a guided, personalized prayer to help you end
  your day in peace."
- download_cta: must be exactly "{config.PRIMARY_CTA}" (Prayonit invites
  people into a moment with God rather than leading with a download
  instruction; this is an invitation, not a store-download button label).
- trial_support: must explicitly say "14-day free trial" (for example:
  "Start your 14-day free trial today."). Never say "try it free today,"
  "download for free," or any free-trial phrase that omits the 14-day limit.
- facebook_caption: 35 to 70 words, natural and persuasive, following the
  pain -> spiritual action -> benefit -> invitation -> trial flow, ending
  with an invitation to pray, not a download instruction. No hashtags.
  Mention the 14-day free trial at most once.
- instagram_caption: shorter and punchier than facebook_caption, 20 to 45
  words, no hashtags (hashtags are added separately). Mention the 14-day
  free trial at most once.
- threads_caption: conversational, shorter than facebook_caption, 15 to 35
  words, no hashtags (hashtags are added separately). Mention the 14-day
  free trial at most once.
- story_headline: very short, maximum 6 words, for a vertical Story image.
- story_spiritual_action: very short version of spiritual_action, maximum 8 words.
- story_app_benefit: very short version of app_benefit, maximum 12 words,
  readable in at most three lines.
- story_download_cta: must be exactly "{config.PRIMARY_CTA}".
- story_trial_support: compact free-trial phrase, maximum 6 words, must say
  "14-day free trial" or "14-day trial" exactly (for example:
  "Start your 14-day free trial.").
- Do not make unverifiable claims.
- Do not promise divine outcomes.
- Do not say the app replaces God, church, clergy, therapy, or medical care.
- Do not use fake statistics, fake testimonials, or fake user counts.
- Avoid repeating the exact phrase "Scripture-inspired prayers" every time.
- Output valid JSON only with keys: brand_header, pain_headline,
  spiritual_action, app_benefit, download_cta, trial_support,
  facebook_caption, instagram_caption, threads_caption, story_headline,
  story_spiritual_action, story_app_benefit, story_download_cta,
  story_trial_support.
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
    "threads_caption",
    "story_headline",
    "story_spiritual_action",
    "story_app_benefit",
    "story_download_cta",
    "story_trial_support",
)

_LEGACY_REQUIRED_AD_COPY_KEYS = (
    "brand_header",
    "pain_headline",
    "spiritual_action",
    "app_benefit",
    "download_cta",
    "trial_support",
    "facebook_caption",
    "instagram_caption",
    "threads_caption",
    "story_headline",
    "story_spiritual_action",
    "story_app_benefit",
    "story_download_cta",
    "story_trial_support",
)

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
    "threads_caption",
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
    "threads_caption",
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


# Explicit forbidden free-trial phrases, checked in addition to the generic
# "mentions trial/free but omits the 14-day duration" rule below. These
# overlap with brand_rules['never_say'] but are kept here too so story_cta
# (which is enforced with its own compact phrase, not the generic
# never_say -> preferred_cta substitution) is still protected.
TRIAL_WORDING_VIOLATIONS = [
    "try it free today",
    "download for free",
    "free app",
    "try prayonit free",
    "100% free",
    "always free",
    "unlimited free",
    "free forever",
]


def enforce_trial_duration(text: str, brand_rules: Dict[str, Any]) -> str:
    """Ensure a caption never contains free-trial wording that omits the
    14-day duration. If a known violation phrase is found, or the text
    mentions "trial"/"free" without also mentioning "14-day", the entire
    field is replaced with the brand's preferred CTA (which always includes
    the 14-day duration).
    """
    preferred_cta = brand_rules.get("preferred_cta", "Start your 14-day free trial.")
    lower = text.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return preferred_cta
    if _mentions_trial_or_free(text) and not _contains_14_day_duration(text):
        return preferred_cta
    return text


def enforce_story_cta_trial_wording(story_cta: str, brand_rules: Dict[str, Any]) -> str:
    """Ensure story_cta never contains free-trial wording that omits the
    14-day duration, using the compact Story-appropriate phrase
    ("Start your 14-day trial.") instead of the longer preferred_cta, since
    story_cta must stay short (max 4 words).
    """
    compact_phrase = brand_rules.get("compact_trial_phrase", "Start your 14-day trial.")
    lower = story_cta.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return compact_phrase
    if _mentions_trial_or_free(story_cta) and not _contains_14_day_duration(story_cta):
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
    """Ensure trial_support/story_trial_support explicitly says the 14-day
    free trial. Falls back to an approved phrase if missing or malformed.
    """
    fallback = (
        brand_rules.get("compact_trial_phrase", "Start your 14-day trial.")
        if compact
        else "Start your 14-day free trial today."
    )
    text = (text or "").strip()
    if not text:
        return fallback
    lower = text.lower()
    if any(phrase in lower for phrase in TRIAL_WORDING_VIOLATIONS):
        return fallback
    if not _contains_14_day_duration(text):
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


def generate_ad_copy(
    *,
    post_type: str,
    selection: Dict[str, Any],
    slot: str,
    tracked_url: str,
) -> Dict[str, str]:
    prompt = build_prompt(
        post_type=post_type, selection=selection, slot=slot, tracked_url=tracked_url
    )

    client = _get_gemini_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=1.0,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
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

    ad_copy = {key: str(data[key]).strip() for key in REQUIRED_AD_COPY_KEYS}
    return apply_brand_enforcement(ad_copy, config.BRAND_RULES)


def generate_local_ad_copy(*, selection: Dict[str, Any], slot: str) -> Dict[str, str]:
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
    spiritual_action = selection.get("spiritual_action", "Give your worries to God.")
    ad_copy = {
        "brand_header": "PRAYONIT",
        "pain_headline": pain_headline,
        "spiritual_action": spiritual_action,
        "app_benefit": LOCKED_APP_BENEFIT,
        "download_cta": config.PRIMARY_CTA,
        "trial_support": "Start your 14-day free trial today.",
        "facebook_caption": (
            f"{pain_headline} {spiritual_action} {LOCKED_APP_BENEFIT} "
            "Come pray with me and start your 14-day free trial."
        ),
        "instagram_caption": f"{pain_headline} {spiritual_action} {LOCKED_APP_BENEFIT}",
        "threads_caption": f"{pain_headline} {spiritual_action} {LOCKED_APP_BENEFIT}",
        "story_headline": pain_headline,
        "story_spiritual_action": spiritual_action,
        "story_app_benefit": LOCKED_STORY_APP_BENEFIT,
        "story_download_cta": config.PRIMARY_CTA,
        "story_trial_support": "Start your 14-day free trial.",
    }
    return apply_brand_enforcement(ad_copy, config.BRAND_RULES)


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


# Sentences/phrases that duplicate the 14-day free trial CTA the system
# always appends to the Instagram caption. Matched case-insensitively
# against whole sentences (split on ., !, ?) so wording variations Gemini
# might produce (e.g. "Get Prayonit today and start your 14-day free
# trial.") are removed before the exact required CTA is appended, avoiding
# duplicate trial-wording sentences in the final caption.
_DUPLICATE_TRIAL_CTA_PATTERN = re.compile(
    r"\b(start|begin|try)\b.{0,80}?\b14-?\s*day\b.{0,40}?\b(free\s+)?trial\b",
    flags=re.IGNORECASE,
)


def _strip_duplicate_trial_cta_sentences(text: str) -> str:
    """Remove any sentence that already contains 14-day-trial CTA wording,
    so the caption builder can append the exact required CTA exactly once.

    Used for Instagram, where the required trial phrase is always appended
    programmatically afterward, so every existing trial-wording sentence in
    Gemini's caption body must be removed (not just extras).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in sentences if s.strip() and not _DUPLICATE_TRIAL_CTA_PATTERN.search(s)]
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


def _keep_only_first_trial_cta_sentence(text: str) -> str:
    """Keep at most one sentence containing 14-day-trial CTA wording,
    removing any additional duplicate sentences.

    Used for Facebook/Threads, where no trial phrase is appended
    programmatically, so a single existing mention from Gemini is fine but
    duplicates are not (task requirement: at most once per caption).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = []
    seen_trial_sentence = False
    for sentence in sentences:
        if not sentence.strip():
            continue
        if _DUPLICATE_TRIAL_CTA_PATTERN.search(sentence):
            if seen_trial_sentence:
                continue
            seen_trial_sentence = True
        kept.append(sentence)
    return " ".join(kept).strip()


def build_platform_captions(
    ad_copy: Dict[str, str],
    selection: Dict[str, Any],
    platform_urls: Dict[str, str],
) -> Dict[str, str]:
    """Build final per-platform captions with hashtags and the exact,
    programmatically-appended download URL for each platform.

    Gemini is never trusted to insert URLs: any URL it produced is stripped
    from each caption, and the exact URL supplied in platform_urls (either
    the tracked URL when TRACKING_ENABLED=true, or DEFAULT_DESTINATION_URL
    when tracking is disabled) is appended afterward, verbatim.
    """
    campaign = selection["campaign"]

    facebook_url = platform_urls["facebook"]
    instagram_url = platform_urls["instagram"]
    threads_url = platform_urls["threads"]

    facebook_body = _strip_invented_urls(ad_copy["facebook_caption"])
    # Remove any simple Gemini-generated download CTA sentences so the
    # system can append the exact required CTA/URL consistently.
    facebook_body = _strip_duplicate_download_cta_sentences(facebook_body)
    # Keep at most one trial-wording sentence (Facebook has no programmatic
    # trial line appended, so a single Gemini-written mention is fine, but
    # duplicates are removed per the "at most once per caption" rule).
    facebook_body = _keep_only_first_trial_cta_sentence(facebook_body)
    facebook_caption = f"{facebook_body}\n\n{config.FACEBOOK_CTA}\n{facebook_url}"

    ig_hashtag_pool = [h for h in campaign.get("instagram_hashtags", []) if h.lower() != "#prayonit"]
    ig_count = min(len(ig_hashtag_pool), random.randint(4, 7)) if ig_hashtag_pool else 0
    ig_hashtags = ["#Prayonit"] + (random.sample(ig_hashtag_pool, k=ig_count) if ig_count else [])
    instagram_body = _strip_invented_urls(ad_copy["instagram_caption"])
    # Remove any Gemini-generated sentence that already duplicates the
    # required 14-day free trial CTA, so it is never appended twice.
    instagram_body = _strip_duplicate_trial_cta_sentences(instagram_body)
    # Also remove simple download CTA sentences so we don't end up with a
    # separate "Download Prayonit" line before the trial CTA/hashtags.
    instagram_body = _strip_duplicate_download_cta_sentences(instagram_body)
    # Instagram feed captions do not make raw URLs clickable, so the
    # destination URL is never appended here. The exact same URL
    # (instagram_url) is instead placed in metadata.instagram.link on the
    # Buffer post (see buffer_client.buffer_create_post).
    instagram_caption = f"{instagram_body}\n\nStart your 14-day free trial.\n\n{config.INSTAGRAM_CTA}"
    if ig_hashtags:
        instagram_caption = f"{instagram_caption}\n\n{' '.join(ig_hashtags)}"

    th_hashtag_pool = [h for h in campaign.get("threads_hashtags", []) if h.lower() != "#prayonit"]
    th_count = min(len(th_hashtag_pool), 1) if th_hashtag_pool else 0
    th_hashtags = ["#Prayonit"] + (random.sample(th_hashtag_pool, k=th_count) if th_count else [])
    threads_body = _strip_invented_urls(ad_copy["threads_caption"])
    # Remove simple Gemini-generated download CTA sentences before the
    # official Try/URL line is appended.
    threads_body = _strip_duplicate_download_cta_sentences(threads_body)
    threads_body = _keep_only_first_trial_cta_sentence(threads_body)
    threads_caption = f"{threads_body}\n\n{config.THREADS_CTA}\n{threads_url}"
    if th_hashtags:
        threads_caption = f"{threads_caption}\n\n{' '.join(th_hashtags)}"

    return {
        "facebook": facebook_caption,
        "instagram": instagram_caption,
        "threads": threads_caption,
    }
