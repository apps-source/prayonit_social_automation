from types import SimpleNamespace

from PIL import Image

import creative_engine_v3
import prayonit_social


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
        "emotional_territory": territory,
    }


def _generic_ad_copy():
    return {
        "brand_header": "PRAYONIT",
        "pain_headline": "Is a prayer app for you?",
        "spiritual_action": "Give your worries to God.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
        "facebook_caption": "x",
        "instagram_caption": "x",
        "threads_caption": "x",
        "story_headline": "Is a prayer app for you?",
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


def test_fallback_pools_pass_validation():
    errors = creative_engine_v3.validate_fallback_headline_pools()
    assert errors == []


def test_fallback_selection_deterministic_and_slot_territory_aware():
    c1 = creative_engine_v3.deterministic_fallback_candidates(
        slot="morning", territory="burnout", date_key="2026-07-12", run_id="run-1"
    )
    c2 = creative_engine_v3.deterministic_fallback_candidates(
        slot="morning", territory="burnout", date_key="2026-07-12", run_id="run-1"
    )
    c3 = creative_engine_v3.deterministic_fallback_candidates(
        slot="evening", territory="burnout", date_key="2026-07-12", run_id="run-1"
    )
    assert c1 == c2
    assert c1 != c3


def test_duplicate_headline_is_replaced_by_next_valid_candidate():
    ordered = creative_engine_v3.deterministic_fallback_candidates(
        slot="morning", territory="burnout", date_key="2026-07-12", run_id="run-dup"
    )
    recent = [ordered[0]]
    recovered = creative_engine_v3.select_recovered_headline(
        slot="morning",
        territory="burnout",
        date_key="2026-07-12",
        run_id="run-dup",
        recent_headlines=recent,
    )
    assert recovered is not None
    assert recovered != ordered[0]


def test_recovery_shortens_original_headline_and_preserves_topic():
    # A too-long friendship-themed headline should be recovered by
    # shortening it (preserving the friendship topic), not by pulling an
    # unrelated headline from the generic "purpose" fallback pool.
    original = "Losing touch with your old friends and feeling distant from people you used to be close to?"
    recovered = creative_engine_v3.select_recovered_headline(
        slot="morning",
        territory="purpose",
        date_key="2026-07-12",
        run_id="run-friendship",
        recent_headlines=[],
        original_headline=original,
    )
    assert recovered is not None
    assert "friend" in recovered.lower()
    # None of the unrelated "purpose" pool headlines (about direction/
    # clarity/next steps) should have been substituted in.
    for pool_headline in creative_engine_v3.deterministic_fallback_candidates(
        slot="morning", territory="purpose", date_key="2026-07-12", run_id="run-friendship"
    ):
        assert recovered != pool_headline


def test_recovery_falls_back_to_pool_when_shortened_original_still_invalid():
    # An empty/invalid original_headline cannot be shortened into anything
    # valid, so recovery must fall back to the deterministic pool exactly
    # as before.
    ordered = creative_engine_v3.deterministic_fallback_candidates(
        slot="morning", territory="burnout", date_key="2026-07-12", run_id="run-empty-original"
    )
    recovered = creative_engine_v3.select_recovered_headline(
        slot="morning",
        territory="burnout",
        date_key="2026-07-12",
        run_id="run-empty-original",
        recent_headlines=[],
        original_headline="",
    )
    assert recovered == ordered[0]


def test_failure_reason_mapping_returns_other_bucket():
    reason = creative_engine_v3.identify_headline_failure_reason(
        headline="Valid sounding headline",
        issues=[],
        territory="burnout",
    )
    assert reason in {
        "recent_duplicate",
        "generic_headline",
        "excessive_length",
        "invalid_formatting",
        "territory_mismatch",
        "other_headline_quality_failure",
    }


def test_production_generic_headline_recovered_and_buffer_allowed(isolated_database, monkeypatch):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "full")
    # This test predates Phase 2A video publishing; keep it isolated from
    # the developer's local .env (which may set VIDEO_ENABLED/
    # VIDEO_PUBLISH_ENABLED=true for manual dry-run testing) since video
    # generation/upload is not what this test is validating.
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_PUBLISH_ENABLED", False)

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
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: "https://example.com")
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _generic_ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i", "threads": "t"},
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (1, 2, 3)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: _image_with_pass_metrics((1080, 1350)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: _image_with_pass_metrics((1080, 1920)))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: ("remote.jpg", "https://cdn/remote.jpg"))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: {"post": {"id": "p1"}})

    def _qa(**kwargs):
        ad = kwargs["ad_copy"]
        # Generic source headline must be replaced deterministically.
        assert ad["pain_headline"] != "Is a prayer app for you?"
        assert ad["story_headline"] == creative_engine_v3.deterministic_headline_shorten(ad["pain_headline"], max_chars=45)
        return {"critical_failures": [], "warnings": [], "pass": True, "score": 100}

    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", _qa)
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: False)

    code = prayonit_social.cmd_run("morning")
    assert code == 0


def test_failed_recovery_blocks_and_returns_nonzero(isolated_database, monkeypatch):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)
    monkeypatch.setattr(prayonit_social.config, "SOCIAL_OUTPUT_MODE", "full")
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_PUBLISH_ENABLED", False)

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
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: "https://example.com")
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _generic_ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i", "threads": "t"},
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (1, 2, 3)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: _image_with_pass_metrics((1080, 1350)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: _image_with_pass_metrics((1080, 1920)))
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "select_recovered_headline", lambda **kwargs: None)

    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: {"critical_failures": ["headline_quality_failed"], "warnings": [], "pass": False, "score": 80},
    )
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: True)
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer should not be called when blocked")),
    )

    code = prayonit_social.cmd_run("morning")
    assert code == 2


def test_main_exit_zero_when_cmd_run_zero(monkeypatch):
    monkeypatch.setattr(prayonit_social, "cmd_run", lambda slot: 0)
    monkeypatch.setattr(prayonit_social, "build_arg_parser", lambda: SimpleNamespace(parse_args=lambda: SimpleNamespace(command="run", slot="morning")))
    assert prayonit_social.main() == 0


def test_main_exit_nonzero_when_cmd_run_nonzero(monkeypatch):
    monkeypatch.setattr(prayonit_social, "cmd_run", lambda slot: 2)
    monkeypatch.setattr(prayonit_social, "build_arg_parser", lambda: SimpleNamespace(parse_args=lambda: SimpleNamespace(command="run", slot="morning")))
    assert prayonit_social.main() == 2


def test_testmode_never_posts(isolated_database, monkeypatch):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)

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
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _generic_ad_copy())
    monkeypatch.setattr(
        prayonit_social.prompt_builder,
        "build_platform_captions",
        lambda ad_copy, selection, platform_urls: {"facebook": "f", "instagram": "i", "threads": "t"},
    )
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (1, 2, 3)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: _image_with_pass_metrics((1080, 1350)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: _image_with_pass_metrics((1080, 1920)))
    monkeypatch.setattr(
        prayonit_social.creative_engine_v3,
        "build_prepublish_qa_report",
        lambda **kwargs: {"critical_failures": [], "warnings": [], "pass": True, "score": 100},
    )
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "should_block_buffer", lambda report: False)
    monkeypatch.setattr(
        prayonit_social.buffer_client,
        "buffer_create_post",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer should never be called in TEST_MODE")),
    )

    code = prayonit_social.cmd_run("morning")
    assert code == 0
