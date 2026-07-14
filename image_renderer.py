"""Feed (1080x1350) and Story (1080x1920) ad image rendering.

Creative Engine v2 message hierarchy: small brand/logo -> pain headline ->
spiritual action -> app benefit -> DOWNLOAD PRAYONIT button -> trial-support
text -> (Story only) official store badges.
"""
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat

import config


# ---------- Safe-zone and layout constants for Creative Engine v2 (visual polish)
# Story canvas (1080 x 1920)
STORY_TOP_SAFE_ZONE = 120
STORY_BOTTOM_SAFE_ZONE = 180
STORY_CONTENT_START_SHIFT_Y = 100  # move full content group downward ~90-120px
STORY_LOGO_SCALE = 1.30            # increase logo size by ~30%
STORY_LOGO_OFFSET_Y = 40           # move logo down ~35-45px
STORY_CTA_SCALE = 1.15             # increase button height/width ~15%
STORY_TRIAL_FONT_SCALE = 1.08      # increase trial font ~8%
STORY_BADGE_SCALE = 1.18           # increase badge heights ~15-20%
STORY_BENEFIT_MAX_LINES = 3
STORY_HEADLINE_MAX_CHARS = 66

# Feed canvas (1080 x 1350)
FEED_TOP_SAFE_ZONE = 60
FEED_BOTTOM_SAFE_ZONE = 60
FEED_LOGO_SCALE = 1.25             # increase logo size ~25%
FEED_BENEFIT_PANEL_REDUCTION = 0.75  # reduce height ~20-25%
FEED_BENEFIT_PANEL_OPACITY = 0.72   # softer translucent fill
FEED_BENEFIT_MAX_LINES = 3
FEED_HEADLINE_MAX_LINES = 3
FEED_HEADLINE_MAX_CHARS = 80       # safe visual enforcement for headline length
FEED_BADGE_SCALE = 1.15


# Locked canonical benefit phrase used in the rendered artwork and by QA
EXACT_BENEFIT_TEXT = "Get a guided, personalized prayer based on your mood right now."

# ---------- Creative Engine V3: deterministic local contrast analysis ----------
CONTRAST_MIN_RATIO_WHITE = 2.6
CONTRAST_MIN_RATIO_GOLD = 2.0


def _relative_luminance(r: float, g: float, b: float) -> float:
    def ch(v: float) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast_ratio(l1: float, l2: float) -> float:
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _estimate_region_luminance(image: Image.Image, box: Tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = box
    x1 = max(0, min(image.width - 1, int(x1)))
    x2 = max(x1 + 1, min(image.width, int(x2)))
    y1 = max(0, min(image.height - 1, int(y1)))
    y2 = max(y1 + 1, min(image.height, int(y2)))
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    mean_r, mean_g, mean_b = ImageStat.Stat(crop).mean
    return _relative_luminance(mean_r, mean_g, mean_b)


def _contrast_regions(canvas_kind: str) -> Dict[str, Tuple[int, int, int, int]]:
    if canvas_kind == "story":
        return {
            "logo": (300, 190, 780, 360),
            "headline": (120, 420, 960, 700),
            "spiritual_action": (140, 700, 940, 860),
            "benefit": (110, 840, 970, 1010),
            "cta_trial_badges": (120, 1010, 960, 1280),
        }
    return {
        "logo": (320, 40, 760, 210),
        "headline": (120, 210, 960, 450),
        "spiritual_action": (140, 440, 940, 560),
        "benefit": (100, 560, 980, 760),
        "cta_trial_badges": (120, 760, 960, 980),
    }


def compute_local_contrast_metrics(base_image: Image.Image, canvas_kind: str) -> Dict[str, Any]:
    """Compute deterministic local contrast metrics and recommended treatment.

    Returns per-zone luminance/contrast plus treatment hints used during draw.
    """
    white_l = _relative_luminance(255, 255, 255)
    gold_l = _relative_luminance(255, 226, 164)
    zones = {}
    all_pass = True
    for zone_name, box in _contrast_regions(canvas_kind).items():
        bg_l = _estimate_region_luminance(base_image, box)
        white_ratio = _contrast_ratio(white_l, bg_l)
        gold_ratio = _contrast_ratio(gold_l, bg_l)
        white_pass = white_ratio >= CONTRAST_MIN_RATIO_WHITE
        gold_pass = gold_ratio >= CONTRAST_MIN_RATIO_GOLD
        all_pass = all_pass and white_pass and gold_pass

        needs_overlay = white_ratio < 2.2 or gold_ratio < 1.8
        zones[zone_name] = {
            "box": box,
            "background_luminance": round(bg_l, 4),
            "white_ratio": round(white_ratio, 3),
            "gold_ratio": round(gold_ratio, 3),
            "white_pass": white_pass,
            "gold_pass": gold_pass,
            "white_stroke_width": 2 if bg_l > 0.30 else 1,
            "gold_stroke_width": 2 if bg_l > 0.34 else 1,
            "white_shadow_alpha": 160 if bg_l > 0.32 else 110,
            "gold_shadow_alpha": 180 if bg_l > 0.32 else 130,
            "overlay_alpha": 72 if needs_overlay else 0,
        }

    return {"canvas_kind": canvas_kind, "zones": zones, "overall_pass": all_pass}


def _apply_local_contrast_overlays(layer: Image.Image, metrics: Dict[str, Any]) -> None:
    draw = ImageDraw.Draw(layer)
    for zone in metrics.get("zones", {}).values():
        alpha = int(zone.get("overlay_alpha", 0))
        if alpha <= 0:
            continue
        x1, y1, x2, y2 = zone["box"]
        draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(0, 0, 0, alpha))


def _boxes_overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _maybe_draw_localized_overlay(
    draw: ImageDraw.ImageDraw,
    *,
    layer_size: Tuple[int, int],
    text_box: Tuple[int, int, int, int],
    requested_alpha: int,
    overlay_records: List[Dict[str, Any]],
    zone_name: str,
    padding_x: int = 20,
    padding_y: int = 14,
    max_area_ratio: float = 0.07,
) -> Optional[Tuple[int, int, int, int]]:
    """Draw a tight, non-overlapping local overlay around text when needed."""
    if requested_alpha <= 0:
        return None

    width, height = layer_size
    x1, y1, x2, y2 = text_box
    rect = (
        max(0, int(x1 - padding_x)),
        max(0, int(y1 - padding_y)),
        min(width, int(x2 + padding_x)),
        min(height, int(y2 + padding_y)),
    )
    rect_w = max(1, rect[2] - rect[0])
    rect_h = max(1, rect[3] - rect[1])
    area_ratio = (rect_w * rect_h) / float(width * height)
    if area_ratio > max_area_ratio:
        return None

    for existing in overlay_records:
        if _boxes_overlap(rect, tuple(existing["box"])):
            return None

    radius = max(8, min(18, int(min(rect_w, rect_h) * 0.22)))
    draw.rounded_rectangle(rect, radius=radius, fill=(0, 0, 0, int(requested_alpha)))
    overlay_records.append({"zone": zone_name, "box": rect, "alpha": int(requested_alpha), "area_ratio": round(area_ratio, 4)})
    return rect


def _shift_overlay_records(records: List[Dict[str, Any]], dy: int) -> List[Dict[str, Any]]:
    shifted: List[Dict[str, Any]] = []
    for item in records:
        x1, y1, x2, y2 = item["box"]
        shifted.append({
            **item,
            "box": (int(x1), int(y1 + dy), int(x2), int(y2 + dy)),
        })
    return shifted


def _synthetic_background_image(tag: str, canvas_size: Tuple[int, int]) -> Image.Image:
    """Generate deterministic local backgrounds for TEST_MODE no-network runs."""
    w, h = canvas_size
    img = Image.new("RGB", (w, h), (18, 28, 45))
    draw = ImageDraw.Draw(img)
    low = tag.lower()

    if "night" in low or "starfield" in low:
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(8 + 24 * t)
            g = int(16 + 36 * t)
            b = int(45 + 60 * t)
            draw.line((0, y, w, y), fill=(r, g, b))
        for i in range(120):
            x = (i * 73) % w
            y = (i * 41) % (h // 2)
            draw.point((x, y), fill=(245, 245, 245))
    elif "sunrise" in low or "morning" in low or "valley" in low:
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(255 - 130 * t)
            g = int(220 - 140 * t)
            b = int(170 - 120 * t)
            draw.line((0, y, w, y), fill=(r, g, b))
    elif "desert" in low or "canyon" in low:
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(230 - 90 * t)
            g = int(170 - 110 * t)
            b = int(120 - 95 * t)
            draw.line((0, y, w, y), fill=(r, g, b))
    else:
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(56 + 70 * t)
            g = int(88 + 58 * t)
            b = int(124 + 52 * t)
            draw.line((0, y, w, y), fill=(r, g, b))
    return img



def public_url(object_path: str) -> str:
    encoded_path = requests.utils.quote(object_path, safe="/")
    return (
        f"{config.SUPABASE_URL}/storage/v1/object/public/"
        f"{config.SUPABASE_BUCKET}/{encoded_path}"
    )


def load_background(object_path: str) -> Image.Image:
    if object_path.startswith("synthetic://"):
        tag = object_path.split("synthetic://", 1)[1]
        return _synthetic_background_image(tag, config.CANVAS_SIZE)
    local_path = Path(object_path)
    if local_path.exists() and local_path.is_file():
        return Image.open(local_path).convert("RGB")
    url = public_url(object_path)
    response = requests.get(url, timeout=45)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def crop_to_canvas(image: Image.Image, canvas_size: Tuple[int, int] = config.CANVAS_SIZE) -> Image.Image:
    target_w, target_h = canvas_size
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        image = image.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        image = image.crop((0, top, src_w, top + new_h))

    return image.resize(canvas_size, Image.Resampling.LANCZOS)


def get_fonts() -> Tuple[str, str]:
    candidates = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ),
    ]
    for bold, regular in candidates:
        if Path(bold).exists() and Path(regular).exists():
            return bold, regular
    raise RuntimeError("Could not find suitable system fonts.")


def load_brand_asset(path: Path) -> Optional[Image.Image]:
    """Load a brand asset (logo or store badge) as an RGBA image.

    Returns None (and logs a warning, never raises) if the file is missing
    or cannot be opened, so callers can fall back to a text-only
    representation and rendering always succeeds. See
    docs/CREATIVE_ENGINE_V2.md for recommended asset requirements.
    """
    try:
        if not path.exists():
            warnings.warn(f"Brand asset not found, using text fallback: {path}")
            return None
        return Image.open(path).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - never let a bad asset crash rendering
        warnings.warn(f"Could not load brand asset {path}: {exc}")
        return None


def paste_scaled(
    canvas: Image.Image,
    asset: Image.Image,
    *,
    center_x: int,
    top_y: int,
    target_height: int,
) -> int:
    """Paste asset onto canvas, scaled to target_height, centered
    horizontally at center_x, top edge at top_y. Returns the asset's
    rendered width (for layout of sibling elements).
    """
    aspect = asset.width / asset.height
    target_width = max(1, int(target_height * aspect))
    resized = asset.resize((target_width, target_height), Image.Resampling.LANCZOS)
    x = int(center_x - target_width / 2)
    canvas.paste(resized, (x, top_y), resized)
    return target_width


def _compute_story_layout_metrics(canvas_size: Tuple[int, int] = (1080, 1920)) -> Dict[str, int]:
    """Return approximate numeric layout metrics for tests to assert visual adjustments."""
    width, height = canvas_size
    logo_base = int(width * 0.18)
    logo_size = int(logo_base * STORY_LOGO_SCALE)
    content_shift = STORY_CONTENT_START_SHIFT_Y
    cta_base_h = int(height * 0.07)
    cta_h = int(cta_base_h * STORY_CTA_SCALE)
    cta_w = int(width * 0.6 * STORY_CTA_SCALE)
    trial_font_size = int(18 * STORY_TRIAL_FONT_SCALE)
    badge_height = int(72 * STORY_BADGE_SCALE)
    content_start_y = STORY_TOP_SAFE_ZONE + content_shift
    content_end_y = height - STORY_BOTTOM_SAFE_ZONE - 80
    return {
        "canvas": (width, height),
        "logo_size_px": logo_size,
        "logo_offset_y": STORY_LOGO_OFFSET_Y,
        "content_shift": content_shift,
        "cta_h_px": cta_h,
        "cta_w_px": cta_w,
        "trial_font_px": trial_font_size,
        "badge_h_px": badge_height,
        "content_start_y": content_start_y,
        "content_end_y": content_end_y,
        "benefit_max_lines": STORY_BENEFIT_MAX_LINES,
        "headline_max_chars": STORY_HEADLINE_MAX_CHARS,
    }


def _compute_feed_layout_metrics(canvas_size: Tuple[int, int] = (1080, 1350)) -> Dict[str, int]:
    width, height = canvas_size
    logo_base = int(width * 0.16)
    logo_size = int(logo_base * FEED_LOGO_SCALE)
    benefit_panel_h = int(height * 0.25 * FEED_BENEFIT_PANEL_REDUCTION)
    headline_max_chars = FEED_HEADLINE_MAX_CHARS
    content_stack_tighten_px = 20
    badge_height = int(56 * 1.15)
    badge_height = int(56 * FEED_BADGE_SCALE)
    return {
        "canvas": (width, height),
        "logo_size_px": logo_size,
        "benefit_panel_h_px": benefit_panel_h,
        "benefit_opacity": FEED_BENEFIT_PANEL_OPACITY,
        "headline_max_lines": FEED_HEADLINE_MAX_LINES,
        "headline_max_chars": headline_max_chars,
        "content_stack_tighten_px": content_stack_tighten_px,
        "badge_h_px": badge_height,
        "benefit_max_lines": FEED_BENEFIT_MAX_LINES,
    }


def _enforce_max_lines(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> str:
    """Wrap text for max_width and ensure it contains at most max_lines.
    If truncated, append an ellipsis to the last line.
    """
    wrapped = wrap_for_width(draw, text, font, max_width)
    lines = [ln for ln in wrapped.splitlines() if ln.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    # Append ellipsis to last line preserving length roughly
    kept[-1] = kept[-1].rstrip()
    if not kept[-1].endswith("…"):
        kept[-1] = kept[-1].rstrip(".,;:") + "…"
    return "\n".join(kept)


def wrap_for_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    return "\n".join(lines)


def add_dark_gradient(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size

    for y in range(height):
        top_alpha = int(155 * max(0, 1 - y / 900))
        bottom_alpha = int(85 * max(0, (y - 1080) / 270))
        alpha = max(top_alpha, bottom_alpha)
        draw.line((0, y, width, y), fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image, overlay)


def compose_ad(background: Image.Image, copy: Dict[str, str]) -> Image.Image:
    """Render a 1080x1350 feed ad using the Creative Engine v2 hierarchy:
    small brand/logo -> pain headline -> spiritual action -> app benefit ->
    DOWNLOAD PRAYONIT button -> trial-support text.
    """
    image = add_dark_gradient(crop_to_canvas(background))
    contrast_metrics = compute_local_contrast_metrics(image, "feed")
    # Draw all content onto a transparent layer first so we can translate
    # the entire group vertically to center it inside the target band.
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    overlay_records: List[Dict[str, Any]] = []
    element_boxes: Dict[str, Tuple[int, int, int, int]] = {}
    bold_path, regular_path = get_fonts()
    # Feed layout metrics used to preserve approved visual sizing and spacing
    feed_metrics = _compute_feed_layout_metrics(image.size)

    logo_asset = load_brand_asset(config.LOGO_PATH)
    app_store_badge = load_brand_asset(config.APP_STORE_BADGE_PATH)
    google_play_badge = load_brand_asset(config.GOOGLE_PLAY_BADGE_PATH)

    brand_font = ImageFont.truetype(bold_path, 30)
    # scale headline/logo/benefit/fonts modestly for feed per design
    headline_font = ImageFont.truetype(bold_path, int(58 * 0.95))
    action_font = ImageFont.truetype(regular_path, 32)
    benefit_font = ImageFont.truetype(regular_path, int(34 * 0.95))
    cta_font = ImageFont.truetype(bold_path, int(44 * 1.12))  # increase CTA font ~10-15%
    trial_font = ImageFont.truetype(bold_path, int(26 * 1.08))

    white = (255, 255, 255, 255)
    accent = (255, 226, 164, 255)
    canvas_width = config.CANVAS_SIZE[0]

    def draw_centered(
        text: str,
        font: ImageFont.FreeTypeFont,
        y: int,
        *,
        fill: Tuple[int, int, int, int] = white,
        spacing: int = 10,
        stroke_width: int = 0,
        stroke_alpha: int = 120,
        overlay_alpha: int = 0,
        overlay_zone: str = "",
        overlay_padding_x: int = 20,
        overlay_padding_y: int = 14,
    ) -> Tuple[int, int, int, int]:
        box = draw.multiline_textbbox(
            (0, 0), text, font=font, spacing=spacing, align="center", stroke_width=stroke_width
        )
        width = box[2] - box[0]
        x = (canvas_width - width) / 2
        absolute_box = (
            int(x + box[0]),
            int(y + box[1]),
            int(x + box[2]),
            int(y + box[3]),
        )
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=absolute_box,
            requested_alpha=int(overlay_alpha),
            overlay_records=overlay_records,
            zone_name=overlay_zone,
            padding_x=overlay_padding_x,
            padding_y=overlay_padding_y,
        )
        draw.multiline_text(
            (x, y), text, font=font, fill=fill, spacing=spacing, align="center",
            stroke_width=stroke_width, stroke_fill=(0, 0, 0, stroke_alpha),
        )
        return absolute_box

    # A. Small brand/logo near the top. Use sequential layout flow.
    # Desired logo center around y=120 (range 90-150)
    target_h = int(64 * FEED_LOGO_SCALE)
    desired_logo_center = 120
    logo_top = int(desired_logo_center - target_h / 2)
    if logo_asset is not None:
        _logo_asset_render_width = paste_scaled(layer, logo_asset, center_x=canvas_width // 2, top_y=logo_top, target_height=target_h)
        # Record the graphic logo asset's own rendered box separately from the
        # PRAYONIT wordmark text box below. This is metadata only (QA
        # observation) and does not affect drawing/coordinates/sizing.
        _logo_asset_x1 = int(canvas_width // 2 - _logo_asset_render_width / 2)
        element_boxes["logo_asset"] = (
            _logo_asset_x1,
            int(logo_top),
            int(_logo_asset_x1 + _logo_asset_render_width),
            int(logo_top + target_h),
        )
        brand_top = logo_top
        brand_bottom = logo_top + target_h
        # brand wordmark sits closely beneath the logo
        brand_text = copy.get("brand_header", "PRAYONIT").upper() or "PRAYONIT"
        brand_box = draw.textbbox((0, 0), brand_text, font=brand_font)
        logo_zone = contrast_metrics["zones"].get("logo", {})
        brand_x = (canvas_width - (brand_box[2] - brand_box[0])) / 2
        brand_y = brand_bottom + 8
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=(int(brand_x + brand_box[0]), int(brand_y + brand_box[1]), int(brand_x + brand_box[2]), int(brand_y + brand_box[3])),
            requested_alpha=int(logo_zone.get("overlay_alpha", 0)),
            overlay_records=overlay_records,
            zone_name="logo",
            padding_x=18,
            padding_y=10,
            max_area_ratio=0.03,
        )
        draw.text(
            (brand_x, brand_y),
            brand_text,
            font=brand_font,
            fill=accent,
            stroke_width=int(logo_zone.get("gold_stroke_width", 1)),
            stroke_fill=(0, 0, 0, int(logo_zone.get("gold_shadow_alpha", 120))),
        )
        brand_bottom = brand_bottom + 8 + (brand_box[3] - brand_box[1])
        element_boxes["wordmark"] = (int(brand_x + brand_box[0]), int(brand_y + brand_box[1]), int(brand_x + brand_box[2]), int(brand_y + brand_box[3]))
    else:
        brand_text = copy.get("brand_header", "PRAYONIT").upper() or "PRAYONIT"
        brand_box = draw.textbbox((0, 0), brand_text, font=brand_font)
        brand_top = 60
        logo_zone = contrast_metrics["zones"].get("logo", {})
        brand_x = (canvas_width - (brand_box[2] - brand_box[0])) / 2
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=(int(brand_x + brand_box[0]), int(brand_top + brand_box[1]), int(brand_x + brand_box[2]), int(brand_top + brand_box[3])),
            requested_alpha=int(logo_zone.get("overlay_alpha", 0)),
            overlay_records=overlay_records,
            zone_name="logo",
            padding_x=18,
            padding_y=10,
            max_area_ratio=0.03,
        )
        draw.text(
            (brand_x, brand_top),
            brand_text,
            font=brand_font,
            fill=accent,
            stroke_width=int(logo_zone.get("gold_stroke_width", 1)),
            stroke_fill=(0, 0, 0, int(logo_zone.get("gold_shadow_alpha", 120))),
        )
        brand_bottom = brand_top + (brand_box[3] - brand_box[1])
        element_boxes["wordmark"] = (int(brand_x + brand_box[0]), int(brand_top + brand_box[1]), int(brand_x + brand_box[2]), int(brand_top + brand_box[3]))

    # C. Pain headline. Place with a gap from the brand bottom.
    gap_logo_headline = 75  # feed: 60-90 px
    headline_top = brand_bottom + gap_logo_headline
    raw_headline = copy.get("pain_headline", "").upper()
    pain_headline = _enforce_max_lines(raw_headline, draw, headline_font, 900, FEED_HEADLINE_MAX_LINES)
    headline_zone = contrast_metrics["zones"].get("headline", {})
    headline_box = draw_centered(
        pain_headline,
        headline_font,
        headline_top,
        stroke_width=int(headline_zone.get("white_stroke_width", 2)),
        stroke_alpha=int(headline_zone.get("white_shadow_alpha", 120)),
        overlay_alpha=int(headline_zone.get("overlay_alpha", 0)),
        overlay_zone="headline",
    )
    element_boxes["headline"] = headline_box
    next_y = headline_box[3]

    # D. Spiritual-action sentence beneath it.
    gap_headline_action = 30  # feed: 25-35 px
    action_top = next_y + gap_headline_action
    spiritual_action = _enforce_max_lines(copy.get("spiritual_action", ""), draw, action_font, 820, 2)
    action_zone = contrast_metrics["zones"].get("spiritual_action", {})
    action_box = draw_centered(
        spiritual_action,
        action_font,
        action_top,
        fill=accent,
        stroke_width=int(action_zone.get("gold_stroke_width", 1)),
        stroke_alpha=int(action_zone.get("gold_shadow_alpha", 130)),
        overlay_alpha=int(action_zone.get("overlay_alpha", 0)),
        overlay_zone="spiritual_action",
    )
    element_boxes["spiritual_action"] = action_box
    next_y = action_box[3]

    # E. App-benefit sentence beneath that, on a soft translucent panel.
    gap_action_benefit = 35  # feed: 30-40 px
    panel_y1 = next_y + gap_action_benefit
    exact_benefit = "Get a guided, personalized prayer based on your mood right now."
    app_benefit = _enforce_max_lines(exact_benefit, draw, benefit_font, 800, 3)
    benefit_box = draw.multiline_textbbox((0, 0), app_benefit, font=benefit_font, spacing=10, align="center")
    benefit_height = benefit_box[3] - benefit_box[1]
    panel_padding = int(48 * FEED_BENEFIT_PANEL_REDUCTION)
    panel_y2 = panel_y1 + benefit_height + panel_padding
    panel_rect = (100, panel_y1, canvas_width - 100, panel_y2)
    draw.rounded_rectangle(panel_rect, radius=24, fill=(0, 0, 0, int(255 * FEED_BENEFIT_PANEL_OPACITY)))
    benefit_zone = contrast_metrics["zones"].get("benefit", {})
    draw_centered(
        app_benefit,
        benefit_font,
        int(panel_y1 + 18),
        fill=white,
        stroke_width=int(benefit_zone.get("white_stroke_width", 1)),
        stroke_alpha=int(benefit_zone.get("white_shadow_alpha", 120)),
        overlay_alpha=0,
        overlay_zone="benefit",
    )
    element_boxes["benefit"] = panel_rect
    panel_bottom = panel_y2

    # F. Large DOWNLOAD PRAYONIT button
    download_cta = copy.get("download_cta", "COME PRAY WITH ME").upper()
    cta_box = draw.textbbox((0, 0), download_cta, font=cta_font)
    cta_width = cta_box[2] - cta_box[0]
    gap_benefit_cta = 40  # feed: 35-45 px
    button_y1 = panel_bottom + gap_benefit_cta
    base_button_h = 100
    button_y2 = button_y1 + int(base_button_h * 1.15)
    x1 = (canvas_width - cta_width) / 2 - 72
    x2 = (canvas_width + cta_width) / 2 + 72
    draw.rounded_rectangle((x1, button_y1, x2, button_y2), radius=24, fill=(20, 31, 45, 235), outline=(255, 255, 255, 200), width=3)
    cta_zone = contrast_metrics["zones"].get("cta_trial_badges", {})
    draw.text(
        ((canvas_width - cta_width) / 2, button_y1 + (button_y2 - button_y1 - (cta_box[3] - cta_box[1])) / 2 - cta_box[1]),
        download_cta,
        font=cta_font,
        fill=white,
        stroke_width=int(cta_zone.get("white_stroke_width", 1)),
        stroke_fill=(0, 0, 0, int(cta_zone.get("white_shadow_alpha", 120))),
    )
    element_boxes["cta"] = (int(x1), int(button_y1), int(x2), int(button_y2))

    # G. Trial-support text immediately below the button.
    trial_support = copy.get("trial_support", "Start your 14-day free trial today.")
    trial_font = ImageFont.truetype(bold_path, int(28 * 1.08))
    trial_box = draw.textbbox((0, 0), trial_support, font=trial_font)
    trial_x = (canvas_width - (trial_box[2] - trial_box[0])) / 2
    trial_y = button_y2 + 22
    # Draw trial-support text without a localized overlay to keep it visually transparent
    draw.text(
        (trial_x, trial_y),
        trial_support,
        font=trial_font,
        fill=white,
        stroke_width=int(cta_zone.get("white_stroke_width", 1)),
        stroke_fill=(0, 0, 0, int(cta_zone.get("white_shadow_alpha", 110))),
    )
    element_boxes["trial"] = (int(trial_x + trial_box[0]), int(trial_y + trial_box[1]), int(trial_x + trial_box[2]), int(trial_y + trial_box[3]))
    trial_bottom = button_y2 + 18 + (trial_box[3] - trial_box[1])

    # H. Store badges row
    gap_trial_badge = 25  # feed: 25-30 px
    badge_height = int(feed_metrics.get("badge_h_px", int(56 * FEED_BADGE_SCALE)))
    badge_top = trial_bottom + gap_trial_badge
    if app_store_badge is not None and google_play_badge is not None:
        gap = 18
        app_aspect = app_store_badge.width / app_store_badge.height
        play_aspect = google_play_badge.width / google_play_badge.height
        app_width = int(badge_height * app_aspect)
        play_width = int(badge_height * play_aspect)
        total_width = app_width + gap + play_width
        start_x = (canvas_width - total_width) // 2
        paste_scaled(layer, app_store_badge, center_x=start_x + app_width // 2, top_y=badge_top, target_height=badge_height)
        paste_scaled(layer, google_play_badge, center_x=start_x + app_width + gap + play_width // 2, top_y=badge_top, target_height=badge_height)
        badge_bottom = badge_top + badge_height
    else:
        badge_text = "Available on the App Store and Google Play"
        b_box = draw.textbbox((0, 0), badge_text, font=brand_font)
        draw.text(((canvas_width - (b_box[2] - b_box[0])) / 2, badge_top), badge_text, font=brand_font, fill=white)
        badge_bottom = badge_top + (b_box[3] - b_box[1])

    # Now compute the vertical group and translate the entire layer to center
    # it inside the desired content band for Feed.
    group_top = logo_top
    group_bottom = badge_bottom
    group_height = group_bottom - group_top
    band_top = 130
    band_bottom = 930
    target_center = (band_top + band_bottom) / 2
    current_center = (group_top + group_bottom) / 2
    feed_group_offset = int(round(target_center - current_center))

    # Paste the layer shifted by the computed offset and composite over
    # the background image. Using paste with mask preserves transparency.
    shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shifted.paste(layer, (0, feed_group_offset), layer)
    composed = Image.alpha_composite(image.convert("RGBA"), shifted)
    rgb = composed.convert("RGB")
    shifted_overlay_records = _shift_overlay_records(overlay_records, feed_group_offset)
    # The contrast_metrics here were computed from the base background prior
    # to localized overlays; attach them but also compute effective metrics
    # on the final composed RGB image so QA can validate the treated result.
    rgb.info["contrast_metrics"] = contrast_metrics
    # Recompute effective per-zone luminance/contrast on the final composed image
    effective = compute_local_contrast_metrics(rgb.convert("RGB"), "feed")
    rgb.info["effective_contrast_metrics"] = effective
    # compute element-level metrics based on tight element boxes and overlays
    element_metrics: Dict[str, Any] = {}
    white_l = _relative_luminance(255, 255, 255)
    gold_l = _relative_luminance(255, 226, 164)

    overlays = shifted_overlay_records

    def _overlay_alpha_for_box(target_box: Tuple[int, int, int, int]) -> int:
        alpha = 0
        for rec in overlays:
            ob = tuple(rec["box"])
            if _boxes_overlap(ob, target_box):
                alpha = max(alpha, int(rec.get("alpha", 0)))
        return alpha

    def _box_effective_luminance(img: Image.Image, box: Tuple[int, int, int, int], overlay_alpha: int) -> float:
        base = _estimate_region_luminance(img, box)
        return base * (1 - float(overlay_alpha) / 255.0)

    final_rgb = rgb.convert("RGB")
    # CTA: measure against button fill
    for name in ("logo_asset", "wordmark", "headline", "spiritual_action", "benefit", "cta", "trial"):
        box = element_boxes.get(name)
        if not box:
            continue
        if name == "logo_asset":
            # The graphic logo asset is observational metadata only. It is a
            # brand image (not body text), so it must not be evaluated with
            # text-contrast thresholds and must not participate in the
            # overall pass/fail decision used to block Buffer.
            eff_l = _estimate_region_luminance(final_rgb, box)
            element_metrics[name] = {
                "box": box,
                "effective_luminance": round(eff_l, 4),
                "contrast_ratio": None,
                "threshold": None,
                "pass": True,
                "observational_only": True,
                "treatment": {"type": "logo_asset_metadata"},
            }
            continue
        if name == "cta":
            button_l = _relative_luminance(20, 31, 45)
            contrast = _contrast_ratio(white_l, button_l)
            threshold = CONTRAST_MIN_RATIO_WHITE
            element_metrics[name] = {
                "box": box,
                "effective_luminance": round(button_l, 4),
                "contrast_ratio": round(contrast, 3),
                "threshold": threshold,
                "pass": contrast >= threshold,
                "treatment": {"type": "button_fill", "color": (20, 31, 45), "alpha": 235},
            }
            continue
        if name == "benefit":
            panel_alpha = int(255 * FEED_BENEFIT_PANEL_OPACITY)
            eff_l = _box_effective_luminance(final_rgb, box, panel_alpha)
            contrast = _contrast_ratio(white_l, eff_l)
            threshold = CONTRAST_MIN_RATIO_WHITE
            element_metrics[name] = {
                "box": box,
                "effective_luminance": round(eff_l, 4),
                "contrast_ratio": round(contrast, 3),
                "threshold": threshold,
                "pass": contrast >= threshold,
                "treatment": {"type": "panel", "overlay_alpha": panel_alpha},
            }
            continue
        overlay_alpha = _overlay_alpha_for_box(box)
        eff_l = _box_effective_luminance(final_rgb, box, overlay_alpha)
        if name in ("spiritual_action", "wordmark"):
            # Wordmark is rendered in the gold accent color, same as
            # spiritual_action, so it must be measured against the gold
            # text luminance and the gold-text threshold, not white body text.
            text_l = gold_l
            threshold = CONTRAST_MIN_RATIO_GOLD
        else:
            text_l = white_l
            threshold = CONTRAST_MIN_RATIO_WHITE
        contrast = _contrast_ratio(text_l, eff_l)
        element_metrics[name] = {
            "box": box,
            "effective_luminance": round(eff_l, 4),
            "contrast_ratio": round(contrast, 3),
            "threshold": threshold,
            "pass": contrast >= threshold,
            "treatment": {"type": "localized_overlay", "overlay_alpha": overlay_alpha},
        }

    # Overall pass excludes the graphic logo asset (observational only);
    # it includes the wordmark and all other text/interactive elements.
    _pass_relevant = {k: v for k, v in element_metrics.items() if not v.get("observational_only")}
    overall_pass = all(v.get("pass") for v in _pass_relevant.values()) if _pass_relevant else False
    rgb.info["element_contrast_metrics"] = {"feed": {**element_metrics, "overall_pass": overall_pass}}
    rgb.info["overlay_rects"] = shifted_overlay_records
    rgb.info["layout_debug"] = {
        "kind": "feed",
        "group_offset_y": feed_group_offset,
        "benefit_panel_rect": (100, panel_y1 + feed_group_offset, canvas_width - 100, panel_y2 + feed_group_offset),
        "cta_rect": (int(x1), int(button_y1 + feed_group_offset), int(x2), int(button_y2 + feed_group_offset)),
    }
    return rgb


def compose_story_ad(background: Image.Image, copy: Dict[str, str]) -> Image.Image:
    """Render a 1080x1920 Story ad using the Creative Engine v2 hierarchy:
    logo -> brand name -> pain headline -> spiritual action -> app benefit ->
    large DOWNLOAD PRAYONIT button -> trial-support text -> store badges.

    All essential content stays safely above the bottom "safe zone" so it is
    never covered by Instagram/Facebook Story reply controls.
    """
    image = add_dark_gradient(crop_to_canvas(background, config.STORY_CANVAS_SIZE))
    contrast_metrics = compute_local_contrast_metrics(image, "story")
    # Draw story content to a transparent layer so we can shift the whole
    # content group down to center it inside the target band.
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    overlay_records: List[Dict[str, Any]] = []
    element_boxes: Dict[str, Tuple[int, int, int, int]] = {}
    bold_path, regular_path = get_fonts()
    width, height = config.STORY_CANVAS_SIZE

    # Bottom safe zone (Instagram/Facebook reply bar + system UI); nothing
    # essential is placed below this line.
    bottom_safe_zone_y = height - 220

    logo_asset = load_brand_asset(config.LOGO_PATH)
    app_store_badge = load_brand_asset(config.APP_STORE_BADGE_PATH)
    google_play_badge = load_brand_asset(config.GOOGLE_PLAY_BADGE_PATH)

    brand_font = ImageFont.truetype(bold_path, 34)
    # Story: scale headline and fonts modestly but support dynamic scaling
    headline_font = ImageFont.truetype(bold_path, int(66 * 0.98))
    action_font = ImageFont.truetype(regular_path, 34)
    # benefit must use locked phrase; font slightly increased and line spacing
    benefit_font = ImageFont.truetype(regular_path, int(38 * 1.02))
    cta_font = ImageFont.truetype(bold_path, int(48 * STORY_CTA_SCALE))
    trial_font = ImageFont.truetype(bold_path, int(30 * STORY_TRIAL_FONT_SCALE))
    badge_fallback_font = ImageFont.truetype(bold_path, 26)

    white = (255, 255, 255, 255)
    accent = (255, 226, 164, 255)

    def draw_centered_story(
        text: str,
        font: ImageFont.FreeTypeFont,
        y: int,
        *,
        fill: Tuple[int, int, int, int] = white,
        spacing: int = 10,
        stroke_width: int = 0,
        stroke_alpha: int = 120,
        overlay_alpha: int = 0,
        overlay_zone: str = "",
        overlay_padding_x: int = 20,
        overlay_padding_y: int = 14,
    ) -> Tuple[int, int, int, int]:
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
        text_width = box[2] - box[0]
        x = (width - text_width) / 2
        absolute_box = (
            int(x + box[0]),
            int(y + box[1]),
            int(x + box[2]),
            int(y + box[3]),
        )
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=absolute_box,
            requested_alpha=int(overlay_alpha),
            overlay_records=overlay_records,
            zone_name=overlay_zone,
            padding_x=overlay_padding_x,
            padding_y=overlay_padding_y,
            max_area_ratio=0.06,
        )
        draw.multiline_text(
            (x, y),
            text,
            font=font,
            fill=fill,
            spacing=spacing,
            align="center",
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, stroke_alpha),
        )
        return absolute_box

    # A + B. Small logo/icon near the top, brand name beside/beneath it.
    # Use sequential layout flow with measured element heights.
    target_height = int(70 * STORY_LOGO_SCALE)
    desired_logo_center = 260  # target center between 230-300
    logo_top = int(desired_logo_center - target_height / 2)
    if logo_asset is not None:
        paste_scaled(layer, logo_asset, center_x=width // 2, top_y=logo_top + 0, target_height=target_height)
        brand_text = copy.get("brand_header", "PRAYONIT").upper() or "PRAYONIT"
        brand_box = draw.multiline_textbbox((0, 0), brand_text, font=brand_font)
        brand_top = logo_top
        brand_bottom = logo_top + target_height
        logo_zone = contrast_metrics["zones"].get("logo", {})
        brand_x = (width - (brand_box[2] - brand_box[0])) / 2
        brand_y = brand_bottom + 8
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=(int(brand_x + brand_box[0]), int(brand_y + brand_box[1]), int(brand_x + brand_box[2]), int(brand_y + brand_box[3])),
            requested_alpha=int(logo_zone.get("overlay_alpha", 0)),
            overlay_records=overlay_records,
            zone_name="logo",
            padding_x=18,
            padding_y=10,
            max_area_ratio=0.025,
        )
        draw.multiline_text(
            (brand_x, brand_y),
            brand_text,
            font=brand_font,
            fill=accent,
            align="center",
            stroke_width=int(logo_zone.get("gold_stroke_width", 1)),
            stroke_fill=(0, 0, 0, int(logo_zone.get("gold_shadow_alpha", 120))),
        )
        brand_bottom = brand_bottom + 8 + (brand_box[3] - brand_box[1])
    else:
        brand_text = copy.get("brand_header", "PRAYONIT").upper() or "PRAYONIT"
        brand_box = draw.multiline_textbbox((0, 0), brand_text, font=brand_font)
        brand_top = 140
        logo_zone = contrast_metrics["zones"].get("logo", {})
        brand_x = (width - (brand_box[2] - brand_box[0])) / 2
        _maybe_draw_localized_overlay(
            draw,
            layer_size=image.size,
            text_box=(int(brand_x + brand_box[0]), int(brand_top + brand_box[1]), int(brand_x + brand_box[2]), int(brand_top + brand_box[3])),
            requested_alpha=int(logo_zone.get("overlay_alpha", 0)),
            overlay_records=overlay_records,
            zone_name="logo",
            padding_x=18,
            padding_y=10,
            max_area_ratio=0.025,
        )
        draw.multiline_text(
            (brand_x, brand_top),
            brand_text,
            font=brand_font,
            fill=accent,
            align="center",
            stroke_width=int(logo_zone.get("gold_stroke_width", 1)),
            stroke_fill=(0, 0, 0, int(logo_zone.get("gold_shadow_alpha", 120))),
        )
        brand_bottom = brand_top + (brand_box[3] - brand_box[1])

    # C. Pain headline: place with measured gap from brand bottom.
    gap_logo_headline = 125  # story: 110-140 px
    headline_top = brand_bottom + gap_logo_headline
    raw_headline = copy.get("story_headline", "").upper()
    if len(raw_headline) > STORY_HEADLINE_MAX_CHARS:
        raw_headline = raw_headline[:STORY_HEADLINE_MAX_CHARS].rstrip(" ") + "…"
    story_headline = _enforce_max_lines(raw_headline, draw, headline_font, 900, 2)
    headline_zone = contrast_metrics["zones"].get("headline", {})
    headline_box = draw_centered_story(
        story_headline,
        headline_font,
        headline_top,
        spacing=14,
        stroke_width=int(headline_zone.get("white_stroke_width", 2)),
        stroke_alpha=int(headline_zone.get("white_shadow_alpha", 130)),
        overlay_alpha=int(max(headline_zone.get("overlay_alpha", 0), 160)),
        overlay_zone="headline",
        overlay_padding_x=14,
        overlay_padding_y=10,
    )
    y = headline_box[3]
    element_boxes["headline"] = headline_box

    # D. Spiritual-action sentence beneath it.
    gap_headline_action = 40  # story: 35-45 px
    action_top = y + gap_headline_action
    story_action = _enforce_max_lines(copy.get("story_spiritual_action", ""), draw, action_font, 820, 2)
    action_zone = contrast_metrics["zones"].get("spiritual_action", {})
    action_box = draw_centered_story(
        story_action,
        action_font,
        action_top,
        fill=accent,
        stroke_width=int(action_zone.get("gold_stroke_width", 1)),
        stroke_alpha=int(action_zone.get("gold_shadow_alpha", 150)),
        overlay_alpha=int(max(action_zone.get("overlay_alpha", 0), 92)),
        overlay_zone="spiritual_action",
    )
    y = action_box[3]
    element_boxes["spiritual_action"] = action_box

    # E. App-benefit sentence beneath that, kept to ~3 lines.
    gap_action_benefit = 40  # story: 35-45 px
    benefit_top = y + gap_action_benefit
    exact_benefit = "Get a guided, personalized prayer based on your mood right now."
    story_benefit = _enforce_max_lines(exact_benefit, draw, benefit_font, 800, 3)
    benefit_zone = contrast_metrics["zones"].get("benefit", {})
    benefit_box = draw_centered_story(
        story_benefit,
        benefit_font,
        benefit_top,
        stroke_width=int(benefit_zone.get("white_stroke_width", 1)),
        stroke_alpha=int(benefit_zone.get("white_shadow_alpha", 120)),
        overlay_alpha=int(benefit_zone.get("overlay_alpha", 0)),
        overlay_zone="benefit",
    )
    y = benefit_box[3]
    element_boxes["benefit"] = benefit_box

    # F. Large DOWNLOAD PRAYONIT button, substantially larger than before.
    gap_benefit_cta = 50  # story: 45-55 px
    button_y1 = y + gap_benefit_cta
    story_cta = copy.get("story_download_cta", "COME PRAY WITH ME").upper()
    cta_box = draw.textbbox((0, 0), story_cta, font=cta_font)
    cta_width = cta_box[2] - cta_box[0]
    base_button_h = 110
    button_y2 = button_y1 + int(base_button_h * STORY_CTA_SCALE)
    x1 = (width - cta_width) / 2 - int(70 * STORY_CTA_SCALE)
    x2 = (width + cta_width) / 2 + int(70 * STORY_CTA_SCALE)
    draw.rounded_rectangle((x1, button_y1, x2, button_y2), radius=26, fill=(20, 31, 45, 235), outline=(255, 255, 255, 200), width=3)
    cta_zone = contrast_metrics["zones"].get("cta_trial_badges", {})
    draw.text(
        ((width - cta_width) / 2, button_y1 + (button_y2 - button_y1 - (cta_box[3] - cta_box[1])) / 2 - cta_box[1]),
        story_cta,
        font=cta_font,
        fill=white,
        stroke_width=int(cta_zone.get("white_stroke_width", 1)),
        stroke_fill=(0, 0, 0, int(cta_zone.get("white_shadow_alpha", 120))),
    )
    y = button_y2
    element_boxes["cta"] = (int(x1), int(button_y1), int(x2), int(button_y2))

    # G. Trial-support text immediately below the button.
    gap_cta_trial = 27  # story: 25-30 px
    trial_top = y + gap_cta_trial
    story_trial = copy.get("story_trial_support", "Start your 14-day free trial.")
    trial_font = ImageFont.truetype(bold_path, int(trial_font.size * STORY_TRIAL_FONT_SCALE))
    trial_box = draw_centered_story(
        story_trial,
        trial_font,
        trial_top,
        stroke_width=int(cta_zone.get("white_stroke_width", 1)),
        stroke_alpha=int(cta_zone.get("white_shadow_alpha", 120)),
        overlay_alpha=int(cta_zone.get("overlay_alpha", 0) * 0.7),
        overlay_zone="trial_support",
        overlay_padding_x=18,
        overlay_padding_y=10,
    )
    y = trial_box[3]
    element_boxes["trial"] = trial_box

    # H. Official App Store / Google Play badges beneath the trial text,
    # kept above the bottom safe zone. Falls back to a text line if either
    # badge asset is missing.
    badge_height = int(64 * STORY_BADGE_SCALE)
    gap_trial_badge = 32  # story: 30-35 px
    badge_top = y + gap_trial_badge
    if app_store_badge is not None and google_play_badge is not None:
        gap = 24
        app_aspect = app_store_badge.width / app_store_badge.height
        play_aspect = google_play_badge.width / google_play_badge.height
        app_width = int(badge_height * app_aspect)
        play_width = int(badge_height * play_aspect)
        total_width = app_width + gap + play_width
        start_x = (width - total_width) // 2
        paste_scaled(layer, app_store_badge, center_x=start_x + app_width // 2, top_y=badge_top, target_height=badge_height)
        paste_scaled(layer, google_play_badge, center_x=start_x + app_width + gap + play_width // 2, top_y=badge_top, target_height=badge_height)
        badge_bottom = badge_top + badge_height
    else:
        badge_fallback = "Available on the App Store and Google Play"
        badge_y = badge_top
        draw_centered_story(badge_fallback, badge_fallback_font, badge_y)
        badge_bottom = badge_top + 40

    # Compute group bounds and translate the whole content group to the
    # Story content band so it visually centers in the requested area.
    group_top = logo_top
    group_bottom = badge_bottom
    band_top = 300
    band_bottom = 1250
    target_center = (band_top + band_bottom) / 2
    current_center = (group_top + group_bottom) / 2
    story_group_offset = int(round(target_center - current_center))

    shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shifted.paste(layer, (0, story_group_offset), layer)
    composed = Image.alpha_composite(image.convert("RGBA"), shifted)
    rgb = composed.convert("RGB")
    shifted_overlay_records = _shift_overlay_records(overlay_records, story_group_offset)
    rgb.info["contrast_metrics"] = contrast_metrics
    effective = compute_local_contrast_metrics(rgb.convert("RGB"), "story")
    rgb.info["effective_contrast_metrics"] = effective
    # compute element-level metrics for story
    element_metrics: Dict[str, Any] = {}
    white_l = _relative_luminance(255, 255, 255)
    gold_l = _relative_luminance(255, 226, 164)
    overlays = shifted_overlay_records

    def _overlay_alpha_for_box(target_box: Tuple[int, int, int, int]) -> int:
        alpha = 0
        for rec in overlays:
            ob = tuple(rec["box"])
            if _boxes_overlap(ob, target_box):
                alpha = max(alpha, int(rec.get("alpha", 0)))
        return alpha

    def _box_effective_luminance(img: Image.Image, box: Tuple[int, int, int, int], overlay_alpha: int) -> float:
        base = _estimate_region_luminance(img, box)
        return base * (1 - float(overlay_alpha) / 255.0)

    final_rgb = rgb.convert("RGB")
    for name in ("logo", "headline", "spiritual_action", "benefit", "cta", "trial"):
        box = element_boxes.get(name)
        if not box:
            continue
        if name == "cta":
            button_l = _relative_luminance(20, 31, 45)
            contrast = _contrast_ratio(white_l, button_l)
            threshold = CONTRAST_MIN_RATIO_WHITE
            element_metrics[name] = {
                "box": box,
                "effective_luminance": round(button_l, 4),
                "contrast_ratio": round(contrast, 3),
                "threshold": threshold,
                "pass": contrast >= threshold,
                "treatment": {"type": "button_fill", "color": (20, 31, 45), "alpha": 235},
            }
            continue
        overlay_alpha = _overlay_alpha_for_box(box)
        eff_l = _box_effective_luminance(final_rgb, box, overlay_alpha)
        if name == "spiritual_action":
            text_l = gold_l
            threshold = CONTRAST_MIN_RATIO_GOLD
        else:
            text_l = white_l
            threshold = CONTRAST_MIN_RATIO_WHITE
        contrast = _contrast_ratio(text_l, eff_l)
        element_metrics[name] = {
            "box": box,
            "effective_luminance": round(eff_l, 4),
            "contrast_ratio": round(contrast, 3),
            "threshold": threshold,
            "pass": contrast >= threshold,
            "treatment": {"type": "localized_overlay", "overlay_alpha": overlay_alpha},
        }

    overall_pass = all(v.get("pass") for v in element_metrics.values()) if element_metrics else False
    rgb.info["element_contrast_metrics"] = {"story": {**element_metrics, "overall_pass": overall_pass}}
    rgb.info["overlay_rects"] = shifted_overlay_records
    rgb.info["layout_debug"] = {
        "kind": "story",
        "group_offset_y": story_group_offset,
        "cta_rect": (int(x1), int(button_y1 + story_group_offset), int(x2), int(button_y2 + story_group_offset)),
    }
    return rgb


def upload_generated(image_path: Path, prefix: str, supabase_client: Any) -> Tuple[str, str]:
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    remote_path = f"{prefix}/prayonit-ad-{timestamp}.jpg"

    with image_path.open("rb") as image_file:
        supabase_client.storage.from_(config.SUPABASE_BUCKET).upload(
            remote_path,
            image_file,
            {"content-type": "image/jpeg", "upsert": "false"},
        )

    return remote_path, public_url(remote_path)
