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
        "threads_hashtags": ["#Prayonit"],
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
        "threads_caption": "x",
        "story_headline": "Struggling to Pray?",
        "story_spiritual_action": "Give your worries to God.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }


def test_testmode_allows_supabase_list_and_download_but_no_external_writes(isolated_database, monkeypatch, capsys):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)

    calls = {"supabase": 0, "list": 0, "download": 0}

    monkeypatch.setattr(
        prayonit_social,
        "get_supabase_client",
        lambda: calls.__setitem__("supabase", calls["supabase"] + 1) or object(),
    )
    monkeypatch.setattr(
        prayonit_social,
        "list_backgrounds",
        lambda supabase: calls.__setitem__("list", calls["list"] + 1) or [
            "Desert_landscape_sunrise_01.jpg",
            "Peaceful_landscape_night_02.jpg",
        ],
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

    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i", "threads": "t"},
    )

    def _load_background(path):
        calls["download"] += 1
        assert path == "Peaceful_landscape_night_02.jpg"
        return Image.new("RGB", (1080, 1350), (11, 22, 33))

    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", _load_background)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "add_dark_gradient", lambda image: image)

    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": [], "pass": True, "score": 100})

    # Must never be called in TEST_MODE
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: (_ for _ in ()).throw(AssertionError("tracking called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload called")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))

    prayonit_social.cmd_run("evening")
    out = capsys.readouterr().out

    assert calls["supabase"] == 1
    assert calls["list"] == 1
    assert calls["download"] == 1
    assert "Selected Supabase background filename: Peaceful_landscape_night_02.jpg" in out
    assert "TEST_MODE=true, so nothing was uploaded or posted." in out


def test_production_background_source_unchanged(isolated_database, tmp_path, monkeypatch):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)

    called = {"supabase": 0, "list": 0}

    monkeypatch.setattr(prayonit_social, "get_supabase_client", lambda: called.__setitem__("supabase", called["supabase"] + 1) or object())
    monkeypatch.setattr(prayonit_social, "list_backgrounds", lambda supabase: called.__setitem__("list", called["list"] + 1) or ["prod/path.jpg"])

    monkeypatch.setattr(prayonit_social.campaign_engine, "choose_selection", lambda slot: _selection())
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_background",
        lambda all_backgrounds, slot, campaign, formula, persona: {
            "path": "prod/path.jpg",
            "metadata": {"time": "daytime", "visual_types": ["mountain"], "emotional_suitability": ["confidence"]},
            "match_score": 2.0,
            "emotional_territory": "confidence",
        },
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "pick_spiritual_action", lambda campaign, slot: "Give your worries to God.")
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: "https://example.com")
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i", "threads": "t"},
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (1, 2, 3)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": ["x"], "pass": False, "score": 20})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: True)

    # Must not queue posts because QA blocks
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))

    prayonit_social.cmd_run("morning")
    assert called["supabase"] == 1
    assert called["list"] == 1
