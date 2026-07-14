"""Tests for Creative Engine v2: new message hierarchy, theology component
library, brand asset fallback behavior, and platform-specific Buffer
placement. Fully mocked; no live network/Gemini/Buffer/Supabase calls.
"""
from unittest.mock import patch

import pytest

import buffer_client
import campaign_engine
import config
import image_renderer
import prompt_builder


def _fake_selection(spiritual_action="Give today's burdens to God in prayer."):
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
        "spiritual_action": spiritual_action,
    }


def _fake_platform_urls():
    return {
        "facebook": "https://example.com/download?t=fb1",
        "instagram": "https://example.com/download?t=ig1",
        "threads": "https://example.com/download?t=th1",
    }


def _fake_ad_copy(**overrides):
    ad_copy = {
        "brand_header": "PRAYONIT",
        "pain_headline": "Need rest tonight?",
        "spiritual_action": "Give today's burdens to God in prayer.",
        "app_benefit": "Get a guided, personalized prayer to help you end your day in peace.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
        "facebook_caption": "Feeling overwhelmed tonight? Prayonit can help. Start your 14-day free trial today.",
        "instagram_caption": "Feeling overwhelmed tonight? Prayonit can help.",
        "threads_caption": "Feeling overwhelmed tonight? Start your 14-day free trial today.",
        "story_headline": "Need Rest?",
        "story_spiritual_action": "Bring it to God.",
        "story_app_benefit": "A guided, personalized prayer for how you feel.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }
    ad_copy.update(overrides)
    return ad_copy


# ---------- 1. Message structure ----------

def test_all_new_required_keys_present_in_required_keys_tuple():
    for key in (
        "brand_header", "pain_headline", "spiritual_action", "app_benefit",
        "download_cta", "trial_support", "facebook_caption", "instagram_caption",
        "threads_caption", "story_headline", "story_spiritual_action",
        "story_app_benefit", "story_download_cta", "story_trial_support",
    ):
        assert key in prompt_builder.REQUIRED_AD_COPY_KEYS


def test_build_prompt_includes_message_hierarchy_and_spiritual_action():
    selection = _fake_selection("Give today's burdens to God in prayer.")
    prompt = prompt_builder.build_prompt(
        post_type="download-focused evening ad", selection=selection, slot="evening",
        tracked_url="https://x.test/d",
    )
    assert "spiritual action" in prompt.lower()
    assert "Give today's burdens to God in prayer." in prompt
    assert "DOWNLOAD PRAYONIT" not in prompt
    assert config.PRIMARY_CTA in prompt


# ---------- App benefit must match the pain headline ----------

def test_app_benefit_matching_pain_is_accepted():
    benefit = "Get a guided, personalized prayer to help you end your day in peace."
    assert prompt_builder.app_benefit_matches_pain(benefit) is True
    assert prompt_builder.enforce_app_benefit_matches_pain(benefit) == benefit


def test_generic_app_benefit_not_connected_to_mood_is_replaced():
    generic = "Prayonit is a great app you should try."
    result = prompt_builder.enforce_app_benefit_matches_pain(generic)
    assert result != generic
    assert "guided" in result.lower()
    assert prompt_builder.app_benefit_matches_pain(result)


# ---------- Download CTA / trial support ----------

def test_download_cta_is_always_download_prayonit():
    assert prompt_builder.enforce_download_cta("Try now") == config.PRIMARY_CTA
    assert prompt_builder.enforce_download_cta("") == config.PRIMARY_CTA


def test_trial_support_falls_back_when_missing_14_day_duration():
    result = prompt_builder.enforce_trial_support("Try it free!", config.BRAND_RULES)
    assert "14-day" in result.lower()


def test_trial_support_kept_when_already_valid():
    text = "Start your 14-day free trial today."
    assert prompt_builder.enforce_trial_support(text, config.BRAND_RULES) == text


def test_story_trial_support_uses_compact_phrase_fallback():
    result = prompt_builder.enforce_trial_support("free trial!!", config.BRAND_RULES, compact=True)
    assert "14-day" in result.lower()
    assert len(result.split()) <= 6


def test_apply_brand_enforcement_forces_download_cta_and_trial_support():
    ad_copy = _fake_ad_copy(download_cta="Try Prayonit", trial_support="free trial")
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert enforced["download_cta"] == config.PRIMARY_CTA
    assert "14-day" in enforced["trial_support"].lower()


# ---------- Theology safety ----------

@pytest.mark.parametrize(
    "forbidden_text",
    [
        "Let God meet you with a personalized prayer tonight.",
        "Receive God's message through this app.",
        "Hear what God wants to tell you right now.",
        "Prayonit guarantees healing for your pain.",
    ],
)
def test_forbidden_theology_language_is_rejected(forbidden_text):
    result = prompt_builder.enforce_theology_safety(forbidden_text, "Give today's burdens to God in prayer.")
    assert result == "Give today's burdens to God in prayer."
    assert "guarantee" not in result.lower()


def test_approved_theology_language_is_kept_unchanged():
    approved = "Give today's burdens to God in prayer."
    result = prompt_builder.enforce_theology_safety(approved, "fallback")
    assert result == approved


def test_apply_brand_enforcement_rejects_forbidden_theology_in_spiritual_action():
    ad_copy = _fake_ad_copy(spiritual_action="Let God meet you with a personalized prayer tonight.")
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert "let god meet you" not in enforced["spiritual_action"].lower()


# ---------- Theology component library ----------

def test_load_theology_actions_has_expected_pools():
    pools = config.load_theology_actions()
    for pool_key in ("surrender_actions", "guidance_actions", "gratitude_actions", "anxiety_actions"):
        assert pool_key in pools
        assert len(pools[pool_key]) >= 1


def test_pick_spiritual_action_returns_string_from_a_pool():
    campaign = {"name": "Anxiety", "pain_point": "feeling anxious", "goal": "reduce anxiety"}
    action = campaign_engine.pick_spiritual_action(campaign, "morning")
    pools = config.load_theology_actions()
    all_actions = [a for pool in pools.values() for a in pool]
    assert action in all_actions


def test_pick_spiritual_action_avoids_recent_when_alternatives_exist(tmp_path, monkeypatch):
    recent_path = tmp_path / "recent_theology_components.json"
    monkeypatch.setattr(config, "RECENT_THEOLOGY_COMPONENTS_PATH", recent_path)
    campaign = {"name": "Anxiety", "pain_point": "feeling anxious", "goal": "reduce anxiety"}
    first = campaign_engine.pick_spiritual_action(campaign, "morning")
    # Force "recent" to contain every candidate except one, so the next
    # pick must avoid duplicates when an alternative is available.
    pools = config.load_theology_actions()
    pool = pools.get("anxiety_actions", [])
    if len(pool) > 1:
        recent_path.write_text(
            __import__("json").dumps({"recent": pool[:-1]}), encoding="utf-8"
        )
        second = campaign_engine.pick_spiritual_action(campaign, "morning")
        assert second == pool[-1]


# ---------- Brand asset fallback ----------

def test_load_brand_asset_returns_none_when_file_missing(tmp_path):
    missing_path = tmp_path / "does_not_exist.png"
    with pytest.warns(UserWarning):
        result = image_renderer.load_brand_asset(missing_path)
    assert result is None


def test_load_brand_asset_loads_existing_png(tmp_path):
    from PIL import Image
    asset_path = tmp_path / "logo.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(asset_path)
    result = image_renderer.load_brand_asset(asset_path)
    assert result is not None
    assert result.size == (10, 10)


def test_config_brand_asset_paths_have_safe_defaults():
    assert config.LOGO_PATH.name == "prayonit_logo.png"
    assert config.APP_STORE_BADGE_PATH.name == "app_store_badge.png"
    assert config.GOOGLE_PLAY_BADGE_PATH.name == "google_play_badge.png"


def test_compose_ad_does_not_crash_with_missing_assets():
    from PIL import Image
    background = Image.new("RGB", (1080, 1350), (30, 30, 30))
    ad_copy = _fake_ad_copy()
    result = image_renderer.compose_ad(background, ad_copy)
    assert result.size == config.CANVAS_SIZE


def test_compose_story_ad_does_not_crash_with_missing_assets():
    from PIL import Image
    background = Image.new("RGB", (1080, 1920), (30, 30, 30))
    ad_copy = _fake_ad_copy()
    result = image_renderer.compose_story_ad(background, ad_copy)
    assert result.size == config.STORY_CANVAS_SIZE


def test_compose_story_ad_with_present_logo_and_badges(tmp_path, monkeypatch):
    from PIL import Image
    logo_path = tmp_path / "logo.png"
    app_badge_path = tmp_path / "app.png"
    play_badge_path = tmp_path / "play.png"
    Image.new("RGBA", (100, 40), (255, 255, 255, 255)).save(logo_path)
    Image.new("RGBA", (200, 60), (255, 255, 255, 255)).save(app_badge_path)
    Image.new("RGBA", (200, 60), (255, 255, 255, 255)).save(play_badge_path)
    monkeypatch.setattr(config, "LOGO_PATH", logo_path)
    monkeypatch.setattr(config, "APP_STORE_BADGE_PATH", app_badge_path)
    monkeypatch.setattr(config, "GOOGLE_PLAY_BADGE_PATH", play_badge_path)

    background = Image.new("RGB", (1080, 1920), (30, 30, 30))
    ad_copy = _fake_ad_copy()
    result = image_renderer.compose_story_ad(background, ad_copy)
    assert result.size == config.STORY_CANVAS_SIZE


# ---------- Platform-specific Buffer placement ----------

def _capture_buffer_input(service, post_type, link=None):
    from unittest.mock import MagicMock
    payload = {"data": {"createPost": {"post": {"id": "abc"}}}}
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["input"] = json["variables"]["input"]
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return resp

    with patch("buffer_client.requests.post", side_effect=fake_post):
        buffer_client.buffer_create_post(
            channel_id="chan-1", caption="caption", image_url="https://example.com/image.jpg",
            service=service, post_type=post_type, due_at_iso="2026-07-10T13:00:00Z", link=link,
        )
    return captured["input"]


def test_instagram_metadata_contains_link():
    input_data = _capture_buffer_input("instagram", "post", link="https://example.com/download?t=ig1")
    assert input_data["metadata"]["instagram"]["link"] == "https://example.com/download?t=ig1"


def test_instagram_caption_contains_no_raw_url_v2():
    selection = _fake_selection()
    ad_copy = _fake_ad_copy()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_threads_keeps_url_and_location_metadata(monkeypatch):
    monkeypatch.setattr(config, "THREADS_LOCATION_NAME", "United States of America")
    monkeypatch.setattr(config, "THREADS_LOCATION_ID", "12345")
    selection = _fake_selection()
    ad_copy = _fake_ad_copy()
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert urls["threads"] in captions["threads"]

    input_data = _capture_buffer_input("threads", "post")
    assert input_data["metadata"]["threads"]["locationName"] == "United States of America"
    assert input_data["metadata"]["threads"]["locationId"] == "12345"


def test_facebook_remains_unchanged_by_v2_changes():
    input_data = _capture_buffer_input("facebook", "post")
    assert input_data["metadata"]["facebook"] == {"type": "post"}
    selection = _fake_selection()
    ad_copy = _fake_ad_copy()
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert urls["facebook"] in captions["facebook"]


# ---------- Trial wording occurs at most once per caption ----------

def test_every_caption_contains_trial_phrase_at_most_once():
    selection = _fake_selection()
    ad_copy = _fake_ad_copy(
        facebook_caption=(
            "Feeling overwhelmed? Start your 14-day free trial today. "
            "Don't wait, start your 14-day free trial now."
        ),
        threads_caption="Try Prayonit with a 14-day free trial. Start your 14-day free trial today.",
    )
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    for platform in ("facebook", "instagram", "threads"):
        lower = captions[platform].lower()
        assert lower.count("14-day") <= 1 or lower.count("trial") <= 1
