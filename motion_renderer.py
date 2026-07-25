"""Prayonit motion ad renderer (TikTok/Reels/Shorts-optimized, single master
9:16 video reused across TikTok, Instagram Reels, Facebook Reels, and
YouTube Shorts -- no platform-specific variants are generated).

`render_motion_ad(ad_copy, background_path, output_path=None,
duration_seconds=8)` is the production-callable entry point. It renders a
hook-first emotional short-form overlay sequence, using dynamic copy
supplied by the caller (the same `ad_copy` dict already produced by
prompt_builder.generate_ad_copy() / generate_local_ad_copy() and used for
Feed/Story):

    Scene 1 (0.15s-2.65s)  Recognition hook       (pain_headline)
    Scene 2 (2.65s-4.90s)  Comfort / hope         (spiritual_action)
    Scene 3 (4.90s-6.35s)  Soft brand reveal      (logo + "Come pray with me.")
    Scene 4 (6.35s-8.00s)  Final invitation       (PRAYONIT + "Come pray with
                                                    me." + "Link in bio.")

The emotional message (Scenes 1-2) always lands fully before any branding,
logo, or invitation appears (Scenes 3-4). No app_benefit, no URL/website
text (e.g. "prayonit.app"), and no App Store/Google Play badges are ever
rendered in this video, per the current creative direction.

This module still does NOT import buffer_client.py, Supabase, tracking.py,
campaign_engine.py, prompt_builder.py, image_renderer.py, creative_engine_v3.py,
or history_store.py, and never uploads or publishes anything itself. It only
reads static, read-only brand assets already on disk (assets/branding/*,
system fonts), a caller-supplied or randomly-selected .mp4 from
assets/motion_backgrounds/, and config.py's PRIMARY_CTA constant is no
longer read here (the video shows a fixed, brand-approved invitation text
instead -- see BRAND_INVITATION_TEXT / LINK_IN_BIO_TEXT below).

Standalone manual run (no ad_copy supplied):
    ./.venv/bin/python motion_renderer.py

Standalone output:
    output/videos/video_test.mp4 (silent, overwritten if it already exists)

Any temporary/intermediate rendering files are written under output/temp/
and are never left in the output/ root.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import VideoFileClip, VideoClip

import config

# ---------- Paths (read-only; no production files are imported) ----------
PROJECT_ROOT = Path(__file__).resolve().parent
MOTION_BG_DIR = PROJECT_ROOT / "assets" / "motion_backgrounds"
BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"
LOGO_PATH = BRANDING_DIR / "prayonit_logo.png"
APP_STORE_BADGE_PATH = BRANDING_DIR / "app_store_badge.png"
GOOGLE_PLAY_BADGE_PATH = BRANDING_DIR / "google_play_badge.png"

# Organized generated-output folders. Only output/videos and output/temp are
# used by this file; output/images/* belong to the static image renderer.
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_VIDEOS_DIR = OUTPUT_DIR / "videos"
OUTPUT_TEMP_DIR = OUTPUT_DIR / "temp"
OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_TEMP_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_PATH = OUTPUT_VIDEOS_DIR / "video_test.mp4"

# ---------- Demo copy (standalone manual testing ONLY) ----------
# Used only when motion_renderer.py is run directly with no ad_copy
# supplied (e.g. `python motion_renderer.py`). The production callable
# render_motion_ad() never reads this dictionary.
DEMO_COPY = {
    "pain_headline": "NEED PEACE TONIGHT?",
    "spiritual_action": "Give your worries to God tonight.",
}

# ---------- Motion-video-only copy style rules ----------
# Scene 1 (recognition hook) and Scene 2 (comfort/hope) must each read as
# one complete, plain-spoken sentence -- never truncated mid-thought and
# never ending in an ellipsis. These limits apply ONLY to the motion video
# overlay text; Feed/Story copy (image_renderer.py) and the Gemini prompt
# itself are untouched.
HOOK_MAX_WORDS = 9
EMOTIONAL_MAX_WORDS = 10

# Known awkward/abstract phrasings to smooth into plain conversational
# language wherever they appear, regardless of topic. This is a general
# style cleanup, not a topic-specific rewrite.
_MOTION_AWKWARD_PHRASE_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("your body's grief", "your grief"),
    ("body's grief", "your grief"),
    ("scattered mind", "busy mind"),
)


def _clean_motion_phrase(text: str) -> str:
    """Replace known awkward/abstract phrasings with plain conversational
    language. Case-insensitive; applied only to motion-video overlay text.
    """
    cleaned = text
    for awkward, plain in _MOTION_AWKWARD_PHRASE_REPLACEMENTS:
        cleaned = re.sub(re.escape(awkward), plain, cleaned, flags=re.IGNORECASE)
    return cleaned


def _shorten_to_word_limit(text: str, max_words: int) -> str:
    """Shorten `text` to at most `max_words` words, preserving meaning by
    keeping the leading words (which normally carry the recognition/comfort
    idea) and re-closing the sentence with its own original end punctuation
    (falling back to a period). Never truncates mid-word and never adds an
    ellipsis -- the result always reads as a complete, plain sentence.
    """
    stripped = (text or "").strip()
    if not stripped:
        return stripped

    trailing_punct = stripped[-1] if stripped[-1] in "?!." else "."
    core = stripped.rstrip("?!.")
    words = core.split()
    if len(words) <= max_words:
        return stripped

    shortened = " ".join(words[:max_words])
    return f"{shortened}{trailing_punct}"

# Fixed, brand-approved text used in Scenes 3-4. These are NOT sourced from
# ad_copy (never from Gemini) -- they are constants, matching the
# invitation-first funnel used elsewhere in the brand (see
# brand/brand_rules.json preferred_cta). No URL/website text (e.g.
# "prayonit.app") and no app_benefit sentence are ever shown in this video.
BRAND_WORDMARK_TEXT = "PRAYONIT"
BRAND_INVITATION_TEXT = "Come pray with me."
LINK_IN_BIO_TEXT = "Link in bio."

# ---------- Visual constants matched to image_renderer.py's Feed styling ----------
WHITE = (255, 255, 255, 255)
GOLD_ACCENT = (255, 226, 164, 255)

FADE_DURATION = 0.4  # default fade duration (seconds) for elements without a tighter spec requirement

# ==========================================================================
# Scene timing (seconds) -- hook-first emotional sequence.
#
#   Scene 1  Recognition hook        HOOK_START           -> HOOK_END
#   Scene 2  Comfort / hope          EMOTIONAL_START       -> EMOTIONAL_END
#   Scene 3  Soft brand reveal       BRAND_START           -> BRAND_END
#   Scene 4  Final invitation        FINAL_FRAME_START     -> VIDEO_END
#
# The emotional content (Scenes 1-2) always fully resolves before any
# logo/branding (Scenes 3-4) begins. Total video duration is exactly
# VIDEO_END (8.00s).
# ==========================================================================
HOOK_START = 0.15                 # hook begins fading in
HOOK_FULLY_VISIBLE_BY = 0.40       # hook must be fully readable by this time
HOOK_FADE_OUT_START = 2.40         # hook begins fading out
HOOK_END = 2.65                    # hook fully gone / Scene 1 ends

EMOTIONAL_START = 2.65             # comfort/hope line fades in as Scene 1 exits
EMOTIONAL_FADE_OUT_START = 4.65    # comfort/hope line begins fading out
EMOTIONAL_END = 4.90               # Scene 2 ends

BRAND_START = 4.90                 # logo + "Come pray with me." softly fade in
BRAND_END = 6.35                   # Scene 3 ends

FINAL_FRAME_START = 6.35           # PRAYONIT wordmark + "Link in bio." fade in
VIDEO_END = 8.00                   # total video duration

HOOK_FADE_IN_DURATION = HOOK_FULLY_VISIBLE_BY - HOOK_START     # 0.25s
HOOK_FADE_OUT_DURATION = HOOK_END - HOOK_FADE_OUT_START        # 0.25s
EMOTIONAL_FADE_IN_DURATION = 0.25                              # fully visible ~2.90s
EMOTIONAL_FADE_OUT_DURATION = EMOTIONAL_END - EMOTIONAL_FADE_OUT_START  # 0.25s
BRAND_FADE_IN_DURATION = 0.4                                   # soft/slow fade-in
FINAL_FRAME_FADE_IN_DURATION = 0.4                             # soft/slow fade-in

DEFAULT_VIDEO_DURATION_SECONDS = VIDEO_END  # 8.00s

# ==========================================================================
# Shared safe zone (conservative, appropriate for TikTok, Instagram Reels,
# Facebook Reels, and YouTube Shorts simultaneously -- single master video,
# no per-platform variants).
# ==========================================================================
SAFE_ZONE_TOP_FRAC = 0.12          # avoid the top 12% of frame height
SAFE_ZONE_BOTTOM_FRAC = 0.20       # avoid the bottom 20% of frame height
SAFE_ZONE_RIGHT_FRAC = 0.15        # avoid the rightmost 15% of frame width
# Centered text is kept within a symmetric horizontal band that already
# clears the excluded right-hand 15% (and, symmetrically, the left side),
# rather than relying on an unexplained fixed pixel margin.
SAFE_ZONE_MAX_TEXT_WIDTH_FRAC = 1.0 - (2 * SAFE_ZONE_RIGHT_FRAC)  # 0.70

# Vertical anchor points, expressed as fractions of frame height, chosen
# within the ranges suggested by the creative spec. HOOK and EMOTIONAL
# share the same anchor so the viewer's eyes do not have to jump between
# Scene 1 and Scene 2 (per spec: "keep text placement stable").
HOOK_CENTER_Y_FRAC = 0.42          # within suggested 35%-42%
EMOTIONAL_CENTER_Y_FRAC = 0.42     # within suggested 42%-50% (shared w/ hook for stability)
LOGO_CENTER_Y_FRAC = 0.42          # within suggested brand-reveal 38%-58%
BRAND_INVITATION_CENTER_Y_FRAC = 0.50   # "Come pray with me." (brand reveal group)
WORDMARK_CENTER_Y_FRAC = 0.57      # "PRAYONIT" label (brand reveal group, Scene 4)
LINK_IN_BIO_CENTER_Y_FRAC = 0.73   # within suggested 72%-75%, above bottom danger zone


def _extract_motion_copy(ad_copy: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Map the shared production ad_copy dict onto the two motion-video
    text slots this renderer now uses (Scene 1 hook, Scene 2 comfort/hope
    line), falling back to DEMO_COPY (manual standalone runs only) when a
    field is absent or blank.

    Per the current creative direction, the motion video no longer reads
    or displays app_benefit, download_cta, or trial_support/URL text at
    all -- Scenes 3-4 use the fixed BRAND_WORDMARK_TEXT /
    BRAND_INVITATION_TEXT / LINK_IN_BIO_TEXT constants instead. The
    ad_copy JSON schema itself is unchanged; this function simply reads
    fewer of its fields for the motion video specifically. Feed/Story
    rendering (image_renderer.py) is untouched and continues to use every
    ad_copy field exactly as before.
    """
    ad_copy = ad_copy or {}

    pain_headline = (ad_copy.get("pain_headline") or ad_copy.get("story_headline") or "").strip()
    emotional_line = (ad_copy.get("spiritual_action") or ad_copy.get("story_spiritual_action") or "").strip()

    if not pain_headline:
        pain_headline = DEMO_COPY["pain_headline"]
    if not emotional_line:
        emotional_line = DEMO_COPY["spiritual_action"]

    # Motion-video-only style pass: smooth awkward/abstract phrasing, then
    # shorten to a plain, complete sentence within the scene's word limit
    # (never truncated mid-thought, never an ellipsis). Feed/Story copy and
    # the ad_copy dict itself are never modified by this function.
    pain_headline = _clean_motion_phrase(pain_headline)
    pain_headline = _shorten_to_word_limit(pain_headline, HOOK_MAX_WORDS)

    emotional_line = _clean_motion_phrase(emotional_line)
    emotional_line = _shorten_to_word_limit(emotional_line, EMOTIONAL_MAX_WORDS)

    return {
        "pain_headline": pain_headline,
        "emotional_line": emotional_line,
    }


def _pick_random_motion_background(motion_backgrounds_dir: Optional[Path] = None) -> Path:
    """Choose ONE random .mp4 from the given directory (defaults to
    assets/motion_backgrounds/).
    """
    directory = motion_backgrounds_dir or MOTION_BG_DIR
    candidates = sorted(Path(directory).glob("*.mp4"))
    if not candidates:
        raise FileNotFoundError(
            f"No .mp4 files found in {directory}. Add at least one motion "
            "background to proceed."
        )
    return random.choice(candidates)


def _get_fonts() -> Tuple[str, str]:
    """Same font discovery approach as image_renderer.get_fonts(), duplicated
    here on purpose so this file never imports image_renderer.py.
    """
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


def _load_brand_asset(path: Path) -> Optional[Image.Image]:
    """Load a brand asset as RGBA. Returns None (never raises) if missing,
    matching image_renderer.py's safe fallback behavior.
    """
    try:
        if not path.exists():
            print(f"[motion_renderer] WARNING: brand asset not found, skipping: {path}")
            return None
        return Image.open(path).convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - never let a bad asset crash rendering
        print(f"[motion_renderer] WARNING: could not load brand asset {path}: {exc}")
        return None


def _paste_scaled(canvas: Image.Image, asset: Image.Image, *, center_x: int, top_y: int, target_height: int) -> int:
    """Paste asset onto canvas scaled to target_height, centered horizontally.
    Returns rendered width. Mirrors image_renderer.paste_scaled().
    """
    aspect = asset.width / asset.height
    target_width = max(1, int(target_height * aspect))
    resized = asset.resize((target_width, target_height), Image.Resampling.LANCZOS)
    x = int(center_x - target_width / 2)
    canvas.paste(resized, (x, top_y), resized)
    return target_width


class _Layer:
    """A single overlay element: a transparent RGBA image, its top-left paste
    position on the video canvas, and explicit fade-in / (optional) fade-out
    timing. No motion other than opacity change is ever applied.

    - fade_in_start / fade_in_start + fade_in_duration: alpha ramps 0 -> 1.
    - If fade_out_start is set, alpha ramps 1 -> min_out_alpha starting at
      fade_out_start over fade_out_duration seconds.
    - Otherwise the element stays fully visible for the rest of the clip.

    fade_in_duration / fade_out_duration default to the shared FADE_DURATION
    but can be overridden per-layer so each scene can match its own exact
    timing spec (e.g. the hook's tighter 0.25s fade window).
    """

    def __init__(
        self,
        image: Image.Image,
        position: Tuple[int, int],
        fade_in_start: float,
        fade_out_start: Optional[float] = None,
        min_out_alpha: float = 0.0,
        fade_in_duration: float = FADE_DURATION,
        fade_out_duration: float = FADE_DURATION,
    ):
        self.position = position
        self.fade_in_start = fade_in_start
        self.fade_out_start = fade_out_start
        self.min_out_alpha = min_out_alpha
        self.fade_in_duration = fade_in_duration
        self.fade_out_duration = fade_out_duration
        # Precompute as numpy array once; alpha channel is scaled per-frame.
        self.array = np.array(image)  # H, W, 4 uint8
        self.base_alpha = self.array[:, :, 3].astype(np.float32)

    def alpha_at(self, t: float) -> float:
        if t <= self.fade_in_start:
            return 0.0
        if t < self.fade_in_start + self.fade_in_duration:
            alpha = (t - self.fade_in_start) / self.fade_in_duration
        else:
            alpha = 1.0

        if self.fade_out_start is not None and t > self.fade_out_start:
            if t >= self.fade_out_start + self.fade_out_duration:
                out_alpha = self.min_out_alpha
            else:
                progress = (t - self.fade_out_start) / self.fade_out_duration
                out_alpha = 1.0 - progress * (1.0 - self.min_out_alpha)
            alpha = min(alpha, out_alpha)
        return max(0.0, min(1.0, alpha))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    scratch = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        box = d.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _wrap_and_clamp(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> str:
    """Wrap text to max_width (via _wrap_text) and, as a minimal dynamic-text
    safeguard, clamp the result to at most max_lines lines. This does not
    change font size, spacing, or layout -- only prevents an unexpectedly
    long dynamic string from overflowing past its intended number of lines.

    Motion-video overlay text is never truncated mid-thought and never
    ends in an ellipsis (see HOOK_MAX_WORDS / EMOTIONAL_MAX_WORDS /
    _shorten_to_word_limit(), which keep Scene 1/2 text short enough that
    this line clamp is not expected to trigger in normal use). If an
    unusually long word or narrow width still causes overflow, the extra
    line(s) are dropped silently rather than adding "..." or cutting a
    word in half.
    """
    wrapped = _wrap_text(text, font, max_width)
    lines = wrapped.split("\n")
    if len(lines) <= max_lines:
        return wrapped
    return "\n".join(lines[:max_lines])


def _fit_text_to_max_lines(
    text: str,
    font_path: str,
    base_font_size: int,
    max_width: int,
    max_lines: int,
    min_font_size: int,
    size_step: int = 2,
) -> Tuple[ImageFont.FreeTypeFont, str]:
    """Find the largest font size (stepping down from base_font_size to
    min_font_size) whose wrapped `text` fits within max_lines lines at
    max_width, WITHOUT ever dropping or truncating a word.

    Every word of `text` is always preserved in the returned wrapped
    string. If even min_font_size still wraps to more than max_lines
    lines, that min_font_size wrapping is returned as-is (allowing extra
    lines rather than ever dropping a word) -- this is the deliberate
    "wrap to more lines if needed" fallback for Scene 1/2 text.
    """
    size = max(base_font_size, min_font_size)
    last_font: Optional[ImageFont.FreeTypeFont] = None
    last_wrapped: Optional[str] = None
    while size >= min_font_size:
        font = ImageFont.truetype(font_path, size)
        wrapped = _wrap_text(text, font, max_width)
        last_font, last_wrapped = font, wrapped
        if len(wrapped.split("\n")) <= max_lines:
            return font, wrapped
        size -= size_step
    return last_font, last_wrapped


def _make_text_layer(
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int, int],
    stroke_width: int = 2,
    stroke_fill: Tuple[int, int, int, int] = (0, 0, 0, 150),
    spacing: int = 10,
    backdrop_fill: Optional[Tuple[int, int, int, int]] = None,
    backdrop_padding: int = 0,
    backdrop_radius: int = 0,
) -> Tuple[Image.Image, Tuple[int, int]]:
    """Render `text` onto a tightly-cropped transparent RGBA image.

    If `backdrop_fill` is given, a subtle rounded rectangle in that color
    is drawn behind the text (inset by `backdrop_padding` on each side)
    before the text itself is drawn, giving a soft readability treatment
    without a hard-edged box.
    """
    scratch = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    box = d.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align="center", stroke_width=stroke_width
    )
    pad = stroke_width + 4 + backdrop_padding
    w = int(box[2] - box[0]) + pad * 2
    h = int(box[3] - box[1]) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if backdrop_fill is not None:
        draw.rounded_rectangle([0, 0, w, h], radius=backdrop_radius, fill=backdrop_fill)
    draw.multiline_text(
        (pad - box[0], pad - box[1]),
        text,
        font=font,
        fill=fill,
        spacing=spacing,
        align="center",
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return img, (w, h)


def _build_overlay_layers(canvas_size: Tuple[int, int], motion_copy: Dict[str, str]) -> List[_Layer]:
    """Build the hook-first emotional overlay sequence:

        Scene 1 (HOOK_START-HOOK_END):             pain_headline hook
        Scene 2 (EMOTIONAL_START-EMOTIONAL_END):    spiritual_action comfort/hope line
        Scene 3 (BRAND_START-BRAND_END):            logo + "Come pray with me."
        Scene 4 (FINAL_FRAME_START-VIDEO_END):      PRAYONIT + "Come pray with
                                                     me." + "Link in bio."

    Positions are expressed as fractions of the video's own width/height
    (see the SAFE_ZONE_*/*_CENTER_Y_FRAC constants above) so this works at
    any source resolution without cropping or resizing the video itself.
    Every element only ever fades in and/or softens out -- no other motion
    is applied (no zooms, no spins, no flash transitions).

    motion_copy must contain "pain_headline" and "emotional_line" string
    values (see _extract_motion_copy()). No app_benefit, download_cta,
    trial_support/URL, or store-badge content is ever rendered here.
    """
    width, height = canvas_size
    bold_path, regular_path = _get_fonts()

    # Font sizes scaled relative to a 1080-wide reference canvas, matching
    # the relative proportions used in image_renderer.py's Feed layout.
    scale = width / 1080.0

    def sz(base: int) -> int:
        return max(10, int(base * scale))

    logo_target_h = sz(72)  # calmer / smaller than the hook, per spec
    invitation_font = ImageFont.truetype(bold_path, sz(56))
    wordmark_font = ImageFont.truetype(bold_path, sz(50))
    link_in_bio_font = ImageFont.truetype(bold_path, sz(44))

    # Base (largest) font sizes Scene 1/2 start from before shrinking (see
    # _fit_text_to_max_lines): the actual font used for each scene is
    # chosen dynamically to fit its max line count without ever dropping
    # a word.
    HOOK_BASE_FONT_SIZE = sz(102)
    EMOTIONAL_BASE_FONT_SIZE = sz(72)

    # Minimum font sizes Scene 1/2 may shrink to while trying to fit their
    # max line count without ever dropping a word (see _fit_text_to_max_lines).
    HOOK_MIN_FONT_SIZE = sz(70)
    EMOTIONAL_MIN_FONT_SIZE = sz(50)

    # Subtle dark readability treatment behind Scene 1/2 text only (a soft
    # rounded panel, not a hard-edged box), so text stays legible over any
    # motion background without changing timing, layout, or scene order.
    READABILITY_BACKDROP_FILL = (0, 0, 0, 90)
    READABILITY_BACKDROP_PADDING = 24
    READABILITY_BACKDROP_RADIUS = 28

    layers: List[_Layer] = []
    max_text_width = int(width * SAFE_ZONE_MAX_TEXT_WIDTH_FRAC)

    hook_center_y = int(height * HOOK_CENTER_Y_FRAC)
    emotional_center_y = int(height * EMOTIONAL_CENTER_Y_FRAC)
    logo_center_y = int(height * LOGO_CENTER_Y_FRAC)
    invitation_center_y = int(height * BRAND_INVITATION_CENTER_Y_FRAC)
    wordmark_center_y = int(height * WORDMARK_CENTER_Y_FRAC)
    link_in_bio_center_y = int(height * LINK_IN_BIO_CENTER_Y_FRAC)

    # ---- Scene 1: Recognition hook (pain_headline) ----
    # Begins fading in at HOOK_START, fully readable by HOOK_FULLY_VISIBLE_BY,
    # begins fading out at HOOK_FADE_OUT_START, fully gone by HOOK_END. No
    # logo, wordmark, app benefit, CTA, URL, or store badges appear here.
    # The full generated sentence is always preserved: font size is shrunk
    # (down to HOOK_MIN_FONT_SIZE) as needed to fit within 2 lines; no word
    # is ever dropped, truncated, or replaced with an ellipsis.
    hook_font, hook_text = _fit_text_to_max_lines(
        motion_copy["pain_headline"],
        bold_path,
        HOOK_BASE_FONT_SIZE,
        max_text_width,
        max_lines=2,
        min_font_size=HOOK_MIN_FONT_SIZE,
    )
    hook_img, (hw, hh) = _make_text_layer(
        hook_text,
        hook_font,
        WHITE,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 170),
        backdrop_fill=READABILITY_BACKDROP_FILL,
        backdrop_padding=READABILITY_BACKDROP_PADDING,
        backdrop_radius=READABILITY_BACKDROP_RADIUS,
    )
    hx = int(width / 2 - hw / 2)
    hy = int(hook_center_y - hh / 2)
    layers.append(
        _Layer(
            hook_img,
            (hx, hy),
            fade_in_start=HOOK_START,
            fade_in_duration=HOOK_FADE_IN_DURATION,
            fade_out_start=HOOK_FADE_OUT_START,
            fade_out_duration=HOOK_FADE_OUT_DURATION,
            min_out_alpha=0.0,
        )
    )

    # ---- Scene 2: Comfort / hope (spiritual_action) ----
    # Fades in smoothly as Scene 1 exits, begins fading out at
    # EMOTIONAL_FADE_OUT_START, fully gone by EMOTIONAL_END. No logo, app
    # benefit, URL, or store badges appear here.
    # The full generated sentence is always preserved: font size is shrunk
    # (down to EMOTIONAL_MIN_FONT_SIZE) as needed to fit within 3 lines; no
    # word is ever dropped, truncated, or replaced with an ellipsis.
    emotional_font, emotional_text = _fit_text_to_max_lines(
        motion_copy["emotional_line"],
        bold_path,
        EMOTIONAL_BASE_FONT_SIZE,
        max_text_width,
        max_lines=10,
        min_font_size=EMOTIONAL_MIN_FONT_SIZE,
    )
    emotional_img, (ew, eh) = _make_text_layer(
        emotional_text,
        emotional_font,
        GOLD_ACCENT,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 160),
        backdrop_fill=READABILITY_BACKDROP_FILL,
        backdrop_padding=READABILITY_BACKDROP_PADDING,
        backdrop_radius=READABILITY_BACKDROP_RADIUS,
    )
    ex = int(width / 2 - ew / 2)
    ey = int(emotional_center_y - eh / 2)
    layers.append(
        _Layer(
            emotional_img,
            (ex, ey),
            fade_in_start=EMOTIONAL_START,
            fade_in_duration=EMOTIONAL_FADE_IN_DURATION,
            fade_out_start=EMOTIONAL_FADE_OUT_START,
            fade_out_duration=EMOTIONAL_FADE_OUT_DURATION,
            min_out_alpha=0.0,
        )
    )

    # ---- Scene 3: Soft brand reveal (logo + "Come pray with me.") ----
    # Fades in softly at BRAND_START and remains visible through the end of
    # the video (Scene 4 also shows the logo, per spec: "Logo may remain
    # visible from Scene 3"). No large boxed CTA button, app benefit, URL,
    # or store badges appear here.
    logo_asset = _load_brand_asset(LOGO_PATH)
    if logo_asset is not None:
        logo_canvas = Image.new("RGBA", (int(width * 0.6), logo_target_h + 10), (0, 0, 0, 0))
        _paste_scaled(
            logo_canvas, logo_asset, center_x=logo_canvas.width // 2, top_y=0, target_height=logo_target_h
        )
        lx = int(width / 2 - logo_canvas.width / 2)
        ly = int(logo_center_y - logo_canvas.height / 2)
        layers.append(
            _Layer(
                logo_canvas,
                (lx, ly),
                fade_in_start=BRAND_START,
                fade_in_duration=BRAND_FADE_IN_DURATION,
            )
        )

    invitation_text = _wrap_and_clamp(BRAND_INVITATION_TEXT, invitation_font, max_text_width, max_lines=1)
    invitation_img, (iw, ih) = _make_text_layer(
        invitation_text, invitation_font, WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 150)
    )
    ix = int(width / 2 - iw / 2)
    iy = int(invitation_center_y - ih / 2)
    layers.append(
        _Layer(
            invitation_img,
            (ix, iy),
            fade_in_start=BRAND_START,
            fade_in_duration=BRAND_FADE_IN_DURATION,
        )
    )

    # ---- Scene 4: Final invitation (PRAYONIT + "Link in bio.") ----
    # Fades in at FINAL_FRAME_START and stays visible through VIDEO_END.
    # Uses exactly "Link in bio." -- never prayonit.app, never store
    # badges, never a hard-sell button.
    wordmark_text = _wrap_and_clamp(BRAND_WORDMARK_TEXT, wordmark_font, max_text_width, max_lines=1)
    wordmark_img, (ww, wh) = _make_text_layer(
        wordmark_text, wordmark_font, GOLD_ACCENT, stroke_width=2, stroke_fill=(0, 0, 0, 150)
    )
    wx = int(width / 2 - ww / 2)
    wy = int(wordmark_center_y - wh / 2)
    layers.append(
        _Layer(
            wordmark_img,
            (wx, wy),
            fade_in_start=FINAL_FRAME_START,
            fade_in_duration=FINAL_FRAME_FADE_IN_DURATION,
        )
    )

    link_in_bio_text = _wrap_and_clamp(LINK_IN_BIO_TEXT, link_in_bio_font, max_text_width, max_lines=1)
    link_img, (lw, lh) = _make_text_layer(
        link_in_bio_text, link_in_bio_font, WHITE, stroke_width=1, stroke_fill=(0, 0, 0, 110)
    )
    lbx = int(width / 2 - lw / 2)
    lby = int(link_in_bio_center_y - lh / 2)
    layers.append(
        _Layer(
            link_img,
            (lbx, lby),
            fade_in_start=FINAL_FRAME_START,
            fade_in_duration=FINAL_FRAME_FADE_IN_DURATION,
        )
    )

    return layers


def render_motion_ad(
    ad_copy: Optional[Dict[str, Any]] = None,
    background_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    duration_seconds: float = DEFAULT_VIDEO_DURATION_SECONDS,
) -> Path:
    """Render the hook-first emotional Prayonit motion ad overlay onto a
    motion background video using dynamic copy, and write a silent .mp4.

    This is the single master 9:16 video reused for TikTok, Instagram
    Reels, Facebook Reels, and YouTube Shorts -- no per-platform variants
    are generated.

    Args:
        ad_copy: the same ad_copy dict already generated for Feed/Story by
            prompt_builder.generate_ad_copy() / generate_local_ad_copy()
            (after brand enforcement). If None, DEMO_COPY is used (manual
            standalone runs only). Only "pain_headline"/"story_headline"
            and "spiritual_action"/"story_spiritual_action" are read; see
            _extract_motion_copy().
        background_path: path to a motion background .mp4. If None, one is
            chosen at random from assets/motion_backgrounds/.
        output_path: destination .mp4 path. Defaults to
            output/videos/video_test.mp4 (the original standalone filename).
        duration_seconds: target output duration in seconds (default 8.00,
            matching VIDEO_END). The source clip is trimmed to this length
            if it is longer; if the source clip is shorter, its own
            (shorter) duration is used unchanged, exactly as before.

    No audio stream is ever encoded into the output MP4. Any
    temporary/intermediate files are written under output/temp/, never
    left in the output/ root. This function never uploads, queues, or
    publishes anything.
    """
    OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    motion_copy = _extract_motion_copy(ad_copy)

    bg_path = Path(background_path) if background_path is not None else _pick_random_motion_background()
    out_path = Path(output_path) if output_path is not None else OUTPUT_PATH
    print(f"[motion_renderer] Selected motion background: {bg_path.name}")

    bg_clip = VideoFileClip(str(bg_path))
    width, height = bg_clip.size
    fps = bg_clip.fps
    duration = bg_clip.duration
    if duration_seconds and duration > duration_seconds:
        bg_clip = bg_clip.subclipped(0, duration_seconds)
        duration = duration_seconds
    print(f"[motion_renderer] Source video: {width}x{height} @ {fps}fps, duration={duration:.2f}s")

    layers = _build_overlay_layers((width, height), motion_copy)

    def make_frame(t: float) -> np.ndarray:
        bg_frame = bg_clip.get_frame(t)  # H, W, 3 uint8 (RGB)
        base = Image.fromarray(bg_frame).convert("RGBA")
        for layer in layers:
            a = layer.alpha_at(t)
            if a <= 0.0:
                continue
            if a >= 1.0:
                frame_arr = layer.array
            else:
                frame_arr = layer.array.copy()
                frame_arr[:, :, 3] = (layer.base_alpha * a).astype(np.uint8)
            frame_img = Image.fromarray(frame_arr)
            base.alpha_composite(frame_img, dest=layer.position)
        return np.array(base.convert("RGB"))

    # Explicitly silent: no audio is attached to this clip at all (no
    # with_audio() call), and write_videofile is called with audio=False
    # so no audio stream is ever encoded into the output MP4, even if the
    # source background clip had its own audio track.
    composed = VideoClip(make_frame, duration=duration)
    composed = composed.with_fps(fps)

    print(f"[motion_renderer] Writing {out_path} (no audio) ...")
    composed.write_videofile(
        str(out_path),
        fps=fps,
        codec="libx264",
        audio=False,
        logger=None,
    )

    bg_clip.close()
    composed.close()
    print(f"[motion_renderer] Done: {out_path}")
    return out_path


if __name__ == "__main__":
    render_motion_ad()

