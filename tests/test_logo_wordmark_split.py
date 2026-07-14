"""Tests for the Feed logo-asset vs wordmark contrast QA split.

The graphic logo asset (brand image) must be observational metadata only and
must never block Buffer publishing. The PRAYONIT wordmark is rendered as
gold body text and must be measured independently using its own tight
bounding box, the gold text color, and the gold-text contrast threshold.
"""
import image_renderer
import prompt_builder
import campaign_engine
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


def _render_feed(bg_tag="valley"):
    sel = _fake_selection()
    ad = prompt_builder.generate_local_ad_copy(selection=sel, slot="morning")
    ad["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    ad["story_app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    bg = image_renderer._synthetic_background_image(bg_tag, image_renderer.config.CANVAS_SIZE)
    return image_renderer.compose_ad(bg, ad), ad, sel


def test_logo_asset_and_wordmark_are_separate_elements():
    feed, _, _ = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    assert "logo_asset" in elem
    assert "wordmark" in elem
    assert "logo" not in elem  # old combined key must no longer exist


def test_logo_asset_is_observational_and_does_not_block_buffer():
    feed, ad, sel = _render_feed("sunrise_bright")
    elem = feed.info["element_contrast_metrics"]["feed"]

    # Even if we simulate the logo asset having terrible contrast, it should
    # never contribute to overall_pass or a critical QA failure.
    elem["logo_asset"]["pass"] = False  # simulate a hypothetical bad reading
    assert elem["logo_asset"].get("observational_only") is True

    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://sunrise_bright",
        background_meta=image_renderer.compute_local_contrast_metrics(
            image_renderer._synthetic_background_image("sunrise_bright", image_renderer.config.CANVAS_SIZE), "feed"
        ),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=elem,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    # logo_asset's forced failure must not surface as a blocking critical failure
    # as long as overall_pass (computed excluding logo_asset) remains true.
    if elem.get("overall_pass"):
        assert creative_engine_v3.should_block_buffer(report) is False


def test_wordmark_contrast_checked_independently_with_gold_threshold():
    feed, _, _ = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    wordmark = elem["wordmark"]
    assert wordmark["threshold"] == image_renderer.CONTRAST_MIN_RATIO_GOLD
    assert wordmark.get("observational_only") is not True


def test_unreadable_wordmark_still_fails_but_non_blocking_when_toggle_off():
    feed, ad, sel = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    # Force the wordmark to be unreadable
    elem["wordmark"]["pass"] = False
    elem["wordmark"]["contrast_ratio"] = 1.0
    elem["overall_pass"] = False

    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://valley",
        background_meta=image_renderer.compute_local_contrast_metrics(
            image_renderer._synthetic_background_image("valley", image_renderer.config.CANVAS_SIZE), "feed"
        ),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=elem,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    assert "contrast_threshold_failed" in report["warnings"]
    assert "contrast_threshold_failed" not in report["critical_failures"]
    assert creative_engine_v3.should_block_buffer(report) is False


def test_other_genuine_contrast_failures_non_blocking_when_toggle_off():
    feed, ad, sel = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    # Force a genuine headline failure (not logo-related)
    elem["headline"]["pass"] = False
    elem["overall_pass"] = False

    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://valley",
        background_meta=image_renderer.compute_local_contrast_metrics(
            image_renderer._synthetic_background_image("valley", image_renderer.config.CANVAS_SIZE), "feed"
        ),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=elem,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    assert "contrast_threshold_failed" in report["warnings"]
    assert creative_engine_v3.should_block_buffer(report) is False


def test_wordmark_failure_blocks_when_toggle_enabled(monkeypatch):
    monkeypatch.setattr(creative_engine_v3, "CONTRAST_BLOCKING_ENABLED", True)
    feed, ad, sel = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    elem["wordmark"]["pass"] = False
    elem["overall_pass"] = False

    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad,
        slot="morning",
        campaign_name=sel["campaign"]["name"],
        background_path="synthetic://valley",
        background_meta=image_renderer.compute_local_contrast_metrics(
            image_renderer._synthetic_background_image("valley", image_renderer.config.CANVAS_SIZE), "feed"
        ),
        territory=sel["campaign"].get("emotional_territory", "general_encouragement"),
        recent_headlines=[],
        has_badges=True,
        contrast_metrics=elem,
        captions={"facebook": "x", "instagram": "y", "threads": "z"},
    )
    assert "contrast_threshold_failed" in report["critical_failures"]
    assert creative_engine_v3.should_block_buffer(report) is True
