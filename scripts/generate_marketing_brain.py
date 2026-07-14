"""Local, offline generator for the Prayonit marketing brain content.

This script does NOT call Gemini, Buffer, or Supabase. It writes JSON files
into campaigns/, formulas/, personas/, and seasonality/ using hand-authored
Prayonit-specific templates. It is safe to re-run; it overwrites existing
generated files deterministically.

Run with:
    python3 scripts/generate_marketing_brain.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGNS_DIR = ROOT / "campaigns"
FORMULAS_DIR = ROOT / "formulas"
PERSONAS_DIR = ROOT / "personas"
SEASONALITY_DIR = ROOT / "seasonality"

PROHIBITED_CLAIMS_DEFAULT = [
    "Do not claim Prayonit guarantees a spiritual, emotional, or medical outcome.",
    "Do not claim Prayonit replaces church, clergy, therapy, or medical care.",
    "Do not use fake statistics, fake testimonials, or fake user counts.",
    "Do not imply the app knows God's will or speaks with divine authority.",
]

# key, display name, goal, pain_point, emotional_promise, eligible_personas, weight
CAMPAIGN_TABLE = [
    ("anxiety", "Anxiety", "Reach anxious users with a calming, specific next step.", "feeling anxious with no simple way to bring it to God", "a calmer, guided way to hand anxious thoughts to God", ["person_with_anxiety", "general_christian"], 1.2),
    ("stress", "Everyday Stress", "Reach overwhelmed users during a stressful day.", "feeling stretched thin and too busy to pray", "a 60-second reset that fits into a packed day", ["busy_parent", "young_professional", "general_christian"], 1.0),
    ("repetitive_prayer", "Repetitive Prayer", "Reach people stuck saying the same prayer every time.", "repeating the same tired prayer every single day", "fresh, specific prayers that actually fit today", ["general_christian", "returning_to_faith"], 1.0),
    ("cannot_find_words", "Cannot Find The Words", "Reach people who freeze when it's time to pray.", "not knowing what to say when it's time to pray", "the right words, given to you in seconds", ["general_christian", "new_christian"], 1.1),
    ("prayer_habit", "Building A Prayer Habit", "Help inconsistent pray-ers build a daily habit.", "wanting to pray daily but never actually sticking with it", "a simple daily habit that finally sticks", ["general_christian", "young_professional"], 1.0),
    ("morning_prayer", "Morning Prayer", "Encourage starting the day with prayer.", "starting the day rushed, without a moment for God", "a grounded, prayerful start before the day takes over", ["general_christian", "busy_parent"], 1.0),
    ("evening_prayer", "Evening Prayer", "Encourage ending the day with prayer.", "falling asleep scrolling instead of praying", "a calm way to close the day with God", ["general_christian", "young_professional"], 1.0),
    ("bedtime_worry", "Bedtime Worry", "Reach people whose minds race at night.", "lying awake with a racing, worried mind", "a guided prayer that quiets a busy mind before sleep", ["person_with_anxiety", "general_christian"], 1.0),
    ("loneliness", "Loneliness", "Reach people who feel isolated or unseen.", "feeling alone even when surrounded by people", "a reminder that you're not praying alone", ["general_christian", "retiree"], 1.0),
    ("burnout", "Burnout", "Reach exhausted, running-on-empty users.", "feeling completely burned out and running on empty", "a small moment of rest with God, not one more task", ["young_professional", "caregiver", "business_owner"], 1.0),
    ("grief", "Grief", "Reach people carrying loss, with care and restraint.", "carrying grief and not knowing how to pray through it", "a gentle place to bring grief honestly to God", ["person_grieving", "general_christian"], 0.9),
    ("fear", "Fear", "Reach people facing a fearful season.", "facing something that feels frightening and uncertain", "a way to bring real fear honestly into prayer", ["general_christian", "person_with_anxiety"], 1.0),
    ("hope", "Hope", "Reach people needing encouragement, not despair.", "feeling like things are too heavy to hope again", "a small, honest spark of hope through Scripture and prayer", ["general_christian", "returning_to_faith"], 1.0),
    ("gratitude", "Gratitude", "Reach people who want to pray more thankfully.", "rushing through prayer without ever pausing to give thanks", "a guided way to actually slow down and give thanks", ["general_christian", "retiree"], 0.9),
    ("forgiveness", "Forgiveness", "Reach people wrestling with forgiving someone.", "struggling to forgive someone and not sure how to pray about it", "a guided prayer to help process forgiveness honestly", ["general_christian", "married_couple"], 0.9),
    ("guilt", "Guilt", "Reach people carrying guilt or shame.", "carrying guilt and unsure how to bring it to God", "a safe, judgment-free way to bring guilt into prayer", ["general_christian", "new_christian"], 0.8),
    ("anger", "Anger", "Reach people who feel angry or frustrated.", "feeling angry and not sure it's okay to pray about it", "a way to bring real anger honestly to God", ["general_christian", "married_couple"], 0.8),
    ("purpose", "Purpose", "Reach people questioning their direction.", "wondering if life has real direction or purpose", "a guided moment to seek clarity through prayer", ["young_professional", "college_student", "general_christian"], 0.9),
    ("feeling_disconnected", "Feeling Disconnected From God", "Reach people who feel spiritually distant.", "feeling distant from God and not sure how to reconnect", "a simple, low-pressure way to reconnect with God today", ["returning_to_faith", "general_christian"], 1.1),
    ("returning_to_faith", "Returning To Faith", "Reach people coming back after time away.", "wanting to come back to faith after time away", "a gentle, no-pressure way to start praying again", ["returning_to_faith", "general_christian"], 1.1),
    ("new_christian", "New Christian", "Reach newer believers who feel unsure how to pray.", "being new to faith and unsure how prayer is supposed to work", "simple guidance for praying as a new believer", ["new_christian"], 1.0),
    ("busy_parent", "Busy Parent", "Reach parents with no quiet time to pray.", "being a parent with no quiet moment left to pray", "a prayer that fits into the middle of a busy day", ["busy_parent", "single_parent"], 1.0),
    ("single_parent", "Single Parent", "Reach single parents carrying it all.", "carrying parenting alone and rarely getting a moment for yourself", "a quick, personal prayer made for an overloaded day", ["single_parent"], 1.0),
    ("marriage", "Marriage", "Reach couples wanting to pray together or individually.", "wanting to pray more for your marriage but not knowing where to start", "guided prayer prompts for your marriage, made simple", ["married_couple"], 0.8),
    ("relationship_conflict", "Relationship Conflict", "Reach people navigating conflict.", "navigating conflict with someone you love and unsure how to pray about it", "a guided prayer to bring a hard relationship to God", ["married_couple", "general_christian"], 0.8),
    ("financial_stress", "Financial Stress", "Reach people anxious about money.", "feeling anxious about money and where things are headed", "a place to bring real financial worry honestly to God", ["young_professional", "business_owner", "general_christian"], 0.9),
    ("job_stress", "Job Stress", "Reach people overwhelmed at work.", "feeling overwhelmed and undervalued at work", "a quick prayer break built for a stressful workday", ["young_professional", "business_owner"], 0.9),
    ("health_worry", "Health Worry", "Reach people worried about their health, without medical claims.", "worrying about your health and not knowing how to pray about it", "a guided way to bring health worries honestly to God", ["general_christian", "retiree", "caregiver"], 0.8),
    ("waiting_for_answers", "Waiting For Answers", "Reach people in a season of waiting.", "waiting on an answer and feeling stuck in the meantime", "a guided prayer for the hard, uncertain waiting season", ["general_christian"], 0.9),
    ("college_student", "College Student", "Reach students juggling school and faith.", "juggling school, stress, and faith all at once", "a fast, simple prayer that fits between classes", ["college_student"], 0.9),
    ("young_adult", "Young Adult", "Reach young adults building their own faith habits.", "figuring out what a personal faith life even looks like", "a simple way to build your own daily prayer habit", ["young_professional", "college_student"], 0.9),
    ("business_owner", "Business Owner", "Reach founders and owners under pressure.", "carrying the weight of a business and rarely slowing down to pray", "a fast, focused prayer built for a demanding schedule", ["business_owner"], 0.8),
    ("caregiver", "Caregiver", "Reach caregivers who are exhausted and stretched.", "caring for someone else and running low on your own strength", "a short prayer made for an exhausted caregiver", ["caregiver"], 0.9),
    ("veteran", "Veteran", "Reach veterans navigating transition or memories.", "carrying experiences that are hard to put into words, even in prayer", "a guided way to bring hard memories honestly to God", ["veteran"], 0.7),
    ("major_life_change", "Major Life Change", "Reach people in a big transition.", "going through a major life change and feeling unsteady", "a steadying prayer for an uncertain new season", ["general_christian", "young_adult"], 0.9),
    ("confidence", "Confidence", "Reach people who feel insecure or unsure of themselves.", "feeling unsure of yourself and needing steadier confidence", "a prayer to root your confidence in something steady", ["general_christian", "young_adult"], 0.8),
    ("decision_making", "Decision Making", "Reach people facing a hard decision.", "facing a hard decision and wanting real clarity", "a guided prayer to seek clarity before deciding", ["general_christian", "young_professional"], 0.9),
    ("personalized_prayer_feature", "Feature: Personalized Prayer", "Highlight the personalized AI-generated prayer feature.", "wanting a prayer that actually reflects your real situation", "a personalized prayer built around exactly how you feel", ["general_christian"], 1.0),
    ("mood_selection_feature", "Feature: Mood Selection", "Highlight the mood/feeling selection flow.", "not knowing where to even start when you sit down to pray", "start with one tap: just pick how you feel", ["general_christian"], 1.0),
    ("journaling_feature", "Feature: Journaling", "Highlight the journaling capability.", "wanting to reflect on your prayers but never actually writing it down", "a simple way to journal your prayer experience afterward", ["general_christian"], 0.8),
    ("scripture_matching_feature", "Feature: Scripture Matching", "Highlight relevant KJV Scripture matched to mood.", "wanting Scripture that actually relates to how you feel right now", "relevant Scripture matched to exactly how you feel", ["general_christian"], 1.0),
    ("three_minute_prayer", "Three Minute Prayer", "Emphasize speed and simplicity.", "feeling like you don't have time to pray properly", "a real, guided prayer in about three minutes", ["busy_parent", "young_professional", "general_christian"], 1.0),
    ("daily_reminder", "Daily Reminder", "Reach people who keep forgetting to pray.", "meaning to pray every day and then forgetting", "a simple daily nudge that actually gets you praying", ["general_christian"], 0.9),
    ("app_download_direct", "Direct Download CTA", "Simple, direct download-focused messaging.", "not having an easy way to pray daily right from your phone", "a free app made to help you pray, right from your phone", ["general_christian"], 1.0),
    ("app_trial", "Try It Free", "Lower the barrier with a low-commitment first try.", "being unsure if a prayer app is even worth trying", "a free, no-pressure way to try guided prayer today", ["general_christian"], 0.9),
    ("prayer_for_family", "Prayer For Family", "Reach people wanting to pray for their family.", "wanting to pray for your family more consistently", "guided prompts to help you pray for your family", ["married_couple", "busy_parent", "single_parent"], 0.9),
    ("prayer_for_children", "Prayer For Children", "Reach parents wanting to pray for their kids.", "wanting to pray for your kids but not knowing where to start", "simple, guided prayers to pray over your children", ["busy_parent", "single_parent"], 0.9),
    ("prayer_for_relationship", "Prayer For A Relationship", "Reach people wanting to pray for a specific relationship.", "wanting to pray for a relationship that feels strained", "a guided prayer built around a specific relationship", ["married_couple", "general_christian"], 0.8),
    ("peaceful_sleep", "Peaceful Sleep", "Reach people who want a calmer bedtime routine.", "going to bed with a mind that won't quiet down", "a calming prayer routine to help you rest", ["general_christian", "person_with_anxiety"], 1.0),
    ("fresh_start", "Fresh Start", "Reach people wanting to reset their faith habits.", "wanting a fresh start with prayer but not knowing how to begin", "a simple, judgment-free way to start fresh today", ["returning_to_faith", "general_christian"], 1.0),
]

STORY_HOOK_TEMPLATE = [
    "Feeling it right now?",
    "You're not alone in this.",
    "There's a simple next step.",
]

FACEBOOK_ANGLE_TEMPLATE = "Talk directly to someone {pain}, and show how Prayonit gives them {promise}."
INSTAGRAM_ANGLE_TEMPLATE = "Short, punchy visual hook about {pain}, then a quick line about {promise}."
THREADS_ANGLE_TEMPLATE = "Conversational, first-person-feeling tone about {pain}, ending with {promise}."

BASE_HASHTAGS = ["#Prayonit", "#PrayerApp", "#ChristianApp", "#FaithJourney", "#PrayerLife", "#DailyPrayer", "#GodFirst", "#ScriptureDaily"]


def build_campaign(key, name, goal, pain, promise, personas, weight):
    hooks = [
        f"Are you {pain}?",
        f"What if {promise} was one tap away?",
        f"You don't have to keep {pain} alone.",
        f"There's a simple way through {pain}.",
    ]
    body_angles = [
        f"Prayonit meets you in {pain} with {promise}.",
        f"No pressure, no perfect words. Just {promise}, built around today.",
        f"Turn {pain} into a real, guided moment with God.",
    ]
    ctas = [
        "Download Prayonit today.",
        "Try Prayonit free right now.",
        "Get your prayer in Prayonit.",
    ]
    thread_topics = [
        f"what it's actually like {pain}",
        f"why {promise} matters more than perfect words",
        f"small steps that help with {pain}",
    ]
    ig_hashtags = list(dict.fromkeys(BASE_HASHTAGS + [f"#{key.title().replace('_', '')}"]))[:8]
    th_hashtags = ["#Prayonit", "#PrayerLife"]

    return {
        "name": name,
        "goal": goal,
        "pain_point": pain,
        "emotional_promise": promise,
        "prohibited_claims": PROHIBITED_CLAIMS_DEFAULT,
        "hooks": hooks,
        "body_angles": body_angles,
        "ctas": ctas,
        "story_hooks": STORY_HOOK_TEMPLATE,
        "facebook_angles": [FACEBOOK_ANGLE_TEMPLATE.format(pain=pain, promise=promise)],
        "instagram_angles": [INSTAGRAM_ANGLE_TEMPLATE.format(pain=pain, promise=promise)],
        "threads_angles": [THREADS_ANGLE_TEMPLATE.format(pain=pain, promise=promise)],
        "thread_topics": thread_topics,
        "instagram_hashtags": ig_hashtags,
        "threads_hashtags": th_hashtags,
        "eligible_slots": ["morning", "evening"],
        "eligible_personas": personas,
        "weight": weight,
        "active": True,
    }


FORMULA_TABLE = [
    ("problem_agitate_solution", "Problem, Agitate, Solution", "State the problem, deepen the pain, then offer Prayonit as the solution.", ["problem", "agitate", "solution", "cta"]),
    ("question_empathy_solution", "Question, Empathy, Solution", "Ask a relatable question, empathize, then present the app.", ["question", "empathy", "solution", "cta"]),
    ("problem_hope_action", "Problem, Hope, Action", "Name the problem, offer hope, then a clear action.", ["problem", "hope", "action", "cta"]),
    ("curiosity_benefit_cta", "Curiosity, Benefit, CTA", "Open a curiosity gap, reveal the benefit, close with a CTA.", ["curiosity", "benefit", "cta"]),
    ("before_after_bridge", "Before, After, Bridge", "Contrast life before and after, with Prayonit as the bridge.", ["before", "after", "bridge", "cta"]),
    ("mistake_solution", "Common Mistake, Solution", "Name a common mistake or misconception, then correct it.", ["mistake", "reframe", "solution", "cta"]),
    ("emotional_truth_solution", "Emotional Truth, Solution", "Say an honest emotional truth, then offer the app as support.", ["truth", "solution", "cta"]),
    ("challenge_action", "Challenge, Action", "Issue a small challenge, then an easy first action.", ["challenge", "action", "cta"]),
    ("contrast_old_way_new_way", "Old Way vs New Way", "Contrast the old, harder way with the new, simpler way.", ["old_way", "new_way", "cta"]),
    ("simple_three_step", "Simple Three Step", "Show prayer in three simple steps using the app.", ["step_1", "step_2", "step_3", "cta"]),
    ("identity_based", "Identity Based", "Speak to who the reader wants to become.", ["identity_statement", "support", "cta"]),
    ("direct_response", "Direct Response", "Skip the story, state benefit and CTA directly.", ["benefit", "cta"]),
    ("micro_story", "Micro Story", "Tell a tiny, relatable one-line story, then the app.", ["micro_story", "solution", "cta"]),
    ("objection_answer", "Objection, Answer", "Name a common objection, then answer it.", ["objection", "answer", "cta"]),
    ("feature_to_benefit", "Feature To Benefit", "State a feature, then translate it into a benefit.", ["feature", "benefit", "cta"]),
]


def build_formula(key, name, description, structure):
    return {
        "name": name,
        "description": description,
        "structure": structure,
        "headline_guidance": "Keep the headline under 9 words and aligned to this formula's structure.",
        "body_guidance": "Keep body copy under 16 words; follow the formula's structure in order.",
        "caption_guidance": "Expand the same structure conversationally per platform; end with a download CTA.",
        "story_guidance": "Compress to a headline and CTA only; skip intermediate structure steps.",
        "avoid": PROHIBITED_CLAIMS_DEFAULT,
    }


PERSONA_TABLE = [
    ("general_christian", "General Christian", "A broad Christian audience open to prayer support.", ["consistency", "distraction", "busyness"], "warm, encouraging", ["general_christian", "new_christian", "returning_to_faith", "busy_parent", "single_parent", "married_couple", "college_student", "young_professional", "business_owner", "caregiver", "veteran", "retiree", "person_with_anxiety", "person_grieving", "person_under_financial_stress"], 1.0),
    ("new_christian", "New Christian", "Someone newer to faith, unsure how prayer works.", ["not knowing how to pray", "feeling behind others"], "gentle, non-judgmental", ["new_christian", "cannot_find_words", "personalized_prayer_feature"], 1.0),
    ("returning_to_faith", "Returning To Faith", "Someone coming back to faith after time away.", ["guilt about distance", "not knowing how to restart"], "welcoming, no-pressure", ["returning_to_faith", "feeling_disconnected", "fresh_start"], 1.0),
    ("busy_parent", "Busy Parent", "A parent with little quiet time.", ["lack of time", "guilt over inconsistency"], "practical, understanding", ["busy_parent", "prayer_for_family", "prayer_for_children", "three_minute_prayer"], 1.0),
    ("single_parent", "Single Parent", "A single parent carrying most responsibilities alone.", ["exhaustion", "lack of support"], "compassionate, practical", ["single_parent", "prayer_for_family", "burnout"], 1.0),
    ("married_couple", "Married Couple", "A couple wanting to strengthen faith together.", ["relationship strain", "different faith habits"], "warm, relational", ["marriage", "relationship_conflict", "forgiveness"], 0.9),
    ("college_student", "College Student", "A student juggling school, social life, and faith.", ["busyness", "spiritual drift"], "casual, relatable", ["college_student", "young_adult", "purpose"], 0.9),
    ("young_professional", "Young Professional", "An early-career adult balancing work and faith.", ["career stress", "burnout"], "confident, modern", ["job_stress", "purpose", "confidence", "decision_making"], 0.9),
    ("business_owner", "Business Owner", "An owner or founder under constant pressure.", ["financial pressure", "responsibility overload"], "direct, respectful of time", ["business_owner", "financial_stress", "job_stress"], 0.8),
    ("caregiver", "Caregiver", "Someone caring for a family member.", ["exhaustion", "isolation"], "gentle, validating", ["caregiver", "burnout", "health_worry"], 0.9),
    ("veteran", "Veteran", "A veteran navigating transition or memories.", ["difficult memories", "transition stress"], "respectful, steady", ["veteran", "major_life_change"], 0.7),
    ("retiree", "Retiree", "An older adult with more time for reflection.", ["loneliness", "health concerns"], "respectful, unhurried", ["loneliness", "gratitude", "health_worry"], 0.8),
    ("person_with_anxiety", "Person With Anxiety", "Someone experiencing frequent anxious feelings.", ["racing thoughts", "overwhelm"], "calm, validating, never diagnostic", ["anxiety", "bedtime_worry", "peaceful_sleep"], 1.1),
    ("person_grieving", "Person Grieving", "Someone processing a loss.", ["grief", "difficulty praying through pain"], "tender, restrained", ["grief"], 0.7),
    ("person_under_financial_stress", "Person Under Financial Stress", "Someone anxious about money.", ["financial uncertainty", "shame around money"], "empathetic, non-judgmental", ["financial_stress", "job_stress"], 0.8),
]


def build_persona(key, name, description, concerns, tone, compatible_campaigns, weight):
    return {
        "name": name,
        "description": description,
        "concerns": concerns,
        "preferred_tone": tone,
        "avoid": [
            "Do not diagnose or label the viewer (e.g. do not say 'you have anxiety').",
            "Use feeling-based language such as 'feeling overwhelmed?' instead of clinical claims.",
        ],
        "compatible_campaigns": compatible_campaigns,
        "weight": weight,
        "active": True,
    }


SEASONALITY_TABLE = [
    ("new_years_day", "fixed", {"month": 1, "day": 1}, 3, 1, ["fresh_start", "app_trial"], ["fresh start", "new habits"], [], 1.3),
    ("valentines_day", "fixed", {"month": 2, "day": 14}, 3, 1, ["marriage", "relationship_conflict", "prayer_for_relationship"], ["love", "relationships"], [], 1.2),
    ("ash_wednesday", "easter_relative", {"offset_days": -46}, 2, 0, ["fresh_start", "guilt", "forgiveness"], ["reflection", "repentance"], ["celebratory"], 1.1),
    ("lent", "easter_relative", {"offset_days": -40, "span_days": 40}, 0, 0, ["fresh_start", "forgiveness", "purpose"], ["reflection", "discipline"], ["celebratory"], 1.0),
    ("palm_sunday", "easter_relative", {"offset_days": -7}, 1, 0, ["hope", "purpose"], ["anticipation"], ["celebratory"], 1.0),
    ("good_friday", "easter_relative", {"offset_days": -2}, 1, 0, ["grief", "hope"], ["solemn reflection"], ["celebratory", "promotional"], 1.0),
    ("easter", "easter_relative", {"offset_days": 0}, 3, 2, ["hope", "fresh_start", "gratitude"], ["new life", "hope"], [], 1.4),
    ("mothers_day", "nth_weekday", {"month": 5, "weekday": 6, "n": 2}, 3, 1, ["prayer_for_family", "prayer_for_children", "gratitude"], ["motherhood", "family"], [], 1.2),
    ("memorial_day", "nth_weekday", {"month": 5, "weekday": 0, "n": -1}, 2, 0, ["veteran", "grief"], ["remembrance", "gratitude"], ["celebratory"], 1.0),
    ("fathers_day", "nth_weekday", {"month": 6, "weekday": 6, "n": 3}, 3, 1, ["prayer_for_family", "prayer_for_children"], ["fatherhood", "family"], [], 1.2),
    ("independence_day", "fixed", {"month": 7, "day": 4}, 2, 0, ["gratitude", "hope"], ["gratitude", "freedom"], [], 1.1),
    ("back_to_school", "fixed", {"month": 8, "day": 15}, 10, 5, ["busy_parent", "college_student", "major_life_change"], ["new routines", "transition"], [], 1.1),
    ("labor_day", "nth_weekday", {"month": 9, "weekday": 0, "n": 1}, 2, 0, ["job_stress", "burnout"], ["rest", "work-life balance"], [], 1.0),
    ("september_11_remembrance", "fixed", {"month": 9, "day": 11}, 1, 0, ["grief", "veteran", "fear"], ["remembrance"], ["celebratory", "promotional"], 1.0),
    ("veterans_day", "fixed", {"month": 11, "day": 11}, 2, 0, ["veteran"], ["gratitude", "respect"], ["celebratory"], 1.1),
    ("thanksgiving", "nth_weekday", {"month": 11, "weekday": 3, "n": 4}, 4, 1, ["gratitude", "prayer_for_family"], ["gratitude"], [], 1.3),
    ("advent", "fixed", {"month": 12, "day": 1}, 0, 0, ["hope", "fresh_start"], ["anticipation", "hope"], [], 1.1),
    ("christmas_eve", "fixed", {"month": 12, "day": 24}, 2, 0, ["gratitude", "hope", "prayer_for_family"], ["gratitude", "family"], [], 1.2),
    ("christmas_day", "fixed", {"month": 12, "day": 25}, 0, 1, ["gratitude", "hope", "prayer_for_family"], ["gratitude", "family"], [], 1.3),
    ("new_years_eve", "fixed", {"month": 12, "day": 31}, 2, 0, ["fresh_start", "gratitude"], ["reflection", "fresh start"], [], 1.2),
    ("winter", "season", {"months": [12, 1, 2]}, 0, 0, ["peaceful_sleep", "loneliness"], ["stillness", "rest"], [], 1.0),
    ("spring", "season", {"months": [3, 4, 5]}, 0, 0, ["fresh_start", "hope"], ["renewal", "growth"], [], 1.0),
    ("summer", "season", {"months": [6, 7, 8]}, 0, 0, ["burnout", "major_life_change"], ["rest", "travel"], [], 1.0),
    ("fall", "season", {"months": [9, 10, 11]}, 0, 0, ["gratitude", "purpose"], ["reflection", "harvest"], [], 1.0),
    ("january_fresh_start", "fixed", {"month": 1, "day": 2}, 0, 14, ["fresh_start", "prayer_habit"], ["new habits", "goals"], [], 1.2),
    ("tax_season_stress", "fixed", {"month": 3, "day": 1}, 0, 44, ["financial_stress", "stress"], ["financial pressure"], [], 1.0),
    ("graduation_season", "fixed", {"month": 5, "day": 1}, 0, 30, ["college_student", "major_life_change", "purpose"], ["new chapter", "transition"], [], 1.0),
    ("summer_travel", "fixed", {"month": 6, "day": 15}, 0, 60, ["burnout", "gratitude"], ["rest", "adventure"], [], 0.9),
    ("back_to_school_stress", "fixed", {"month": 8, "day": 20}, 0, 20, ["busy_parent", "stress"], ["transition stress"], [], 1.0),
    ("holiday_loneliness", "fixed", {"month": 12, "day": 10}, 0, 20, ["loneliness", "grief"], ["connection", "presence"], ["celebratory"], 1.1),
    ("year_end_reflection", "fixed", {"month": 12, "day": 26}, 0, 5, ["gratitude", "purpose", "fresh_start"], ["reflection", "gratitude"], [], 1.1),
]


def build_seasonality(key, date_rule_type, date_rule_params, lead_days, follow_days, eligible_campaigns, suggested_angles, prohibited_tones, weight_boost):
    return {
        "name": key.replace("_", " ").title(),
        "date_rule": {"type": date_rule_type, **date_rule_params},
        "lead_days": lead_days,
        "follow_days": follow_days,
        "eligible_campaigns": eligible_campaigns,
        "suggested_angles": suggested_angles,
        "prohibited_tones": prohibited_tones,
        "weight_boost": weight_boost,
        "active": True,
    }


def main() -> None:
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
    FORMULAS_DIR.mkdir(parents=True, exist_ok=True)
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    SEASONALITY_DIR.mkdir(parents=True, exist_ok=True)

    for key, name, goal, pain, promise, personas, weight in CAMPAIGN_TABLE:
        data = build_campaign(key, name, goal, pain, promise, personas, weight)
        with (CAMPAIGNS_DIR / f"{key}.json").open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    print(f"Wrote {len(CAMPAIGN_TABLE)} campaign files to {CAMPAIGNS_DIR}")

    for key, name, description, structure in FORMULA_TABLE:
        data = build_formula(key, name, description, structure)
        with (FORMULAS_DIR / f"{key}.json").open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    print(f"Wrote {len(FORMULA_TABLE)} formula files to {FORMULAS_DIR}")

    for key, name, description, concerns, tone, compatible, weight in PERSONA_TABLE:
        data = build_persona(key, name, description, concerns, tone, compatible, weight)
        with (PERSONAS_DIR / f"{key}.json").open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    print(f"Wrote {len(PERSONA_TABLE)} persona files to {PERSONAS_DIR}")

    for row in SEASONALITY_TABLE:
        key = row[0]
        data = build_seasonality(*row)
        with (SEASONALITY_DIR / f"{key}.json").open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    print(f"Wrote {len(SEASONALITY_TABLE)} seasonality files to {SEASONALITY_DIR}")


if __name__ == "__main__":
    main()
