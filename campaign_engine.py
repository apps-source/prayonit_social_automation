"""Campaign/formula/persona/seasonality selection with weighting and
non-repetition rules (Parts 6-11).

Movable Christian holidays are computed with the standard "Anonymous Gregorian
algorithm" for Easter Sunday (no external dependency required), and other
holidays use fixed-date or nth-weekday-of-month rules driven by Python's
built-in date logic. Nothing here is hardcoded to a single year.
"""
import json
import random
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import creative_engine_v3
import config
import history_store


def _load_json_dir(directory) -> List[Dict[str, Any]]:
    items = []
    if not directory.exists():
        return items
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            data["_key"] = path.stem
            items.append(data)
    return items


def load_campaigns() -> List[Dict[str, Any]]:
    items = _load_json_dir(config.CAMPAIGNS_DIR)
    if not items:
        raise RuntimeError(f"No campaign JSON files found in {config.CAMPAIGNS_DIR}")
    return [c for c in items if c.get("active", True)]


def load_formulas() -> List[Dict[str, Any]]:
    return [f for f in _load_json_dir(config.FORMULAS_DIR) if f.get("active", True)]


def load_personas() -> List[Dict[str, Any]]:
    return [p for p in _load_json_dir(config.PERSONAS_DIR) if p.get("active", True)]


def load_seasonality() -> List[Dict[str, Any]]:
    return [s for s in _load_json_dir(config.SEASONALITY_DIR) if s.get("active", True)]


# ---------- Movable holiday math ----------

def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm for the date of Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day_of_month = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day_of_month)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Monday=0..Sunday=6. n: 1-based occurrence, or -1 for last."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        d = d + timedelta(days=offset + 7 * (n - 1))
        return d

    # last occurrence in month
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    d = next_month - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def resolve_seasonality_date(rule: Dict[str, Any], year: int) -> Optional[date]:
    rule_type = rule.get("type")
    if rule_type == "fixed":
        return date(year, rule["month"], rule["day"])
    if rule_type == "easter_relative":
        base = easter_sunday(year)
        return base + timedelta(days=rule.get("offset_days", 0))
    if rule_type == "nth_weekday":
        return _nth_weekday(year, rule["month"], rule["weekday"], rule["n"])
    if rule_type == "season":
        return None  # handled separately; seasons are month-range based
    return None


def active_seasonal_contexts(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Return seasonality entries currently within their lead/follow window."""
    today = today or date.today()
    active = []

    for entry in load_seasonality():
        rule = entry["date_rule"]
        if rule.get("type") == "season":
            months = rule.get("months", [])
            if today.month in months:
                active.append(entry)
            continue

        for year in (today.year - 1, today.year, today.year + 1):
            occurrence = resolve_seasonality_date(rule, year)
            if occurrence is None:
                continue
            span = rule.get("span_days", 0)
            window_start = occurrence - timedelta(days=entry.get("lead_days", 0))
            window_end = occurrence + timedelta(days=span + entry.get("follow_days", 0))
            if window_start <= today <= window_end:
                active.append(entry)
                break

    return active


# ---------- Non-repetition + weighted selection ----------

def get_performance_multiplier(
    campaign_name: str,
    formula_name: Optional[str],
    persona_name: Optional[str],
    platform: Optional[str],
    slot: Optional[str],
) -> float:
    """Placeholder for future Buffer/download-analytics-driven weighting.

    Always returns 1.0 today. Once post_metrics has enough verified
    observations, this function is the intended integration point for
    performance-weighted selection, without changing any caller code.
    """
    return 1.0


def _recent_names(rows, field: str, limit: Optional[int] = None) -> List[str]:
    values = [row[field] for row in rows if row[field]]
    if limit is not None:
        values = values[:limit]
    return values


def _weighted_choice(candidates: List[Dict[str, Any]], weight_key: str = "weight") -> Dict[str, Any]:
    weights = [max(float(c.get(weight_key, 1.0)), 0.01) for c in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def _is_both_slots_campaign(campaign: Dict[str, Any]) -> bool:
    """A campaign is considered a 'both' campaign when its eligible_slots
    explicitly include both morning and evening (or the field is absent,
    meaning no restriction was specified)."""
    eligible = campaign.get("eligible_slots")
    if not eligible:
        return True
    return "morning" in eligible and "evening" in eligible


def _filter_campaigns_by_slot(campaigns: List[Dict[str, Any]], slot: str) -> List[Dict[str, Any]]:
    """Restrict campaigns to those eligible for the given slot.

    - A campaign with no eligible_slots field is treated as eligible for any
      slot (backward compatible default).
    - A campaign is eligible for `slot` if `slot` is in its eligible_slots
      list.
    - If no campaign is eligible for the requested slot, fall back to
      campaigns eligible for both morning and evening.
    """
    eligible = [
        c for c in campaigns
        if not c.get("eligible_slots") or slot in c.get("eligible_slots", [])
    ]
    if eligible:
        return eligible

    both_slot_campaigns = [c for c in campaigns if _is_both_slots_campaign(c)]
    return both_slot_campaigns or campaigns


def choose_campaign(slot: str, seasonal_boosts: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Pick a campaign honoring eligible_slots, weights, seasonal boosts,
    and non-repetition.

    Slot eligibility is enforced first: a morning run may only select
    campaigns whose eligible_slots include "morning" (or that have no
    eligible_slots restriction), and likewise for evening. If no compatible
    campaign exists for the requested slot, this falls back to an active
    campaign eligible for both slots rather than crashing.

    Relaxation order when everything is excluded:
      1. drop the "avoid last N runs" rule
      2. drop the "avoid combination for N days" rule (handled by caller)
      3. use the full (slot-eligible) pool
    Logs (returns via a note) which rule was relaxed, and never raises.
    """
    seasonal_boosts = seasonal_boosts or {}
    all_campaigns = load_campaigns()

    slot_eligible_campaigns = _filter_campaigns_by_slot(all_campaigns, slot)

    recent_rows = history_store.get_recent_campaign_history(days=90)
    recent_names = _recent_names(recent_rows, "campaign_name", limit=config.HISTORY_CAMPAIGN_RUNS)

    pool = [c for c in slot_eligible_campaigns if c["name"] not in recent_names]
    relaxed_rule = None
    if not pool:
        pool = slot_eligible_campaigns
        relaxed_rule = f"avoid same campaign for last {config.HISTORY_CAMPAIGN_RUNS} runs"

    boosted_pool = []
    for c in pool:
        boost = seasonal_boosts.get(c["_key"], 1.0)
        territory = creative_engine_v3.classify_emotional_territory(
            campaign_name=c.get("name", ""),
            pain_point=c.get("pain_point", ""),
            goal=c.get("goal", ""),
        )
        territory_mult = creative_engine_v3.territory_weight_multiplier(territory)
        entry = dict(c)
        entry["weight"] = float(c.get("weight", 1.0)) * boost * territory_mult
        entry["emotional_territory"] = territory
        boosted_pool.append(entry)

    chosen = _weighted_choice(boosted_pool)
    chosen["_relaxed_rule"] = relaxed_rule
    return chosen


def choose_formula(recent_days: int = 30) -> Dict[str, Any]:
    all_formulas = load_formulas()
    recent_rows = history_store.get_recent_campaign_history(days=recent_days)
    recent_names = _recent_names(recent_rows, "formula_name", limit=config.HISTORY_FORMULA_RUNS)

    pool = [f for f in all_formulas if f["name"] not in recent_names]
    relaxed_rule = None
    if not pool:
        pool = all_formulas
        relaxed_rule = f"avoid same formula for last {config.HISTORY_FORMULA_RUNS} runs"

    chosen = _weighted_choice(pool, weight_key="weight") if any("weight" in f for f in pool) else random.choice(pool)
    chosen = dict(chosen)
    chosen["_relaxed_rule"] = relaxed_rule
    return chosen


def choose_persona(campaign: Dict[str, Any], recent_days: int = 30) -> Optional[Dict[str, Any]]:
    all_personas = load_personas()
    compatible = [
        p for p in all_personas
        if campaign["_key"] in p.get("compatible_campaigns", []) or not p.get("compatible_campaigns")
    ]
    if not compatible:
        compatible = all_personas
    if not compatible:
        return None

    recent_rows = history_store.get_recent_campaign_history(days=recent_days)
    recent_names = _recent_names(recent_rows, "persona_name", limit=config.HISTORY_PERSONA_RUNS)

    pool = [p for p in compatible if p["name"] not in recent_names]
    relaxed_rule = None
    if not pool:
        pool = compatible
        relaxed_rule = f"avoid same persona for last {config.HISTORY_PERSONA_RUNS} runs"

    chosen = _weighted_choice(pool)
    chosen = dict(chosen)
    chosen["_relaxed_rule"] = relaxed_rule
    return chosen


def choose_background(
    all_backgrounds: List[str],
    *,
    slot: str,
    campaign: Optional[Dict[str, Any]] = None,
    formula: Optional[Dict[str, Any]] = None,
    persona: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pick a background with V3 matching + duplicate prevention.

    Rules (relaxed conservatively only when needed):
      1) avoid recent exact background reuse
      2) avoid same campaign+formula+background combo too soon
      3) maximize emotional/time compatibility score
    """
    recent_rows = history_store.get_recent_campaign_history(days=max(30, config.HISTORY_BACKGROUND_DAYS))
    recent_backgrounds = {
        row["background_object_path"] for row in recent_rows
        if row["background_object_path"]
    }

    pool = [b for b in all_backgrounds if b not in recent_backgrounds]
    relaxed_rule = None
    if not pool:
        pool = list(all_backgrounds)
        relaxed_rule = f"avoid same background for {config.HISTORY_BACKGROUND_DAYS} days"

    campaign_name = campaign.get("name") if campaign else None
    formula_name = formula.get("name") if formula else None
    too_soon_combo = set()
    for row in recent_rows:
        if campaign_name and row["campaign_name"] != campaign_name:
            continue
        if formula_name and row["formula_name"] != formula_name:
            continue
        if row["background_object_path"]:
            too_soon_combo.add(row["background_object_path"])

    strict_pool = [b for b in pool if b not in too_soon_combo]
    if strict_pool:
        pool = strict_pool
    elif not relaxed_rule:
        relaxed_rule = "avoid same campaign+formula+background combination too soon"

    territory = creative_engine_v3.classify_emotional_territory(
        campaign_name=(campaign or {}).get("name", ""),
        pain_point=(campaign or {}).get("pain_point", ""),
        goal=(campaign or {}).get("goal", ""),
    )
    scored = []
    for bg in pool:
        meta = creative_engine_v3.classify_background(bg)
        score = creative_engine_v3.background_match_score(
            background_meta=meta,
            territory=territory,
            slot=slot,
        )
        scored.append((bg, meta, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    top = scored[: min(6, len(scored))] or scored
    chosen_bg, meta, score = random.choice(top)

    return {
        "path": chosen_bg,
        "metadata": meta,
        "match_score": score,
        "emotional_territory": territory,
        "_relaxed_rule": relaxed_rule,
    }


def choose_selection(slot: str) -> Dict[str, Any]:
    """Top-level selection: campaign, hook/body_angle/cta/thread_topic, formula, persona, season.

    slot ("morning" or "evening") is enforced during campaign selection via
    eligible_slots so, for example, a morning run can never select an
    evening-only campaign.
    """
    active_seasons = active_seasonal_contexts()
    seasonal_boosts: Dict[str, float] = {}
    seasonal_names: List[str] = []
    for season in active_seasons:
        seasonal_names.append(season["name"])
        for campaign_key in season.get("eligible_campaigns", []):
            seasonal_boosts[campaign_key] = max(
                seasonal_boosts.get(campaign_key, 1.0), season.get("weight_boost", 1.0)
            )

    campaign = choose_campaign(slot, seasonal_boosts)
    formula = choose_formula()
    persona = choose_persona(campaign)

    relaxed_rules = [
        r for r in [campaign.get("_relaxed_rule"), formula.get("_relaxed_rule"),
                    persona.get("_relaxed_rule") if persona else None]
        if r
    ]

    return {
        "campaign": campaign,
        "formula": formula,
        "persona": persona,
        "emotional_territory": campaign.get("emotional_territory"),
        "seasonal_context": ", ".join(seasonal_names) if seasonal_names else None,
        "hook": random.choice(campaign["hooks"]),
        "body_angle": random.choice(campaign["body_angles"]),
        "cta": random.choice(campaign["ctas"]),
        "thread_topic": random.choice(campaign["thread_topics"]),
        "relaxed_rules": relaxed_rules,
    }


# ---------- Creative Engine v2: modular theology component library ----------

# Maps keywords found in a campaign's name/pain_point/goal (checked in
# order) to a theology_actions.json pool key. Falls back to slot-based
# pools, and finally to surrender_actions, so a pool is always found.
_CAMPAIGN_KEYWORD_POOLS = [
    ("anxi", "anxiety_actions"),
    ("grief", "grief_actions"),
    ("griev", "grief_actions"),
    ("purpose", "purpose_actions"),
    ("relationship", "relationship_actions"),
    ("marriage", "relationship_actions"),
    ("financ", "financial_stress_actions"),
    ("money", "financial_stress_actions"),
    ("gratitude", "gratitude_actions"),
    ("thank", "gratitude_actions"),
    ("praise", "praise_actions"),
    ("guidance", "guidance_actions"),
    ("decision", "guidance_actions"),
    ("comfort", "comfort_actions"),
    ("hope", "comfort_actions"),
]


def _theology_pool_key_for(campaign: Dict[str, Any], slot: str) -> str:
    haystack = " ".join(
        str(campaign.get(field, "")) for field in ("name", "pain_point", "goal")
    ).lower()
    for keyword, pool_key in _CAMPAIGN_KEYWORD_POOLS:
        if keyword in haystack:
            return pool_key
    if slot == "morning":
        return "morning_actions"
    if slot == "evening":
        return "evening_actions"
    return "surrender_actions"


def _load_recent_theology_choices() -> List[str]:
    path = config.RECENT_THEOLOGY_COMPONENTS_PATH
    if path is None or not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return list(data.get("recent", []))
    except (json.JSONDecodeError, OSError):
        return []


def _save_recent_theology_choice(action: str, limit: int = 10) -> None:
    path = config.RECENT_THEOLOGY_COMPONENTS_PATH
    if path is None:
        return
    recent = _load_recent_theology_choices()
    recent.append(action)
    recent = recent[-limit:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"recent": recent}, fh, indent=2)
    except OSError:
        pass


def pick_spiritual_action(campaign: Dict[str, Any], slot: str) -> str:
    """Choose an approved spiritual-action sentence from
    brand/theology_actions.json, matched to the campaign's pain point/slot,
    avoiding recently used exact statements when an alternative exists.

    Gemini may adapt grammar around this sentence but must not invent an
    unsupported theological claim; the sentence itself always comes from
    the approved component library.
    """
    theology_actions = config.load_theology_actions()
    pool_key = _theology_pool_key_for(campaign, slot)
    pool = theology_actions.get(pool_key) or theology_actions.get("surrender_actions", [])
    if not pool:
        return "Give today's burdens to God in prayer."

    recent = set(_load_recent_theology_choices())
    candidates = [action for action in pool if action not in recent]
    if not candidates:
        candidates = pool

    chosen = random.choice(candidates)
    _save_recent_theology_choice(chosen)
    return chosen
