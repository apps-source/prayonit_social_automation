"""Tests for prompt_builder.py: prompt construction and platform caption rules.
Gemini is fully mocked; no live network calls occur.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import campaign_engine
import config
import history_store
import prompt_builder


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


def test_build_prompt_forbids_invented_urls_and_includes_slot_guidance():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="evening",
        tracked_url="https://prayonit.example.com/download?t=abc123",
    )
    assert "do not include any url" in prompt.lower()
    assert "prayonit.com" in prompt.lower()  # named explicitly as a forbidden invented domain
    assert "tonight" in prompt.lower()
    assert "start your day" in prompt.lower()  # appears in the "never say" instruction


def test_generate_ad_copy_parses_valid_json(monkeypatch):
    selection = _fake_selection()
    fake_response = SimpleNamespace(text=(
        '{"brand_header": "PRAYONIT", "pain_headline": "Feeling anxious tonight?", '
        '"spiritual_action": "Give today\'s burdens to God in prayer.", '
        '"app_benefit": "Get a guided, personalized prayer to help you bring your worries to God.", '
        '"download_cta": "Download Prayonit now.", '
        '"trial_support": "Start your 14-day free trial today.", '
        '"facebook_caption": "Test facebook caption with link https://x.test/download?t=abc", '
        '"instagram_caption": "Test instagram caption https://x.test/download?t=abc", '
        '"threads_caption": "Test threads caption https://x.test/download?t=abc", '
        '"story_headline": "Feeling Anxious?", "story_spiritual_action": "Bring it to God.", '
        '"story_app_benefit": "A guided prayer for how you feel.", '
        '"story_download_cta": "Download Now", '
        '"story_trial_support": "Start your 14-day trial."}'
    ))
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        ad_copy = prompt_builder.generate_ad_copy(
            post_type="download-focused evening ad",
            selection=selection,
            slot="evening",
            tracked_url="https://x.test/download?t=abc",
        )

    assert ad_copy["brand_header"] == "PRAYONIT"
    assert "story_trial_support" in ad_copy
    # download_cta must always be forced to the exact required invitation-first CTA.
    assert ad_copy["download_cta"] == config.PRIMARY_CTA
    assert ad_copy["story_download_cta"] == config.PRIMARY_CTA


def test_generate_ad_copy_raises_on_missing_key(monkeypatch):
    selection = _fake_selection()
    fake_response = SimpleNamespace(text='{"brand_header": "PRAYONIT"}')
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = fake_response

    with patch.object(prompt_builder, "_get_gemini_client", return_value=mock_client):
        try:
            prompt_builder.generate_ad_copy(
                post_type="x", selection=selection, slot="morning", tracked_url="https://x.test/d"
            )
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


def _fake_platform_urls():
    return {
        "facebook": "https://example.com/download?t=fb1",
        "instagram": "https://example.com/download?t=ig1",
        "threads": "https://example.com/download?t=th1",
    }


def test_facebook_caption_has_no_hashtags():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Plain facebook caption with no tags.",
        "instagram_caption": "Instagram caption base text.",
        "threads_caption": "Threads caption base text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "#" not in captions["facebook"]


def test_instagram_caption_has_5_to_8_hashtags_including_prayonit():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb",
        "instagram_caption": "ig base",
        "threads_caption": "th base",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert 5 <= len(hashtags) <= 8
    assert "#Prayonit" in hashtags


def test_threads_caption_has_at_most_2_hashtags_including_prayonit():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "fb",
        "instagram_caption": "ig base",
        "threads_caption": "th base",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["threads"].split() if w.startswith("#")]
    assert 1 <= len(hashtags) <= 2
    assert "#Prayonit" in hashtags


def test_gemini_invented_urls_are_stripped_from_all_captions():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Check it out at https://prayonit.com/download right now!",
        "instagram_caption": "Get it here: https://prayonit.com/download",
        "threads_caption": "Try it: https://prayonit.com/download today",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert "prayonit.com" not in captions["facebook"]
    assert "prayonit.com" not in captions["instagram"]
    assert "prayonit.com" not in captions["threads"]


def test_exact_configured_url_is_appended_per_platform():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert urls["facebook"] in captions["facebook"]
    # Instagram feed captions never include a raw URL (not clickable on
    # Instagram); the same URL is instead placed in Buffer's
    # metadata.instagram.link. See test_buffer_client.py.
    assert urls["instagram"] not in captions["instagram"]
    assert urls["threads"] in captions["threads"]


def test_tracking_disabled_all_captions_use_same_destination_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    destination = "https://example.com/app"
    urls = {"facebook": destination, "instagram": destination, "threads": destination}
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert destination in captions["facebook"]
    assert destination not in captions["instagram"]
    assert destination in captions["threads"]


def test_tracking_enabled_each_platform_uses_distinct_tracked_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert captions["facebook"].count(urls["facebook"]) == 1
    assert urls["instagram"] not in captions["facebook"]
    assert urls["threads"] not in captions["facebook"]
    assert urls["facebook"] not in captions["instagram"]


# ---------- Brand Brain enforcement tests ----------

def test_prompt_always_injects_brand_brain():
    selection = _fake_selection()
    prompt = prompt_builder.build_prompt(
        post_type="download-focused morning ad",
        selection=selection,
        slot="morning",
        tracked_url="https://x.test/download?t=abc",
    )
    assert "You MUST follow every rule contained in brand_rules.json." in prompt
    assert config.BRAND_RULES["preferred_cta"] in prompt
    assert "Never invent features." in prompt
    assert "Never invent pricing." in prompt
    assert "Never invent URLs." in prompt


def test_enforce_cta_replaces_invalid_cta():
    result = prompt_builder.enforce_cta("Buy now for $9.99!", config.BRAND_RULES)
    assert result == config.BRAND_RULES["preferred_cta"]


def test_enforce_cta_keeps_approved_cta_unchanged():
    approved = config.BRAND_RULES["approved_ctas"][1]
    result = prompt_builder.enforce_cta(approved, config.BRAND_RULES)
    assert result == approved


def test_enforce_forbidden_phrases_replaces_never_say_terms():
    text = "Prayonit is a free app you can use forever, 100% free!"
    result = prompt_builder.enforce_forbidden_phrases(text, config.BRAND_RULES)
    assert "free app" not in result.lower()
    assert "100% free" not in result.lower()
    assert config.BRAND_RULES["preferred_cta"] in result


def test_enforce_feature_claims_removes_nonexistent_feature_sentences():
    text = "Prayonit gives you a personalized prayer. You can also join our community forum."
    result = prompt_builder.enforce_feature_claims(text, config.BRAND_RULES)
    assert "community forum" not in result.lower()
    assert "personalized prayer" in result.lower()


def test_enforce_feature_claims_keeps_known_core_features():
    text = "Prayonit offers a prayer journal and a 14-day free trial."
    result = prompt_builder.enforce_feature_claims(text, config.BRAND_RULES)
    assert "prayer journal" in result.lower()


def test_apply_brand_enforcement_fixes_cta_and_phrases_together():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Bring it to God.",
        "cta": "Buy now, it's 100% free forever!",
        "facebook_caption": "This app is completely free forever, join our community forum today.",
        "instagram_caption": "Free app, no strings attached.",
        "threads_caption": "Totally free forever, try it now.",
        "story_headline": "Feeling Anxious?",
        "story_cta": "Pray Now",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert enforced["cta"] == config.BRAND_RULES["preferred_cta"]
    assert "free forever" not in enforced["facebook_caption"].lower()
    assert "community forum" not in enforced["facebook_caption"].lower()
    assert "free app" not in enforced["instagram_caption"].lower()
    assert "free forever" not in enforced["threads_caption"].lower()


# ---------- Issue 2: free-trial wording enforcement ----------

def test_story_cta_try_it_free_today_is_replaced_with_compact_14_day_phrase():
    result = prompt_builder.enforce_story_cta_trial_wording("Try it free today.", config.BRAND_RULES)
    assert result == config.BRAND_RULES["compact_trial_phrase"]
    assert "14-day" in result.lower()


def test_story_cta_missing_14_day_duration_is_replaced():
    result = prompt_builder.enforce_story_cta_trial_wording("Start your free trial.", config.BRAND_RULES)
    assert "14-day" in result.lower()
    assert result == config.BRAND_RULES["compact_trial_phrase"]


def test_story_cta_with_14_day_duration_is_left_unchanged():
    compact = config.BRAND_RULES["compact_trial_phrase"]
    result = prompt_builder.enforce_story_cta_trial_wording(compact, config.BRAND_RULES)
    assert result == compact


def test_facebook_caption_free_trial_without_duration_is_replaced():
    text = "Download Prayonit and try Prayonit free right now, no strings attached."
    result = prompt_builder.enforce_trial_duration(text, config.BRAND_RULES)
    assert "14-day" in result.lower()
    assert result == config.BRAND_RULES["preferred_cta"]


def test_all_free_trial_language_across_fields_includes_14_day_limit():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Bring it to God.",
        "cta": "Try it free today.",
        "facebook_caption": "Download for free and try Prayonit free right now.",
        "instagram_caption": "Download for free today, no catch.",
        "threads_caption": "Try it free today, seriously.",
        "story_headline": "Feeling Anxious?",
        "story_cta": "Try it free today",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    for field in ("cta", "facebook_caption", "instagram_caption", "threads_caption", "story_cta"):
        text_lower = enforced[field].lower()
        if "trial" in text_lower or "free" in text_lower:
            assert "14-day" in text_lower or "14 day" in text_lower


def test_personalized_scripture_phrase_remains_allowed_and_unchanged():
    ad_copy = {
        "header": "Peace",
        "headline": "Feeling anxious?",
        "body": "Receive personalized Scripture and a devotion today.",
        "cta": config.BRAND_RULES["preferred_cta"],
        "facebook_caption": "Prayonit gives you personalized Scripture, a devotion, and a guided prayer.",
        "instagram_caption": "Get personalized Scripture in seconds.",
        "threads_caption": "Personalized Scripture for how you feel today.",
        "story_headline": "Personalized Scripture",
        "story_cta": "Pray Now",
    }
    enforced = prompt_builder.apply_brand_enforcement(ad_copy, config.BRAND_RULES)
    assert "personalized scripture" in enforced["body"].lower()
    assert "personalized scripture" in enforced["facebook_caption"].lower()
    assert "personalized scripture" in enforced["instagram_caption"].lower()
    assert "personalized scripture" in enforced["threads_caption"].lower()
    assert enforced["story_headline"] == "Personalized Scripture"


# ---------- Buffer metadata placement: Instagram/Threads (this change) ----------

def test_instagram_caption_contains_no_raw_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_instagram_caption_ends_naturally_with_trial_cta_and_keeps_hashtags():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Start your 14-day free trial." in captions["instagram"]
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert "#Prayonit" in hashtags
    assert len(hashtags) >= 1


def test_threads_caption_still_contains_its_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert urls["threads"] in captions["threads"]


# ---------- Duplicate Instagram trial-CTA fix (this change) ----------

@pytest.mark.parametrize(
    "duplicate_phrase",
    [
        "Get Prayonit today and start your 14-day free trial.",
        "Start your 14-day free trial.",
        "Begin your 14-day free trial today!",
        "Try Prayonit with a 14-day free trial.",
        "Don't wait, start your 14 day free trial now.",
    ],
)
def test_instagram_cta_appears_exactly_once_despite_gemini_duplicate_wording(duplicate_phrase):
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": f"Feeling overwhelmed? Prayonit can help. {duplicate_phrase}",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    count = captions["instagram"].lower().count("start your 14-day free trial.")
    assert count == 1


def test_instagram_caption_hashtags_preserved_after_dedup():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Feeling overwhelmed? Get Prayonit today and start your 14-day free trial.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    hashtags = [w for w in captions["instagram"].split() if w.startswith("#")]
    assert "#Prayonit" in hashtags
    assert len(hashtags) >= 1


def test_instagram_caption_no_url_after_dedup():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Feeling overwhelmed? Get Prayonit today and start your 14-day free trial.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_facebook_and_threads_unaffected_by_instagram_dedup_fix():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Get Prayonit today and start your 14-day free trial.",
        "instagram_caption": "Get Prayonit today and start your 14-day free trial.",
        "threads_caption": "Get Prayonit today and start your 14-day free trial.",
    }
    urls = _fake_platform_urls()
    captions = prompt_builder.build_platform_captions(ad_copy, selection, urls)
    assert "get prayonit today and start your 14-day free trial" in captions["facebook"].lower()
    assert urls["facebook"] in captions["facebook"]
    assert "get prayonit today and start your 14-day free trial" in captions["threads"].lower()
    assert urls["threads"] in captions["threads"]
