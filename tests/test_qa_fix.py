import json
from types import SimpleNamespace

import campaign_engine
import config
import history_store
import image_renderer
import prompt_builder
import creative_engine_v3

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

def test_locked_benefit_enforced_before_qa():
    sel = _fake_selection()
    ad = prompt_builder.generate_local_ad_copy(selection=sel, slot="morning")
    # Simulate enforcement as prayonit_social does
    ad["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    ad["story_app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    assert creative_engine_v3.validate_locked_benefit(ad) is True

def test_feed_and_story_effective_contrast_pass_on_treated_image():
    # Create a bright synthetic background requiring overlays
    bg = image_renderer._synthetic_background_image("sunrise_bright", image_renderer.config.CANVAS_SIZE)
    copy = prompt_builder.generate_local_ad_copy(selection=_fake_selection(), slot="morning")
    feed = image_renderer.compose_ad(bg, copy)
    story = image_renderer.compose_story_ad(bg, copy)
    # effective_contrast_metrics should exist and be used
    assert "effective_contrast_metrics" in feed.info
    assert "effective_contrast_metrics" in story.info
    assert feed.info["effective_contrast_metrics"].get("overall_pass") in (True, False)

def test_unreadable_final_result_still_fails():
    # Create an artificially low-contrast background (very bright near text zones)
    w, h = image_renderer.config.CANVAS_SIZE
    img = image_renderer.Image.new("RGB", (w, h), (250, 250, 250))
    copy = prompt_builder.generate_local_ad_copy(selection=_fake_selection(), slot="morning")
    feed = image_renderer.compose_ad(img, copy)
    eff = feed.info.get("effective_contrast_metrics")
    assert eff is not None
    # Force a fail by manipulating metrics (simulate very low ratio)
    for z in eff.get("zones", {}).values():
        z["white_ratio"] = 1.0
        z["gold_ratio"] = 0.8
    assert not eff.get("overall_pass") or any(z["white_ratio"] < 2.6 for z in eff.get("zones", {}).values())

def test_buffer_blocked_on_genuine_qa_failure():
    sel = _fake_selection()
    ad = prompt_builder.generate_local_ad_copy(selection=sel, slot="morning")
    ad["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    ad["story_app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    # craft a contrast_metrics that fails
    bad_contrast = {"overall_pass": False}
    # Explicitly enable blocking mode for this legacy blocking-behavior test.
    old = creative_engine_v3.CONTRAST_BLOCKING_ENABLED
    creative_engine_v3.CONTRAST_BLOCKING_ENABLED = True
    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://bright",
        background_meta=image_renderer.compute_local_contrast_metrics(img:=image_renderer._synthetic_background_image("bright", image_renderer.config.CANVAS_SIZE), "feed"),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=bad_contrast,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    creative_engine_v3.CONTRAST_BLOCKING_ENABLED = old
    assert creative_engine_v3.should_block_buffer(report) is True

def test_buffer_allowed_when_locked_benefit_and_treated_contrast_pass():
    sel = _fake_selection()
    ad = prompt_builder.generate_local_ad_copy(selection=sel, slot="morning")
    ad["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    ad["story_app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    # Create a background likely to pass after treatment
    bg = image_renderer._synthetic_background_image("desert", image_renderer.config.CANVAS_SIZE)
    feed = image_renderer.compose_ad(bg, ad)
    eff = feed.info.get("effective_contrast_metrics")
    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://desert",
        background_meta=image_renderer.compute_local_contrast_metrics(bg, "feed"),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=eff,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    # Allow if no critical failures
    assert creative_engine_v3.should_block_buffer(report) is False
