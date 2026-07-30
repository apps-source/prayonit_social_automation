import json
import sqlite3
from dataclasses import replace

import config
import history_store
import prayonit_social
import prompt_builder
import pytest
import resolved_content_brief


def _weekly(
    emotion="overwhelmed",
    slot="morning",
    content_type="app_feature",
    video_template="short_promo",
    engagement_prompt_enabled=False,
    engagement_prompt_type="none",
    prayer_category_id=None,
    theme="strength",
):
    weekly = {
        "content_type": content_type,
        "theme": theme,
        "emotion": emotion,
        "hook_style": "recognition",
        "objective": "Offer one gentle next step.",
        "video_template": video_template,
        "video_library": "short",
        "duration_seconds": 8,
        "marketing_enabled": content_type == "app_feature",
        "show_logo": True,
        "show_badges": True,
        "show_cta": True,
        "show_link_in_bio": True,
        "show_app_benefit": content_type == "app_feature",
        "engagement_prompt_enabled": engagement_prompt_enabled,
        "engagement_prompt_type": engagement_prompt_type,
        "cta_text": "Come pray with me.",
    }
    if prayer_category_id is not None:
        weekly["prayer_category_id"] = prayer_category_id
    return weekly


def _life_moments():
    return [
        {"category": "Work & Ambition", "moment": "Feeling overwhelmed at work", "emotions": ["overwhelm"]},
        {"category": "Family & Parenting", "moment": "Missing a child who's grown and gone", "emotions": ["longing"]},
    ]


def _hooks():
    return [{"name": "Recognition", "emotions": ["overwhelm"]}]


def _campaign(key="job_stress", name="Job Stress", pain_point="feeling overwhelmed at work"):
    return {"_key": key, "name": name, "pain_point": pain_point, "goal": pain_point}


def _resolve(**overrides):
    kwargs = {
        "run_id": "run-1",
        "slot": "morning",
        "post_date": "2026-07-27",
        "platform_mode": "reels_only",
        "candidate_campaign": _campaign(),
        "campaigns": [_campaign()],
        "weekly_content": _weekly(),
        "life_moments": _life_moments(),
        "hook_styles": _hooks(),
    }
    kwargs.update(overrides)
    return resolved_content_brief.resolve_content_brief(**kwargs)


def test_overwhelmed_normalizes_to_overwhelm():
    assert resolved_content_brief.normalize_pain_point("feeling overwhelmed") == "overwhelm"


def test_alias_matching_selects_appropriate_life_moment():
    brief = _resolve()
    assert brief.pain_point_id == "overwhelm"
    assert brief.life_moment_text == "Feeling overwhelmed at work"
    assert brief.resolution_reason == "exact_or_alias_match"


def test_unmatched_pain_point_never_uses_an_unrelated_random_life_moment():
    brief = _resolve(
        weekly_content=_weekly(emotion="unmapped emotion"),
        candidate_campaign=None,
        campaigns=[],
    )
    assert brief.life_moment_id is None
    assert brief.life_moment_text is None
    assert brief.resolution_reason == "unresolved_no_emotionally_compatible_fallback"
    assert resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_resolved_content_brief(brief)
    )


def test_resolved_life_moment_controls_gemini_creative_brief():
    brief = _resolve()
    prompt = prompt_builder.build_prompt(
        post_type="morning ad",
        selection={"spiritual_action": "Bring this to God in prayer."},
        slot="morning",
        tracked_url="https://example.com",
        resolved_brief=brief,
    )
    assert "Life Moment:\nFeeling overwhelmed at work" in prompt


def test_morning_work_overwhelm_selects_a_morning_semantic_engagement_prompt():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="save_or_share",
        )
    )
    assert brief.engagement_prompt_id == "work-overwhelm-carry"
    assert "2am" not in brief.engagement_prompt.lower()
    assert "semantic match" in brief.engagement_selection_reason


def test_evening_anxiety_may_select_a_nighttime_engagement_prompt():
    brief = _resolve(
        slot="evening",
        weekly_content=_weekly(
            emotion="anxious",
            slot="evening",
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="comment_or_send",
        ),
        life_moments=[{"category": "Sleep & Nighttime", "moment": "Racing thoughts at 2am", "emotions": ["anxiety"]}],
    )
    assert brief.engagement_prompt_id in {"evening-anxiety-2am", "evening-anxiety-release"}
    assert any(word in brief.engagement_prompt.lower() for word in ("2am", "tonight"))


def test_parenting_life_moment_selects_a_parenting_compatible_prompt():
    brief = _resolve(
        weekly_content=_weekly(
            emotion="longing",
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="comment_or_send",
        ),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[_life_moments()[1]],
    )
    assert brief.engagement_prompt_id == "parenting-longing-memory"
    assert "child" in brief.engagement_prompt.lower()


def test_share_or_amen_selects_a_type_compatible_prompt():
    brief = _resolve(
        slot="evening",
        weekly_content=_weekly(
            emotion="anxious",
            content_type="night_prayer_or_rest",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="share_or_amen",
        ),
        life_moments=[{"category": "Sleep & Nighttime", "moment": "Racing thoughts at 2am", "emotions": ["anxiety"]}],
    )
    profile = next(profile for profile in resolved_content_brief.load_engagement_prompt_profiles() if profile["id"] == brief.engagement_prompt_id)
    assert "share_or_amen" in profile["engagement_types"]
    assert "Amen" in brief.engagement_prompt


def test_unmatched_content_uses_neutral_type_compatible_fallback(monkeypatch):
    fallback = {
        "id": "fallback",
        "prompt": "Save this prayer for when you need it again today.",
        "slots": ["morning"],
        "content_types": ["prayer_read"],
        "engagement_types": ["save_or_share"],
        "fallback": True,
    }
    monkeypatch.setattr(resolved_content_brief, "load_engagement_prompt_profiles", lambda: [fallback])
    brief = _resolve(
        weekly_content=_weekly(
            emotion="unmapped emotion",
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="save_or_share",
        ),
        candidate_campaign=None,
        campaigns=[],
    )
    assert brief.engagement_prompt == fallback["prompt"]
    assert "neutral type-compatible fallback" in brief.engagement_selection_reason
    report = resolved_content_brief.validate_resolved_content_brief(brief)
    assert any(item["field"] == "engagement_prompt" and item["status"] == "warning" for item in report)


def test_time_conflicting_engagement_prompt_fails_validation():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="save_or_share",
        )
    )
    evening_profile = next(
        profile for profile in resolved_content_brief.load_engagement_prompt_profiles()
        if profile["id"] == "evening-anxiety-release"
    )
    invalid = replace(
        brief,
        engagement_prompt_id=evening_profile["id"],
        engagement_prompt=evening_profile["prompt"],
    )
    report = resolved_content_brief.validate_resolved_content_brief(invalid)
    assert any(item["field"] == "engagement_prompt" and item["status"] == "critical failure" for item in report)


def test_resolved_engagement_prompt_reaches_gemini_brief_and_corrects_mismatch(capsys):
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            engagement_prompt_enabled=True,
            engagement_prompt_type="save_or_share",
        )
    )
    prompt = prompt_builder.build_creative_brief_preamble("morning", resolved_brief=brief)
    corrected = prompt_builder.enforce_resolved_engagement_line({"engagement_line": "Unrelated question?"}, brief)
    assert brief.engagement_prompt in prompt
    assert "verbatim as engagement_line" in prompt
    assert corrected["engagement_line"] == brief.engagement_prompt
    assert "corrected" in capsys.readouterr().out


def test_incompatible_business_campaign_is_not_authoritative_for_grown_child_brief():
    business_campaign = _campaign("business_owner", "Business Owner", "carrying the weight of a business")
    brief = _resolve(
        weekly_content=_weekly(emotion="longing"),
        candidate_campaign=business_campaign,
        campaigns=[business_campaign],
        life_moments=[_life_moments()[1]],
    )
    assert brief.life_moment_text == "Missing a child who's grown and gone"
    assert brief.campaign_id is None
    assert brief.campaign_name is None
    assert "incompatible_campaign_dropped" in brief.resolution_reason


def test_compatible_campaign_is_retained():
    brief = _resolve()
    assert brief.campaign_id == "job_stress"
    assert brief.campaign_compatible is True


def test_creator_search_topic_follows_resolved_life_moment():
    brief = _resolve(
        weekly_content=_weekly(emotion="longing"),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[_life_moments()[1]],
    )
    assert brief.creator_search_topic == "prayer for parents missing grown children"
    assert prayonit_social._resolve_creator_search_topic({}, {}, brief) == brief.creator_search_topic


def test_asset_time_validation_rejects_explicit_slot_conflicts():
    morning_brief = _resolve()
    evening_brief = _resolve(slot="evening", weekly_content=_weekly(slot="evening"))
    assert not resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_asset_metadata(morning_brief, {"time": "morning"})
    )
    assert resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_asset_metadata(evening_brief, {"time": "morning"})
    )
    assert not resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_asset_metadata(evening_brief, {"time": "anytime"})
    )


def test_hopeful_resolves_to_hope_compatible_life_moment_not_anger_after_loss():
    brief = _resolve(
        weekly_content=_weekly(emotion="hopeful"),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[
            {"category": "Faith & Spiritual Life", "moment": "Anger toward God after a loss", "emotions": ["anger", "grief"]},
            {"category": "Faith & Spiritual Life", "moment": "Looking for gentle encouragement today", "emotions": ["hope", "encouragement"]},
        ],
    )
    assert brief.pain_point_id == "hope"
    assert brief.life_moment_text == "Looking for gentle encouragement today"
    assert brief.resolution_reason == "exact_or_alias_match"


def test_grief_or_loss_can_select_anger_and_loss_compatible_life_moment():
    brief = _resolve(
        weekly_content=_weekly(emotion="loss"),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[
            {"category": "Faith & Spiritual Life", "moment": "Anger toward God after a loss", "emotions": ["anger", "grief"]},
        ],
    )
    assert brief.pain_point_id == "grief"
    assert brief.life_moment_text == "Anger toward God after a loss"


def test_contradictory_life_moment_is_a_critical_validation_failure():
    brief = _resolve(
        weekly_content=_weekly(emotion="hopeful"),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[
            {"category": "Faith & Spiritual Life", "moment": "Looking for gentle encouragement today", "emotions": ["hope"]},
        ],
    )
    contradictory = replace(
        brief,
        life_moment_text="Anger toward God after a loss",
        life_moment_emotions=("anger", "grief"),
    )
    report = resolved_content_brief.validate_resolved_content_brief(contradictory)
    assert any(item["field"] == "life_moment" and item["status"] == "critical failure" for item in report)


def test_no_emotionally_compatible_fallback_blocks_before_rendering():
    brief = _resolve(
        weekly_content=_weekly(emotion="hopeful"),
        candidate_campaign=None,
        campaigns=[],
        life_moments=[
            {"category": "Faith & Spiritual Life", "moment": "Anger toward God after a loss", "emotions": ["anger", "grief"]},
        ],
    )
    assert brief.life_moment_text is None
    assert "unresolved_no_emotionally_compatible_fallback" in brief.resolution_reason
    assert resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_resolved_content_brief(brief)
    )


def test_approved_cta_and_destination_are_preserved():
    brief = _resolve()
    report = resolved_content_brief.validate_resolved_content_brief(brief)
    assert brief.cta_text == config.FACEBOOK_CTA
    assert brief.destination_url == config.DEFAULT_DESTINATION_URL
    assert all(item["status"] != "critical failure" for item in report)


def test_explicit_prayer_category_is_resolved():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="hope_encouragement",
            video_template="long_encouragement",
            prayer_category_id="hope",
            theme="release",
        )
    )
    assert brief.prayer_category_id == "hope"
    assert brief.prayer_category_resolution_reason == "explicit_weekly_category"


def test_morning_prayer_category_is_inferred_without_explicit_input():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            theme="strength",
        )
    )
    assert brief.prayer_category_id == "morning_prayer"
    assert brief.prayer_category_resolution_reason == "inferred_from_morning_prayer_format"


def test_night_prayer_category_is_inferred_without_explicit_input():
    brief = _resolve(
        slot="evening",
        weekly_content=_weekly(
            slot="evening",
            content_type="prayer_read",
            video_template="long_prayer",
            theme="rest",
        ),
    )
    assert brief.prayer_category_id == "night_prayer"
    assert brief.prayer_category_resolution_reason == "inferred_from_evening_prayer_format"


def test_bible_verse_category_is_inferred_from_explicit_format_theme():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="recognition_engagement",
            video_template="short_engagement",
            theme="Bible Verse",
        )
    )
    assert brief.prayer_category_id == "bible_verse"
    assert brief.prayer_category_resolution_reason == "inferred_from_explicit_bible_verse_format"


def test_devotional_category_is_inferred_from_existing_format():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="devotional_read",
            video_template="long_devotional",
            theme="perseverance",
        )
    )
    assert brief.prayer_category_id == "devotional"
    assert brief.prayer_category_resolution_reason == "inferred_from_devotional_format"


def test_ambiguous_input_uses_documented_general_prayer_fallback(capsys):
    brief = _resolve(
        weekly_content=_weekly(
            content_type="app_feature",
            video_template="short_promo",
            theme="personalized prayer",
        )
    )
    assert brief.prayer_category_id == "general_prayer"
    assert brief.prayer_category_resolution_reason == "fallback_no_safe_category_inference"
    assert "fallback to general_prayer" in capsys.readouterr().out
    report = resolved_content_brief.validate_resolved_content_brief(brief)
    assert any(
        item["field"] == "prayer_category_id" and item["status"] == "warning"
        for item in report
    )


def test_unknown_explicit_category_falls_back_safely(capsys):
    brief = _resolve(
        weekly_content=_weekly(prayer_category_id="not_a_real_category")
    )
    assert brief.prayer_category_id == "general_prayer"
    assert brief.prayer_category_resolution_reason == (
        "fallback_unknown_explicit_category:not_a_real_category"
    )
    assert "unknown explicit category" in capsys.readouterr().out


def test_incompatible_explicit_category_falls_back_safely():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            prayer_category_id="night_prayer",
        )
    )
    assert brief.prayer_category_id == "general_prayer"
    assert brief.prayer_category_resolution_reason.startswith(
        "fallback_incompatible_explicit_category"
    )


def test_category_and_global_profile_defaults_resolve_deterministically():
    registry = resolved_content_brief.load_creative_profile_registry()
    category_override = {
        "default_profiles": {"hook_profile_id": "category_hook"}
    }
    custom_registry = {
        **registry,
        "global_defaults": {
            **registry["global_defaults"],
            "hook_profile_id": "global_hook",
        },
    }
    resolved = resolved_content_brief._resolve_creative_profile_ids(
        category_override, custom_registry
    )
    assert resolved["hook_profile_id"] == "category_hook"
    assert resolved["body_profile_id"] == "current_default"
    assert resolved["caption_profile_id"] == "current_default"


def test_policy_version_and_all_profile_ids_are_captured():
    brief = _resolve()
    assert brief.creative_policy_version == "1"
    assert brief.hook_profile_id == "gentle_invitation"
    assert brief.voice_profile_id == "natural_conversational"
    assert brief.body_profile_id == "general_prayer"
    assert brief.caption_profile_id == "current_default"
    assert brief.scene_profile_id == "current_default"
    assert brief.cta_profile_id == "current_default"
    assert brief.hashtag_profile_id == "current_default"


def test_rolling_caption_profile_is_valid_but_not_assigned_by_default():
    profile = resolved_content_brief.get_caption_profile_definition(
        "rolling_short",
        creative_policy_version="1",
    )
    assert profile["id"] == "rolling_short"
    assert profile["mode"] == "rolling_phrase"
    assert _resolve().caption_profile_id == "current_default"


def test_explicit_caption_profile_override_is_resolver_owned():
    brief = _resolve(caption_profile_override="rolling_short")
    assert brief.caption_profile_id == "rolling_short"
    assert not resolved_content_brief.has_critical_failure(
        resolved_content_brief.validate_resolved_content_brief(brief)
    )


def test_unknown_caption_profile_lookup_fails_safely():
    with pytest.raises(RuntimeError, match="Unknown caption profile"):
        resolved_content_brief.get_caption_profile_definition("does_not_exist")


def test_caption_profile_lookup_respects_creative_policy_version():
    with pytest.raises(RuntimeError, match="does not match the active creative policy"):
        resolved_content_brief.get_caption_profile_definition(
            "rolling_short",
            creative_policy_version="999",
        )


def test_hook_writing_and_body_profile_lookup_uses_active_policy():
    hook = resolved_content_brief.get_hook_profile_definition(
        "empathetic_recognition",
        creative_policy_version="1",
    )
    writing = resolved_content_brief.get_writing_profile_definition(
        "gentle_encouraging",
        creative_policy_version="1",
    )
    body = resolved_content_brief.get_body_profile_definition(
        "anxiety_relief",
        creative_policy_version="1",
    )
    assert hook["writing_guidance"]
    assert writing["purpose"] == "content_writing_only"
    assert "voice_style_profile" not in writing
    assert body["petition_focus"]


def test_unknown_hook_writing_and_body_profiles_fail_safely():
    with pytest.raises(RuntimeError, match="Unknown hook profile"):
        resolved_content_brief.get_hook_profile_definition("missing")
    with pytest.raises(RuntimeError, match="Unknown writing profile"):
        resolved_content_brief.get_writing_profile_definition("missing")
    with pytest.raises(RuntimeError, match="Unknown body profile"):
        resolved_content_brief.get_body_profile_definition("missing")


def test_category_hook_writing_and_body_defaults_are_compatible():
    for category in resolved_content_brief.load_prayer_categories():
        hook_id = category["default_profiles"].get("hook_profile_id")
        writing_id = category["default_profiles"].get("voice_profile_id")
        body_id = category["default_profiles"].get("body_profile_id")
        if not hook_id or not writing_id or not body_id:
            continue
        hook = resolved_content_brief.get_hook_profile_definition(hook_id)
        writing = resolved_content_brief.get_writing_profile_definition(writing_id)
        body = resolved_content_brief.get_body_profile_definition(body_id)
        assert (
            "any" in hook["compatible_categories"]
            or category["id"] in hook["compatible_categories"]
        )
        assert (
            "any" in writing["compatible_categories"]
            or category["id"] in writing["compatible_categories"]
        )
        assert (
            "any" in body["compatible_categories"]
            or category["id"] in body["compatible_categories"]
        )


def test_resolver_owns_category_profile_selection():
    weekly = _weekly(
        content_type="prayer_read",
        video_template="long_prayer",
        prayer_category_id="morning_prayer",
    )
    brief = _resolve(weekly_content=weekly)
    assert brief.hook_profile_id == "hopeful_encouragement"
    assert brief.voice_profile_id == "natural_conversational"
    assert brief.body_profile_id == "morning_direction"


def test_general_prayer_uses_safe_hook_and_neutral_writing_profiles():
    brief = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            prayer_category_id="general_prayer",
        )
    )
    assert brief.prayer_category_id == "general_prayer"
    assert brief.hook_profile_id == "gentle_invitation"
    assert brief.voice_profile_id == "natural_conversational"
    assert brief.body_profile_id == "general_prayer"


def test_category_profile_mappings_remain_explicit_and_stable():
    actual = {
        category["id"]: (
            category["default_profiles"]["hook_profile_id"],
            category["default_profiles"]["voice_profile_id"],
            category["default_profiles"]["body_profile_id"],
        )
        for category in resolved_content_brief.load_prayer_categories()
    }
    assert actual == {
        "morning_prayer": ("hopeful_encouragement", "natural_conversational", "morning_direction"),
        "night_prayer": ("gentle_invitation", "calm_reflective", "night_release"),
        "hope": ("hopeful_encouragement", "gentle_encouraging", "hope_and_encouragement"),
        "peace": ("quiet_reflection", "calm_reflective", "peace_and_rest"),
        "anxiety": ("empathetic_recognition", "gentle_encouraging", "anxiety_relief"),
        "fear": ("empathetic_recognition", "gentle_encouraging", "anxiety_relief"),
        "healing": ("empathetic_recognition", "calm_reflective", "healing_and_comfort"),
        "protection": ("protective_intercession", "gentle_encouraging", "protection_and_covering"),
        "forgiveness": ("quiet_reflection", "calm_reflective", "forgiveness_and_restoration"),
        "guidance": ("curiosity", "natural_conversational", "guidance_and_decisions"),
        "strength": ("hopeful_encouragement", "gentle_encouraging", "strength_and_perseverance"),
        "gratitude": ("quiet_reflection", "calm_reflective", "gratitude_and_praise"),
        "family": ("protective_intercession", "gentle_encouraging", "family_and_relationships"),
        "bible_verse": ("scripture_first", "scripture_reader", "scripture_centered"),
        "devotional": ("curiosity", "natural_conversational", "devotional_reflection"),
        "general_prayer": ("gentle_invitation", "natural_conversational", "general_prayer"),
    }


def test_key_categories_resolve_distinct_body_profiles():
    anxiety = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            prayer_category_id="anxiety",
        )
    )
    protection = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            prayer_category_id="protection",
        )
    )
    morning = _resolve(
        weekly_content=_weekly(
            content_type="prayer_read",
            video_template="long_prayer",
            prayer_category_id="morning_prayer",
        )
    )
    night = _resolve(
        slot="evening",
        weekly_content=_weekly(
            content_type="night_prayer_or_rest",
            video_template="long_prayer",
            prayer_category_id="night_prayer",
        ),
    )
    bible = _resolve(
        weekly_content=_weekly(
            content_type="devotional_read",
            video_template="long_devotional",
            prayer_category_id="bible_verse",
        )
    )

    assert anxiety.body_profile_id == "anxiety_relief"
    assert protection.body_profile_id == "protection_and_covering"
    assert anxiety.body_profile_id != protection.body_profile_id
    assert morning.body_profile_id == "morning_direction"
    assert night.body_profile_id == "night_release"
    assert morning.body_profile_id != night.body_profile_id
    assert bible.body_profile_id == "scripture_centered"


def test_legacy_empathy_hook_style_is_resolved_in_canonical_brief():
    weekly = {**_weekly(), "hook_style": "empathy"}
    brief = _resolve(
        weekly_content=weekly,
        hook_styles=resolved_content_brief.content_engine.load_hook_styles(),
    )
    assert brief.hook_style_id == "recognition"
    assert brief.hook_style_label == "Recognition"


def test_incompatible_hook_and_writing_profiles_are_critical():
    incompatible = replace(
        _resolve(),
        hook_profile_id="scripture_first",
        voice_profile_id="calm_reflective",
    )
    report = resolved_content_brief.validate_resolved_content_brief(incompatible)
    assert any(
        item["field"] == "hook_profile_id"
        and item["status"] == "critical failure"
        for item in report
    )
    assert any(
        item["field"] == "voice_profile_id"
        and item["status"] == "critical failure"
        for item in report
    )


def test_missing_profile_definition_fields_are_critical(monkeypatch):
    brief = _resolve()
    registry = json.loads(
        json.dumps(resolved_content_brief.load_creative_profile_registry())
    )
    registry["hook_profiles"]["gentle_invitation"].pop("compatible_categories")
    monkeypatch.setattr(
        resolved_content_brief,
        "load_creative_profile_registry",
        lambda: registry,
    )
    report = resolved_content_brief.validate_resolved_content_brief(brief)
    assert any(
        item["field"] == "hook_profile_id"
        and item["status"] == "critical failure"
        and "incomplete" in item["message"].lower()
        for item in report
    )


def test_missing_body_profile_structured_field_is_critical(monkeypatch):
    brief = _resolve()
    registry = json.loads(
        json.dumps(resolved_content_brief.load_creative_profile_registry())
    )
    registry["body_profiles"]["general_prayer"].pop("petition_focus")
    monkeypatch.setattr(
        resolved_content_brief,
        "load_creative_profile_registry",
        lambda: registry,
    )
    report = resolved_content_brief.validate_resolved_content_brief(brief)
    assert any(
        item["field"] == "body_profile_id"
        and item["status"] == "critical failure"
        and "incomplete" in item["message"].lower()
        for item in report
    )


def test_incompatible_body_profile_is_critical():
    invalid = replace(_resolve(), body_profile_id="scripture_centered")
    report = resolved_content_brief.validate_resolved_content_brief(invalid)
    assert any(
        item["field"] == "body_profile_id"
        and item["status"] == "critical failure"
        for item in report
    )


def test_unknown_body_profile_id_is_critical():
    invalid = replace(_resolve(), body_profile_id="missing_body_profile")
    report = resolved_content_brief.validate_resolved_content_brief(invalid)
    assert any(
        item["field"] == "body_profile_id"
        and item["status"] == "critical failure"
        for item in report
    )


def test_explicit_weekly_categories_are_compatible_with_their_slots_and_types():
    categories = resolved_content_brief.load_prayer_categories()
    for day_config in resolved_content_brief.content_engine.load_weekly_rhythm().values():
        for slot, weekly in day_config.items():
            explicit_id = weekly.get("prayer_category_id")
            if not explicit_id:
                continue
            presentation = resolved_content_brief.content_engine.get_presentation_config(
                weekly
            )
            long_form_type = {
                "long_prayer": "prayer",
                "long_devotional": "devotional",
                "long_encouragement": "encouragement",
            }.get(presentation["video_template"], "none")
            category, reason = resolved_content_brief._resolve_prayer_category(
                explicit_category_id=explicit_id,
                slot=slot,
                content_type=weekly["content_type"],
                weekly_theme=weekly["theme"],
                video_template=presentation["video_template"],
                long_form_type=long_form_type,
                category_definitions=categories,
            )
            assert category["id"] == explicit_id
            assert reason == "explicit_weekly_category"


def test_unknown_profile_reference_is_a_critical_validation_failure():
    invalid = replace(_resolve(), scene_profile_id="unknown_scene_profile")
    report = resolved_content_brief.validate_resolved_content_brief(invalid)
    assert any(
        item["field"] == "scene_profile_id"
        and item["status"] == "critical failure"
        for item in report
    )


def test_missing_policy_version_is_a_critical_validation_failure():
    report = resolved_content_brief.validate_resolved_content_brief(
        replace(_resolve(), creative_policy_version="")
    )
    assert any(
        item["field"] == "creative_policy_version"
        and item["status"] == "critical failure"
        for item in report
    )


def test_incompatible_resolved_category_is_a_critical_validation_failure():
    invalid = replace(
        _resolve(
            weekly_content=_weekly(
                content_type="prayer_read",
                video_template="long_prayer",
            )
        ),
        prayer_category_id="night_prayer",
    )
    report = resolved_content_brief.validate_resolved_content_brief(invalid)
    assert any(
        item["field"] == "prayer_category_id"
        and item["status"] == "critical failure"
        for item in report
    )


def test_legacy_brief_construction_uses_safe_creative_defaults():
    current = _resolve().to_history_dict()
    for field_name in (
        "prayer_category_id",
        "hook_profile_id",
        "voice_profile_id",
        "body_profile_id",
        "caption_profile_id",
        "scene_profile_id",
        "cta_profile_id",
        "hashtag_profile_id",
        "creative_policy_version",
        "prayer_category_resolution_reason",
    ):
        current.pop(field_name)
    legacy = resolved_content_brief.ResolvedContentBrief(**current)
    assert legacy.prayer_category_id == "general_prayer"
    assert legacy.voice_profile_id == "natural_conversational"
    assert legacy.body_profile_id == "current_default"
    assert legacy.creative_policy_version == "1"


def test_history_serialization_includes_creative_resolution_fields():
    payload = _resolve().to_history_dict()
    serialized = json.dumps(payload)
    restored = json.loads(serialized)
    assert restored["prayer_category_id"]
    assert restored["hook_profile_id"] == "gentle_invitation"
    assert restored["body_profile_id"] == "general_prayer"
    assert restored["creative_policy_version"] == "1"
    assert "default_profiles" not in restored


def test_prompt_context_reads_resolved_profiles_without_reselecting_them():
    brief = replace(
        _resolve(),
        hook_profile_id="resolver_owned_hook",
        body_profile_id="resolver_owned_body",
        caption_profile_id="resolver_owned_caption",
    )
    creative_context = prompt_builder.build_creative_brief_data(
        "morning", resolved_brief=brief
    )
    assert creative_context["hook_profile_id"] == "resolver_owned_hook"
    assert creative_context["body_profile_id"] == "resolver_owned_body"
    assert creative_context["caption_profile_id"] == "resolver_owned_caption"
    assert creative_context["prayer_category_id"] == brief.prayer_category_id


def test_current_renderer_facing_fields_remain_unchanged():
    weekly = _weekly(
        content_type="prayer_read",
        video_template="long_prayer",
        prayer_category_id="morning_prayer",
    )
    brief = _resolve(weekly_content=weekly)
    presentation = resolved_content_brief.content_engine.get_presentation_config(
        weekly
    )
    assert brief.video_template == presentation["video_template"]
    assert brief.duration_seconds == presentation["duration_seconds"]
    assert brief.voice_style_profile == "natural_conversational"


def test_history_persists_resolved_brief_and_migrates_existing_schema(monkeypatch, tmp_path):
    database_path = tmp_path / "history.db"
    monkeypatch.setattr(config, "DATABASE_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE campaigns_used (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                slot TEXT NOT NULL, campaign_name TEXT NOT NULL,
                formula_name TEXT, persona_name TEXT, seasonal_context TEXT,
                selected_hook TEXT, selected_body_angle TEXT, selected_cta TEXT,
                selected_thread_topic TEXT, background_object_path TEXT,
                generated_feed_object_path TEXT, generated_story_object_path TEXT,
                headline TEXT, story_headline TEXT, status TEXT NOT NULL,
                error_message TEXT
            )
            """
        )
    history_store.initialize_database()
    brief = _resolve()
    history_store.create_run_record(
        run_id=brief.run_id,
        slot=brief.slot,
        campaign_name=brief.campaign_name or "",
        resolved_brief=brief.to_history_dict(),
    )
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(campaigns_used)")}
        row = connection.execute(
            "SELECT pain_point_id, life_moment_text, selected_creator_search_topic, resolved_brief_json, "
            "engagement_prompt_type, resolved_engagement_prompt, engagement_selection_reason "
            "FROM campaigns_used WHERE run_id = ?", (brief.run_id,)
        ).fetchone()
    assert {"pain_point_id", "life_moment_text", "voice_style_profile", "resolved_brief_json", "engagement_prompt_type", "resolved_engagement_prompt", "engagement_selection_reason"} <= columns
    assert row[0] == "overwhelm"
    assert row[1] == "Feeling overwhelmed at work"
    assert row[2] == brief.creator_search_topic
    assert '"pain_point_id": "overwhelm"' in row[3]
    persisted_brief = json.loads(row[3])
    assert persisted_brief["prayer_category_id"] == brief.prayer_category_id
    assert persisted_brief["creative_policy_version"] == "1"
    assert row[4] == brief.engagement_prompt_type
    assert row[5] == brief.engagement_prompt
    assert row[6] == brief.engagement_selection_reason
