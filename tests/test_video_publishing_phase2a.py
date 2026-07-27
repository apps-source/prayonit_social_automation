"""Phase 2A validation: environment validation and orchestrator wiring for
Facebook Reel / Instagram Reel / TikTok video publishing.

Direct Buffer GraphQL payload shape tests live in test_buffer_client.py.
This file covers:
  - config.require_env() BUFFER_TIKTOK_CHANNEL_ID validation (Task 4)
  - prayonit_social.cmd_run() orchestrator job-creation wiring (Task 3)

No live network calls are made anywhere in this file: Gemini, Supabase,
Buffer, tracking, image rendering, and video rendering are all mocked.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

import config
import prayonit_social
from engines import content_engine


# ---------- Task 4: BUFFER_TIKTOK_CHANNEL_ID environment validation ----------

def test_tiktok_channel_id_not_required_when_video_publish_disabled(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", False)
    monkeypatch.delenv("BUFFER_TIKTOK_CHANNEL_ID", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")
    # Should not raise: TikTok channel id is not required when video
    # publishing is disabled.
    config.require_env(test_mode=False)


def test_tiktok_channel_id_required_when_video_publish_enabled(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(config, "TIKTOK_MANUAL_HANDOFF", False)
    monkeypatch.delenv("BUFFER_TIKTOK_CHANNEL_ID", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")
    try:
        config.require_env(test_mode=False)
        assert False, "expected RuntimeError due to missing BUFFER_TIKTOK_CHANNEL_ID"
    except RuntimeError as exc:
        assert "BUFFER_TIKTOK_CHANNEL_ID" in str(exc)


def test_tiktok_channel_id_satisfied_when_present_and_video_publish_enabled(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(config, "TIKTOK_MANUAL_HANDOFF", False)
    monkeypatch.setenv("BUFFER_TIKTOK_CHANNEL_ID", "tiktok-chan-1")
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")
    # Should not raise.
    config.require_env(test_mode=False)


def test_tiktok_channel_id_not_required_in_test_mode_even_if_video_publish_enabled(monkeypatch):
    # TEST_MODE path never requires any Buffer credentials at all, regardless
    # of VIDEO_PUBLISH_ENABLED -- this must remain true since TEST_MODE never
    # uploads or posts anything.
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.delenv("BUFFER_TIKTOK_CHANNEL_ID", raising=False)
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config.require_env(test_mode=True)


def test_tiktok_channel_id_not_required_when_manual_handoff_enabled(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.delenv("BUFFER_TIKTOK_CHANNEL_ID", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")

    config.require_env(test_mode=False)


def test_require_env_passes_with_only_gemini_api_key_primary(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "primary-only")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")

    config.require_env(test_mode=False)


def test_require_env_passes_with_only_legacy_gemini_api_key(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.delenv("GEMINI_API_KEY_PRIMARY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-only")
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")

    config.require_env(test_mode=False)


def test_require_env_fails_when_both_gemini_keys_are_missing_or_blank(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")

    try:
        config.require_env(test_mode=True)
        assert False, "expected RuntimeError for missing Gemini key"
    except RuntimeError as exc:
        message = str(exc)
        assert "GEMINI_API_KEY_PRIMARY" in message
        assert "legacy GEMINI_API_KEY" in message
        assert "primary-only" not in message
        assert "legacy-only" not in message


def test_gemini_primary_key_prefers_primary_over_legacy(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "preferred-primary")
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-fallback")
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")

    assert config.get_gemini_primary_api_key() == "preferred-primary"


def test_gemini_secondary_key_falls_back_to_resolved_primary(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "preferred-primary")
    monkeypatch.setenv("GEMINI_API_KEY_SECONDARY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-fallback")

    assert config.get_gemini_secondary_api_key() == "preferred-primary"


# ---------- Task 3: orchestrator (prayonit_social.cmd_run) job creation ----------

def _selection(territory="burnout"):
    campaign = {
        "name": "Burnout",
        "pain_point": "burnout",
        "goal": "strength",
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
        "emotional_territory": territory,
    }


def _generic_ad_copy():
    return {
        "brand_header": "PRAYONIT",
        "pain_headline": "Not a generic prayer headline for this test",
        "spiritual_action": "Give your worries to God.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
        "facebook_caption": "x",
        "instagram_caption": "x",
        "story_headline": "Not a generic prayer headline for this test",
        "story_spiritual_action": "Give your worries to God.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }


def _image_with_pass_metrics(size):
    img = Image.new("RGB", size, (0, 0, 0))
    if size[1] == 1350:
        img.info["element_contrast_metrics"] = {"feed": {"overall_pass": True}}
    else:
        img.info["element_contrast_metrics"] = {"story": {"overall_pass": True}}
    return img


def _wire_common_mocks(monkeypatch, tmp_path):
    """Mock every external dependency cmd_run touches, matching the pattern
    used by tests/test_headline_recovery_and_exit.py, plus the Phase 2A
    video-specific mocks (motion_renderer, upload_generated_video).
    """
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(prayonit_social.config, "VOICE_ENABLED", False)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CHANNEL_ID", "tiktok-chan-1")
    monkeypatch.setattr(prayonit_social.config, "FACEBOOK_CHANNEL_ID", "fb-chan-1")
    monkeypatch.setattr(prayonit_social.config, "INSTAGRAM_CHANNEL_ID", "ig-chan-1")

    # A real, empty-but-existent directory containing one dummy .mp4 so the
    # "no motion backgrounds found" skip branch is not taken.
    motion_dir = tmp_path / "motion_backgrounds"
    motion_dir.mkdir()
    (motion_dir / "bg1.mp4").write_bytes(b"not a real video, mocked renderer ignores this")
    monkeypatch.setattr(prayonit_social.config, "MOTION_BACKGROUNDS_DIR", motion_dir)

    monkeypatch.setattr(prayonit_social, "get_supabase_client", lambda: object())
    monkeypatch.setattr(prayonit_social, "list_backgrounds", lambda supabase: ["bg.jpg"])
    monkeypatch.setattr(prayonit_social.campaign_engine, "choose_selection", lambda slot: _selection("burnout"))
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_background",
        lambda all_backgrounds, slot, campaign, formula, persona: {
            "path": "bg.jpg",
            "metadata": {"time": "morning", "visual_types": ["valley"], "emotional_suitability": ["burnout"]},
            "match_score": 3.0,
            "emotional_territory": "burnout",
        },
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "pick_spiritual_action", lambda campaign, slot: "Give your worries to God.")
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "app_feature",
            "theme": "test",
            "emotion": "test",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: "https://example.com")
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _generic_ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {
            "facebook": "FACEBOOK CAPTION",
            "instagram": "INSTAGRAM CAPTION #Prayonit",
        },
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (1, 2, 3)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: _image_with_pass_metrics((1080, 1350)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: _image_with_pass_metrics((1080, 1920)))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: ("remote.jpg", "https://cdn/remote.jpg"))
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: {"critical_failures": [], "warnings": [], "pass": True, "score": 100},
    )
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: False)

    import motion_renderer

    def fake_render_motion_ad(*, ad_copy, background_path, output_path):
        Path(output_path).write_bytes(b"fake mp4 bytes")

    monkeypatch.setattr(motion_renderer, "render_motion_ad", fake_render_motion_ad)


def test_video_jobs_created_with_correct_captions_and_shared_url(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)

    upload_video_calls = []

    def fake_upload_generated_video(video_path, prefix, supabase_client):
        upload_video_calls.append((video_path, prefix))
        return "video/remote.mp4", "https://cdn/remote-reel.mp4"

    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", fake_upload_generated_video)

    created_jobs = []

    def fake_buffer_create_post(**kwargs):
        created_jobs.append(kwargs)
        return {"post": {"id": "post-{0}".format(len(created_jobs))}}

    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", fake_buffer_create_post)

    code = prayonit_social.cmd_run("evening")

    assert code == 0
    # The MP4 upload helper is called exactly once.
    assert len(upload_video_calls) == 1

    jobs_by_label = {(job["service"], job["post_type"]): job for job in created_jobs}

    # Existing image jobs remain present.
    assert ("facebook", "post") in jobs_by_label
    assert ("instagram", "post") in jobs_by_label
    assert ("facebook", "story") in jobs_by_label
    assert ("instagram", "story") in jobs_by_label
    # New video jobs created.
    assert ("facebook", "reel") in jobs_by_label
    assert ("instagram", "reel") in jobs_by_label
    assert ("tiktok", "video") in jobs_by_label

    fb_reel = jobs_by_label[("facebook", "reel")]
    ig_reel = jobs_by_label[("instagram", "reel")]
    tiktok_job = jobs_by_label[("tiktok", "video")]

    # Same uploaded video URL reused for all three.
    assert fb_reel["video_url"] == "https://cdn/remote-reel.mp4"
    assert ig_reel["video_url"] == "https://cdn/remote-reel.mp4"
    assert tiktok_job["video_url"] == "https://cdn/remote-reel.mp4"

    # Correct captions per platform.
    assert fb_reel["caption"] == "FACEBOOK CAPTION"
    assert ig_reel["caption"] == "INSTAGRAM CAPTION #Prayonit"
    assert tiktok_job["caption"] == "INSTAGRAM CAPTION #Prayonit"

    # No image_url passed for video jobs.
    assert fb_reel["image_url"] is None
    assert ig_reel["image_url"] is None
    assert tiktok_job["image_url"] is None

    # Channel ids wired correctly.
    assert fb_reel["channel_id"] == "fb-chan-1"
    assert ig_reel["channel_id"] == "ig-chan-1"
    assert tiktok_job["channel_id"] == "tiktok-chan-1"


def test_reels_only_is_the_default_production_mode():
    assert config.SOCIAL_OUTPUT_MODE == "reels_only"


def test_reels_only_mode_skips_static_render_upload_and_buffer_jobs(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "reels_only")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "morning prayer",
            "emotion": "peace",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })

    import long_form_renderer

    def fake_render_long_form_video(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr(
        long_form_renderer,
        "render_long_form_video",
        fake_render_long_form_video,
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "compose_ad",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("feed image should not be rendered")),
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "compose_story_ad",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("story image should not be rendered")),
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("static assets should not be uploaded")),
    )
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("static QA should not run in reels_only")),
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *args, **kwargs: ("video/remote.mp4", "https://cdn/remote-reel.mp4"),
    )
    handoff_calls = []
    monkeypatch.setattr(
        prayonit_social,
        "_create_tiktok_manual_handoff",
        lambda **kwargs: handoff_calls.append(kwargs) or {
            "creator_search_topic": "morning prayer before work",
            "backup_path": tmp_path / "backup.mp4",
            "notes_path": tmp_path / "notes.txt",
            "photos_status": {"attempted": False, "succeeded": False, "already_imported": False, "album_added": False},
            "note_status": {"attempted": False, "succeeded": False, "already_created": False},
        },
    )
    created_jobs = []
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: created_jobs.append(kwargs) or {"post": {"id": "ok"}},
    )

    code = prayonit_social.cmd_run("evening")
    labels = {(job["service"], job["post_type"]) for job in created_jobs}

    assert code == 0
    assert ("facebook", "post") not in labels
    assert ("instagram", "post") not in labels
    assert ("facebook", "story") not in labels
    assert ("instagram", "story") not in labels
    assert ("facebook", "reel") in labels
    assert ("instagram", "reel") in labels
    assert ("tiktok", "video") not in labels
    assert len(handoff_calls) == 1


def test_reels_only_static_qa_cannot_block_reels(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "reels_only")
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "morning prayer",
            "emotion": "peace",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })
    import long_form_renderer
    def fake_render_long_form_video(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_bytes(b"x")
        return path
    monkeypatch.setattr(
        long_form_renderer,
        "render_long_form_video",
        fake_render_long_form_video,
    )
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("static QA should not run")),
    )
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *args, **kwargs: ("video/remote.mp4", "https://cdn/remote-reel.mp4"),
    )
    created_jobs = []
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: created_jobs.append(kwargs) or {"post": {"id": "ok"}},
    )

    code = prayonit_social.cmd_run("evening")

    assert code == 0
    assert {(job["service"], job["post_type"]) for job in created_jobs} == {
        ("facebook", "reel"),
        ("instagram", "reel"),
    }


def test_reels_only_video_specific_failure_blocks_reels_and_handoff(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "reels_only")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "morning prayer",
            "emotion": "peace",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })
    import long_form_renderer
    monkeypatch.setattr(long_form_renderer, "render_long_form_video", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("video failed")))
    handoff_calls = []
    monkeypatch.setattr(prayonit_social, "_create_tiktok_manual_handoff", lambda **kwargs: handoff_calls.append(kwargs))
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer should not be called")),
    )

    code = prayonit_social.cmd_run("evening")

    assert code == 2
    assert handoff_calls == []


def test_video_job_failure_does_not_prevent_image_jobs(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)

    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *args, **kwargs: ("video/remote.mp4", "https://cdn/remote-reel.mp4"),
    )

    created_jobs = []

    def flaky_buffer_create_post(**kwargs):
        # Facebook Reel job fails; every other job (image and video) must
        # still be attempted independently.
        if kwargs["service"] == "facebook" and kwargs["post_type"] == "reel":
            raise RuntimeError("simulated Buffer rejection for facebook reel")
        created_jobs.append(kwargs)
        return {"post": {"id": "post-{0}".format(len(created_jobs))}}

    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", flaky_buffer_create_post)

    code = prayonit_social.cmd_run("evening")

    # Overall run reports failure (non-zero) because one job failed...
    assert code == 1
    labels = {(job["service"], job["post_type"]) for job in created_jobs}
    # ...but every other job, including the remaining video jobs and all
    # pre-existing image jobs, was still attempted and succeeded.
    assert ("facebook", "post") in labels
    assert ("instagram", "post") in labels
    assert ("facebook", "story") in labels
    assert ("instagram", "story") in labels
    assert ("instagram", "reel") in labels
    assert ("tiktok", "video") in labels
    assert ("facebook", "reel") not in labels


def test_no_video_jobs_when_video_publish_disabled(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_PUBLISH_ENABLED", False)

    upload_video_calls = []
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *a, **k: upload_video_calls.append(1) or ("v", "u"),
    )

    created_jobs = []

    def fake_buffer_create_post(**kwargs):
        created_jobs.append(kwargs)
        return {"post": {"id": "post-{0}".format(len(created_jobs))}}

    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", fake_buffer_create_post)

    code = prayonit_social.cmd_run("evening")

    assert code == 0
    assert len(upload_video_calls) == 0
    labels = {(job["service"], job["post_type"]) for job in created_jobs}
    assert ("facebook", "reel") not in labels
    assert ("instagram", "reel") not in labels
    assert ("tiktok", "video") not in labels
    # Original 4 image jobs remain present.
    assert len(labels) == 4


def test_require_env_does_not_require_threads_channel(monkeypatch):
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", False)
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY_PRIMARY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "x")
    monkeypatch.setenv("BUFFER_FACEBOOK_CHANNEL_ID", "x")
    monkeypatch.setenv("BUFFER_INSTAGRAM_CHANNEL_ID", "x")
    monkeypatch.delenv("BUFFER_THREADS_CHANNEL_ID", raising=False)

    config.require_env(test_mode=False)


def test_tiktok_buffer_publish_is_skipped_only_when_manual_handoff_enabled(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "test",
            "emotion": "test",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })
    def fake_render_long_form_video(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr("long_form_renderer.render_long_form_video", fake_render_long_form_video)
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *args, **kwargs: ("video/remote.mp4", "https://cdn/remote-reel.mp4"),
    )
    handoff_calls = []
    monkeypatch.setattr(
        prayonit_social,
        "_create_tiktok_manual_handoff",
        lambda **kwargs: handoff_calls.append(kwargs) or {
            "creator_search_topic": "morning prayer before work",
            "backup_path": tmp_path / "backup.mp4",
            "notes_path": tmp_path / "notes.txt",
            "photos_status": {
                "attempted": False,
                "succeeded": False,
                "already_imported": False,
                "album_added": False,
            },
            "note_status": {
                "attempted": False,
                "succeeded": False,
                "already_created": False,
            },
        },
    )
    created_jobs = []
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: created_jobs.append(kwargs) or {"post": {"id": "ok"}},
    )

    code = prayonit_social.cmd_run("evening")
    labels = {(job["service"], job["post_type"]) for job in created_jobs}

    assert code == 0
    assert ("tiktok", "video") not in labels
    assert ("facebook", "reel") in labels
    assert ("instagram", "reel") in labels
    assert len(handoff_calls) == 1


def test_manual_handoff_disabled_preserves_current_tiktok_behavior(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        prayonit_social.image_renderer,
        "upload_generated_video",
        lambda *args, **kwargs: ("video/remote.mp4", "https://cdn/remote-reel.mp4"),
    )
    created_jobs = []
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: created_jobs.append(kwargs) or {"post": {"id": "ok"}},
    )

    code = prayonit_social.cmd_run("evening")
    labels = {(job["service"], job["post_type"]) for job in created_jobs}

    assert code == 0
    assert ("tiktok", "video") in labels


def test_tiktok_manual_handoff_creates_local_backup_and_notes_file(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)

    result = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption line\n\n#Prayonit #MorningPrayer", "opening_hook": "Hook", "creator_search_topic": "morning prayer before work", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert result["backup_path"].exists()
    assert result["notes_path"].exists()
    notes = result["notes_path"].read_text(encoding="utf-8")
    assert "Creator Search Insights target phrase: morning prayer before work" in notes
    assert "TikTok caption: Caption line\n\n#Prayonit #MorningPrayer" in notes
    assert "hashtags: #Prayonit #MorningPrayer" in notes
    assert "genre label: MORNING PRAYER" in notes


def test_photos_direct_import_script_finds_or_creates_album_before_import(tmp_path):
    script = prayonit_social._build_photos_direct_import_script(tmp_path / "video.mp4", "Prayonit TikTok Ready")

    assert 'set targetAlbum to missing value' in script
    assert 'make new album named albumName' in script
    assert 'import {targetFile} into targetAlbum skip check duplicates yes' in script


def test_photos_direct_import_script_does_not_depend_on_delay_or_filename_lookup(tmp_path):
    script = prayonit_social._build_photos_direct_import_script(tmp_path / "video.mp4", "Prayonit TikTok Ready")

    assert "delay 1" not in script
    assert "media items whose filename" not in script


def test_photos_returned_items_fallback_uses_imported_media_objects(tmp_path):
    script = prayonit_social._build_photos_returned_items_script(tmp_path / "video.mp4", "Prayonit TikTok Ready")

    assert "set importedItems to import {targetFile} skip check duplicates yes" in script
    assert "add importedItems to targetAlbum" in script


def test_photos_import_falls_back_to_returned_media_items(monkeypatch, tmp_path):
    phases = []

    def fake_run(script, *, app_label, phase):
        phases.append((app_label, phase))
        if phase == "import_into_album":
            raise RuntimeError("unsupported direct import")
        return subprocess.CompletedProcess(["osascript"], 0, stdout="ok", stderr="")

    monkeypatch.setattr(prayonit_social, "_run_osascript", fake_run)

    result = prayonit_social._import_video_to_apple_photos(tmp_path / "video.mp4", "Prayonit TikTok Ready")

    assert result["succeeded"] is True
    assert result["fallback_used"] == "returned_items"
    assert phases == [
        ("Apple Photos", "import_into_album"),
        ("Apple Photos", "import_returned_items_then_add_to_album"),
    ]


def test_run_osascript_logs_stdout_stderr_and_return_code_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        prayonit_social.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="stdout details", stderr="stderr details"),
    )

    try:
        prayonit_social._run_osascript("return 1", app_label="Apple Photos", phase="import_into_album")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Apple Photos failure phase import_into_album" in str(exc)

    out = capsys.readouterr().out
    assert "Apple Photos osascript return code: 1" in out
    assert "Apple Photos osascript stdout: stdout details" in out
    assert "Apple Photos osascript stderr: stderr details" in out
    assert "Apple Photos failure phase: import_into_album" in out


def test_duplicate_photos_imports_are_prevented(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    handoff_dir = tmp_path / "handoff"
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    import_calls = {"count": 0}
    monkeypatch.setattr(
        prayonit_social,
        "_import_video_to_apple_photos",
        lambda *args, **kwargs: import_calls.__setitem__("count", import_calls["count"] + 1) or {
            "attempted": True,
            "succeeded": True,
            "album_added": True,
        },
    )

    first = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )
    second = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert import_calls["count"] == 1
    assert first["photos_status"]["succeeded"] is True
    assert second["photos_status"]["already_imported"] is True


def test_failed_photos_import_remains_retryable_and_success_updates_manifest(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    handoff_dir = tmp_path / "handoff"
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    calls = {"count": 0}

    def flaky_import(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Photos unavailable")
        return {"attempted": True, "succeeded": True, "album_added": True, "fallback_used": None}

    monkeypatch.setattr(prayonit_social, "_import_video_to_apple_photos", flaky_import)

    first = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-26T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )
    second = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-26T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    manifest = json.loads((handoff_dir / "photos_import_manifest.json").read_text(encoding="utf-8"))
    entry = next(iter(manifest["imports"].values()))

    assert first["photos_status"]["succeeded"] is False
    assert second["photos_status"]["succeeded"] is True
    assert calls["count"] == 2
    assert entry["succeeded"] is True


def test_photos_import_failure_does_not_fail_handoff_creation(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    monkeypatch.setattr(
        prayonit_social,
        "_import_video_to_apple_photos",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Photos unavailable")),
    )

    result = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption", "opening_hook": "Hook", "creator_search_topic": "god prayers for protection", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert result["backup_path"].exists()
    assert result["notes_path"].exists()
    assert result["photos_status"]["succeeded"] is False
    assert "Open Photos" in result["photos_status"]["recovery_guidance"]


def test_apple_note_contains_full_caption_and_topic(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    captured = {}
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda **kwargs: captured.update(kwargs) or {"attempted": True, "succeeded": True},
    )

    result = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Main caption line\n\n#Prayonit #PrayerLife", "opening_hook": "Hook", "creator_search_topic": "prayer for guidance and clarity", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert result["note_status"]["succeeded"] is True
    assert "prayer for guidance and clarity" in captured["body"]
    assert "Main caption line\n\n#Prayonit #PrayerLife" in captured["body"]
    assert "#Prayonit #PrayerLife" in captured["body"]


def test_apple_note_duplicate_creation_is_prevented(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    handoff_dir = tmp_path / "handoff"
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    note_calls = {"count": 0}
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda **kwargs: note_calls.__setitem__("count", note_calls["count"] + 1) or {"attempted": True, "succeeded": True},
    )

    prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption\n\n#Prayonit", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )
    second = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption\n\n#Prayonit", "opening_hook": "Hook", "creator_search_topic": "powerful daily prayers", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert note_calls["count"] == 1
    assert second["note_status"]["already_created"] is True


def test_apple_note_failure_does_not_fail_handoff_creation(monkeypatch, tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", tmp_path / "handoff")
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Notes unavailable")),
    )

    result = prayonit_social._create_tiktok_manual_handoff(
        video_local_path=source_video,
        ad_copy={"instagram_caption": "Caption\n\n#Prayonit", "opening_hook": "Hook", "creator_search_topic": "god prayers for protection", "pain_headline": "Need peace?"},
        selection={"thread_topic": "fallback topic"},
        presentation_config={"video_template": "long_prayer", "content_type": "prayer_read", "slot": "morning"},
        due_at_iso="2026-07-25T12:00:00Z",
        slot="morning",
        run_row_id=1,
    )

    assert result["notes_path"].exists()
    assert result["note_status"]["succeeded"] is False
    assert "Open Apple Notes" in result["note_status"]["recovery_guidance"]


def test_retry_tiktok_handoff_retries_local_package_without_generation_or_publish(monkeypatch, tmp_path):
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    video_path = handoff_dir / "retry.mp4"
    notes_path = handoff_dir / "retry.txt"
    video_path.write_bytes(b"video")
    notes_path.write_text("Caption package", encoding="utf-8")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    manifest_path = handoff_dir / "photos_import_manifest.json"
    manifest_path.write_text(json.dumps({
        "imports": {
            "source-key": {
                "backup_path": str(video_path.resolve()),
                "notes_path": str(notes_path.resolve()),
                "succeeded": False,
                "already_imported": False,
                "apple_note_created": False,
                "apple_note_title": "Retry Note",
            }
        }
    }), encoding="utf-8")
    photos_calls = {"count": 0}
    note_calls = {"count": 0}
    monkeypatch.setattr(
        prayonit_social,
        "_import_video_to_apple_photos",
        lambda *args, **kwargs: photos_calls.__setitem__("count", photos_calls["count"] + 1) or {
            "attempted": True,
            "succeeded": True,
            "album_added": True,
            "fallback_used": None,
        },
    )
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda **kwargs: note_calls.__setitem__("count", note_calls["count"] + 1) or {"attempted": True, "succeeded": True},
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not regenerate content")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not publish to Buffer")))

    result = prayonit_social.cmd_retry_tiktok_handoff(str(video_path), str(notes_path))

    assert result == 0
    assert photos_calls["count"] == 1
    assert note_calls["count"] == 1


def test_retry_tiktok_handoff_preserves_existing_apple_note_success(monkeypatch, tmp_path):
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    video_path = handoff_dir / "retry.mp4"
    notes_path = handoff_dir / "retry.txt"
    video_path.write_bytes(b"video")
    notes_path.write_text("Caption package", encoding="utf-8")
    monkeypatch.setattr(prayonit_social.config, "OUTPUT_TIKTOK_HANDOFF_DIR", handoff_dir)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    (handoff_dir / "photos_import_manifest.json").write_text(json.dumps({
        "imports": {
            "source-key": {
                "backup_path": str(video_path.resolve()),
                "notes_path": str(notes_path.resolve()),
                "succeeded": False,
                "already_imported": False,
                "apple_note_created": True,
                "apple_note_title": "Retry Note",
            }
        }
    }), encoding="utf-8")
    monkeypatch.setattr(
        prayonit_social,
        "_import_video_to_apple_photos",
        lambda *args, **kwargs: {"attempted": True, "succeeded": True, "album_added": True, "fallback_used": None},
    )
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("apple note should not be recreated")),
    )

    result = prayonit_social._retry_tiktok_handoff_package(video_path=video_path, notes_path=notes_path)

    assert result["note_status"]["already_created"] is True
    assert result["note_status"]["attempted"] is False


def test_retry_tiktok_handoff_cli_invokes_retry_command(monkeypatch, tmp_path):
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    video_path = handoff_dir / "retry.mp4"
    notes_path = handoff_dir / "retry.txt"
    video_path.write_bytes(b"video")
    notes_path.write_text("Caption package", encoding="utf-8")
    called = {}
    monkeypatch.setattr(
        prayonit_social,
        "cmd_retry_tiktok_handoff",
        lambda video, notes: called.update({"video": video, "notes": notes}) or 0,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prayonit_social.py", "retry-tiktok-handoff", "--video", str(video_path), "--notes", str(notes_path)],
    )

    result = prayonit_social.main()

    assert result == 0
    assert called == {"video": str(video_path), "notes": str(notes_path)}


def test_valid_tiktok_handoff_occurs_despite_static_qa_failure(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", False)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", False)
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "test",
            "emotion": "test",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })
    def fake_render_long_form_video(**kwargs):
        path = Path(kwargs["output_path"])
        path.write_bytes(b"x")
        return path

    monkeypatch.setattr("long_form_renderer.render_long_form_video", fake_render_long_form_video)
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: {"critical_failures": ["headline_quality_failed"], "warnings": [], "pass": False, "score": 70},
    )
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: True)
    handoff_calls = []
    monkeypatch.setattr(
        prayonit_social,
        "_create_tiktok_manual_handoff",
        lambda **kwargs: handoff_calls.append(kwargs) or {
            "creator_search_topic": "morning prayer before work",
            "backup_path": tmp_path / "backup.mp4",
            "notes_path": tmp_path / "notes.txt",
            "photos_status": {"attempted": False, "succeeded": False, "already_imported": False, "album_added": False},
            "note_status": {"attempted": False, "succeeded": False, "already_created": False},
        },
    )
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer should not be called when blocked")),
    )

    code = prayonit_social.cmd_run("evening")

    assert code == 2
    assert len(handoff_calls) == 1


def test_preview_mode_creates_neither_photos_import_nor_apple_note(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_IMPORT_TO_PHOTOS", True)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_CREATE_APPLE_NOTE", True)
    monkeypatch.setattr(
        prayonit_social,
        "_import_video_to_apple_photos",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("photos import should not run in preview")),
    )
    monkeypatch.setattr(
        prayonit_social,
        "_create_apple_note",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("apple note should not run in preview")),
    )

    code = prayonit_social.cmd_run("evening")

    assert code == 0


def test_video_specific_failure_blocks_handoff(monkeypatch, tmp_path):
    _wire_common_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TIKTOK_MANUAL_HANDOFF", True)
    monkeypatch.setattr(
        content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "test",
            "emotion": "test",
            "hook_style": "recognition",
            "objective": "test",
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
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: {
        **_generic_ad_copy(),
        "opening_hook": "Hook",
        "bridge_line": "Bridge",
        "script_segments": ["Segment one.", "Segment two."],
        "closing_line": "Amen.",
        "long_form_type": "prayer",
        "estimated_spoken_seconds": 30,
    })
    monkeypatch.setattr("long_form_renderer.render_long_form_video", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("video failed")))
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: {"critical_failures": ["contrast_failure"], "warnings": [], "pass": False, "score": 70},
    )
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: True)
    handoff_calls = []
    monkeypatch.setattr(prayonit_social, "_create_tiktok_manual_handoff", lambda **kwargs: handoff_calls.append(kwargs))

    code = prayonit_social.cmd_run("evening")

    assert code == 2
    assert handoff_calls == []
