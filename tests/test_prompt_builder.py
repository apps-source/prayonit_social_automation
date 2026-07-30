"""Tests for prompt_builder.py: prompt construction and platform caption rules.
Gemini is fully mocked; no live network calls occur.
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import campaign_engine
import config
import history_store
import prompt_builder
import resolved_content_brief
import voice_provider


@pytest.fixture(autouse=True)
def _disable_real_content_retry_waits(monkeypatch):
    monkeypatch.setattr(
        prompt_builder, "_CONTENT_503_RETRY_DELAYS_SECONDS", ()
    )


def _presentation_content(
    *,
    content_type: str,
    video_template: str,
    duration_seconds: int,
    engagement_prompt_enabled: bool,
):
    return {
        "content_type": content_type,
        "theme": "test theme",
        "emotion": "test emotion",
        "hook_style": "recognition",
        "objective": "test objective",
        "video_template": video_template,
        "video_library": "long" if duration_seconds > 10 else "short",
        "duration_seconds": duration_seconds,
        "marketing_enabled": content_type == "app_feature",
        "show_logo": True,
        "show_badges": content_type == "app_feature",
        "show_cta": True,
        "show_link_in_bio": True,
        "show_app_benefit": content_type == "app_feature",
        "engagement_prompt_enabled": engagement_prompt_enabled,
        "engagement_prompt_type": "save_or_share" if engagement_prompt_enabled else "none",
        "cta_text": "Come pray with me.",
    }


def _fake_selection():
    campaigns = campaign_engine.load_campaigns()
    campaign = campaigns[0]
    formulas = campaign_engine.load_formulas()
    personas = campaign_engine.load_personas()
    return {
        "campaign": campaign,
        "formula": formulas[0],
        "persona": personas[0],
        "seasonal_context": None,
        "hook": campaign["hooks"][0],
        "body_angle": campaign["body_angles"][0],
        "cta": campaign["ctas"][0],
        "thread_topic": campaign["thread_topics"][0],
    }


def _resolved_profile_brief(
    *,
    category_id="general_prayer",
    content_type="prayer_read",
    video_template="long_prayer",
):
    return resolved_content_brief.resolve_content_brief(
        run_id="profile-test",
        slot="morning",
        post_date="2026-07-29",
        platform_mode="reels_only",
        candidate_campaign=None,
        campaigns=[],
        weekly_content={
            **_presentation_content(
                content_type=content_type,
                video_template=video_template,
                duration_seconds=30,
                engagement_prompt_enabled=True,
            ),
            "emotion": "anxiety",
            "hook_style": "recognition",
            "objective": "Offer a safe next step.",
            "prayer_category_id": category_id,
        },
        life_moments=[
            {
                "category": "Faith & Spiritual Life",
                "moment": "Feeling anxious before the day begins",
                "emotions": ["anxiety"],
            }
        ],
        hook_styles=[
            {
                "name": "Recognition",
                "psychology": "Recognize the felt experience.",
                "best_time": "Any",
                "emotions": ["anxiety"],
                "example": "Example text that must not enter profile guidance.",
            }
        ],
    )


def test_build_prompt_forbids_invented_urls_and_includes_slot_guidance():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="evening",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    assert "do not include any url" in prompt.lower()
    assert "prayonit.com" in prompt.lower()  # named explicitly as a forbidden invented domain
    assert "tonight" in prompt.lower()
    assert "start your day" in prompt.lower()  # appears in the "never say" instruction


def test_build_prompt_prepends_weekly_rhythm_schedule():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    # The Weekly Rhythm block must be prepended without removing any
    # existing prompt instructions.
    assert "today's schedule" in prompt.lower()
    assert "content type:" in prompt.lower()
    assert "objective:" in prompt.lower()
    assert "video template:" in prompt.lower()
    assert "target duration:" in prompt.lower()
    # Existing instructions remain intact.
    assert "do not include any url" in prompt.lower()


def test_build_prompt_prepends_creative_brief():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="monday_evening_stub",  # invalid slot falls back gracefully
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    assert "creative brief" in prompt.lower()
    # Existing instructions remain fully intact regardless.
    assert "do not include any url" in prompt.lower()


def test_build_creative_brief_data_evening_prayer_allows_engagement_prompt():
    # Monday evening in creative/weekly_rhythm.json is content_type
    # "prayer_read", which should allow an Engagement Prompt but not a
    # Soft Promotion.
    from datetime import datetime, timezone

    import engines.content_engine as content_engine

    monday_evening = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)  # Monday
    todays = content_engine.get_todays_content(slot="evening", now=monday_evening)
    assert todays["content_type"] == "prayer_read"
    assert prompt_builder.creative_brief_allows_engagement_prompt(todays["content_type"]) is True
    assert prompt_builder.creative_brief_allows_soft_promotion(todays["content_type"]) is False


def test_build_creative_brief_data_app_feature_allows_soft_promotion():
    # Tuesday evening in creative/weekly_rhythm.json is content_type
    # "app_feature", which should allow a Soft Promotion but not an
    # Engagement Prompt.
    from datetime import datetime, timezone

    import engines.content_engine as content_engine

    tuesday_evening = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)  # Tuesday
    todays = content_engine.get_todays_content(slot="evening", now=tuesday_evening)
    assert todays["content_type"] == "app_feature"
    assert prompt_builder.creative_brief_allows_engagement_prompt(todays["content_type"]) is False
    assert prompt_builder.creative_brief_allows_soft_promotion(todays["content_type"]) is True


def test_build_creative_brief_data_returns_required_fields():
    brief = prompt_builder.build_creative_brief_data(slot="morning")
    assert brief is not None
    for key in (
        "weekly_theme",
        "content_type",
        "video_template",
        "target_duration",
        "marketing_enabled",
        "engagement_prompt_enabled",
        "engagement_prompt_type",
        "expected_long_form_type",
        "objective",
        "tone",
        "emotional_goal",
        "life_moment",
        "hook",
    ):
        assert key in brief
    assert brief["life_moment"] is not None
    assert brief["hook"] is not None


def test_select_hook_for_style_matches_named_style():
    hook = prompt_builder.select_hook_for_style("recognition")
    assert hook is not None
    assert hook["name"].lower() == "recognition"


# ---------- Creative Brief as single source of truth (legacy Campaign/
# Persona/Formula/Hook/CTA no longer steer Gemini generation) ----------

def test_build_prompt_no_longer_contains_legacy_campaign_persona_formula_text():
    selection = _fake_selection()
    campaign = selection["campaign"]
    formula = selection["formula"]
    persona = selection["persona"]

    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()

    # Legacy steering labels must be gone from the actual Gemini prompt.
    assert "campaign:" not in lower
    assert "hook inspiration" not in lower
    assert "body angle inspiration" not in lower
    assert "cta inspiration" not in lower
    assert "use this proven advertising formula" not in lower
    assert "write with this audience in mind" not in lower

    # Legacy field values themselves must not leak into the prompt either.
    assert campaign["name"].lower() not in lower
    assert campaign["pain_point"].lower() not in lower
    assert formula["name"].lower() not in lower
    assert persona["name"].lower() not in lower
    assert selection["hook"].lower() not in lower
    assert selection["cta"].lower() not in lower


def test_build_prompt_states_primary_goal_is_not_to_advertise():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()
    assert "the primary goal is not to advertise the app" in lower
    assert "the primary goal is to help" in lower
    assert "feel understood" in lower


def test_build_prompt_includes_content_format_and_duration_guidance():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()
    assert "content type:" in lower
    assert "video template:" in lower
    assert "target duration:" in lower
    assert "marketing enabled:" in lower
    assert "expected long-form type:" in lower
    assert "engagement prompt type:" in lower


def test_prayer_days_receive_prayer_writing_instructions():
    guidance = prompt_builder.build_format_specific_guidance("prayer_read").lower()
    assert "actual complete prayer" in guidance
    assert "do not turn it into app marketing" in guidance
    assert "amen" in guidance


def test_marketing_days_retain_promotional_instructions():
    guidance = prompt_builder.build_format_specific_guidance("app_feature").lower()
    assert "concise promotional behavior" in guidance


def test_existing_output_json_schema_remains_unchanged():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()
    assert "output valid json only with keys:" in lower
    schema_section = lower.split("output valid json only with keys:", 1)[1]
    assert "long_form_type" in schema_section
    assert "script_segments" in schema_section
    assert "duration_seconds" not in schema_section


def test_build_prompt_emotional_flow_ordering():
    """Creative Brief (Life Moment / Hook) must appear before Brand Rules,
    which must appear before the app-feature description, which must
    appear before the constraints/requirements section."""
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()

    creative_brief_pos = lower.index("creative brief")
    brand_rules_pos = lower.index("you must follow every rule contained in brand_rules.json")
    app_features_pos = lower.index("you are the direct-response social media copywriter")
    constraints_pos = lower.index("a real destination link will be appended automatically")
    requirements_pos = lower.index("requirements:")

    assert creative_brief_pos < brand_rules_pos < app_features_pos < constraints_pos < requirements_pos


def test_current_default_profiles_leave_prompt_byte_for_byte_unchanged(monkeypatch):
    brief = replace(
        _resolved_profile_brief(),
        hook_profile_id="current_default",
        body_profile_id="current_default",
    )
    assert brief.hook_profile_id == "current_default"
    assert brief.voice_profile_id == "natural_conversational"
    assert brief.body_profile_id == "current_default"
    actual = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=_fake_selection(),
        slot="morning",
        tracked_url="https://example.com",
        resolved_brief=brief,
    )
    monkeypatch.setattr(
        prompt_builder,
        "build_resolved_profile_guidance",
        lambda _resolved_brief: "",
    )
    expected = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=_fake_selection(),
        slot="morning",
        tracked_url="https://example.com",
        resolved_brief=brief,
    )
    assert actual == expected
    assert "Resolved Creative Profile Guidance" not in actual


def test_general_prayer_injects_hook_guidance_without_changing_writing_or_tts():
    brief = _resolved_profile_brief()
    assert brief.hook_profile_id == "gentle_invitation"
    assert brief.voice_profile_id == "natural_conversational"
    assert brief.body_profile_id == "general_prayer"

    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=_fake_selection(),
        slot="morning",
        tracked_url="https://example.com",
        resolved_brief=brief,
    )
    assert "Resolved Creative Profile Guidance" in prompt
    assert "Resolved Hook Profile:" in prompt
    assert "ID: gentle_invitation" in prompt
    assert "Resolved Writing Profile:" in prompt
    assert "ID: natural_conversational" in prompt
    assert "Resolved Body Profile:" in prompt
    assert "ID: general_prayer" in prompt
    assert (
        voice_provider.select_style_profile(
            {
                "long_form_type": "prayer",
                "hook_profile_id": brief.hook_profile_id,
                "voice_profile_id": brief.voice_profile_id,
            }
        )
        == "natural_conversational"
    )


def test_nondefault_hook_and_writing_guidance_is_injected_deterministically():
    brief = _resolved_profile_brief(category_id="anxiety")
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=_fake_selection(),
        slot="morning",
        tracked_url="https://example.com",
        resolved_brief=brief,
    )
    assert "Resolved Hook Profile:" in prompt
    assert "ID: empathetic_recognition" in prompt
    assert "Resolved Writing Profile:" in prompt
    assert "ID: gentle_encouraging" in prompt
    assert "Resolved Body Profile:" in prompt
    assert "ID: anxiety_relief" in prompt
    assert "content writing only; never use this profile to control TTS" in prompt
    assert "Example text that must not enter profile guidance." not in prompt
    assert prompt.index("Resolved Hook Profile:") < prompt.index(
        "Resolved Writing Profile:"
    )
    assert prompt.index("Resolved Writing Profile:") < prompt.index(
        "Resolved Body Profile:"
    )
    assert prompt.index("Resolved Body Profile:") < prompt.index(
        "The Life Moment, Hook Style, Objective, Tone, and Emotional Goal above"
    )
    assert prompt.index("Resolved Creative Profile Guidance") < prompt.index(
        "The Life Moment, Hook Style, Objective, Tone, and Emotional Goal above"
    )
    assert "bridge_line: optional. One natural sentence" in prompt
    assert "script_segments: optional. JSON array of 2 to 5" in prompt
    assert "Write toward this emotional arc, in this order" in prompt


def test_prompt_builder_consumes_exact_resolved_profile_ids(monkeypatch):
    brief = _resolved_profile_brief(category_id="anxiety")
    calls = []
    original_hook_lookup = resolved_content_brief.get_hook_profile_definition
    original_writing_lookup = resolved_content_brief.get_writing_profile_definition
    original_body_lookup = resolved_content_brief.get_body_profile_definition

    def hook_lookup(profile_id, **kwargs):
        calls.append(("hook", profile_id, kwargs["creative_policy_version"]))
        return original_hook_lookup(profile_id, **kwargs)

    def writing_lookup(profile_id, **kwargs):
        calls.append(("writing", profile_id, kwargs["creative_policy_version"]))
        return original_writing_lookup(profile_id, **kwargs)

    def body_lookup(profile_id, **kwargs):
        calls.append(("body", profile_id, kwargs["creative_policy_version"]))
        return original_body_lookup(profile_id, **kwargs)

    monkeypatch.setattr(
        resolved_content_brief,
        "get_hook_profile_definition",
        hook_lookup,
    )
    monkeypatch.setattr(
        resolved_content_brief,
        "get_writing_profile_definition",
        writing_lookup,
    )
    monkeypatch.setattr(
        resolved_content_brief,
        "get_body_profile_definition",
        body_lookup,
    )
    prompt_builder.build_resolved_profile_guidance(brief)
    assert calls == [
        ("hook", "empathetic_recognition", "1"),
        ("writing", "gentle_encouraging", "1"),
        ("body", "anxiety_relief", "1"),
    ]


def test_writing_profile_guidance_never_invokes_or_mutates_tts(monkeypatch):
    brief = _resolved_profile_brief(category_id="anxiety")
    style_profiles_before = {
        key: dict(value)
        for key, value in voice_provider.STYLE_PROFILES.items()
    }
    monkeypatch.setattr(
        voice_provider,
        "select_style_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("TTS selection must not be called")
        ),
    )
    guidance = prompt_builder.build_resolved_profile_guidance(brief)
    assert "gentle_encouraging" in guidance
    assert voice_provider.STYLE_PROFILES == style_profiles_before


def test_voice_profile_id_is_ignored_by_tts_style_selection():
    assert (
        voice_provider.select_style_profile(
            {
                "long_form_type": "prayer",
                "voice_profile_id": "gentle_encouraging",
            }
        )
        == "natural_conversational"
    )


def test_body_guidance_scope_does_not_duplicate_hook_or_cta_instructions():
    guidance = prompt_builder.build_resolved_profile_guidance(
        _resolved_profile_brief(category_id="anxiety")
    )
    assert guidance.count("Apply the Hook Profile only to opening_hook") == 1
    assert guidance.count("CTA language") == 1
    body_section = guidance.split("Resolved Body Profile:", 1)[1]
    assert "opening_hook" not in body_section
    assert "Come pray with me" not in body_section
    assert "hashtags" not in body_section.lower()


def test_body_profile_diagnostics_are_advisory_and_do_not_rewrite_copy():
    brief = _resolved_profile_brief(category_id="anxiety")
    ad_copy = {
        "opening_hook": "Bring this burden to God.",
        "bridge_line": "Bring this burden to God.",
        "script_segments": [
            "Everything will be fine.",
            "Everything will be fine.",
        ],
        "closing_line": "Nothing bad will happen.",
    }
    original = {
        key: list(value) if isinstance(value, list) else value
        for key, value in ad_copy.items()
    }
    warnings = prompt_builder.validate_body_profile_output(ad_copy, brief)
    assert "body_may_be_overly_generic_for_category" in warnings
    assert "body_duplicates_opening_hook" in warnings
    assert "body_repeats_petition" in warnings
    assert "body_contains_unsupported_promise" in warnings
    assert ad_copy == original


def test_morning_body_profile_warns_about_nighttime_crossover():
    brief = _resolved_profile_brief(category_id="morning_prayer")
    warnings = prompt_builder.validate_body_profile_output(
        {
            "bridge_line": "As you prepare for bedtime, bring this day to God.",
            "script_segments": ["Give us direction and purpose through the night."],
            "closing_line": "Amen.",
        },
        brief,
    )
    assert "body_contains_inappropriate_time_language" in warnings


def test_opening_hook_validation_accepts_valid_hook():
    profile = resolved_content_brief.get_hook_profile_definition(
        "gentle_invitation"
    )
    assert (
        prompt_builder.validate_opening_hook(
            "Before you sleep, pray with me.",
            profile,
        )
        == []
    )


def test_opening_hook_validation_warns_for_blank_hook():
    profile = resolved_content_brief.get_hook_profile_definition(
        "gentle_invitation"
    )
    assert prompt_builder.validate_opening_hook("", profile) == ["hook_blank"]


def test_opening_hook_validation_warns_without_rewriting_copy():
    profile = resolved_content_brief.get_hook_profile_definition(
        "empathetic_recognition"
    )
    hook = "Anxiety has been following you through every single moment of this difficult day"
    warnings = prompt_builder.validate_opening_hook(hook, profile)
    assert "hook_exceeds_preferred_word_range" in warnings
    assert "hook_excessively_long" in warnings
    assert "hook_incomplete_thought" in warnings
    assert "hook_exceeds_preferred_reading_duration" in warnings
    assert hook == "Anxiety has been following you through every single moment of this difficult day"


def test_opening_hook_validation_warns_below_preferred_word_range():
    profile = resolved_content_brief.get_hook_profile_definition(
        "hopeful_encouragement"
    )
    warnings = prompt_builder.validate_opening_hook("Hope remains.", profile)
    assert "hook_below_preferred_word_range" in warnings


def test_build_prompt_does_not_lock_gemini_to_preselected_spiritual_action():
    """Gemini must write its own spiritual action aligned to the Life
    Moment, not be forced to reuse the preselected selection["spiritual_action"]
    verbatim (which can drift from the Creative Brief's Life Moment)."""
    selection = _fake_selection()
    selection["spiritual_action"] = "Ask God for clarity on your calling."
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    lower = prompt.lower()
    assert "use this exact sentence" not in lower
    assert "never replace it with a different spiritual claim" not in lower
    assert "write this spiritual action yourself so it stays specific to" in lower
    # The preselected sentence may still appear only as a non-binding
    # tone/style example, not as a hard requirement.
    assert "only as a tone/style example" in lower


def test_build_prompt_still_includes_seasonal_context_when_present():
    selection = _fake_selection()
    selection["seasonal_context"] = "Christmas season"
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    assert "Christmas season" in prompt


def test_select_life_moment_for_emotion_matches_or_falls_back():
    moment = prompt_builder.select_life_moment_for_emotion("overwhelmed")
    assert moment is not None
    assert "emotions" in moment


def test_generate_ad_copy_parses_valid_json(monkeypatch):
    selection = _fake_selection()
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    fake_response = SimpleNamespace(text=(
        '{"brand_header": "PRAYONIT", "pain_headline": "Feeling anxious tonight?", '
        '"spiritual_action": "Give today\'s burdens to God in prayer.", '
        '"app_benefit": "Get a guided, personalized prayer to help you bring your worries to God.", '
        '"download_cta": "Download Prayonit now.", '
        '"trial_support": "Start your 14-day free trial today.", '
        '"facebook_caption": "Test facebook caption with link https://x.test/download?t=abc", '
        '"instagram_caption": "Test instagram caption https://x.test/download?t=abc", '
        '"story_headline": "Feeling Anxious?", "story_spiritual_action": "Bring it to God.", '
        '"story_app_benefit": "A guided prayer for how you feel.", '
        '"story_download_cta": "Download Now", '
        '"story_trial_support": "Start your 14-day trial.", '
        '"long_form_type": "prayer", '
        '"opening_hook": "Feeling worn down today?", '
        '"bridge_line": "Let this prayer meet you where you are.", '
        '"script_segments": ["Lord, steady my heart today.", "Give me peace and strength for what is ahead.", "Help me trust You one step at a time."], '
        '"closing_line": "Amen.", '
        '"engagement_line": "Save this prayer for later today.", '
        '"estimated_spoken_seconds": 30}'
    ))
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert "story_trial_support" in ad_copy
    # download_cta must always be forced to the exact required invitation-first CTA.
    assert ad_copy["download_cta"] == config.PRIMARY_CTA
    assert ad_copy["story_download_cta"] == config.PRIMARY_CTA
    assert ad_copy["long_form_type"] == "prayer"
    assert len(ad_copy["script_segments"]) == 3
    assert ad_copy["estimated_spoken_seconds"] == 30


def test_parse_ad_copy_response_accepts_expanded_schema():
    with patch.object(
        prompt_builder.content_engine,
        "get_todays_content",
        return_value=_presentation_content(
            content_type="devotional_read",
            video_template="long_devotional",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    ):
        raw = (
            '{"brand_header": "PRAYONIT", "pain_headline": "Need peace today?", '
            '"spiritual_action": "Bring it to God in prayer.", '
            '"app_benefit": "Get a guided, personalized prayer based on your mood right now.", '
            '"download_cta": "COME PRAY WITH ME", '
            '"trial_support": "Start your prayer at\\nprayonit.app", '
            '"facebook_caption": "x", "instagram_caption": "x", '
            '"story_headline": "Need peace?", "story_spiritual_action": "Bring it to God.", '
            '"story_app_benefit": "A guided prayer for how you feel.", '
            '"story_download_cta": "COME PRAY WITH ME", '
            '"story_trial_support": "Start your prayer at\\nprayonit.app", '
            '"long_form_type": "devotional", '
            '"opening_hook": "You are not alone.", '
            '"bridge_line": "Take this reflection with you.", '
            '"script_segments": ["God still sees your tired heart.", "His peace can steady you today."], '
            '"closing_line": "Hold onto hope today.", '
            '"engagement_line": "Share this with someone who needs hope.", '
            '"estimated_spoken_seconds": 30}'
        )
        parsed = prompt_builder.parse_ad_copy_response(raw, slot="morning")
    assert parsed["long_form_type"] == "devotional"
    assert isinstance(parsed["script_segments"], list)


def test_parse_ad_copy_response_accepts_legacy_threads_caption_without_requiring_it():
    with patch.object(
        prompt_builder.content_engine,
        "get_todays_content",
        return_value=_presentation_content(
            content_type="devotional_read",
            video_template="long_devotional",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    ):
        raw = (
            '{"brand_header": "PRAYONIT", "pain_headline": "Need peace today?", '
            '"spiritual_action": "Bring it to God in prayer.", '
            '"app_benefit": "Get a guided, personalized prayer based on your mood right now.", '
            '"download_cta": "COME PRAY WITH ME", '
            '"trial_support": "Start your prayer at\\nprayonit.app", '
            '"facebook_caption": "x", "instagram_caption": "x", "threads_caption": "legacy threads", '
            '"story_headline": "Need peace?", "story_spiritual_action": "Bring it to God.", '
            '"story_app_benefit": "A guided prayer for how you feel.", '
            '"story_download_cta": "COME PRAY WITH ME", '
            '"story_trial_support": "Start your prayer at\\nprayonit.app"}'
        )
        parsed = prompt_builder.parse_ad_copy_response(raw, slot="morning")
    assert parsed["facebook_caption"] == "x"
    assert parsed["instagram_caption"] == "x"
    assert parsed["threads_caption"] == "legacy threads"


def test_missing_long_form_fields_receive_safe_defaults():
    with patch.object(
        prompt_builder.content_engine,
        "get_todays_content",
        return_value=_presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    ):
        raw = (
            '{"brand_header": "PRAYONIT", "pain_headline": "Need peace today?", '
            '"spiritual_action": "Bring it to God in prayer.", '
            '"app_benefit": "Get a guided, personalized prayer based on your mood right now.", '
            '"download_cta": "COME PRAY WITH ME", '
            '"trial_support": "Start your prayer at\\nprayonit.app", '
            '"facebook_caption": "x", "instagram_caption": "x", '
            '"story_headline": "Need peace?", "story_spiritual_action": "Bring it to God.", '
            '"story_app_benefit": "A guided prayer for how you feel.", '
            '"story_download_cta": "COME PRAY WITH ME", '
            '"story_trial_support": "Start your prayer at\\nprayonit.app"}'
        )
        parsed = prompt_builder.parse_ad_copy_response(raw, slot="morning")
    assert parsed["long_form_type"] == "prayer"
    assert parsed["script_segments"] == []
    assert parsed["opening_hook"] == ""
    assert parsed["closing_line"] == "Amen."
    assert parsed["estimated_spoken_seconds"] == 30


def test_generate_ad_copy_raises_on_missing_key(monkeypatch):
    selection = _fake_selection()
    fake_response = SimpleNamespace(text='{"brand_header": "PRAYONIT"}')
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        try:
            prompt_builder.generate_ad_copy(
                post_type="x", selection=selection, slot="morning", tracked_url="https://x.test/d"
            )
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


def _valid_ad_copy_response():
    return SimpleNamespace(text=(
        '{"brand_header": "PRAYONIT", "pain_headline": "Feeling anxious tonight?", '
        '"spiritual_action": "Give today\'s burdens to God in prayer.", '
        '"app_benefit": "Get a guided, personalized prayer based on your mood right now.", '
        '"download_cta": "Download Prayonit now.", '
        '"trial_support": "Start your prayer at\\nprayonit.app", '
        '"facebook_caption": "x", "instagram_caption": "x", "threads_caption": "x", '
        '"story_headline": "Feeling Anxious?", "story_spiritual_action": "Bring it to God.", '
        '"story_app_benefit": "A guided prayer for how you feel.", '
        '"story_download_cta": "Download Now", '
        '"story_trial_support": "Start your prayer at\\nprayonit.app", '
        '"long_form_type": "prayer", "opening_hook": "", "bridge_line": "", '
        '"script_segments": [], "closing_line": "Amen.", "engagement_line": "", '
        '"estimated_spoken_seconds": 30}'
    ))


def _generate_content_models(mock_client):
    return [call.kwargs["model"] for call in mock_client.models.generate_content.call_args_list]


def _configure_content_model_keys(
    monkeypatch,
    *,
    primary_key="primary-key",
    secondary_key="secondary-key",
):
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY", primary_key)
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY_PRIMARY", primary_key)
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY_SECONDARY", secondary_key)
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", primary_key)
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", secondary_key)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_production_content_model_order_excludes_unavailable_legacy_fallback():
    assert prompt_builder._get_configured_content_models() == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    assert "gemini-2.5-flash" not in (
        prompt_builder._get_configured_content_models()
    )


def test_generate_ad_copy_retries_503_with_backoff_before_fallback(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    monkeypatch.setattr(
        prompt_builder, "_CONTENT_503_RETRY_DELAYS_SECONDS", (2.0, 5.0)
    )
    client = MagicMock()
    client.models.generate_content.side_effect = [
        RuntimeError("503 service unavailable"),
        _valid_ad_copy_response(),
    ]
    sleeps = []
    monkeypatch.setattr(prompt_builder.time, "sleep", sleeps.append)

    with patch.object(prompt_builder, "_get_gemini_client", return_value=client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert _generate_content_models(client) == [
        "gemini-3.6-flash",
        "gemini-3.6-flash",
    ]
    assert sleeps == [2.0]


def test_generate_ad_copy_bounds_503_retries_then_switches_model(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    monkeypatch.setattr(
        prompt_builder, "_CONTENT_503_RETRY_DELAYS_SECONDS", (2.0, 5.0)
    )
    primary_client = MagicMock()
    secondary_client = MagicMock()
    primary_client.models.generate_content.side_effect = RuntimeError(
        "503 service unavailable"
    )
    secondary_client.models.generate_content.return_value = (
        _valid_ad_copy_response()
    )
    sleeps = []
    monkeypatch.setattr(prompt_builder.time, "sleep", sleeps.append)

    def fake_get_client(api_key=None):
        return primary_client if api_key == "primary-key" else secondary_client

    with patch.object(
        prompt_builder, "_get_gemini_client", side_effect=fake_get_client
    ):
        prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert _generate_content_models(primary_client) == [
        "gemini-3.6-flash",
        "gemini-3.6-flash",
        "gemini-3.6-flash",
    ]
    assert _generate_content_models(secondary_client) == ["gemini-3.5-flash"]
    assert sleeps == [2.0, 5.0]


def test_unavailable_secondary_model_does_not_continue_to_tertiary(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    client = MagicMock()
    client.models.generate_content.side_effect = [
        RuntimeError("502 bad gateway"),
        RuntimeError("404 model unavailable to this account"),
    ]

    with patch.object(prompt_builder, "_get_gemini_client", return_value=client):
        with pytest.raises(RuntimeError, match="404"):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]


def test_generate_ad_copy_primary_model_uses_primary_key(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _valid_ad_copy_response()
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return mock_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert client_keys == ["primary-key"]
    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def test_generate_ad_copy_secondary_model_uses_secondary_key_when_configured(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    primary_client = MagicMock()
    secondary_client = MagicMock()
    primary_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    secondary_client.models.generate_content.return_value = _valid_ad_copy_response()
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return primary_client if api_key == "primary-key" else secondary_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert client_keys == ["primary-key", "secondary-key"]
    assert _generate_content_models(primary_client) == ["gemini-3.6-flash"]
    assert _generate_content_models(secondary_client) == ["gemini-3.5-flash"]


def test_generate_ad_copy_tertiary_model_uses_secondary_key_when_configured(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    primary_client = MagicMock()
    secondary_client = MagicMock()
    primary_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    secondary_client.models.generate_content.side_effect = [
        RuntimeError("429 quota temporarily exhausted"),
        _valid_ad_copy_response(),
    ]
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return primary_client if api_key == "primary-key" else secondary_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert client_keys == ["primary-key", "secondary-key", "secondary-key"]
    assert _generate_content_models(primary_client) == ["gemini-3.6-flash"]
    assert _generate_content_models(secondary_client) == [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]


def test_generate_ad_copy_missing_secondary_key_uses_primary_for_all_models(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch, secondary_key="")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        RuntimeError("503 service unavailable"),
        RuntimeError("502 bad gateway"),
        _valid_ad_copy_response(),
    ]
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return mock_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert client_keys == ["primary-key", "primary-key", "primary-key"]
    assert _generate_content_models(mock_client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]


def test_generate_ad_copy_legacy_gemini_api_key_remains_valid_primary_key(monkeypatch):
    selection = _fake_selection()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY", "legacy-key")
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY_PRIMARY", "legacy-key")
    monkeypatch.setattr(prompt_builder.config, "GEMINI_API_KEY_SECONDARY", "legacy-key")
    monkeypatch.delenv("GEMINI_API_KEY_PRIMARY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-key")
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _valid_ad_copy_response()
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return mock_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert client_keys == ["legacy-key"]


def test_generate_ad_copy_primary_success_does_not_initialize_secondary_client(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    primary_client = MagicMock()
    primary_client.models.generate_content.return_value = _valid_ad_copy_response()
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        if api_key != "primary-key":
            raise AssertionError("secondary client should not be requested")
        return primary_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert client_keys == ["primary-key"]


def test_generate_ad_copy_switches_model_and_client_after_temporary_primary_failure(monkeypatch):
    selection = _fake_selection()
    _configure_content_model_keys(monkeypatch)
    primary_client = MagicMock()
    secondary_client = MagicMock()
    primary_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    secondary_client.models.generate_content.return_value = _valid_ad_copy_response()
    client_keys = []

    def fake_get_client(api_key=None):
        client_keys.append(api_key)
        return primary_client if api_key == "primary-key" else secondary_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert client_keys == ["primary-key", "secondary-key"]
    assert _generate_content_models(primary_client) == ["gemini-3.6-flash"]
    assert _generate_content_models(secondary_client) == ["gemini-3.5-flash"]


def test_generate_ad_copy_secondary_key_auth_failure_does_not_expose_key(monkeypatch, capsys):
    selection = _fake_selection()
    _configure_content_model_keys(
        monkeypatch,
        primary_key="primary-secret-key",
        secondary_key="secondary-secret-key",
    )
    primary_client = MagicMock()
    secondary_client = MagicMock()
    primary_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    secondary_client.models.generate_content.side_effect = RuntimeError("401 invalid api key")

    def fake_get_client(api_key=None):
        return primary_client if api_key == "primary-secret-key" else secondary_client

    with patch.object(prompt_builder, "_get_gemini_client", side_effect=fake_get_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    output = capsys.readouterr().out
    assert "primary-secret-key" not in output
    assert "secondary-secret-key" not in output


def test_generate_ad_copy_primary_success_calls_only_primary_model(monkeypatch):
    selection = _fake_selection()
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _valid_ad_copy_response()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def test_generate_ad_copy_temporary_primary_failure_immediately_calls_secondary(monkeypatch):
    selection = _fake_selection()
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    responses = [RuntimeError("503 service unavailable"), _valid_ad_copy_response()]
    mock_client = MagicMock()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    def fake_generate_content(**kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_client.models.generate_content.side_effect = fake_generate_content

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert _generate_content_models(mock_client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]


def test_generate_ad_copy_temporary_primary_and_secondary_failures_call_tertiary(monkeypatch):
    selection = _fake_selection()
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    responses = [
        RuntimeError("503 service unavailable"),
        RuntimeError("429 quota temporarily exhausted"),
        _valid_ad_copy_response(),
    ]
    mock_client = MagicMock()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    def fake_generate_content(**kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_client.models.generate_content.side_effect = fake_generate_content

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert _generate_content_models(mock_client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]


def test_generate_ad_copy_calls_each_configured_model_no_more_than_once(monkeypatch):
    selection = _fake_selection()
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(mock_client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]


def test_generate_ad_copy_does_not_fallback_on_permanent_primary_error(monkeypatch):
    selection = _fake_selection()
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("400 invalid argument")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def test_generate_ad_copy_parsing_error_does_not_trigger_another_model(monkeypatch):
    selection = _fake_selection()
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text='{"brand_header": "PRAYONIT"}')
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "gemini-3.5-flash-lite")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def test_generate_ad_copy_without_tertiary_uses_only_primary_and_secondary(monkeypatch):
    selection = _fake_selection()
    responses = [RuntimeError("503 service unavailable"), RuntimeError("502 bad gateway")]
    mock_client = MagicMock()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "gemini-3.5-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "")

    def fake_generate_content(**kwargs):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    mock_client.models.generate_content.side_effect = fake_generate_content

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(mock_client) == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]


def test_generate_ad_copy_without_secondary_and_tertiary_preserves_single_model_behavior(monkeypatch):
    selection = _fake_selection()
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("503 service unavailable")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            prompt_builder.generate_ad_copy(
                post_type="download-focused evening ad",
                selection=selection,
                slot="evening",
                tracked_url="https://x.test/download?t=abc",
            )

    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def test_generate_ad_copy_never_uses_tts_model_settings(monkeypatch):
    selection = _fake_selection()
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _valid_ad_copy_response()
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_PRIMARY", "gemini-3.6-flash")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_SECONDARY", "")
    monkeypatch.setattr(prompt_builder.config, "CONTENT_MODEL_TERTIARY", "")
    monkeypatch.setattr(prompt_builder.config, "VOICE_MODEL", "gemini-3.1-flash-tts-preview")
    monkeypatch.setattr(prompt_builder.config, "VOICE_MODEL_PRIMARY", "gemini-3.1-flash-tts-preview")
    monkeypatch.setattr(prompt_builder.config, "VOICE_MODEL_SECONDARY", "gemini-2.5-flash-preview-tts")

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert _generate_content_models(mock_client) == ["gemini-3.6-flash"]


def _fake_platform_urls():
    return {
        "facebook": "https://example.com/download?t=fb1",
        "instagram": "https://example.com/download?t=ig1",
    }


def test_facebook_caption_has_no_hashtags():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Plain facebook caption with no tags.",
        "instagram_caption": "Instagram caption base text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "#" not in captions["facebook"]


def test_instagram_caption_has_5_to_8_hashtags_including_prayonit():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb",
        "instagram_caption": "ig base",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert 5 <= len(hashtags) <= 8
    assert "#Prayonit" in hashtags


def test_build_platform_captions_returns_only_facebook_and_instagram():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb",
        "instagram_caption": "ig base",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert set(captions) == {"facebook", "instagram"}


def test_facebook_existing_cta_is_not_duplicated():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.\n\nCome pray with me.",
        "instagram_caption": "ig base",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert captions["facebook"].count("Come pray with me.") == 1


def test_instagram_existing_cta_is_not_duplicated_and_link_in_bio_remains():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb base",
        "instagram_caption": "Some instagram body text.\n\nCome pray with me.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert captions["instagram"].count("Come pray with me.") == 1
    assert "Link in bio." in captions["instagram"]


@pytest.mark.parametrize(
    "existing_cta",
    [
        "COME PRAY WITH ME",
        "Come pray with me!",
        "come   pray   with   me",
    ],
)
def test_cta_normalization_recognizes_case_punctuation_and_whitespace(existing_cta):
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": f"Some facebook body text.\n\n{existing_cta}",
        "instagram_caption": f"Some instagram body text.\n\n{existing_cta}",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert captions["facebook"].lower().count("come pray with me") == 1
    assert captions["instagram"].lower().count("come pray with me") == 1


def test_absent_cta_is_appended_exactly_once():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert captions["facebook"].count("Come pray with me.") == 1
    assert captions["instagram"].count("Come pray with me.") == 1


def test_gemini_invented_urls_are_stripped_from_all_captions():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Check it out at https://prayonit.com/download right now!",
        "instagram_caption": "Get it here: https://prayonit.com/download",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert "prayonit.com" not in captions["facebook"]
    assert "prayonit.com" not in captions["instagram"]


def test_exact_configured_url_is_appended_per_platform():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert urls["facebook"] in captions["facebook"]
    # Instagram feed captions never include a raw URL (not clickable on
    # Instagram); the same URL is instead placed in Buffer's
    # metadata.instagram.link. See test_buffer_client.py.
    assert urls["instagram"] not in captions["instagram"]


def test_hashtags_remain_unchanged_when_instagram_cta_already_exists():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb base",
        "instagram_caption": "Some instagram body text.\n\nCome pray with me.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert "#Prayonit" in hashtags
    assert len(hashtags) >= 1


def test_unrelated_repeated_text_is_not_removed():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Hold on. Hold on.\n\nCome pray with me.",
        "instagram_caption": "Stay steady. Stay steady.\n\nCome pray with me.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Hold on. Hold on." in captions["facebook"]
    assert "Stay steady. Stay steady." in captions["instagram"]
def test_tracking_disabled_all_active_captions_use_same_destination_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    destination = "https://example.com/app"
    urls = {"facebook": destination, "instagram": destination}
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert destination in captions["facebook"]
    assert destination not in captions["instagram"]


def test_tracking_enabled_each_platform_uses_distinct_tracked_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert captions["facebook"].count(urls["facebook"]) == 1
    assert urls["instagram"] not in captions["facebook"]
    assert urls["facebook"] not in captions["instagram"]


# ---------- Brand Brain enforcement tests ----------

def test_prompt_always_injects_brand_brain():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://x.test/download?t=abc",
    )
    assert "You MUST follow every rule contained in brand_rules.json." in prompt
    assert config.BRAND_RULES["preferred_cta"] in prompt
    assert "Never invent features." in prompt
    assert "Never invent pricing." in prompt
    assert "Never invent URLs." in prompt


def test_enforce_cta_replaces_invalid_cta():
    result = prompt_builder.enforce_cta("Buy now for $9.99!", config.BRAND_RULES)
    assert result == config.BRAND_RULES["preferred_cta"]


def test_enforce_cta_keeps_approved_cta_unchanged():
    approved = config.BRAND_RULES["approved_ctas"][1]
    result = prompt_builder.enforce_cta(approved, config.BRAND_RULES)
    assert result == approved


def test_enforce_forbidden_phrases_replaces_never_say_terms():
    text = "Prayonit is a free app you can use forever, 100% free!"
    result = prompt_builder.enforce_forbidden_phrases(text, config.BRAND_RULES)
    assert "free app" not in result.lower()
    assert "100% free" not in result.lower()
    assert config.BRAND_RULES["preferred_cta"] in result


def test_enforce_feature_claims_removes_nonexistent_feature_sentences():
    text = "Prayonit gives you a personalized prayer. You can also join our community forum."
    result = prompt_builder.enforce_feature_claims(text, config.BRAND_RULES)
    assert "community forum" not in result.lower()
    assert "personalized prayer" in result.lower()


def test_enforce_feature_claims_keeps_known_core_features():
    text = "Prayonit offers a prayer journal and a 14-day free trial."
    result = prompt_builder.enforce_feature_claims(text, config.BRAND_RULES)
    assert "prayer journal" in result.lower()


def test_apply_brand_enforcement_fixes_cta_and_phrases_together():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Bring it to God.",
        "cta": "Buy now, it's 100% free forever!",
        "facebook_caption": "This app is completely free forever, join our community forum today.",
        "instagram_caption": "Free app, no strings attached.",
        "story_headline": "Feeling Anxious?",
        "story_cta": "Pray Now",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert enforced["cta"] == config.BRAND_RULES["preferred_cta"]
    assert "free forever" not in enforced["facebook_caption"].lower()
    assert "community forum" not in enforced["facebook_caption"].lower()
    assert "free app" not in enforced["instagram_caption"].lower()


# ---------- Issue 2: free-trial wording enforcement ----------

def test_story_cta_try_it_free_today_is_replaced_with_website_first_phrase():
    result = prompt_builder.enforce_story_cta_trial_wording("Try it free today.", config.BRAND_RULES)
    assert result == config.BRAND_RULES["compact_trial_phrase"]
    assert "prayonit.app" in result.lower()
    assert "trial" not in result.lower()
    assert "free" not in result.lower()


def test_story_cta_free_trial_wording_is_replaced_with_website_first_phrase():
    result = prompt_builder.enforce_story_cta_trial_wording("Start your free trial.", config.BRAND_RULES)
    assert "prayonit.app" in result.lower()
    assert result == config.BRAND_RULES["compact_trial_phrase"]


def test_story_cta_website_first_phrase_is_left_unchanged():
    compact = config.BRAND_RULES["compact_trial_phrase"]
    result = prompt_builder.enforce_story_cta_trial_wording(compact, config.BRAND_RULES)
    assert result == compact


def test_facebook_caption_free_trial_wording_is_replaced_with_invitation_cta():
    text = "Download Prayonit and try Prayonit free right now, no strings attached."
    result = prompt_builder.enforce_trial_duration(text, config.BRAND_RULES)
    assert result == config.BRAND_RULES["preferred_cta"]
    assert "trial" not in result.lower()
    assert "download" not in result.lower()


def test_all_trial_and_download_language_is_removed_across_fields():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Bring it to God.",
        "cta": "Try it free today.",
        "facebook_caption": "Download for free and try Prayonit free right now.",
        "instagram_caption": "Download for free today, no catch.",
        "story_headline": "Feeling Anxious?",
        "story_cta": "Try it free today",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    for field in ("cta", "facebook_caption", "instagram_caption", "story_cta"):
        text_lower = enforced[field].lower()
        assert "trial" not in text_lower
        assert "download" not in text_lower
        assert "free" not in text_lower


def test_personalized_scripture_phrase_remains_allowed_and_unchanged():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Receive personalized Scripture and a devotion today.",
        "cta": config.BRAND_RULES["preferred_cta"],
        "facebook_caption": "Prayonit gives you personalized Scripture, a devotion, and a guided prayer.",
        "instagram_caption": "Get personalized Scripture in seconds.",
        "story_headline": "Personalized Scripture",
        "story_cta": "Pray Now",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert "personalized scripture" in enforced["body"].lower()
    assert "personalized scripture" in enforced["facebook_caption"].lower()
    assert "personalized scripture" in enforced["instagram_caption"].lower()
    assert enforced["story_headline"] == "Personalized Scripture"


# ---------- Buffer metadata placement: Instagram/Threads (this change) ----------

def test_instagram_caption_contains_no_raw_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_instagram_caption_ends_naturally_with_invitation_cta_and_keeps_hashtags():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["instagram"]
    assert "Link in bio" in captions["instagram"]
    assert "start your 14-day free trial" not in captions["instagram"].lower()
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert "#Prayonit" in hashtags
    assert len(hashtags) >= 1


# ---------- Duplicate Instagram trial-CTA fix (this change) ----------

@pytest.mark.parametrize(
    "duplicate_phrase",
    [
        "Get Prayonit today and start your 14-day free trial.",
        "Start your 14-day free trial.",
        "Begin your 14-day free trial today!",
        "Try Prayonit with a 14-day free trial.",
        "Don't wait, start your 14 day free trial now.",
    ],
)
def test_instagram_never_contains_trial_wording_despite_gemini_wording(duplicate_phrase):
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": f"Feeling overwhelmed? Prayonit can help. {duplicate_phrase}",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "start your 14-day free trial" not in captions["instagram"].lower()
    assert "trial" not in captions["instagram"].lower()
    # Invitation-first CTA still appears exactly once.
    assert captions["instagram"].lower().count("come pray with me") == 1


def test_instagram_caption_hashtags_preserved_after_dedup():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Feeling overwhelmed? Get Prayonit today and start your 14-day free trial.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert "#Prayonit" in hashtags
    assert len(hashtags) >= 1


def test_instagram_caption_no_url_after_dedup():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Feeling overwhelmed? Get Prayonit today and start your 14-day free trial.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_facebook_never_contains_trial_or_download_wording():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Get Prayonit today and start your 14-day free trial.",
        "instagram_caption": "Get Prayonit today and start your 14-day free trial.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert "get prayonit today and start your 14-day free trial" not in captions["facebook"].lower()
    assert "come pray with me" in captions["facebook"].lower()
    assert urls["facebook"] in captions["facebook"]


# ---------- Phase 2B: invitation-first / website-first funnel (this change) ----------

def test_brand_brain_preferred_cta_is_come_pray_with_me():
    assert config.BRAND_RULES["preferred_cta"] == "Come pray with me."
    assert config.BRAND_RULES["preferred_cta"] in config.BRAND_RULES["approved_ctas"]


def test_test_mode_fallback_copy_contains_no_trial_language():
    selection = _fake_selection()
    with patch.object(
        prompt_builder.content_engine,
        "get_todays_content",
        return_value=_presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    ):
        ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    forbidden_substrings = ("trial", "14-day", "14 day")
    for field in (
        "trial_support",
        "story_trial_support",
        "facebook_caption",
        "instagram_caption",
    ):
        lower = ad_copy[field].lower()
        for phrase in forbidden_substrings:
            assert phrase not in lower, f"{field} unexpectedly contains {phrase!r}: {ad_copy[field]!r}"


def test_test_mode_returns_expanded_schema_without_gemini():
    selection = _fake_selection()
    with patch.object(
        prompt_builder.content_engine,
        "get_todays_content",
        return_value=_presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    ):
        ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    for key in prompt_builder.LONG_FORM_OPTIONAL_KEYS:
        assert key in ad_copy
    assert ad_copy["long_form_type"] == "prayer"
    assert len(ad_copy["script_segments"]) >= 2
    assert ad_copy["estimated_spoken_seconds"] == 30


def test_monday_prayer_content_contains_two_to_five_complete_script_segments(monkeypatch):
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    selection = _fake_selection()
    ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    assert ad_copy["long_form_type"] == "prayer"
    assert 2 <= len(ad_copy["script_segments"]) <= 5
    assert all(segment[-1] in ".?!" for segment in ad_copy["script_segments"])
    assert 25 <= ad_copy["estimated_spoken_seconds"] <= 35


def test_wednesday_devotional_returns_long_form_type_devotional(monkeypatch):
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="devotional_read",
            video_template="long_devotional",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    selection = _fake_selection()
    ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    assert ad_copy["long_form_type"] == "devotional"
    assert 2 <= len(ad_copy["script_segments"]) <= 5
    assert 25 <= ad_copy["estimated_spoken_seconds"] <= 35


def test_tuesday_short_promo_returns_none_and_empty_script_segments(monkeypatch):
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="app_feature",
            video_template="short_promo",
            duration_seconds=8,
            engagement_prompt_enabled=False,
        ),
    )
    raw = (
        '{"brand_header": "PRAYONIT", "pain_headline": "Need peace today?", '
        '"spiritual_action": "Bring it to God in prayer.", '
        '"app_benefit": "Get a guided, personalized prayer based on your mood right now.", '
        '"download_cta": "COME PRAY WITH ME", '
        '"trial_support": "Start your prayer at\\nprayonit.app", '
        '"facebook_caption": "x", "instagram_caption": "x", '
        '"story_headline": "Need peace?", "story_spiritual_action": "Bring it to God.", '
        '"story_app_benefit": "A guided prayer for how you feel.", '
        '"story_download_cta": "COME PRAY WITH ME", '
        '"story_trial_support": "Start your prayer at\\nprayonit.app"}'
    )
    parsed = prompt_builder.parse_ad_copy_response(raw, slot="evening")
    assert parsed["long_form_type"] == "none"
    assert parsed["script_segments"] == []
    assert parsed["estimated_spoken_seconds"] == 8


def test_existing_short_form_fields_remain_present_with_long_form_additions(monkeypatch):
    monkeypatch.setattr(
        prompt_builder.content_engine,
        "get_todays_content",
        lambda slot: _presentation_content(
            content_type="prayer_read",
            video_template="long_prayer",
            duration_seconds=30,
            engagement_prompt_enabled=True,
        ),
    )
    selection = _fake_selection()
    ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    for key in prompt_builder.REQUIRED_AD_COPY_KEYS:
        assert key in ad_copy
        assert ad_copy[key]


def test_gemini_prompt_instructions_prohibit_trial_first_social_copy():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="invitation-first ad",
        selection=selection,
        slot="morning",
        tracked_url="https://x.test/download?t=abc",
    )
    lower = prompt.lower()
    assert "never mention a 14-day trial" in lower
    assert "strictly forbidden" in lower
    assert "start your free trial" in lower
    assert "try prayonit free" in lower
    assert "download prayonit" in lower
    assert "install the app" in lower
    assert "get the app" in lower
    # The message hierarchy must no longer end in a trial/download step.
    assert "download action -> 14-day free-trial support" not in lower


def test_facebook_caption_ends_with_invitation_and_website_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    urls = {
        "facebook": "https://prayonit.app",
        "instagram": "https://prayonit.app",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert captions["facebook"].endswith("Come pray with me.\nhttps://prayonit.app")


def test_instagram_caption_ends_with_invitation_and_link_in_bio():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    urls = {
        "facebook": "https://prayonit.app",
        "instagram": "https://prayonit.app",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    # #Prayonit (+ optional extra hashtags) is always appended after the
    # CTA, so the invitation + "Link in bio" must appear immediately before
    # the hashtag block, not necessarily as the literal final characters.
    before_hashtags = captions["instagram"].split("\n\n#")[0]
    assert before_hashtags.endswith("Come pray with me.\nLink in bio.")


def test_trial_support_fields_contain_website_first_destination_text():
    selection = _fake_selection()
    ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="evening")
    assert ad_copy["trial_support"] == "Start your prayer at\nprayonit.app"
    assert ad_copy["story_trial_support"] == "Start your prayer at\nprayonit.app"
    assert "prayonit.app" in ad_copy["trial_support"].lower()
    assert "prayonit.app" in ad_copy["story_trial_support"].lower()


@pytest.mark.parametrize(
    "forbidden_phrase",
    [
        "14-day free trial",
        "start your free trial",
        "try prayonit free",
        "download prayonit",
        "install the app",
        "get the app",
    ],
)
def test_old_trial_and_download_phrases_are_rejected_by_cta_enforcement(forbidden_phrase):
    text = f"Feeling overwhelmed? {forbidden_phrase.capitalize()} right now."
    result = prompt_builder.enforce_forbidden_phrases(text, config.BRAND_RULES)
    assert forbidden_phrase.lower() not in result.lower()
    assert config.BRAND_RULES["preferred_cta"] in result


def test_descriptive_app_references_are_not_rejected():
    # References to "the app" that are descriptive (not a download-first
    # CTA) must remain allowed -- only directive download/install/trial
    # phrases are forbidden.
    text = "The app gives you a guided, personalized prayer based on how you feel."
    result = prompt_builder.enforce_forbidden_phrases(text, config.BRAND_RULES)
    assert result == text
    result2 = prompt_builder.enforce_trial_duration(text, config.BRAND_RULES)
    assert result2 == text
