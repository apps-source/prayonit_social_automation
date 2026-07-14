from PIL import Image

import config
import image_renderer


def _white_contrast_pass(image, box):
    bg_l = image_renderer._estimate_region_luminance(image, box)
    white_l = image_renderer._relative_luminance(255, 255, 255)
    return image_renderer._contrast_ratio(white_l, bg_l) >= image_renderer.CONTRAST_MIN_RATIO_WHITE


def _copy_feed():
    return {
        "brand_header": "PRAYONIT",
        "pain_headline": "Struggling to Pray?",
        "spiritual_action": "Bring your worries to God in prayer.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
    }


def _copy_story():
    return {
        "brand_header": "PRAYONIT",
        "story_headline": "Struggling to Pray?",
        "story_spiritual_action": "Bring your worries to God in prayer.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_feed_overlays_are_localized_and_non_overlapping():
    # Bright background exercises maximum contrast treatment path.
    bg = Image.new("RGB", config.CANVAS_SIZE, (246, 246, 246))
    img = image_renderer.compose_ad(bg, _copy_feed())
    overlays = img.info.get("overlay_rects", [])

    assert overlays, "Expected localized overlays to be recorded on bright backgrounds"
    # No giant zone-spanning panels should be produced.
    assert all(item["area_ratio"] <= 0.07 for item in overlays)
    assert all((item["box"][2] - item["box"][0]) < 760 for item in overlays)

    boxes = [tuple(item["box"]) for item in overlays]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _overlap(boxes[i], boxes[j]), "Overlay rectangles must not overlap"


def test_feed_benefit_panel_compact_and_cta_unchanged_dark_button():
    bg = Image.new("RGB", config.CANVAS_SIZE, (246, 246, 246))
    img = image_renderer.compose_ad(bg, _copy_feed())
    dbg = img.info.get("layout_debug", {})
    benefit = dbg.get("benefit_panel_rect")
    cta = dbg.get("cta_rect")

    assert benefit is not None
    assert cta is not None

    # Compact approved feed benefit panel geometry.
    benefit_w = benefit[2] - benefit[0]
    benefit_h = benefit[3] - benefit[1]
    assert benefit_w == config.CANVAS_SIZE[0] - 200
    assert benefit_h <= 190

    # CTA button remains dark and visually unchanged in treatment intent.
    cta_x = int((cta[0] + cta[2]) / 2)
    cta_y = int((cta[1] + cta[3]) / 2)
    px = img.convert("RGB").getpixel((cta_x, cta_y))
    assert px[0] < 90 and px[1] < 90 and px[2] < 110


def test_story_no_large_multiregion_panels_and_cta_dark():
    bg = Image.new("RGB", config.STORY_CANVAS_SIZE, (247, 247, 247))
    img = image_renderer.compose_story_ad(bg, _copy_story())
    overlays = img.info.get("overlay_rects", [])

    # Story should avoid giant section-spanning overlays.
    assert all(item["area_ratio"] <= 0.06 for item in overlays)
    assert all((item["box"][2] - item["box"][0]) <= 860 for item in overlays)
    assert all((item["box"][3] - item["box"][1]) <= 260 for item in overlays)

    boxes = [tuple(item["box"]) for item in overlays]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not _overlap(boxes[i], boxes[j]), "Overlay rectangles must not overlap"

    dbg = img.info.get("layout_debug", {})
    cta = dbg.get("cta_rect")
    assert cta is not None
    cta_x = int((cta[0] + cta[2]) / 2)
    cta_y = int((cta[1] + cta[3]) / 2)
    px = img.convert("RGB").getpixel((cta_x, cta_y))
    assert px[0] < 90 and px[1] < 90 and px[2] < 110


def test_bright_background_text_contrast_remains_passing():
    # Verify text-local contrast on rendered result (post treatment) remains passing.
    feed_bg = Image.new("RGB", config.CANVAS_SIZE, (246, 246, 246))
    feed_img = image_renderer.compose_ad(feed_bg, _copy_feed())
    feed_metrics = image_renderer.compute_local_contrast_metrics(feed_img, "feed")
    feed_overlays = feed_img.info.get("overlay_rects", [])
    feed_headline_box = next((tuple(item["box"]) for item in feed_overlays if item.get("zone") == "headline"), None)
    feed_dbg = feed_img.info.get("layout_debug", {})
    feed_cta = feed_dbg.get("cta_rect")
    assert feed_cta is not None
    if feed_headline_box is not None:
        assert _white_contrast_pass(feed_img, feed_headline_box)
    else:
        assert feed_metrics["zones"]["headline"]["white_pass"] is True
    assert _white_contrast_pass(feed_img, feed_cta)

    story_bg = Image.new("RGB", config.STORY_CANVAS_SIZE, (246, 246, 246))
    story_img = image_renderer.compose_story_ad(story_bg, _copy_story())
    story_metrics = image_renderer.compute_local_contrast_metrics(story_img, "story")
    story_overlays = story_img.info.get("overlay_rects", [])
    story_headline_box = next((tuple(item["box"]) for item in story_overlays if item.get("zone") == "headline"), None)
    story_dbg = story_img.info.get("layout_debug", {})
    story_cta = story_dbg.get("cta_rect")
    assert story_cta is not None
    if story_headline_box is not None:
        assert _white_contrast_pass(story_img, story_headline_box)
    else:
        assert story_metrics["zones"]["headline"]["white_pass"] is True
    assert _white_contrast_pass(story_img, story_cta)
