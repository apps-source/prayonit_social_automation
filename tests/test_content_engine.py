"""Tests for engines/content_engine.py: Weekly Rhythm content engine.

This engine is an additive content-selection layer only; these tests
verify it in isolation and do not touch Gemini, Supabase, Buffer, or the
image/video rendering pipeline.
"""
from datetime import datetime, timezone

import pytest

from engines import content_engine
import motion_renderer


def _sample_rhythm():
    return {
        "monday": {
            "morning": {
                "content_type": "prayer_read",
                "theme": "strength",
                "emotion": "overwhelmed",
                "hook_style": "recognition",
                "objective": "Help people start the week trusting God.",
                "video_template": "long_prayer",
                "video_library": "long",
                "duration_seconds": 30,
                "marketing_enabled": False,
                "show_logo": True,
                "show_badges": False,
                "show_cta": True,
                "show_link_in_bio": True,
                "show_app_benefit": False,
                "engagement_prompt_enabled": True,
                "engagement_prompt_type": "save_or_share",
                "cta_text": "Come pray with me.",
            },
            "evening": {
                "content_type": "prayer_read",
                "theme": "rest",
                "emotion": "exhausted",
                "hook_style": "empathy",
                "objective": "Help people release the weight of the day before sleep.",
                "video_template": "long_prayer",
                "video_library": "long",
                "duration_seconds": 30,
                "marketing_enabled": False,
                "show_logo": True,
                "show_badges": False,
                "show_cta": True,
                "show_link_in_bio": True,
                "show_app_benefit": False,
                "engagement_prompt_enabled": True,
                "engagement_prompt_type": "save_or_share",
                "cta_text": "Come pray with me.",
            },
        },
        "tuesday": {
            "morning": {
                "content_type": "app_feature",
                "theme": "focus",
                "emotion": "scattered",
                "hook_style": "recognition",
                "objective": "Help people center their day around God.",
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
            },
            "evening": {
                "content_type": "app_feature",
                "theme": "personalized prayer",
                "emotion": "hopeful",
                "hook_style": "curiosity",
                "objective": "Introduce Prayonit naturally without sounding like an advertisement.",
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
            },
        },
        "wednesday": {
            "morning": {
                "content_type": "devotional_read",
                "theme": "perseverance",
                "emotion": "weary",
                "hook_style": "recognition",
                "objective": "Encourage people to keep going through the midweek slump with God's help.",
                "video_template": "long_devotional",
                "video_library": "long",
                "duration_seconds": 30,
                "marketing_enabled": False,
                "show_logo": True,
                "show_badges": False,
                "show_cta": True,
                "show_link_in_bio": True,
                "show_app_benefit": False,
                "engagement_prompt_enabled": True,
                "engagement_prompt_type": "save_or_share",
                "cta_text": "Come pray with me.",
            },
        },
    }


def test_load_weekly_rhythm_default_path_loads_all_seven_days():
    rhythm = content_engine.load_weekly_rhythm()
    expected_days = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    assert expected_days.issubset(rhythm.keys())
    for day in expected_days:
        assert "morning" in rhythm[day]
        assert "evening" in rhythm[day]
        for slot_name in ("morning", "evening"):
            slot_cfg = rhythm[day][slot_name]
            for key in ("content_type", "theme", "emotion", "hook_style", "objective"):
                assert slot_cfg.get(key), "{0} {1} missing {2}".format(day, slot_name, key)
            presentation = content_engine.get_presentation_config(slot_cfg)
            assert presentation["video_template"]
            assert presentation["video_library"] in {"short", "long"}
            assert 8 <= presentation["duration_seconds"] <= 35


def test_get_current_weekday_monday():
    monday = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)  # 2026-07-20 is a Monday
    assert content_engine.get_current_weekday(now=monday) == "monday"


def test_get_current_slot_morning_and_evening():
    morning_dt = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
    evening_dt = datetime(2026, 7, 20, 19, 0, tzinfo=timezone.utc)
    assert content_engine.get_current_slot(now=morning_dt) == "morning"
    assert content_engine.get_current_slot(now=evening_dt) == "evening"


def test_get_todays_content_monday_morning_matches_expected_example():
    monday = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        slot="morning", now=monday, weekly_rhythm=_sample_rhythm()
    )
    assert result["content_type"] == "prayer_read"
    assert result["video_template"] == "long_prayer"
    assert result["video_library"] == "long"
    assert result["duration_seconds"] == 30
    assert result["theme"] == "strength"
    assert result["objective"] == "Help people start the week trusting God."


def test_get_todays_content_tuesday_evening_matches_expected_example():
    tuesday = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        slot="evening", now=tuesday, weekly_rhythm=_sample_rhythm()
    )
    assert result["content_type"] == "app_feature"
    assert result["video_template"] == "short_promo"
    assert result["video_library"] == "short"
    assert result["duration_seconds"] == 8
    assert result["theme"] == "personalized prayer"


def test_get_todays_content_wednesday_morning_matches_expected_example():
    wednesday = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        slot="morning", now=wednesday, weekly_rhythm=_sample_rhythm()
    )
    assert result["content_type"] == "devotional_read"
    assert result["video_template"] == "long_devotional"
    assert result["video_library"] == "long"
    assert result["duration_seconds"] == 30


def test_get_todays_content_infers_slot_when_not_provided():
    monday_morning = datetime(2026, 7, 20, 7, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        now=monday_morning, weekly_rhythm=_sample_rhythm()
    )
    assert result["content_type"] == "prayer_read"


def test_get_todays_content_missing_day_raises_keyerror():
    with pytest.raises(KeyError):
        content_engine.get_todays_content(
            slot="morning",
            now=datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),  # Thursday, absent in sample
            weekly_rhythm=_sample_rhythm(),
        )


def test_get_presentation_config_missing_fields_falls_back_to_short_promo_defaults():
    presentation = content_engine.get_presentation_config(
        {
            "content_type": "prayer_read",
            "marketing_enabled": "false",
            "show_logo": "yes",
            "duration_seconds": 99,
            "video_template": "invalid",
            "video_library": "invalid",
            "engagement_prompt_enabled": "true",
            "engagement_prompt_type": "invalid",
        }
    )
    assert presentation["content_type"] == "prayer_read"
    assert presentation["video_template"] == "short_promo"
    assert presentation["video_library"] == "short"
    assert presentation["duration_seconds"] == 8
    assert presentation["marketing_enabled"] is True
    assert presentation["show_logo"] is True
    assert presentation["engagement_prompt_enabled"] is False
    assert presentation["engagement_prompt_type"] == "none"


def test_existing_weekly_rhythm_fields_still_work_with_presentation_metadata():
    monday = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        slot="morning", now=monday, weekly_rhythm=_sample_rhythm()
    )
    assert result["theme"] == "strength"
    assert result["emotion"] == "overwhelmed"
    assert result["hook_style"] == "recognition"
    assert result["objective"] == "Help people start the week trusting God."


def test_existing_production_renderer_defaults_are_unchanged():
    monday = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)
    result = content_engine.get_todays_content(
        slot="morning", now=monday, weekly_rhythm=_sample_rhythm()
    )
    assert result["duration_seconds"] == 30
    assert motion_renderer.DEFAULT_VIDEO_DURATION_SECONDS == 8.0


def test_load_hook_styles_returns_25_entries_with_required_fields():
    styles = content_engine.load_hook_styles()
    assert len(styles) == 25
    for entry in styles:
        for key in ("name", "psychology", "best_time", "emotions", "example"):
            assert key in entry


def test_load_life_moments_returns_100_entries_with_required_fields():
    moments = content_engine.load_life_moments()
    assert len(moments) == 100
    for entry in moments:
        for key in ("category", "moment", "emotions"):
            assert key in entry


def test_load_engagement_prompts_returns_50_entries_with_required_fields():
    prompts = content_engine.load_engagement_prompts()
    assert len(prompts) == 50
    for entry in prompts:
        for key in ("prompt", "category"):
            assert key in entry


def test_load_soft_promotions_returns_50_entries_with_required_fields():
    promos = content_engine.load_soft_promotions()
    assert len(promos) == 50
    for entry in promos:
        for key in ("text", "style"):
            assert key in entry


def test_load_content_rules_has_weekly_themes_and_ratio():
    rules = content_engine.load_content_rules()
    assert "guiding_principle" in rules
    assert "weekly_themes" in rules
    assert "monday" in rules["weekly_themes"]


def test_get_random_hook_filters_by_style():
    hook = content_engine.get_random_hook(style="Recognition")
    assert hook is not None
    assert hook["name"] == "Recognition"


def test_get_random_hook_unknown_style_returns_none():
    assert content_engine.get_random_hook(style="Nonexistent Style") is None


def test_get_random_emotional_moment_filters_by_category():
    moment = content_engine.get_random_emotional_moment(category="Grief & Loss")
    assert moment is not None
    assert moment["category"] == "Grief & Loss"


def test_get_random_engagement_prompt_filters_by_category():
    prompt = content_engine.get_random_engagement_prompt(category="gratitude")
    assert prompt is not None
    assert prompt["category"] == "gratitude"


def test_get_random_soft_promotion_filters_by_style():
    promo = content_engine.get_random_soft_promotion(style="friend_recommendation")
    assert promo is not None
    assert promo["style"] == "friend_recommendation"


def test_get_random_hook_no_filter_returns_some_entry():
    hook = content_engine.get_random_hook()
    assert hook is not None
    assert "name" in hook
