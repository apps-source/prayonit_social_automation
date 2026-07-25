"""Tests for the Brand Brain loader (config.load_brand_rules)."""
import config


def test_brand_rules_json_loads():
    rules = config.load_brand_rules()
    assert rules["brand_name"] == "Prayonit"
    assert rules["preferred_cta"] == "Come pray with me."
    assert "core_features" in rules
    assert isinstance(rules["core_features"], list)
    assert len(rules["core_features"]) > 0


def test_brand_rules_cached_at_module_load():
    assert config.BRAND_RULES["brand_name"] == "Prayonit"
    assert config.BRAND_RULES["preferred_cta"] in config.BRAND_RULES["approved_ctas"]


def test_brand_rules_contains_expected_sections():
    rules = config.load_brand_rules()
    for key in (
        "brand_name", "tagline", "mission", "core_features", "approved_ctas",
        "preferred_cta", "voice", "approved_language", "never_claim",
        "never_say", "trial_policy", "app_store_links",
    ):
        assert key in rules
