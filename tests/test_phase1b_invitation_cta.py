"""Phase 1B tests: invitation-first CTA messaging ("COME PRAY WITH ME" /
"Come pray with me.") replaces legacy "DOWNLOAD PRAYONIT" / "Download
Prayonit" language across brand config, prompt builder, and QA validation.
"""
import campaign_engine
import config
import creative_engine_v3
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


def _fake_platform_urls():
    return {
        "facebook": "https://prayonit.nextwavestudiosapp.com",
        "instagram": "https://prayonit.nextwavestudiosapp.com",
        "threads": "https://prayonit.nextwavestudiosapp.com",
    }


# ---------- 1. Brand config exposes new CTA fields ----------

def test_brand_config_has_new_cta_fields():
    copy_section = config.BRAND_CONFIG.get("copy", {})
    assert copy_section.get("primary_cta") == "COME PRAY WITH ME"
    assert copy_section.get("facebook_cta") == "Come pray with me."
    assert "Link in bio" in copy_section.get("instagram_cta", "")
    assert copy_section.get("threads_cta") == "Come pray with me."


def test_config_exposes_flattened_cta_constants():
    assert config.PRIMARY_CTA == "COME PRAY WITH ME"
    assert config.FACEBOOK_CTA == "Come pray with me."
    assert config.THREADS_CTA == "Come pray with me."
    assert "Link in bio" in config.INSTAGRAM_CTA
    assert config.STORY_CTA == "COME PRAY WITH ME"


# ---------- 2. Primary visual CTA ----------

def test_enforce_download_cta_returns_invitation_first_phrase():
    assert prompt_builder.enforce_download_cta("anything") == "COME PRAY WITH ME"
    assert prompt_builder.PRIMARY_DOWNLOAD_CTA == "COME PRAY WITH ME"


# ---------- 3. Platform caption content ----------

def test_facebook_caption_contains_invitation_and_website_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["facebook"]
    assert "https://prayonit.nextwavestudiosapp.com" in captions["facebook"]


def test_instagram_caption_contains_invitation_and_link_in_bio_no_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["instagram"]
    assert "Link in bio" in captions["instagram"]
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_threads_caption_contains_invitation_and_website_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
        "threads_caption": "Some threads body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["threads"]
    assert "https://prayonit.nextwavestudiosapp.com" in captions["threads"]


def test_no_caption_contains_legacy_download_prayonit_phrase():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Download Prayonit today and feel the difference.",
        "instagram_caption": "Install Prayonit now, don't wait.",
        "threads_caption": "Get the app and try it out.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    for text in captions.values():
        lower = text.lower()
        assert "download prayonit" not in lower


# ---------- 4. TEST_MODE fallback uses invitation-first wording ----------

def test_generate_local_ad_copy_uses_invitation_first_cta():
    selection = _fake_selection()
    ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot="morning")
    assert ad_copy["download_cta"] == "COME PRAY WITH ME"
    assert ad_copy["story_download_cta"] == "COME PRAY WITH ME"
    assert "download prayonit" not in ad_copy["facebook_caption"].lower()


# ---------- 5. QA accepts new CTA / rejects legacy download phrases ----------

def _qa_kwargs(captions):
    return dict(
        campaign_name="anger",
        slot="morning",
        background_path="fake.jpg",
        territory="anger",
        background_meta={},
        contrast_metrics={"overall_pass": True},
        has_badges=True,
        recent_headlines=[],
        ad_copy={"pain_headline": "Feeling anxious tonight?"},
        captions=captions,
    )


def test_qa_accepts_new_invitation_cta():
    captions = {
        "facebook": "Come pray with me.\nhttps://prayonit.nextwavestudiosapp.com",
        "instagram": "Come pray with me.\nLink in bio.",
        "threads": "Come pray with me.\nhttps://prayonit.nextwavestudiosapp.com",
    }
    report = creative_engine_v3.build_prepublish_qa_report(**_qa_kwargs(captions))
    assert "legacy_download_cta_facebook" not in report["critical_failures"]
    assert "legacy_download_cta_instagram" not in report["critical_failures"]
    assert "legacy_download_cta_threads" not in report["critical_failures"]


def test_qa_rejects_legacy_download_cta_phrases():
    captions = {
        "facebook": "Download Prayonit today and start your journey.",
        "instagram": "Install Prayonit now for free.",
        "threads": "Get the app right now.",
    }
    report = creative_engine_v3.build_prepublish_qa_report(**_qa_kwargs(captions))
    assert "legacy_download_cta_facebook" in report["critical_failures"]
    assert "legacy_download_cta_instagram" in report["critical_failures"]
    assert "legacy_download_cta_threads" in report["critical_failures"]
    assert report["pass"] is False
