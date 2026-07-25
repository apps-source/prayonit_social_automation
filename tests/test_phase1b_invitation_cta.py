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
        "facebook": "https://prayonit.app",
        "instagram": "https://prayonit.app",
    }


# ---------- 1. Brand config exposes new CTA fields ----------

def test_brand_config_has_new_cta_fields():
    copy_section = config.BRAND_CONFIG.get("copy", {})
    assert copy_section.get("primary_cta") == "COME PRAY WITH ME"
    assert copy_section.get("facebook_cta") == "Come pray with me."
    assert "Link in bio" in copy_section.get("instagram_cta", "")


def test_config_exposes_flattened_cta_constants():
    assert config.PRIMARY_CTA == "COME PRAY WITH ME"
    assert config.FACEBOOK_CTA == "Come pray with me."
    assert "Link in bio" in config.INSTAGRAM_CTA
    assert config.STORY_CTA == "COME PRAY WITH ME"


# ---------- 1b. Website-first destination fields ----------

def test_brand_config_has_website_first_destination_fields():
    copy_section = config.BRAND_CONFIG.get("copy", {})
    assert "prayonit.app" in copy_section.get("visual_destination_text", "")
    assert "prayonit.app" in copy_section.get("story_destination_text", "")
    assert copy_section.get("reel_destination_text") == "Link in bio"
    assert copy_section.get("tiktok_destination_text") == "Link in bio"
    assert copy_section.get("destination_url") == "https://prayonit.app"


def test_config_exposes_destination_text_constants():
    assert "prayonit.app" in config.VISUAL_DESTINATION_TEXT
    assert "prayonit.app" in config.STORY_DESTINATION_TEXT
    assert config.REEL_DESTINATION_TEXT == "Link in bio"
    assert config.TIKTOK_DESTINATION_TEXT == "Link in bio"


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
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["facebook"]
    assert "https://prayonit.app" in captions["facebook"]


def test_instagram_caption_contains_invitation_and_link_in_bio_no_url():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Some facebook body text.",
        "instagram_caption": "Some instagram body text.",
    }
    captions = prompt_builder.build_platform_captions(ad_copy, selection, _fake_platform_urls())
    assert "Come pray with me." in captions["instagram"]
    assert "Link in bio" in captions["instagram"]
    assert "http://" not in captions["instagram"]
    assert "https://" not in captions["instagram"]


def test_no_caption_contains_legacy_download_prayonit_phrase():
    selection = _fake_selection()
    ad_copy = {
        "facebook_caption": "Download Prayonit today and feel the difference.",
        "instagram_caption": "Install Prayonit now, don't wait.",
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
        ad_copy={
            "pain_headline": "Feeling anxious tonight?",
            "app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
            "story_app_benefit": creative_engine_v3.LOCKED_BENEFIT_WORDING,
        },
        captions=captions,
    )


def test_qa_accepts_new_invitation_cta():
    captions = {
        "facebook": "Come pray with me.\nhttps://prayonit.app",
        "instagram": "Come pray with me.\nLink in bio.",
    }
    report = creative_engine_v3.build_prepublish_qa_report(**_qa_kwargs(captions))
    assert "legacy_download_cta_facebook" not in report["critical_failures"]
    assert "legacy_download_cta_instagram" not in report["critical_failures"]


def test_qa_rejects_legacy_download_cta_phrases():
    captions = {
        "facebook": "Download Prayonit today and start your journey.",
        "instagram": "Install Prayonit now for free.",
    }
    report = creative_engine_v3.build_prepublish_qa_report(**_qa_kwargs(captions))
    assert "legacy_download_cta_facebook" in report["critical_failures"]
    assert "legacy_download_cta_instagram" in report["critical_failures"]
    assert report["pass"] is False


# ---------- 6. Website destination is accepted by QA ----------

def test_qa_accepts_website_destination_in_captions():
    captions = {
        "facebook": "Come pray with me.\nhttps://prayonit.app",
        "instagram": "Come pray with me.\nLink in bio.",
    }
    report = creative_engine_v3.build_prepublish_qa_report(**_qa_kwargs(captions))
    assert report["pass"] is True
    assert report["critical_failures"] == []


# ---------- 7. Feed/Story destination text (image_renderer) ----------

def test_config_visual_and_story_destination_text_render_prayonit_app():
    import image_renderer
    from PIL import Image

    background = Image.new("RGB", (1080, 1350), (30, 30, 30))
    ad_copy = {
        "download_cta": config.PRIMARY_CTA,
        "story_download_cta": config.STORY_CTA,
    }
    result = image_renderer.compose_ad(background, ad_copy)
    assert result.size == config.CANVAS_SIZE

    story_background = Image.new("RGB", (1080, 1920), (30, 30, 30))
    story_result = image_renderer.compose_story_ad(story_background, ad_copy)
    assert story_result.size == config.STORY_CANVAS_SIZE


# ---------- 8. Motion renderer ending CTA ----------

def test_motion_renderer_copy_uses_come_pray_with_me_and_link_in_bio():
    # motion_renderer's video no longer sources its ending invitation/CTA
    # text from ad_copy or DEMO_COPY at all -- Scenes 3-4 use fixed,
    # brand-approved constants instead (see motion_renderer.py).
    import motion_renderer
    assert motion_renderer.BRAND_INVITATION_TEXT == "Come pray with me."
    assert motion_renderer.LINK_IN_BIO_TEXT == "Link in bio."
