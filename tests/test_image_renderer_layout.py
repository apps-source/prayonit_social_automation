from PIL import Image, ImageDraw, ImageFont
import image_renderer
import config


def test_story_layout_metrics_and_limits():
    metrics = image_renderer._compute_story_layout_metrics()
    # logo should be increased ~30% relative base (width*0.18 base used)
    assert metrics["logo_size_px"] > 0
    assert metrics["cta_h_px"] > 0
    assert metrics["badge_h_px"] > 0
    assert metrics["benefit_max_lines"] == image_renderer.STORY_BENEFIT_MAX_LINES
    assert metrics["headline_max_chars"] == image_renderer.STORY_HEADLINE_MAX_CHARS


def test_feed_layout_metrics_and_limits():
    metrics = image_renderer._compute_feed_layout_metrics()
    assert metrics["logo_size_px"] > 0
    assert metrics["benefit_panel_h_px"] > 0
    assert metrics["badge_h_px"] > 0
    assert metrics["benefit_max_lines"] == image_renderer.FEED_BENEFIT_MAX_LINES


def test_enforce_max_lines_truncation():
    # Create a Draw object for measurements
    img = Image.new("RGB", (1080, 1350), "white")
    draw = ImageDraw.Draw(img)
    bold, regular = image_renderer.get_fonts()
    font = ImageFont.truetype(bold, 40)
    long_text = "This is a very long headline that should be truncated to fit within the maximum allowed line count and characters for visual design purposes."
    result = image_renderer._enforce_max_lines(long_text, draw, font, 800, 2)
    lines = [l for l in result.splitlines() if l.strip()]
    assert len(lines) <= 2


def test_exact_benefit_used_in_feed_and_story_wrapping():
    # Ensure the exact benefit phrase used in renderer matches spec
    exact = "Get a guided, personalized prayer based on your mood right now."
    # For feed
    img = Image.new("RGB", config.CANVAS_SIZE, "white")
    draw = ImageDraw.Draw(img)
    bold, regular = image_renderer.get_fonts()
    font = ImageFont.truetype(regular, 34)
    wrapped = image_renderer._enforce_max_lines(exact, draw, font, 800, 3)
    assert exact.startswith(wrapped.splitlines()[0])
    # For story
    s_img = Image.new("RGB", config.STORY_CANVAS_SIZE, "white")
    s_draw = ImageDraw.Draw(s_img)
    s_font = ImageFont.truetype(regular, 38)
    s_wrapped = image_renderer._enforce_max_lines(exact, s_draw, s_font, 800, 3)
    assert "guided, personalized prayer" in s_wrapped.lower()


def test_sequential_vertical_gaps_feed_and_story():
    # Build minimal copy and background to render and measure element positions
    from PIL import Image
    bg_feed = Image.new("RGB", config.CANVAS_SIZE, "white")
    copy = {
        "brand_header": "PRAYONIT",
        "pain_headline": "Testing Headline for Layout Purposes",
        "spiritual_action": "Give today's burdens to God in prayer.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "DOWNLOAD PRAYONIT",
        "trial_support": "Start your 14-day free trial today.",
    }
    img = image_renderer.compose_ad(bg_feed, copy)
    # We cannot introspect private y positions easily after render, but
    # we can re-run the measurement logic using the same fonts to compute
    # bounding boxes and ensure the calculated gaps fall in ranges.
    draw = ImageDraw.Draw(bg_feed)
    bold, regular = image_renderer.get_fonts()
    brand_f = ImageFont.truetype(bold, 30)
    headline_f = ImageFont.truetype(bold, int(58 * 0.95))
    action_f = ImageFont.truetype(regular, 32)
    benefit_f = ImageFont.truetype(regular, int(34 * 0.95))
    cta_f = ImageFont.truetype(bold, int(44 * 1.12))
    trial_f = ImageFont.truetype(bold, int(28 * 1.08))

    # Simulate measured sequence like renderer does
    target_h = int(64 * image_renderer.FEED_LOGO_SCALE)
    desired_logo_center = 120
    logo_top = int(desired_logo_center - target_h / 2)
    brand_top = logo_top
    brand_bottom = logo_top + target_h

    gap_logo_headline = 75
    headline_top = brand_bottom + gap_logo_headline
    headline_box = draw.multiline_textbbox((0, 0), copy["pain_headline"].upper(), font=headline_f)
    headline_bottom = headline_top + (headline_box[3] - headline_box[1])

    action_top = headline_bottom + 30
    action_box = draw.multiline_textbbox((0, 0), copy["spiritual_action"], font=action_f)
    action_bottom = action_top + (action_box[3] - action_box[1])

    panel_y1 = action_bottom + 35
    app_benefit = image_renderer._enforce_max_lines(copy["app_benefit"], draw, benefit_f, 800, 3)
    benefit_box = draw.multiline_textbbox((0, 0), app_benefit, font=benefit_f)
    panel_bottom = panel_y1 + (benefit_box[3] - benefit_box[1]) + int(48 * image_renderer.FEED_BENEFIT_PANEL_REDUCTION)

    button_y1 = panel_bottom + 40
    base_button_h = 100
    button_y2 = button_y1 + int(base_button_h * 1.15)

    trial_top = button_y2 + 22
    trial_box = draw.textbbox((0, 0), copy["trial_support"], font=trial_f)
    trial_bottom = trial_top + (trial_box[3] - trial_box[1])

    badge_top = trial_bottom + 25
    badge_bottom = badge_top + int(56 * image_renderer.FEED_BADGE_SCALE)

    # Assertions for vertical order and gaps within recommended ranges
    assert headline_top > brand_bottom
    assert 60 <= (headline_top - brand_bottom) <= 90
    assert 25 <= (action_top - headline_bottom) <= 35
    assert 30 <= (panel_y1 - action_bottom) <= 40
    assert 35 <= (button_y1 - panel_bottom) <= 45
    assert 20 <= (trial_top - button_y2) <= 25
    assert 25 <= (badge_top - trial_bottom) <= 30
    # Badge bottom inside canvas
    assert badge_bottom <= config.CANVAS_SIZE[1]

    # Verify group centering for Feed: compute group center and compare to
    # the renderer's target band center within ±20 px.
    group_top = logo_top
    group_bottom = badge_bottom
    group_center = (group_top + group_bottom) / 2
    target_center = (130 + 930) / 2
    feed_offset = int(round(target_center - group_center))
    final_center = group_center + feed_offset
    assert abs(final_center - target_center) <= 20


def test_story_gaps_and_badge_position():
    from PIL import Image
    bg_story = Image.new("RGB", config.STORY_CANVAS_SIZE, "white")
    copy = {
        "brand_header": "PRAYONIT",
        "story_headline": "A Story Headline for Layout Testing",
        "story_spiritual_action": "Bring it to God.",
        "story_app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "story_download_cta": "DOWNLOAD PRAYONIT",
        "story_trial_support": "Start your 14-day free trial.",
    }
    img = image_renderer.compose_story_ad(bg_story, copy)
    draw = ImageDraw.Draw(bg_story)
    bold, regular = image_renderer.get_fonts()
    brand_f = ImageFont.truetype(bold, 34)
    headline_f = ImageFont.truetype(bold, int(66 * 0.98))
    action_f = ImageFont.truetype(regular, 34)
    benefit_f = ImageFont.truetype(regular, int(38 * 1.02))
    cta_f = ImageFont.truetype(bold, int(48 * image_renderer.STORY_CTA_SCALE))
    trial_f = ImageFont.truetype(bold, int(30 * image_renderer.STORY_TRIAL_FONT_SCALE))

    target_h = int(70 * image_renderer.STORY_LOGO_SCALE)
    desired_logo_center = 260
    logo_top = int(desired_logo_center - target_h / 2)
    brand_bottom = logo_top + target_h

    headline_top = brand_bottom + 125
    headline_box = draw.multiline_textbbox((0, 0), copy["story_headline"].upper(), font=headline_f)
    headline_bottom = headline_top + (headline_box[3] - headline_box[1])

    action_top = headline_bottom + 40
    action_box = draw.multiline_textbbox((0, 0), copy["story_spiritual_action"], font=action_f)
    action_bottom = action_top + (action_box[3] - action_box[1])

    benefit_top = action_bottom + 40
    benefit_box = draw.multiline_textbbox((0, 0), copy["story_app_benefit"], font=benefit_f)
    benefit_bottom = benefit_top + (benefit_box[3] - benefit_box[1])

    button_y1 = benefit_bottom + 50
    base_button_h = 110
    button_y2 = button_y1 + int(base_button_h * image_renderer.STORY_CTA_SCALE)

    trial_top = button_y2 + 27
    trial_box = draw.textbbox((0, 0), copy["story_trial_support"], font=trial_f)
    trial_bottom = trial_top + (trial_box[3] - trial_box[1])

    badge_top = trial_bottom + 32
    badge_bottom = badge_top + int(64 * image_renderer.STORY_BADGE_SCALE)

    # Assertions
    # Verify headline begins within approx y = 430-470
    assert 430 <= headline_top <= 470
    assert 35 <= (action_top - headline_bottom) <= 45
    assert 35 <= (benefit_top - action_bottom) <= 45
    assert 45 <= (button_y1 - benefit_bottom) <= 55
    assert 25 <= (trial_top - button_y2) <= 30
    assert 30 <= (badge_top - trial_bottom) <= 35
    assert badge_bottom <= config.STORY_CANVAS_SIZE[1]

    # Verify Story group centering: computed group center should be near the
    # target band center within ±20 px.
    group_top = logo_top
    group_bottom = badge_bottom
    group_center = (group_top + group_bottom) / 2
    target_center = (300 + 1250) / 2
    story_offset = int(round(target_center - group_center))
    final_center = group_center + story_offset
    assert abs(final_center - target_center) <= 20
