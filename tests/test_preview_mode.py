"""Tests for PREVIEW_MODE: uses real Gemini generation path (generate_ad_copy)
with the full Creative Brief, renders local previews exactly like
TEST_MODE, but never uploads, never calls Buffer, never publishes/schedules,
and never writes production tracking records.
"""
from PIL import Image

import prayonit_social


def _selection():
    campaign = {
        "name": "Anxiety",
        "pain_point": "anxious",
        "goal": "calm",
        "hooks": ["h"],
        "body_angles": ["b"],
        "ctas": ["c"],
        "thread_topics": ["t"],
        "instagram_hashtags": ["#Prayonit"],
    }
    return {
        "campaign": campaign,
        "formula": {"name": "f"},
        "persona": {"name": "p"},
        "seasonal_context": None,
        "hook": "h",
        "body_angle": "b",
        "cta": "c",
        "thread_topic": "t",
        "relaxed_rules": [],
        "emotional_territory": "insomnia",
    }


def _ad_copy():
    return {
        "brand_header": "PRAYONIT",
        "pain_headline": "Struggling to Pray?",
        "spiritual_action": "Give your worries to God.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
        "facebook_caption": "x",
        "instagram_caption": "x",
        "story_headline": "Struggling to Pray?",
        "story_spiritual_action": "Give your worries to God.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }


def _patch_common_pipeline(monkeypatch):
    """Patch out everything downstream of copy generation so tests focus
    only on mode-gating behavior (identical setup to
    tests/test_testmode_backgrounds.py).
    """
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)

    monkeypatch.setattr(prayonit_social, "get_supabase_client", lambda: object())
    monkeypatch.setattr(
        prayonit_social,
        "list_backgrounds",
        lambda supabase: ["Peaceful_landscape_night_02.jpg"],
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "choose_selection", lambda slot: _selection())
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_background",
        lambda all_backgrounds, slot, campaign, formula, persona: {
            "path": "Peaceful_landscape_night_02.jpg",
            "metadata": {"time": "night", "visual_types": ["starfield"], "emotional_suitability": ["insomnia"]},
            "match_score": 3.5,
            "emotional_territory": "insomnia",
        },
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "pick_spiritual_action", lambda campaign, slot: "Give your worries to God.")

    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i"},
    )

    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (11, 22, 33)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "add_dark_gradient", lambda image: image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": [], "pass": True, "score": 100})

    # Must never be reached in either TEST_MODE or PREVIEW_MODE.
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: (_ for _ in ()).throw(AssertionError("tracking called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("video upload called")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))


def test_test_mode_still_uses_generate_local_ad_copy_unchanged(isolated_database, monkeypatch, capsys):
    """Requirement: TEST_MODE path unchanged."""
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    _patch_common_pipeline(monkeypatch)

    calls = {"local": 0, "gemini": 0}
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: calls.__setitem__("local", calls["local"] + 1) or _ad_copy())
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: calls.__setitem__("gemini", calls["gemini"] + 1) or _ad_copy())

    result = prayonit_social.cmd_run("evening")
    out = capsys.readouterr().out

    assert result == 0
    assert calls["local"] == 1
    assert calls["gemini"] == 0
    assert "PREVIEW_MODE: False" in out
    assert "TEST_MODE=true, so nothing was uploaded or posted." in out


def test_preview_mode_uses_generate_ad_copy(isolated_database, monkeypatch, capsys):
    """Requirement: PREVIEW_MODE uses generate_ad_copy() (the real Gemini
    path with the full Creative Brief), not generate_local_ad_copy()."""
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    _patch_common_pipeline(monkeypatch)

    calls = {"local": 0, "gemini": 0}
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: calls.__setitem__("local", calls["local"] + 1) or _ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "generate_ad_copy",
        lambda **kwargs: calls.__setitem__("gemini", calls["gemini"] + 1) or _ad_copy(),
    )

    result = prayonit_social.cmd_run("morning")
    out = capsys.readouterr().out

    assert result == 0
    assert calls["gemini"] == 1
    assert calls["local"] == 0
    assert "PREVIEW_MODE: True" in out
    assert "PREVIEW_MODE=true, so nothing was uploaded or posted." in out


def test_explicit_caption_profile_override_is_available_in_production(monkeypatch):
    monkeypatch.setattr(
        prayonit_social.config,
        "CAPTION_PROFILE_PREVIEW_OVERRIDE",
        "rolling_short",
    )
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    assert (
        prayonit_social._caption_profile_preview_override()
        == "rolling_short"
    )


def test_blank_caption_profile_override_preserves_production_default(monkeypatch):
    monkeypatch.setattr(
        prayonit_social.config,
        "CAPTION_PROFILE_PREVIEW_OVERRIDE",
        "",
    )
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    assert prayonit_social._caption_profile_preview_override() is None


def test_run_schedule_uses_eastern_weekday_at_utc_boundary():
    started, content = prayonit_social._resolve_run_weekly_content(
        "evening",
        now=prayonit_social.datetime(
            2026, 7, 30, 3, 1, tzinfo=prayonit_social.timezone.utc
        ),
    )
    assert started.isoformat() == "2026-07-30T03:01:00+00:00"
    assert content["content_type"] == "devotional_read"
    assert content["prayer_category_id"] == "devotional"
    assert content["video_template"] == "long_devotional"


def test_preview_mode_never_reaches_upload_logic(isolated_database, monkeypatch, capsys):
    """Requirement: PREVIEW_MODE never reaches upload logic. upload_generated,
    upload_generated_video, buffer_create_post, and create_tracked_link are
    all monkeypatched to raise AssertionError if called -- this test passes
    only if cmd_run() returns before any of them are invoked."""
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    _patch_common_pipeline(monkeypatch)

    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _ad_copy())

    result = prayonit_social.cmd_run("evening")
    assert result == 0  # returned early; no AssertionError raised means no upload/Buffer/tracking call happened


def test_preview_mode_output_does_not_list_threads(isolated_database, monkeypatch, capsys):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    _patch_common_pipeline(monkeypatch)
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _ad_copy())

    result = prayonit_social.cmd_run("morning")
    out = capsys.readouterr().out

    assert result == 0
    assert "Threads caption:" not in out


def test_production_path_still_uses_generate_ad_copy_and_reaches_uploads(isolated_database, monkeypatch, capsys):
    """Requirement: existing production path (TEST_MODE=false,
    PREVIEW_MODE=false) unchanged -- it still uses generate_ad_copy() and
    proceeds past the early-return guard to uploads/Buffer."""
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    fixed_run_time = prayonit_social.datetime(
        2026,
        7,
        27,
        12,
        0,
        tzinfo=prayonit_social.timezone.utc,
    )
    monkeypatch.setattr(
        prayonit_social,
        "_resolve_run_weekly_content",
        lambda slot, now=None: (
            fixed_run_time,
            prayonit_social.content_engine.get_todays_content(
                slot=slot,
                now=fixed_run_time,
            ),
        ),
    )
    _patch_common_pipeline(monkeypatch)

    # In production mode, tracking/upload/buffer ARE expected to be called,
    # so override the "must never be called" assertions from
    # _patch_common_pipeline with working fakes.
    monkeypatch.setattr(
        prayonit_social.tracking,
        "create_tracked_link",
        lambda **kwargs: "https://prayonit.example.com/download?t=abc123",
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated",
        lambda local_path, prefix, supabase: (f"{prefix}/{local_path.name}", f"https://cdn.example.com/{prefix}/{local_path.name}"),
    )
    buffer_calls = {"count": 0}
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: buffer_calls.__setitem__("count", buffer_calls["count"] + 1) or {"post": {"id": "abc"}},
    )

    calls = {"gemini": 0}
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "generate_ad_copy",
        lambda **kwargs: calls.__setitem__("gemini", calls["gemini"] + 1) or _ad_copy(),
    )

    result = prayonit_social.cmd_run("morning")
    out = capsys.readouterr().out

    assert calls["gemini"] == 1
    assert buffer_calls["count"] > 0
    assert "PREVIEW_MODE: False" in out
    assert result == 0
