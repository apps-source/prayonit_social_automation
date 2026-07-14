"""Standalone proof-of-concept: TikTok/Reels-optimized Prayonit motion ad.

THIS FILE IS NOT PART OF THE PRODUCTION PIPELINE.

It does NOT import, call, or modify prayonit_social.py, image_renderer.py,
creative_engine_v3.py, prompt_builder.py, buffer_client.py, history_store.py,
tracking.py, campaign_engine.py, or any Supabase/QA/scheduling code. It only
reads static, read-only brand assets that already exist on disk
(assets/branding/*, system fonts) and a random .mp4 from
assets/motion_backgrounds/.

Run:
    ./.venv/bin/python motion_renderer.py

Output:
    output/videos/video_test.mp4 (silent, overwritten if it already exists)

Any temporary/intermediate rendering files are written under output/temp/
and are never left in the output/ root.

This version trims the ad down to a fast, TikTok-style hook sequence
(logo -> big headline -> "LET'S PRAY." -> CTA -> trial text -> store badges),
with no audio track in the exported file. See README_MOTION_RENDERER.md.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from moviepy import VideoFileClip, VideoClip

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

# ---------- Copy (hardcoded for this proof-of-concept only) ----------
# Trimmed for the TikTok/Reels hook test: no benefit line, no spiritual
# action line from v1 -- replaced with a short "LET'S PRAY." second beat.
COPY = {
    "pain_headline": "NEED PEACE TONIGHT?",
    "second_line": "LET'S PRAY.",
    "download_cta": "COME PRAY WITH ME",
    "trial_support": "Start your 14-day free trial.",
}

# ---------- Visual constants matched to image_renderer.py's Feed styling ----------
WHITE = (255, 255, 255, 255)
GOLD_ACCENT = (255, 226, 164, 255)
CTA_FILL = (20, 31, 45, 235)
CTA_OUTLINE = (255, 255, 255, 200)

FADE_DURATION = 0.5  # seconds for each fade-in / fade-out transition

# ---------- TikTok hook timing sequence (seconds), per the spec ----------
T_LOGO_IN = 0.3
T_HEADLINE_IN = 0.5
T_HEADLINE_OUT = 2.3       # headline starts softening/fading out here
T_SECOND_LINE_IN = 2.5
T_CTA_IN = 4.2
T_TRIAL_IN = 5.8
T_BADGES_IN = 6.2


def _pick_random_motion_background() -> Path:
    """Choose ONE random .mp4 from assets/motion_backgrounds/."""
    candidates = sorted(MOTION_BG_DIR.glob("*.mp4"))
    if not candidates:
        raise FileNotFoundError(
            f"No .mp4 files found in {MOTION_BG_DIR}. Add at least one motion "
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

    - fade_in_start / fade_in_start + FADE_DURATION: alpha ramps 0 -> 1.
    - If fade_out_start is set, alpha ramps 1 -> min_out_alpha starting at
      fade_out_start over FADE_DURATION seconds (used for the headline
      "softening" rather than a full disappear, per the spec's "fades out
      or softens").
    - Otherwise the element stays fully visible for the rest of the clip.
    """

    def __init__(
        self,
        image: Image.Image,
        position: Tuple[int, int],
        fade_in_start: float,
        fade_out_start: Optional[float] = None,
        min_out_alpha: float = 0.0,
    ):
        self.position = position
        self.fade_in_start = fade_in_start
        self.fade_out_start = fade_out_start
        self.min_out_alpha = min_out_alpha
        # Precompute as numpy array once; alpha channel is scaled per-frame.
        self.array = np.array(image)  # H, W, 4 uint8
        self.base_alpha = self.array[:, :, 3].astype(np.float32)

    def alpha_at(self, t: float) -> float:
        if t <= self.fade_in_start:
            return 0.0
        if t < self.fade_in_start + FADE_DURATION:
            alpha = (t - self.fade_in_start) / FADE_DURATION
        else:
            alpha = 1.0

        if self.fade_out_start is not None and t > self.fade_out_start:
            if t >= self.fade_out_start + FADE_DURATION:
                out_alpha = self.min_out_alpha
            else:
                progress = (t - self.fade_out_start) / FADE_DURATION
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


def _make_text_layer(
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int, int],
    stroke_width: int = 2,
    stroke_fill: Tuple[int, int, int, int] = (0, 0, 0, 150),
    spacing: int = 10,
) -> Tuple[Image.Image, Tuple[int, int]]:
    scratch = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    box = d.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align="center", stroke_width=stroke_width
    )
    pad = stroke_width + 4
    w = int(box[2] - box[0]) + pad * 2
    h = int(box[3] - box[1]) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
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


def _build_overlay_layers(canvas_size: Tuple[int, int]) -> List[_Layer]:
    """Build the trimmed TikTok/Reels overlay set: logo, big headline,
    "LET'S PRAY." second line, CTA button, trial text, store badges.
    Positions are expressed as fractions of the video's own width/height so
    this works at any source resolution without cropping or resizing the
    video itself. Every element only ever fades in (and, for the headline
    only, softens out) -- no other motion is applied.
    """
    width, height = canvas_size
    bold_path, regular_path = _get_fonts()

    # Font sizes scaled relative to a 1080-wide reference canvas, matching
    # the relative proportions used in image_renderer.py's Feed layout.
    scale = width / 1080.0

    def sz(base: int) -> int:
        return max(10, int(base * scale))

    # Headline is significantly larger than the v1 motion renderer (58pt
    # base) to work as a fast-hook TikTok title.
    headline_font = ImageFont.truetype(bold_path, sz(92))
    second_line_font = ImageFont.truetype(bold_path, sz(72))
    cta_font = ImageFont.truetype(bold_path, sz(int(44 * 1.12)))
    trial_font = ImageFont.truetype(bold_path, sz(int(28 * 1.08)))

    layers: List[_Layer] = []
    max_text_width = int(width * 0.86)

    # Vertical anchor points, spread across the safe area of a vertical
    # (9:16-style) canvas. All content is centered horizontally.
    logo_center_y = int(height * 0.14)
    headline_center_y = int(height * 0.40)
    second_line_center_y = int(height * 0.40)  # occupies same hook zone as headline
    cta_center_y = int(height * 0.66)
    trial_center_y = int(height * 0.73)
    badges_center_y = int(height * 0.80)

    # 1. Logo: fades in at 0.3s, stays visible for the rest of the clip.
    logo_asset = _load_brand_asset(LOGO_PATH)
    logo_target_h = sz(90)
    if logo_asset is not None:
        logo_canvas = Image.new("RGBA", (int(width * 0.6), logo_target_h + 10), (0, 0, 0, 0))
        _paste_scaled(
            logo_canvas, logo_asset, center_x=logo_canvas.width // 2, top_y=0, target_height=logo_target_h
        )
        x = int(width / 2 - logo_canvas.width / 2)
        y = int(logo_center_y - logo_canvas.height / 2)
        layers.append(_Layer(logo_canvas, (x, y), fade_in_start=T_LOGO_IN))

    # 2. Headline: large fade-in at 0.5s, softens (does not fully vanish)
    # starting at 2.3s so the cut to the second line reads cleanly.
    headline_text = _wrap_text(COPY["pain_headline"], headline_font, max_text_width)
    headline_img, (hw, hh) = _make_text_layer(
        headline_text, headline_font, WHITE, stroke_width=3, stroke_fill=(0, 0, 0, 170)
    )
    hx = int(width / 2 - hw / 2)
    hy = int(headline_center_y - hh / 2)
    layers.append(
        _Layer(
            headline_img,
            (hx, hy),
            fade_in_start=T_HEADLINE_IN,
            fade_out_start=T_HEADLINE_OUT,
            min_out_alpha=0.0,
        )
    )

    # 3. Second line "LET'S PRAY." fades in at 2.5s, stays for the rest.
    second_img, (sw, sh) = _make_text_layer(
        COPY["second_line"], second_line_font, GOLD_ACCENT, stroke_width=2, stroke_fill=(0, 0, 0, 160)
    )
    sx = int(width / 2 - sw / 2)
    sy = int(second_line_center_y - sh / 2)
    layers.append(_Layer(second_img, (sx, sy), fade_in_start=T_SECOND_LINE_IN))

    # 4. CTA button fades in at 4.2s, stays for the rest.
    cta_text = COPY["download_cta"].upper()
    scratch = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    cta_text_box = d.textbbox((0, 0), cta_text, font=cta_font)
    cta_text_w = cta_text_box[2] - cta_text_box[0]
    cta_text_h = cta_text_box[3] - cta_text_box[1]
    cta_pad_x = sz(72)
    cta_h = int(sz(100) * 1.15)
    cta_w = cta_text_w + cta_pad_x * 2
    cta_img = Image.new("RGBA", (cta_w, cta_h), (0, 0, 0, 0))
    cta_draw = ImageDraw.Draw(cta_img)
    cta_draw.rounded_rectangle((0, 0, cta_w, cta_h), radius=sz(24), fill=CTA_FILL, outline=CTA_OUTLINE, width=3)
    cta_draw.text(
        (cta_w / 2, cta_h / 2 - cta_text_box[1] - cta_text_h / 2),
        cta_text,
        font=cta_font,
        fill=WHITE,
        anchor="ma",
        stroke_width=1,
        stroke_fill=(0, 0, 0, 120),
    )
    cx = int(width / 2 - cta_w / 2)
    cy = int(cta_center_y - cta_h / 2)
    layers.append(_Layer(cta_img, (cx, cy), fade_in_start=T_CTA_IN))

    # 5. Trial-support text fades in at 5.8s, stays for the rest.
    trial_img, (tw, th) = _make_text_layer(
        COPY["trial_support"], trial_font, WHITE, stroke_width=1, stroke_fill=(0, 0, 0, 110)
    )
    tx = int(width / 2 - tw / 2)
    ty = int(trial_center_y - th / 2)
    layers.append(_Layer(trial_img, (tx, ty), fade_in_start=T_TRIAL_IN))

    # 6. Store badges row fades in at 6.2s (or later), stays for the rest.
    app_badge = _load_brand_asset(APP_STORE_BADGE_PATH)
    play_badge = _load_brand_asset(GOOGLE_PLAY_BADGE_PATH)
    badge_h = sz(56)
    if app_badge is not None and play_badge is not None:
        gap = sz(18)
        app_w = int(badge_h * (app_badge.width / app_badge.height))
        play_w = int(badge_h * (play_badge.width / play_badge.height))
        total_w = app_w + gap + play_w
        badges_canvas = Image.new("RGBA", (total_w, badge_h), (0, 0, 0, 0))
        _paste_scaled(badges_canvas, app_badge, center_x=app_w // 2, top_y=0, target_height=badge_h)
        _paste_scaled(badges_canvas, play_badge, center_x=app_w + gap + play_w // 2, top_y=0, target_height=badge_h)
        bx = int(width / 2 - total_w / 2)
        by = int(badges_center_y - badge_h / 2)
        layers.append(_Layer(badges_canvas, (bx, by), fade_in_start=T_BADGES_IN))

    return layers


def render_motion_ad() -> Path:
    """Render the trimmed TikTok/Reels Prayonit ad overlay onto a random
    motion background video and write a silent output/videos/video_test.mp4.
    Original resolution, FPS, and duration of the source clip are all
    preserved (no trim/speed changes). The exported file has no audio
    stream at all (no music, narration, or sound effects are added, and
    any source audio track is dropped). Any temporary/intermediate files
    are written under output/temp/, never left in the output/ root.
    """
    OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    bg_path = _pick_random_motion_background()
    print(f"[motion_renderer] Selected motion background: {bg_path.name}")

    bg_clip = VideoFileClip(str(bg_path))
    width, height = bg_clip.size
    fps = bg_clip.fps
    duration = bg_clip.duration
    print(f"[motion_renderer] Source video: {width}x{height} @ {fps}fps, duration={duration:.2f}s")

    layers = _build_overlay_layers((width, height))

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

    print(f"[motion_renderer] Writing {OUTPUT_PATH} (no audio) ...")
    composed.write_videofile(
        str(OUTPUT_PATH),
        fps=fps,
        codec="libx264",
        audio=False,
        logger=None,
    )

    bg_clip.close()
    composed.close()
    print(f"[motion_renderer] Done: {OUTPUT_PATH}")
    return OUTPUT_PATH


if __name__ == "__main__":
    render_motion_ad()
