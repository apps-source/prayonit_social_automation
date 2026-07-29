import sqlite3
from dataclasses import replace

import config
import history_store
import prayonit_social
import prompt_builder
import resolved_content_brief


def _weekly(
    emotion="overwhelmed",
    slot="morning",
    content_type="app_feature",
    video_template="short_promo",
    engagement_prompt_enabled=False,
    engagement_prompt_type="none",
):
    return {
        "content_type": content_type,
        "theme": "strength",
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
    assert row[4] == brief.engagement_prompt_type
    assert row[5] == brief.engagement_prompt
    assert row[6] == brief.engagement_selection_reason
