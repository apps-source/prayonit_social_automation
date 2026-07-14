"""Feed-only visual regression tests.

These tests guard against regressions like the one fixed in this change:
duplicate/misplaced draw calls or coordinate overrides that corrupted the
Feed vertical layout (logo size, wordmark position, headline overlap).

Story rendering is intentionally not touched or tested here.
"""
import image_renderer
import prompt_builder
import campaign_engine


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


def _render_feed():
    sel = _fake_selection()
    ad = prompt_builder.generate_local_ad_copy(selection=sel, slot="morning")
    ad["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    ad["story_app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT
    bg = image_renderer._synthetic_background_image("valley", image_renderer.config.CANVAS_SIZE)
    return image_renderer.compose_ad(bg, ad), ad


def test_feed_logo_size_matches_approved_scale():
    feed, _ = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    logo_box = elem["wordmark"]["box"]
    # Wordmark text box height should be small (a text line), not a huge
    # graphic-sized box. This guards against the regression where the logo
    # target height ballooned to ~215px via layout-metric misuse.
    logo_height = logo_box[3] - logo_box[1]
    assert logo_height < 80, f"Feed logo/wordmark box unexpectedly large: {logo_height}px"


def test_feed_element_vertical_order_and_no_overlap():
    feed, _ = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    layout = feed.info["layout_debug"]

    logo_box = elem["wordmark"]["box"]
    headline_box = elem["headline"]["box"]
    action_box = elem["spiritual_action"]["box"]
    benefit_box = elem["benefit"]["box"]
    cta_box = elem["cta"]["box"]
    trial_box = elem["trial"]["box"]

    # Each element key maps to exactly one box (a duplicate/misplaced draw
    # regression would corrupt spacing enough to break this strict
    # top-to-bottom ordering).
    assert logo_box[3] <= headline_box[1], "Headline overlaps logo/wordmark"
    assert headline_box[3] <= action_box[1], "Spiritual action overlaps headline"
    assert action_box[3] <= benefit_box[1], "Benefit overlaps spiritual action"
    assert benefit_box[3] <= cta_box[1], "CTA overlaps benefit panel"
    assert cta_box[3] <= trial_box[1], "Trial overlaps CTA"

    # layout_debug cta_rect should be consistent with the element cta box
    # (same button, single source of truth, not drawn twice with different
    # coordinates).
    cta_rect = layout["cta_rect"]
    assert abs(cta_box[0] - cta_rect[0]) < 5
    assert abs(cta_box[2] - cta_rect[2]) < 5


def test_feed_no_background_rectangle_behind_trial_text():
    feed, _ = _render_feed()
    trial_box = feed.info["element_contrast_metrics"]["feed"]["trial"]["box"]
    overlays = feed.info.get("overlay_rects", [])
    for rec in overlays:
        ob = tuple(rec["box"])
        overlaps = not (ob[2] <= trial_box[0] or ob[0] >= trial_box[2] or ob[3] <= trial_box[1] or ob[1] >= trial_box[3])
        assert not overlaps, "A localized overlay rectangle was drawn behind the Feed trial text"


def test_feed_elements_within_safe_zones():
    feed, _ = _render_feed()
    elem = feed.info["element_contrast_metrics"]["feed"]
    width, height = image_renderer.config.CANVAS_SIZE
    for name, data in elem.items():
        if name == "overall_pass":
            continue
        box = data["box"]
        assert box[0] >= 0 and box[2] <= width, f"{name} box exceeds horizontal canvas bounds: {box}"
        assert box[1] >= 0, f"{name} box above canvas top: {box}"
        assert box[3] <= height, f"{name} box below canvas bottom: {box}"
