import sqlite3

import config
import history_store
import prayonit_social
import prompt_builder
import resolved_content_brief


def _weekly(emotion="overwhelmed", slot="morning"):
    return {
        "content_type": "app_feature",
        "theme": "strength",
        "emotion": emotion,
        "hook_style": "recognition",
        "objective": "Offer one gentle next step.",
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
    assert brief.resolution_reason == "unresolved_no_safe_fallback"
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
            "SELECT pain_point_id, life_moment_text, selected_creator_search_topic, resolved_brief_json "
            "FROM campaigns_used WHERE run_id = ?", (brief.run_id,)
        ).fetchone()
    assert {"pain_point_id", "life_moment_text", "voice_style_profile", "resolved_brief_json"} <= columns
    assert row[0] == "overwhelm"
    assert row[1] == "Feeling overwhelmed at work"
    assert row[2] == brief.creator_search_topic
    assert '"pain_point_id": "overwhelm"' in row[3]
