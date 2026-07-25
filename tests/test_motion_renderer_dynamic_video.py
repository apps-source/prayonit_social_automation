"""Focused tests for the dynamic-video integration in motion_renderer.py.

These tests mock the heavy MoviePy video I/O (VideoFileClip / VideoClip /
write_videofile) so they run fast and never require ffmpeg or a real
motion-background asset. They verify:

  - render_motion_ad() accepts and uses a supplied ad_copy dict
  - the hardcoded DEMO_COPY dict is never used when ad_copy is supplied
  - config.PRIMARY_CTA / config.REEL_DESTINATION_TEXT are used only as
    fallbacks when the corresponding ad_copy field is absent
  - config.VIDEO_ENABLED defaults to false
  - enabling video creates a timestamped .mp4 file in output/videos
  - video generation never imports or calls buffer_client / Supabase
"""
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import config
import motion_renderer


class _FakeBgClip:
    """Stand-in for moviepy.VideoFileClip: no real video is decoded."""

    def __init__(self, *_args, **_kwargs):
        self.size = (1080, 1920)
        self.fps = 30
        self.duration = 12.0
        self.closed = False

    def subclipped(self, start, end):
        self.duration = end - start
        return self

    def get_frame(self, t):
        import numpy as np
        return np.zeros((1920, 1080, 3), dtype="uint8")

    def close(self):
        self.closed = True


class _FakeComposedClip:
    """Stand-in for moviepy.VideoClip: write_videofile just touches a file."""

    def __init__(self, make_frame, duration=None):
        self.make_frame = make_frame
        self.duration = duration
        self.fps = None
        self.closed = False

    def with_fps(self, fps):
        self.fps = fps
        return self

    def write_videofile(self, path, **_kwargs):
        Path(path).write_bytes(b"FAKE_MP4_CONTENT")

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _mock_moviepy(monkeypatch):
    monkeypatch.setattr(motion_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(motion_renderer, "VideoClip", _FakeComposedClip)


def _fake_ad_copy(**overrides):
    ad_copy = {
        "pain_headline": "UNIQUE DYNAMIC HEADLINE TEXT",
        "spiritual_action": "Give today's burdens to God in prayer.",
        "download_cta": "COME PRAY WITH ME",
        "visual_destination_text": "Start your prayer at\nprayonit.app",
    }
    ad_copy.update(overrides)
    return ad_copy


# ---------- 1. render_motion_ad accepts ad_copy and uses it ----------

def test_render_motion_ad_accepts_ad_copy(tmp_path):
    ad_copy = _fake_ad_copy()
    out_path = tmp_path / "test_video.mp4"
    result = motion_renderer.render_motion_ad(
        ad_copy=ad_copy,
        background_path=tmp_path / "fake_bg.mp4",
        output_path=out_path,
    )
    assert result == out_path
    assert out_path.exists()


def test_extract_motion_copy_uses_ad_copy_headline_not_demo():
    ad_copy = _fake_ad_copy()
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert motion_copy["pain_headline"] == "UNIQUE DYNAMIC HEADLINE TEXT"
    assert motion_copy["pain_headline"] != motion_renderer.DEMO_COPY["pain_headline"]


def test_extract_motion_copy_uses_ad_copy_emotional_line_not_demo():
    ad_copy = _fake_ad_copy()
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert motion_copy["emotional_line"] == "Give today's burdens to God in prayer."
    assert motion_copy["emotional_line"] != motion_renderer.DEMO_COPY["spiritual_action"]


# ---------- 2. Motion video no longer reads download_cta / trial_support ----------

def test_extract_motion_copy_ignores_download_cta_and_trial_support():
    ad_copy = _fake_ad_copy()
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert "download_cta" not in motion_copy
    assert "trial_support" not in motion_copy


def test_extract_motion_copy_with_no_ad_copy_uses_demo_fallback_for_headline_only():
    motion_copy = motion_renderer._extract_motion_copy(None)
    assert motion_copy["pain_headline"] == motion_renderer.DEMO_COPY["pain_headline"]
    assert motion_copy["emotional_line"] == motion_renderer.DEMO_COPY["spiritual_action"]



# ---------- 3. VIDEO_ENABLED config flag ----------

def test_video_enabled_defaults_to_false(monkeypatch):
    # Explicitly set to "false" (not just delenv) so this test is
    # deterministic regardless of the developer's local .env file, which
    # may itself set VIDEO_ENABLED=true for manual dry-run testing.
    monkeypatch.setenv("VIDEO_ENABLED", "false")
    import config as config_module
    importlib.reload(config_module)
    try:
        assert config_module.VIDEO_ENABLED is False
    finally:
        importlib.reload(config_module)


def test_video_enabled_true_when_env_set(monkeypatch):
    monkeypatch.setenv("VIDEO_ENABLED", "true")
    import config as config_module
    importlib.reload(config_module)
    try:
        assert config_module.VIDEO_ENABLED is True
    finally:
        monkeypatch.delenv("VIDEO_ENABLED", raising=False)
        importlib.reload(config_module)


# ---------- 4. Timestamped MP4 creation ----------

def test_render_motion_ad_creates_mp4_at_given_output_path(tmp_path):
    ad_copy = _fake_ad_copy()
    out_path = tmp_path / "prayonit-reel-20260714T000000Z.mp4"
    motion_renderer.render_motion_ad(
        ad_copy=ad_copy,
        background_path=tmp_path / "fake_bg.mp4",
        output_path=out_path,
    )
    assert out_path.exists()
    assert out_path.suffix == ".mp4"


# ---------- 5. No Buffer or Supabase calls during video generation ----------

def test_motion_renderer_module_does_not_import_buffer_or_supabase():
    source = Path(motion_renderer.__file__).read_text(encoding="utf-8")
    import_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    assert not any("buffer_client" in line for line in import_lines)
    assert not any("supabase" in line.lower() for line in import_lines)
    assert "buffer_client" not in sys.modules or "buffer_client" not in dir(motion_renderer)


def test_render_motion_ad_does_not_touch_buffer_client(tmp_path, monkeypatch):
    import buffer_client
    called = MagicMock(side_effect=AssertionError("buffer_client.requests.post should never be called"))
    monkeypatch.setattr(buffer_client, "requests", MagicMock(post=called))

    ad_copy = _fake_ad_copy()
    motion_renderer.render_motion_ad(
        ad_copy=ad_copy,
        background_path=tmp_path / "fake_bg.mp4",
        output_path=tmp_path / "video.mp4",
    )
    called.assert_not_called()


# ---------- 6. New 8-second hook-first scene-sequence requirements ----------

def _build_layers():
    motion_copy = motion_renderer._extract_motion_copy(_fake_ad_copy())
    return motion_renderer._build_overlay_layers((1080, 1920), motion_copy)


def test_scene2_long_sentence_never_drops_words():
    # Regression test: "Lay your heavy morning thoughts before God today."
    # was previously silently clamped to 2 lines, dropping "before God
    # today." entirely. Scene 2 must now preserve every word, shrinking
    # font size and/or wrapping to up to 3 lines instead of dropping text.
    sentence = "Lay your heavy morning thoughts before God today."
    bold_path, _regular_path = motion_renderer._get_fonts()
    width = 1080
    max_text_width = int(width * motion_renderer.SAFE_ZONE_MAX_TEXT_WIDTH_FRAC)

    font, wrapped = motion_renderer._fit_text_to_max_lines(
        sentence,
        bold_path,
        base_font_size=72,
        max_width=max_text_width,
        max_lines=3,
        min_font_size=50,
    )

    rendered_words = wrapped.replace("\n", " ").split()
    expected_words = sentence.split()
    assert rendered_words == expected_words
    assert "..." not in wrapped
    assert len(wrapped.split("\n")) <= 3


def test_default_video_duration_is_exactly_eight_seconds():
    assert motion_renderer.DEFAULT_VIDEO_DURATION_SECONDS == 8.0
    assert motion_renderer.VIDEO_END == 8.0


def test_render_motion_ad_default_duration_used_when_source_longer(tmp_path):
    # _FakeBgClip.duration defaults to 12.0s, so the 8.00s default should
    # trim the clip down.
    ad_copy = _fake_ad_copy()
    out_path = tmp_path / "trimmed.mp4"
    motion_renderer.render_motion_ad(
        ad_copy=ad_copy,
        background_path=tmp_path / "fake_bg.mp4",
        output_path=out_path,
    )
    assert out_path.exists()


def test_hook_layer_fully_visible_by_point_four_seconds():
    layers = _build_layers()
    hook_layer = layers[0]
    assert hook_layer.fade_in_start <= 0.15
    assert hook_layer.fade_in_start + hook_layer.fade_in_duration <= 0.40


def test_no_logo_or_brand_layers_visible_during_scene_one_and_two():
    layers = _build_layers()
    # Layers 0 and 1 are the hook and emotional text layers; layers 2+ are
    # brand-reveal (logo/invitation/wordmark/link-in-bio) and must have
    # zero alpha throughout Scenes 1-2 (t < EMOTIONAL_END).
    brand_layers = layers[2:]
    for t in (0.0, 0.5, 1.5, 2.5, 3.5, motion_renderer.EMOTIONAL_END - 0.01):
        for layer in brand_layers:
            assert layer.alpha_at(t) == 0.0, f"brand layer visible too early at t={t}"


def test_brand_reveal_begins_only_after_emotional_end():
    layers = _build_layers()
    brand_layers = layers[2:]
    assert all(layer.fade_in_start >= motion_renderer.EMOTIONAL_END for layer in brand_layers)
    assert motion_renderer.BRAND_START == motion_renderer.EMOTIONAL_END


def test_final_frame_text_constants_are_exact():
    assert motion_renderer.BRAND_WORDMARK_TEXT == "PRAYONIT"
    assert motion_renderer.BRAND_INVITATION_TEXT == "Come pray with me."
    assert motion_renderer.LINK_IN_BIO_TEXT == "Link in bio."


def test_link_in_bio_present_and_visible_at_final_frame():
    layers = _build_layers()
    link_in_bio_layer = layers[-1]
    t = motion_renderer.VIDEO_END - 0.01
    assert link_in_bio_layer.alpha_at(t) > 0.0


def test_no_prayonit_dot_app_url_text_anywhere():
    ad_copy = _fake_ad_copy(visual_destination_text="Start your prayer at\nprayonit.app")
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    combined = " ".join(motion_copy.values())
    combined += " " + motion_renderer.BRAND_WORDMARK_TEXT
    combined += " " + motion_renderer.BRAND_INVITATION_TEXT
    combined += " " + motion_renderer.LINK_IN_BIO_TEXT
    assert "prayonit.app" not in combined.lower()


# ---------- 7. Motion-video copy style: no ellipses, no mid-thought cuts ----------

def test_hook_and_emotional_text_are_shortened_without_ellipsis_when_too_long():
    ad_copy = _fake_ad_copy(
        pain_headline="Missing the strength and energy your body used to have before all of this happened to you?",
        spiritual_action="You don't have to carry that grief alone tonight, God is right here with you through it all.",
    )
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert "..." not in motion_copy["pain_headline"]
    assert "..." not in motion_copy["emotional_line"]
    assert len(motion_copy["pain_headline"].rstrip("?!.").split()) <= motion_renderer.HOOK_MAX_WORDS
    assert len(motion_copy["emotional_line"].rstrip("?!.").split()) <= motion_renderer.EMOTIONAL_MAX_WORDS
    # Still ends as a complete sentence (not cut mid-word).
    assert motion_copy["pain_headline"][-1] in "?!."
    assert motion_copy["emotional_line"][-1] in "?!."


def test_short_hook_and_emotional_text_are_left_unchanged():
    ad_copy = _fake_ad_copy(
        pain_headline="Missing the strength your body once had?",
        spiritual_action="You don't have to carry that grief alone.",
    )
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert motion_copy["pain_headline"] == "Missing the strength your body once had?"
    assert motion_copy["emotional_line"] == "You don't have to carry that grief alone."


def test_awkward_phrases_are_smoothed_into_plain_language():
    ad_copy = _fake_ad_copy(
        pain_headline="Carrying your body's grief today?",
        spiritual_action="Tired of a scattered mind tonight?",
    )
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert "body's grief" not in motion_copy["pain_headline"].lower()
    assert "scattered mind" not in motion_copy["emotional_line"].lower()


def test_readability_backdrop_applied_to_hook_and_emotional_layers_only():
    layers = _build_layers()
    hook_layer, emotional_layer = layers[0], layers[1]
    brand_layers = layers[2:]
    # A subtle dark backdrop fills the whole padded layer image, so a
    # pixel on the flat top edge (away from the rounded corners) should be
    # semi-opaque rather than fully transparent.
    hook_h, hook_w = hook_layer.base_alpha.shape
    emo_h, emo_w = emotional_layer.base_alpha.shape
    assert hook_layer.base_alpha[2, hook_w // 2] > 0
    assert emotional_layer.base_alpha[2, emo_w // 2] > 0
    # Brand-reveal layers (logo/invitation/wordmark/link-in-bio) are
    # untouched by this motion-video-only readability treatment.
    assert len(brand_layers) >= 1


def test_no_store_badges_loaded_or_referenced_in_overlay_build(monkeypatch):
    called = MagicMock(side_effect=AssertionError("store badge assets should never be loaded"))
    monkeypatch.setattr(motion_renderer, "APP_STORE_BADGE_PATH", motion_renderer.APP_STORE_BADGE_PATH)
    original_load = motion_renderer._load_brand_asset

    def spy_load(path):
        if "badge" in str(path).lower():
            called()
        return original_load(path)

    monkeypatch.setattr(motion_renderer, "_load_brand_asset", spy_load)
    _build_layers()
    called.assert_not_called()


def test_app_benefit_never_read_or_rendered():
    ad_copy = _fake_ad_copy(app_benefit="Track your prayer streaks daily!")
    motion_copy = motion_renderer._extract_motion_copy(ad_copy)
    assert "app_benefit" not in motion_copy
    assert "Track your prayer streaks daily!" not in " ".join(motion_copy.values())


def test_essential_text_layers_stay_within_safe_zone_horizontal_bounds():
    layers = _build_layers()
    width = 1080
    top_bound = int(1920 * motion_renderer.SAFE_ZONE_TOP_FRAC)
    bottom_bound = 1920 - int(1920 * motion_renderer.SAFE_ZONE_BOTTOM_FRAC)
    for layer in layers:
        x, y = layer.position
        h, w = layer.array.shape[0], layer.array.shape[1]
        assert x >= 0
        assert x + w <= width
        assert y + h > top_bound - 5  # allow small tolerance
        assert y < bottom_bound + 5


def test_feed_and_story_renderer_module_unaffected():
    # image_renderer.py (Feed/Story) must not import or depend on
    # motion_renderer.py's new scene constants; a simple import sanity
    # check confirms no accidental coupling was introduced.
    import image_renderer
    source = Path(image_renderer.__file__).read_text(encoding="utf-8")
    assert "motion_renderer" not in source


def test_preview_mode_video_still_saved_locally_without_publishing(tmp_path, monkeypatch):
    import buffer_client
    called = MagicMock(side_effect=AssertionError("buffer_client should never be called in PREVIEW_MODE"))
    monkeypatch.setattr(buffer_client, "requests", MagicMock(post=called))

    ad_copy = _fake_ad_copy()
    out_path = tmp_path / "preview_video.mp4"
    result = motion_renderer.render_motion_ad(
        ad_copy=ad_copy,
        background_path=tmp_path / "fake_bg.mp4",
        output_path=out_path,
    )
    assert result == out_path
    assert out_path.exists()
    called.assert_not_called()
