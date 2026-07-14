from PIL import Image

import campaign_engine
import creative_engine_v3
import image_renderer
import prompt_builder


def test_bright_background_contrast_treatment_feed():
    img = Image.new("RGB", (1080, 1350), (245, 245, 245))
    metrics = image_renderer.compute_local_contrast_metrics(img, "feed")
    assert "zones" in metrics
    # bright backgrounds should request stronger treatment
    headline = metrics["zones"]["headline"]
    assert headline["white_stroke_width"] >= 2


def test_dark_background_contrast_treatment_feed():
    img = Image.new("RGB", (1080, 1350), (15, 18, 30))
    metrics = image_renderer.compute_local_contrast_metrics(img, "feed")
    headline = metrics["zones"]["headline"]
    assert headline["white_stroke_width"] >= 1


def test_gold_spiritual_action_readability_rules():
    bright = Image.new("RGB", (1080, 1920), (240, 240, 230))
    dark = Image.new("RGB", (1080, 1920), (20, 24, 35))
    b_metrics = image_renderer.compute_local_contrast_metrics(bright, "story")
    d_metrics = image_renderer.compute_local_contrast_metrics(dark, "story")
    b = b_metrics["zones"]["spiritual_action"]
    d = d_metrics["zones"]["spiritual_action"]
    assert b["gold_stroke_width"] >= d["gold_stroke_width"]


def test_background_classification_and_matching():
    meta = creative_engine_v3.classify_background("night_starfield_mountain.jpg")
    assert meta["time"] == "night"
    assert "starfield" in meta["visual_types"]

    score = creative_engine_v3.background_match_score(
        background_meta=meta,
        territory="insomnia",
        slot="evening",
    )
    assert score >= 2.0


def test_headline_quality_rejection_and_shortening():
    bad = "Is a prayer app for you and your stress and your burnout and your worries today?"
    result = creative_engine_v3.validate_headline_quality(bad, max_chars=45)
    assert result["accepted"] is False
    assert "too_long" in result["issues"]

    shortened = prompt_builder.enforce_headline_quality(bad, max_chars=45)
    assert len(shortened) <= 45


def test_near_duplicate_headline_detection():
    assert creative_engine_v3.is_near_duplicate_headline(
        "Mind Racing at Bedtime?",
        "Mind racing at bedtime?",
    )


def test_recent_background_reuse_prevention(monkeypatch):
    recent_rows = [
        {
            "background_object_path": "night_starfield_mountain.jpg",
            "campaign_name": "Anxiety",
            "formula_name": "problem_agitate_solution",
        }
    ]

    monkeypatch.setattr(campaign_engine.history_store, "get_recent_campaign_history", lambda days=30: recent_rows)
    backgrounds = ["night_starfield_mountain.jpg", "sunrise_valley.jpg"]
    campaign = {"name": "Anxiety", "pain_point": "anxious", "goal": "calm"}
    formula = {"name": "problem_agitate_solution"}
    choice = campaign_engine.choose_background(
        backgrounds,
        slot="evening",
        campaign=campaign,
        formula=formula,
        persona=None,
    )
    assert choice["path"] != "night_starfield_mountain.jpg"


def test_locked_benefit_exact_match():
    ad_copy = {
        "app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
        "story_app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
    }
    assert creative_engine_v3.validate_locked_benefit(ad_copy)


def test_qa_failure_blocking_buffer():
    report = {
        "critical_failures": ["contrast_threshold_failed"],
    }
    assert creative_engine_v3.should_block_buffer(report)


def test_qa_success_allows_pipeline():
    report = {"critical_failures": []}
    assert not creative_engine_v3.should_block_buffer(report)


def test_badge_presence_rule_in_qa():
    ad_copy = {
        "app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
        "story_app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
        "pain_headline": "Struggling to Pray?",
    }
    report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad_copy,
        slot="morning",
        campaign_name="Anxiety",
        background_path="sunrise_valley.jpg",
        background_meta=creative_engine_v3.classify_background("sunrise_valley.jpg"),
        territory="confidence",
        recent_headlines=[],
        has_badges=False,
        contrast_metrics={"overall_pass": True},
        captions={"facebook": "x", "instagram": "x", "threads": "x"},
    )
    assert "missing_store_badges" in report["critical_failures"]
