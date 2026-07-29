"""Automatic Facebook, Instagram, and TikTok video delivery tests.

All external dependencies are mocked. These tests intentionally cover no
Apple Photos, Apple Notes, manual package, or Buffer network behavior.
"""
from pathlib import Path

import config
import prayonit_social
from engines import content_engine


def _selection():
    campaign = {
        "_key": "burnout",
        "name": "Burnout",
        "pain_point": "burnout from work",
        "goal": "encourage rest",
        "instagram_hashtags": ["#Prayer", "#Encouragement"],
        "tiktok_hashtags": ["#PrayerTok", "#ChristianTikTok"],
    }
    return {
        "campaign": campaign,
        "formula": {"name": "formula"},
        "persona": {"name": "persona"},
        "body_angle": "angle",
        "cta": "Come pray with me.",
        "thread_topic": "prayer for burnout at work",
        "relaxed_rules": [],
        "emotional_territory": "burnout",
    }


def _ad_copy(tiktok_caption=""):
    return {
        "brand_header": "PRAYONIT",
        "pain_headline": "Feeling burned out?",
        "spiritual_action": "Bring your workday to God in prayer.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": config.PRIMARY_CTA,
        "trial_support": config.VISUAL_DESTINATION_TEXT,
        "facebook_caption": "Facebook caption.",
        "instagram_caption": "Instagram caption. Link in bio.",
        "story_headline": "Feeling burned out?",
        "story_spiritual_action": "Bring it to God.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": config.PRIMARY_CTA,
        "story_trial_support": config.VISUAL_DESTINATION_TEXT,
        "opening_hook": "Your workday feels heavy.",
        "bridge_line": "God sees what you are carrying.",
        "script_segments": ["Bring this burden to God in prayer."],
        "closing_line": "Amen.",
        "long_form_type": "none",
        "estimated_spoken_seconds": 8,
        "tiktok_caption": tiktok_caption,
    }


def _content():
    return {
        "content_type": "app_feature",
        "theme": "rest",
        "emotion": "burnout",
        "hook_style": "recognition",
        "objective": "Offer a gentle next step.",
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


def _wire_run(monkeypatch, tmp_path, *, preview=False, tiktok_caption=""):
    monkeypatch.delenv("SOCIAL_OUTPUT_MODE", raising=False)
    monkeypatch.setattr(config, "TEST_MODE", False)
    monkeypatch.setattr(config, "PREVIEW_MODE", preview)
    monkeypatch.setattr(config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(config, "VIDEO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(config, "VOICE_ENABLED", False)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "reels_only")
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "history.db")
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "https://prayonit.app")
    monkeypatch.setattr(config, "TIKTOK_CHANNEL_ID", "tiktok-channel")
    monkeypatch.setattr(config, "FACEBOOK_CHANNEL_ID", "facebook-channel")
    monkeypatch.setattr(config, "INSTAGRAM_CHANNEL_ID", "instagram-channel")
    monkeypatch.setattr(config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(config, "validate_destination_config", lambda: None)

    motion_dir = tmp_path / "motion"
    motion_dir.mkdir()
    (motion_dir / "background.mp4").write_bytes(b"mock")
    monkeypatch.setattr(config, "MOTION_BACKGROUNDS_DIR", motion_dir)
    monkeypatch.setattr(prayonit_social, "get_supabase_client", lambda: object())
    monkeypatch.setattr(prayonit_social, "list_backgrounds", lambda _: ["background.jpg"])
    monkeypatch.setattr(prayonit_social.campaign_engine, "choose_selection", lambda _: _selection())
    monkeypatch.setattr(prayonit_social.campaign_engine, "load_campaigns", lambda: [_selection()["campaign"]])
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_background",
        lambda *args, **kwargs: {
            "path": "background.jpg",
            "metadata": {"time": "morning"},
            "resolved_brief_applied": True,
        },
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "pick_spiritual_action", lambda *_: "Bring it to God.")
    monkeypatch.setattr(content_engine, "get_todays_content", lambda *args, **kwargs: _content())
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **_: _ad_copy(tiktok_caption))
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda *_: {"facebook": "Facebook Reel caption.", "instagram": "Instagram Reel caption. Link in bio."},
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *_: ("video/master.mp4", "https://cdn.example/master.mp4"))
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda _: False)

    import motion_renderer

    def render_motion_ad(*, output_path, **_):
        Path(output_path).write_bytes(b"video")

    monkeypatch.setattr(motion_renderer, "render_motion_ad", render_motion_ad)


def test_reels_only_queues_facebook_instagram_and_tiktok(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path, tiktok_caption="Dedicated TikTok caption. #TikTokOnly")
    jobs = []
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: jobs.append(kwargs) or {"post": {"id": kwargs["service"]}})

    assert prayonit_social.cmd_run("morning") == 0
    assert {(job["service"], job["post_type"]) for job in jobs} == {
        ("facebook", "reel"), ("instagram", "reel"), ("tiktok", "video")
    }
    tiktok = next(job for job in jobs if job["service"] == "tiktok")
    assert tiktok["video_url"] == "https://cdn.example/master.mp4"
    assert tiktok["caption"].startswith("Dedicated TikTok caption.")
    assert "Instagram Reel caption" not in tiktok["caption"]


def test_tiktok_fallback_uses_resolved_brief_and_tiktok_hashtags(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: jobs.append(kwargs) or {"post": {"id": "ok"}})

    assert prayonit_social.cmd_run("morning") == 0
    caption = next(job["caption"] for job in jobs if job["service"] == "tiktok")
    assert "Your workday feels heavy." in caption
    assert "#PrayerTok" in caption
    assert "Link in bio" not in caption


def test_preview_shows_tiktok_payload_without_upload_or_buffer(monkeypatch, tmp_path, capsys):
    _wire_run(monkeypatch, tmp_path, preview=True)
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *_: (_ for _ in ()).throw(AssertionError("preview must not upload")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **_: (_ for _ in ()).throw(AssertionError("preview must not publish")))

    assert prayonit_social.cmd_run("morning") == 0
    output = capsys.readouterr().out
    assert "SOCIAL_OUTPUT_MODE: reels_only" in output
    assert "TikTok scheduling payload:" in output


def test_normal_runs_never_call_manual_handoff_or_apple_automation(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **_: {"post": {"id": "ok"}})
    monkeypatch.setattr(prayonit_social, "_create_tiktok_manual_handoff", lambda **_: (_ for _ in ()).throw(AssertionError("manual handoff must be unreachable")))
    monkeypatch.setattr(prayonit_social, "_import_video_to_apple_photos", lambda *_: (_ for _ in ()).throw(AssertionError("Photos must be unreachable")))
    monkeypatch.setattr(prayonit_social, "_create_apple_note", lambda **_: (_ for _ in ()).throw(AssertionError("Notes must be unreachable")))

    assert prayonit_social.cmd_run("morning") == 0
    assert not (tmp_path / "tiktok_handoff").exists()


def test_tiktok_failure_does_not_prevent_other_platforms(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path)
    calls = []

    def publish(**kwargs):
        calls.append(kwargs["service"])
        if kwargs["service"] == "tiktok":
            raise RuntimeError("TikTok unavailable")
        return {"post": {"id": kwargs["service"]}}

    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", publish)
    assert prayonit_social.cmd_run("morning") == 1
    assert calls == ["facebook", "instagram", "tiktok"]


def test_repeated_run_id_skips_already_scheduled_platform_jobs(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.uuid, "uuid4", lambda: "fixed-run-id")
    calls = []
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: calls.append(kwargs["service"]) or {"post": {"id": kwargs["service"]}},
    )

    assert prayonit_social.cmd_run("morning") == 0
    assert prayonit_social.cmd_run("morning") == 0
    assert calls == ["facebook", "instagram", "tiktok"]


def test_explicit_environment_output_mode_overrides_module_default(monkeypatch):
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setenv("SOCIAL_OUTPUT_MODE", "reels_only")
    assert config.get_social_output_mode() == "reels_only"


def test_environment_reels_only_mode_skips_static_delivery(monkeypatch, tmp_path):
    _wire_run(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setenv("SOCIAL_OUTPUT_MODE", "reels_only")
    jobs = []
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: jobs.append(kwargs) or {"post": {"id": "ok"}})

    assert prayonit_social.cmd_run("morning") == 0
    assert {(job["service"], job["post_type"]) for job in jobs} == {
        ("facebook", "reel"), ("instagram", "reel"), ("tiktok", "video")
    }


def test_cli_no_longer_exposes_manual_handoff_command():
    parser = prayonit_social.build_arg_parser()
    assert "retry-tiktok-handoff" not in parser.format_help()
