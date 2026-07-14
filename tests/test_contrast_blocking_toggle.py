import creative_engine_v3


def _valid_ad_copy():
    locked = creative_engine_v3.LOCKED_BENEFIT_WORDING
    return {
        "pain_headline": "Need Prayer Support Today?",
        "app_benefit": locked,
        "story_app_benefit": locked,
    }


def _base_report_kwargs():
    return {
        "ad_copy": _valid_ad_copy(),
        "slot": "evening",
        "campaign_name": "Test Campaign",
        "background_path": "synthetic://test",
        "background_meta": {"time": "neutral", "visual_types": ["other"], "emotional_suitability": ["general encouragement"]},
        "territory": "general_encouragement",
        "recent_headlines": [],
        "has_badges": True,
        "captions": {"facebook": "x", "instagram": "y", "threads": "z"},
    }


def test_contrast_failure_warning_when_blocking_disabled(monkeypatch):
    monkeypatch.setattr(creative_engine_v3, "CONTRAST_BLOCKING_ENABLED", False)
    kwargs = _base_report_kwargs()
    kwargs["contrast_metrics"] = {"overall_pass": False, "feed": {"overall_pass": False}}

    report = creative_engine_v3.build_prepublish_qa_report(**kwargs)

    assert "contrast_threshold_failed" in report["warnings"]
    assert "contrast_threshold_failed" not in report["critical_failures"]
    assert report["contrast_metrics"]["overall_pass"] is False
    assert report["score"] < 100
    assert creative_engine_v3.should_block_buffer(report) is False


def test_other_critical_failures_still_block_when_contrast_non_blocking(monkeypatch):
    monkeypatch.setattr(creative_engine_v3, "CONTRAST_BLOCKING_ENABLED", False)
    kwargs = _base_report_kwargs()
    kwargs["contrast_metrics"] = {"overall_pass": False}
    kwargs["has_badges"] = False  # genuine critical

    report = creative_engine_v3.build_prepublish_qa_report(**kwargs)

    assert "missing_store_badges" in report["critical_failures"]
    assert creative_engine_v3.should_block_buffer(report) is True


def test_contrast_failure_blocks_when_toggle_enabled(monkeypatch):
    monkeypatch.setattr(creative_engine_v3, "CONTRAST_BLOCKING_ENABLED", True)
    kwargs = _base_report_kwargs()
    kwargs["contrast_metrics"] = {"overall_pass": False}

    report = creative_engine_v3.build_prepublish_qa_report(**kwargs)

    assert "contrast_threshold_failed" in report["critical_failures"]
    assert creative_engine_v3.should_block_buffer(report) is True
