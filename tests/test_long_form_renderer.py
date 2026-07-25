from pathlib import Path
import math
import struct
import wave

import numpy as np
from PIL import Image

import long_form_renderer
import prayonit_social
import voice_provider


class _FakeBgClip:
    def __init__(self, path):
        self.path = Path(path)
        self.size = (1080, 1920)
        self.fps = 30
        self.duration = 12.0
        self.closed = False

    def get_frame(self, _t):
        return np.zeros((1920, 1080, 3), dtype="uint8")

    def close(self):
        self.closed = True


class _FakeComposedClip:
    instances = []

    def __init__(self, make_frame, duration=None):
        self.make_frame = make_frame
        self.duration = duration
        self.fps = None
        self.closed = False
        self.audio_clip = None
        self.write_kwargs = None
        self.write_paths = []
        _FakeComposedClip.instances.append(self)

    def with_fps(self, fps):
        self.fps = fps
        return self

    def with_audio(self, audio_clip):
        self.audio_clip = audio_clip
        return self

    def write_videofile(self, path, **_kwargs):
        self.write_kwargs = _kwargs
        self.write_paths.append(Path(path))
        Path(path).write_bytes(b"FAKE_LONG_MP4")

    def close(self):
        self.closed = True


class _FakeAudioClip:
    def __init__(self, path):
        self.path = Path(path)
        self.closed = False

    def close(self):
        self.closed = True


def _tone_wav(path: Path, *, seconds: float = 1.0, leading_silence_seconds: float = 0.0, rate: int = 24000):
    total_frames = int(rate * (seconds + leading_silence_seconds))
    silence_frames = int(rate * leading_silence_seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = bytearray()
        for i in range(total_frames):
            if i < silence_frames:
                sample = 0
            else:
                tone_index = i - silence_frames
                sample = int(10000 * math.sin(2 * math.pi * 440 * (tone_index / rate)))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))


def _segmented_tone_wav(
    path: Path,
    *,
    segment_seconds,
    pause_seconds,
    leading_silence_seconds: float = 0.0,
    rate: int = 24000,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = bytearray()
        for _ in range(int(rate * leading_silence_seconds)):
            frames.extend(struct.pack("<h", 0))
        for index, duration in enumerate(segment_seconds):
            for i in range(int(rate * duration)):
                sample = int(10000 * math.sin(2 * math.pi * 440 * (i / rate)))
                frames.extend(struct.pack("<h", sample))
            if index < len(pause_seconds):
                for _ in range(int(rate * pause_seconds[index])):
                    frames.extend(struct.pack("<h", 0))
        wav_file.writeframes(bytes(frames))


def _presentation(video_template="long_prayer", **overrides):
    config = {
        "content_type": "prayer_read",
        "video_template": video_template,
        "video_library": "long",
        "duration_seconds": 30,
        "marketing_enabled": False,
        "show_logo": True,
        "show_badges": False,
        "show_cta": True,
        "show_link_in_bio": True,
        "show_app_benefit": False,
        "engagement_prompt_enabled": True,
        "engagement_prompt_type": "save_or_share",
        "cta_text": "Come pray with me.",
    }
    config.update(overrides)
    return config


def _long_copy(long_form_type="prayer", **overrides):
    copy = {
        "brand_header": "PRAYONIT",
        "pain_headline": "Feeling overwhelmed today?",
        "spiritual_action": "Bring it to God in prayer.",
        "app_benefit": "Get a guided, personalized prayer based on your mood right now.",
        "download_cta": "COME PRAY WITH ME",
        "trial_support": "Start your prayer at\nprayonit.app",
        "facebook_caption": "x",
        "instagram_caption": "x",
        "threads_caption": "x",
        "story_headline": "Feeling overwhelmed?",
        "story_spiritual_action": "Bring it to God.",
        "story_app_benefit": "A guided prayer for how you feel.",
        "story_download_cta": "COME PRAY WITH ME",
        "story_trial_support": "Start your prayer at\nprayonit.app",
        "long_form_type": long_form_type,
        "opening_hook": "God sees your burden.",
        "bridge_line": "Let this prayer meet you right where you are.",
        "script_segments": [
            "Lord, meet me in this moment and calm the worries I have been carrying.",
            "Give me strength to trust You with what feels heavy and wisdom for the next step in front of me.",
            "Cover this day with Your peace and help me remember that I do not walk through it alone.",
        ],
        "closing_line": "Amen.",
        "engagement_line": "Save this prayer for later today.",
        "estimated_spoken_seconds": 30,
    }
    copy.update(overrides)
    return copy


def _patch_cmd_run_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(prayonit_social.config, "require_env", lambda test_mode, preview_mode=False: None)
    monkeypatch.setattr(prayonit_social.config, "validate_destination_config", lambda: None)
    monkeypatch.setattr(prayonit_social, "get_supabase_client", lambda: object())
    monkeypatch.setattr(prayonit_social, "list_backgrounds", lambda supabase: ["bg.jpg"])
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_selection",
        lambda slot: {
            "campaign": {
                "name": "Anxiety",
                "pain_point": "anxious",
                "goal": "peace",
                "hooks": ["h"],
                "body_angles": ["b"],
                "ctas": ["c"],
                "thread_topics": ["t"],
                "instagram_hashtags": ["#Prayonit"],
                "threads_hashtags": ["#Prayonit"],
            },
            "formula": {"name": "f"},
            "persona": {"name": "p"},
            "seasonal_context": None,
            "hook": "h",
            "body_angle": "b",
            "cta": "c",
            "thread_topic": "t",
            "relaxed_rules": [],
            "emotional_territory": "insomnia",
        },
    )
    monkeypatch.setattr(
        prayonit_social.campaign_engine,
        "choose_background",
        lambda *args, **kwargs: {
            "path": "bg.jpg",
            "metadata": {"time": "morning", "visual_types": ["lake"], "emotional_suitability": ["insomnia"]},
            "match_score": 3.0,
            "emotional_territory": "insomnia",
        },
    )
    monkeypatch.setattr(prayonit_social.campaign_engine, "pick_spiritual_action", lambda campaign, slot: "Bring it to God.")
    monkeypatch.setattr(prayonit_social.prompt_builder, "build_platform_captions", lambda *args, **kwargs: {"facebook": "f", "instagram": "i", "threads": "t"})
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": [], "pass": True, "score": 100})
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: (_ for _ in ()).throw(AssertionError("tracking called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("video upload called")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))
    motion_dir = tmp_path / "motion_backgrounds"
    motion_dir.mkdir()
    (motion_dir / "bg1.mp4").write_bytes(b"fake")
    monkeypatch.setattr(prayonit_social.config, "MOTION_BACKGROUNDS_DIR", motion_dir)


def test_select_long_form_video_assets_uses_four_to_six_unique_clips_when_available(tmp_path):
    video_dir = tmp_path / "long"
    video_dir.mkdir()
    for index in range(6):
        (video_dir / f"clip{index}.mp4").write_bytes(b"x")
    selected = long_form_renderer.select_long_form_video_assets(long_video_dir=video_dir)
    assert 4 <= len(selected) <= 6
    assert len({spec.path.name for spec in selected}) == len(selected)


def test_select_long_form_video_assets_reuses_only_when_library_is_small(tmp_path):
    video_dir = tmp_path / "long"
    video_dir.mkdir()
    for index in range(2):
        (video_dir / f"clip{index}.mp4").write_bytes(b"x")
    selected = long_form_renderer.select_long_form_video_assets(long_video_dir=video_dir)
    assert len(selected) == 4
    assert len({spec.path.name for spec in selected}) == 2


def test_build_clip_plan_has_crossfades_and_matches_target_duration(tmp_path):
    clips = []
    durations = {}
    for index in range(5):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        clips.append(long_form_renderer.VideoAssetSpec(path))
        durations[path] = 12.0
    plan = long_form_renderer.build_clip_plan(clips, durations, 30.0)
    assert len(plan) == 5
    assert plan[-1].clip_end == 30.0
    assert any(item.crossfade_out > 0 for item in plan[:-1])
    assert any(item.crossfade_in > 0 for item in plan[1:])


def test_build_script_cards_preserves_order_and_words_without_ellipses():
    cards = long_form_renderer.build_script_cards(_long_copy(), _presentation(), 30.0)
    script_texts = [card.text for card in cards if card.kind == "script_segment"]
    assert script_texts == _long_copy()["script_segments"]
    assert all("..." not in card.text for card in cards)


def test_build_script_cards_include_closing_line():
    cards = long_form_renderer.build_script_cards(_long_copy(), _presentation(), 30.0)
    assert any(card.kind == "closing_line" and card.text == "Amen." for card in cards)


def test_actual_audio_duration_controls_long_form_timing():
    total_duration, hook_window, brand_start = long_form_renderer.resolve_long_form_duration(
        _long_copy(),
        _presentation(),
        narration_duration=18.5,
    )
    assert hook_window == long_form_renderer.OPENING_HOOK_DURATION
    assert brand_start == hook_window + 18.5
    assert total_duration >= brand_start + long_form_renderer.FINAL_BRAND_DURATION


def test_captions_span_the_narration_duration():
    timeline = voice_provider.build_narration_segment_timeline(
        _long_copy(),
        18.0,
        hook_window=long_form_renderer.OPENING_HOOK_DURATION,
    )
    assert timeline[0]["start"] == long_form_renderer.OPENING_HOOK_DURATION
    assert timeline[-1]["end"] == long_form_renderer.OPENING_HOOK_DURATION + 18.0
    assert timeline[0]["text"] == _long_copy()["bridge_line"]


def test_no_hook_content_starts_narration_near_zero_seconds():
    copy = _long_copy(opening_hook="")
    timeline = voice_provider.build_narration_segment_timeline(copy, 8.0, hook_window=0.0)
    assert long_form_renderer._resolve_narration_start_time(copy, timeline) == 0.0
    cards, _source, _boundaries = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=Path("/dev/null"),
        trim_seconds=0.0,
        actual_speech_start_time=long_form_renderer.NARRATION_SYNC_DELAY_SECONDS,
        audio_offset_seconds=long_form_renderer.NARRATION_SYNC_DELAY_SECONDS,
        remaining_lead_seconds=0.0,
        brand_start=12.0,
    )
    first_narrated = [card for card in cards if card.kind != "opening_hook"][0]
    assert 0.0 <= first_narrated.start <= 0.35


def test_hook_content_starts_narration_immediately_after_hook_window():
    copy = _long_copy()
    timeline = voice_provider.build_narration_segment_timeline(
        copy,
        8.0,
        hook_window=long_form_renderer.OPENING_HOOK_DURATION,
    )
    assert long_form_renderer._resolve_narration_start_time(copy, timeline) == long_form_renderer.OPENING_HOOK_DURATION
    cards, _source, _boundaries = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=Path("/dev/null"),
        trim_seconds=0.0,
        actual_speech_start_time=long_form_renderer.OPENING_HOOK_DURATION + long_form_renderer.NARRATION_SYNC_DELAY_SECONDS,
        audio_offset_seconds=long_form_renderer.OPENING_HOOK_DURATION + long_form_renderer.NARRATION_SYNC_DELAY_SECONDS,
        remaining_lead_seconds=0.0,
        brand_start=12.0,
    )
    non_hook_cards = [card for card in cards if card.kind != "opening_hook"]
    assert non_hook_cards[0].start >= long_form_renderer.OPENING_HOOK_DURATION
    assert abs(non_hook_cards[0].start - (long_form_renderer.OPENING_HOOK_DURATION + long_form_renderer.NARRATION_SYNC_DELAY_SECONDS - long_form_renderer.CAPTION_LEAD_SECONDS)) < 0.01


def test_extra_wav_leading_silence_is_trimmed_conservatively(tmp_path):
    audio_path = tmp_path / "leading.wav"
    _tone_wav(audio_path, seconds=1.0, leading_silence_seconds=0.20)
    leading = long_form_renderer._detect_wav_leading_silence(audio_path)
    assert 0.18 <= leading <= 0.22
    trim = max(0.0, leading - long_form_renderer.LEADING_SILENCE_PRESERVE_SECONDS)
    assert 0.15 <= trim <= 0.19


def test_build_final_brand_layers_respect_presentation_flags():
    layers = long_form_renderer.build_final_brand_layers(
        _long_copy(),
        _presentation(show_logo=True, show_cta=True, show_link_in_bio=True, show_badges=False, show_app_benefit=False),
        long_form_renderer.TARGET_CANVAS_SIZE,
        30.0,
    )
    labels = [layer.label for layer in layers]
    assert "logo" in labels
    assert "cta" in labels
    assert "link_in_bio" in labels
    assert "badge" not in labels
    assert "app_benefit" not in labels


def test_prayer_content_final_brand_stays_inside_safe_zone():
    layers = long_form_renderer.build_final_brand_layers(
        _long_copy(),
        _presentation(),
        long_form_renderer.TARGET_CANVAS_SIZE,
        30.0,
    )
    _width, height = long_form_renderer.TARGET_CANVAS_SIZE
    top_bound = int(height * long_form_renderer.SAFE_ZONE_TOP_FRAC)
    bottom_bound = height - int(height * long_form_renderer.SAFE_ZONE_BOTTOM_FRAC)
    for layer in layers:
        assert layer.position[1] >= top_bound
        assert layer.position[1] + layer.image.height <= bottom_bound + 2


def test_render_long_form_video_uses_requested_duration(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    out_path = tmp_path / "long.mp4"
    result = long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=out_path,
    )
    assert result == out_path
    assert out_path.exists()
    assert _FakeComposedClip.instances[-1].duration == 25.0


def test_long_form_mp4_includes_audio_track_when_voice_is_enabled(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    audio_path = tmp_path / "voice.wav"
    _tone_wav(audio_path, seconds=4.0, leading_silence_seconds=0.0)
    out_path = tmp_path / "long-audio.mp4"
    timeline = voice_provider.build_narration_segment_timeline(_long_copy(), 4.0, hook_window=2.5)
    mux_calls = []
    verify_calls = []

    def fake_mux(**kwargs):
        mux_calls.append(kwargs)
        kwargs["output_path"].write_bytes(b"FAKE_MUXED_MP4")

    def fake_verify(path):
        verify_calls.append(path)
        return {"video_found": True, "audio_found": True, "audio_duration": 4.0, "duration": 10.5}

    monkeypatch.setattr(long_form_renderer, "_mux_narration_audio", fake_mux)
    monkeypatch.setattr(long_form_renderer, "_verify_exported_mp4", fake_verify)
    result = long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=out_path,
        narration_audio_path=audio_path,
        narration_duration=4.0,
        narration_segment_timeline=timeline,
    )
    instance = _FakeComposedClip.instances[-1]
    assert result == out_path
    assert instance.write_kwargs["audio"] is False
    assert instance.write_paths[-1].name == "long-audio.silent.mp4"
    assert mux_calls[0]["output_path"] == out_path
    assert abs(mux_calls[0]["audio_offset_seconds"] - 3.15) < 0.05
    assert verify_calls == [out_path]
    assert out_path.exists()


def test_narration_audio_offset_is_preserved_in_final_mp4(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    audio_path = tmp_path / "voice.wav"
    _tone_wav(audio_path, seconds=1.0, leading_silence_seconds=0.20)
    timeline = voice_provider.build_narration_segment_timeline(_long_copy(), 1.2, hook_window=2.5)
    recorded = {}

    def fake_mux(**kwargs):
        recorded.update(kwargs)
        kwargs["output_path"].write_bytes(b"FAKE_MUXED_MP4")

    monkeypatch.setattr(long_form_renderer, "_mux_narration_audio", fake_mux)
    monkeypatch.setattr(
        long_form_renderer,
        "_verify_exported_mp4",
        lambda path: {"video_found": True, "audio_found": True, "audio_duration": 1.2, "duration": 7.7},
    )

    long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=tmp_path / "offset.mp4",
        narration_audio_path=audio_path,
        narration_duration=1.2,
        narration_segment_timeline=timeline,
    )

    assert 0.16 <= recorded["audio_trim_seconds"] <= 0.18
    assert 3.11 <= recorded["audio_offset_seconds"] <= 3.13


def test_no_duplicate_lead_in_silence_when_hook_and_wav_both_have_lead_in(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    audio_path = tmp_path / "voice.wav"
    _tone_wav(audio_path, seconds=1.0, leading_silence_seconds=0.30)
    timeline = voice_provider.build_narration_segment_timeline(_long_copy(), 1.3, hook_window=2.5)
    recorded = {}

    def fake_mux(**kwargs):
        recorded.update(kwargs)
        kwargs["output_path"].write_bytes(b"FAKE_MUXED_MP4")

    monkeypatch.setattr(long_form_renderer, "_mux_narration_audio", fake_mux)
    monkeypatch.setattr(
        long_form_renderer,
        "_verify_exported_mp4",
        lambda path: {"video_found": True, "audio_found": True, "audio_duration": 1.3, "duration": 7.8},
    )

    long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=tmp_path / "dedupe.mp4",
        narration_audio_path=audio_path,
        narration_duration=1.3,
        narration_segment_timeline=timeline,
    )

    remaining_lead = 0.30 - recorded["audio_trim_seconds"]
    assert remaining_lead <= long_form_renderer.LEADING_SILENCE_PRESERVE_SECONDS + 0.01
    assert abs((recorded["audio_offset_seconds"] + remaining_lead) - (2.5 + long_form_renderer.NARRATION_SYNC_DELAY_SECONDS)) <= 0.05


def test_first_caption_appears_before_first_audible_speech():
    copy = _long_copy()
    timeline = voice_provider.build_narration_segment_timeline(copy, 8.0, hook_window=long_form_renderer.OPENING_HOOK_DURATION)
    cards, _source, _boundaries = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=Path("/dev/null"),
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.15,
        remaining_lead_seconds=0.0,
        brand_start=12.0,
    )
    first_card = [card for card in cards if card.kind != "opening_hook"][0]
    assert abs((3.15 - first_card.start) - long_form_renderer.CAPTION_LEAD_SECONDS) < 0.01


def test_caption_fade_in_does_not_become_readable_late():
    cards = [long_form_renderer.TextCard("Bridge", 2.8, 5.0, "bridge_line")]
    layers = long_form_renderer.build_script_layers(cards, long_form_renderer.TARGET_CANVAS_SIZE)
    assert layers[0].fade_in <= 0.20
    assert layers[0].start + layers[0].fade_in <= 2.98


def test_detected_wav_pauses_are_used_for_segment_boundaries_when_reliable(tmp_path):
    audio_path = tmp_path / "segments.wav"
    _segmented_tone_wav(audio_path, segment_seconds=[0.3, 0.7, 0.5, 0.4], pause_seconds=[0.20, 0.30, 0.25], leading_silence_seconds=0.03)
    copy = _long_copy(script_segments=["One.", "Two.", "Three."])
    timeline = [
        {"text": copy["bridge_line"], "start": 2.5, "end": 3.1, "kind": "bridge_line"},
        {"text": "One.", "start": 3.1, "end": 3.8, "kind": "script_segment"},
        {"text": "Two.", "start": 3.8, "end": 4.7, "kind": "script_segment"},
        {"text": "Three.", "start": 4.7, "end": 5.4, "kind": "script_segment"},
    ]
    cards, source, detected = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=audio_path,
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.12,
        remaining_lead_seconds=0.03,
        brand_start=6.0,
    )
    assert source == "clamped_audio_pause_detection"
    assert len(detected) == 3
    narrated = [card for card in cards if card.kind != "opening_hook"]
    assert narrated[1].start <= (3.15 + (3.1 - 2.5)) - long_form_renderer.CAPTION_TRANSITION_LEAD_SECONDS + 0.01
    assert narrated[2].start <= (3.15 + (3.8 - 2.5)) - long_form_renderer.CAPTION_TRANSITION_LEAD_SECONDS + 0.01


def test_detected_pause_later_than_safe_estimate_is_rejected():
    boundary, reason = long_form_renderer._select_caption_transition_boundary(
        transition_index=3,
        hook_window=2.5,
        estimated_speech_boundary=30.90,
        detected_pause_boundary=31.35,
    )
    assert abs(boundary - 30.60) < 0.01
    assert reason == "pause_boundary_too_late"


def test_reliable_earlier_pause_boundary_may_still_be_used():
    boundary, reason = long_form_renderer._select_caption_transition_boundary(
        transition_index=2,
        hook_window=2.5,
        estimated_speech_boundary=12.00,
        detected_pause_boundary=11.55,
    )
    assert abs(boundary - 11.55) < 0.01
    assert reason == "audio_pause_detection"


def test_caption_changes_before_or_at_next_spoken_segment(tmp_path):
    audio_path = tmp_path / "segments.wav"
    _segmented_tone_wav(audio_path, segment_seconds=[0.6, 0.7, 0.5], pause_seconds=[0.25, 0.25], leading_silence_seconds=0.03)
    copy = _long_copy(script_segments=["One.", "Two."])
    timeline = [
        {"text": copy["bridge_line"], "start": 2.5, "end": 3.1, "kind": "bridge_line"},
        {"text": "One.", "start": 3.1, "end": 3.8, "kind": "script_segment"},
        {"text": "Two.", "start": 3.8, "end": 4.6, "kind": "script_segment"},
    ]
    cards, source, detected = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=audio_path,
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.12,
        remaining_lead_seconds=0.03,
        brand_start=5.5,
    )
    next_spoken_segment = 3.12 + detected[0]
    narrated = [card for card in cards if card.kind != "opening_hook"]
    assert narrated[1].start <= next_spoken_segment
    assert narrated[0].end == narrated[1].start


def test_safe_proportional_transition_is_used_when_pause_detection_is_late(tmp_path):
    audio_path = tmp_path / "late_pause.wav"
    _segmented_tone_wav(audio_path, segment_seconds=[1.0, 1.0, 1.0], pause_seconds=[0.8, 0.8], leading_silence_seconds=0.03)
    copy = _long_copy(script_segments=["One.", "Two."])
    timeline = [
        {"text": copy["bridge_line"], "start": 2.5, "end": 3.1, "kind": "bridge_line"},
        {"text": "One.", "start": 3.1, "end": 3.8, "kind": "script_segment"},
        {"text": "Two.", "start": 3.8, "end": 4.6, "kind": "script_segment"},
    ]
    cards, source, _detected = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=audio_path,
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.12,
        remaining_lead_seconds=0.03,
        brand_start=5.5,
    )
    narrated = [card for card in cards if card.kind != "opening_hook"]
    safe_boundary = (3.15 + (3.8 - 2.5)) - long_form_renderer.CAPTION_TRANSITION_LEAD_SECONDS
    assert source == "clamped_audio_pause_detection"
    assert narrated[2].start <= safe_boundary + 0.01
    assert narrated[2].start >= safe_boundary - 0.05


def test_proportional_timing_remains_as_fallback_when_pauses_unavailable(tmp_path):
    audio_path = tmp_path / "continuous.wav"
    _segmented_tone_wav(audio_path, segment_seconds=[2.0], pause_seconds=[], leading_silence_seconds=0.03)
    copy = _long_copy(script_segments=["One.", "Two.", "Three."])
    timeline = [
        {"text": copy["bridge_line"], "start": 2.5, "end": 3.1, "kind": "bridge_line"},
        {"text": "One.", "start": 3.1, "end": 3.8, "kind": "script_segment"},
        {"text": "Two.", "start": 3.8, "end": 4.7, "kind": "script_segment"},
        {"text": "Three.", "start": 4.7, "end": 5.4, "kind": "script_segment"},
    ]
    cards, source, _detected = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=audio_path,
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.12,
        remaining_lead_seconds=0.03,
        brand_start=6.0,
    )
    narrated = [card for card in cards if card.kind != "opening_hook"]
    assert source == "proportional_fallback"
    assert abs(narrated[1].start - ((3.15 + (3.1 - 2.5)) - long_form_renderer.CAPTION_TRANSITION_LEAD_SECONDS)) < 0.05


def test_closing_line_caption_remains_through_closing_narration():
    copy = _long_copy()
    timeline = voice_provider.build_narration_segment_timeline(copy, 8.0, hook_window=long_form_renderer.OPENING_HOOK_DURATION)
    cards, _source, _boundaries = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=Path("/dev/null"),
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.15,
        remaining_lead_seconds=0.0,
        brand_start=11.0,
    )
    assert cards[-1].kind == "closing_line"
    assert cards[-1].end == 11.0


def test_final_script_segment_to_closing_line_transition_cannot_lag(tmp_path):
    audio_path = tmp_path / "closing.wav"
    _segmented_tone_wav(audio_path, segment_seconds=[0.8, 1.2, 0.9, 0.8], pause_seconds=[0.25, 0.25, 0.8], leading_silence_seconds=0.03)
    copy = _long_copy(script_segments=["One.", "Two."], closing_line="Amen.")
    timeline = [
        {"text": copy["bridge_line"], "start": 2.5, "end": 3.1, "kind": "bridge_line"},
        {"text": "One.", "start": 3.1, "end": 3.8, "kind": "script_segment"},
        {"text": "Two.", "start": 3.8, "end": 4.7, "kind": "script_segment"},
        {"text": "Amen.", "start": 4.7, "end": 5.4, "kind": "closing_line"},
    ]
    cards, source, _detected = long_form_renderer._build_audio_timed_script_cards(
        copy,
        _presentation(),
        20.0,
        narration_units=long_form_renderer._extract_narration_units(copy, timeline),
        narration_audio_path=audio_path,
        trim_seconds=0.0,
        actual_speech_start_time=3.15,
        audio_offset_seconds=3.12,
        remaining_lead_seconds=0.03,
        brand_start=6.0,
    )
    narrated = [card for card in cards if card.kind != "opening_hook"]
    closing_start = narrated[-1].start
    safe_closing_transition = (3.15 + (4.7 - 2.5)) - long_form_renderer.CAPTION_TRANSITION_LEAD_SECONDS
    assert source in {"clamped_audio_pause_detection", "audio_pause_detection", "proportional_fallback"}
    assert closing_start <= safe_closing_transition + 0.01
    assert narrated[-2].end == closing_start


def test_final_brand_frame_begins_after_narration_ends(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    audio_path = tmp_path / "voice.wav"
    _tone_wav(audio_path, seconds=4.0, leading_silence_seconds=0.0)

    monkeypatch.setattr(
        long_form_renderer,
        "_mux_narration_audio",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"FAKE_MUXED_MP4"),
    )
    monkeypatch.setattr(
        long_form_renderer,
        "_verify_exported_mp4",
        lambda path: {"video_found": True, "audio_found": True, "audio_duration": 4.0, "duration": 11.15},
    )
    long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=tmp_path / "brand.mp4",
        narration_audio_path=audio_path,
        narration_duration=4.0,
        narration_segment_timeline=voice_provider.build_narration_segment_timeline(_long_copy(), 4.0, hook_window=2.5),
    )
    assert _FakeComposedClip.instances[-1].duration >= 11.15


def test_silent_rendering_still_works_without_narration(monkeypatch, tmp_path):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)

    out_path = tmp_path / "silent.mp4"
    result = long_form_renderer.render_long_form_video(
        copy=_long_copy(),
        presentation_config=_presentation(duration_seconds=25),
        video_assets=assets,
        output_path=out_path,
        narration_audio_path=None,
    )

    instance = _FakeComposedClip.instances[-1]
    assert result == out_path
    assert instance.write_paths[-1] == out_path
    assert instance.write_kwargs["audio"] is False


def test_success_log_occurs_only_after_audio_stream_verification_passes(monkeypatch, tmp_path, capsys):
    _FakeComposedClip.instances.clear()
    monkeypatch.setattr(long_form_renderer, "VideoFileClip", _FakeBgClip)
    monkeypatch.setattr(long_form_renderer, "VideoClip", _FakeComposedClip)
    assets = []
    for index in range(4):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        assets.append(path)
    audio_path = tmp_path / "voice.wav"
    voice_provider.create_silent_wav(audio_path, 4.0)

    monkeypatch.setattr(
        long_form_renderer,
        "_mux_narration_audio",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"FAKE_MUXED_MP4"),
    )
    monkeypatch.setattr(
        long_form_renderer,
        "_verify_exported_mp4",
        lambda path: {"video_found": True, "audio_found": False, "audio_duration": 0.0, "duration": 10.5},
    )

    try:
        long_form_renderer.render_long_form_video(
            copy=_long_copy(),
            presentation_config=_presentation(duration_seconds=25),
            video_assets=assets,
            output_path=tmp_path / "broken.mp4",
            narration_audio_path=audio_path,
            narration_duration=4.0,
            narration_segment_timeline=voice_provider.build_narration_segment_timeline(_long_copy(), 4.0, hook_window=2.5),
        )
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass

    output = capsys.readouterr().out
    assert "Done:" not in output


def test_monday_long_prayer_routes_to_long_form_renderer(isolated_database, monkeypatch, tmp_path):
    _patch_cmd_run_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {**_presentation(video_template="long_prayer"), "theme": "strength", "emotion": "overwhelmed", "hook_style": "recognition", "objective": "obj"},
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _long_copy())
    calls = {"long": 0, "short": 0}
    monkeypatch.setattr("long_form_renderer.render_long_form_video", lambda **kwargs: calls.__setitem__("long", calls["long"] + 1) or Path(kwargs["output_path"]).write_bytes(b"x") or kwargs["output_path"])
    monkeypatch.setattr("motion_renderer.render_motion_ad", lambda **kwargs: calls.__setitem__("short", calls["short"] + 1))
    result = prayonit_social.cmd_run("morning")
    assert result == 0
    assert calls["long"] == 1
    assert calls["short"] == 0


def test_tuesday_short_promo_still_routes_to_motion_renderer(isolated_database, monkeypatch, tmp_path):
    _patch_cmd_run_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {**_presentation(video_template="short_promo", content_type="app_feature", video_library="short", duration_seconds=8, marketing_enabled=True, show_badges=True, show_app_benefit=True, engagement_prompt_enabled=False, engagement_prompt_type="none"), "theme": "focus", "emotion": "hopeful", "hook_style": "curiosity", "objective": "obj"},
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _long_copy(long_form_type="none", script_segments=[], engagement_line="", estimated_spoken_seconds=8))
    calls = {"long": 0, "short": 0}
    monkeypatch.setattr("long_form_renderer.render_long_form_video", lambda **kwargs: calls.__setitem__("long", calls["long"] + 1))
    monkeypatch.setattr("motion_renderer.render_motion_ad", lambda **kwargs: calls.__setitem__("short", calls["short"] + 1) or Path(kwargs["output_path"]).write_bytes(b"x"))
    result = prayonit_social.cmd_run("evening")
    assert result == 0
    assert calls["long"] == 0
    assert calls["short"] == 1


def test_wednesday_long_devotional_routes_to_long_form_renderer(isolated_database, monkeypatch, tmp_path):
    _patch_cmd_run_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {**_presentation(video_template="long_devotional", content_type="devotional_read"), "theme": "perseverance", "emotion": "weary", "hook_style": "recognition", "objective": "obj"},
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _long_copy(long_form_type="devotional", closing_line="Take the next faithful step today."))
    calls = {"long": 0, "short": 0}
    monkeypatch.setattr("long_form_renderer.render_long_form_video", lambda **kwargs: calls.__setitem__("long", calls["long"] + 1) or Path(kwargs["output_path"]).write_bytes(b"x") or kwargs["output_path"])
    monkeypatch.setattr("motion_renderer.render_motion_ad", lambda **kwargs: calls.__setitem__("short", calls["short"] + 1))
    result = prayonit_social.cmd_run("morning")
    assert result == 0
    assert calls["long"] == 1
    assert calls["short"] == 0


def test_preview_mode_saves_long_form_video_locally_without_publishing(isolated_database, monkeypatch, tmp_path):
    _patch_cmd_run_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {**_presentation(video_template="long_encouragement", content_type="hope_encouragement"), "theme": "hope", "emotion": "tired", "hook_style": "recognition", "objective": "obj"},
    )
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_ad_copy", lambda **kwargs: _long_copy(long_form_type="encouragement", closing_line="You can keep going."))
    saved = {"path": None}

    def fake_render_long_form_video(**kwargs):
        saved["path"] = Path(kwargs["output_path"])
        saved["path"].write_bytes(b"x")
        return saved["path"]

    monkeypatch.setattr("long_form_renderer.render_long_form_video", fake_render_long_form_video)
    monkeypatch.setattr("motion_renderer.render_motion_ad", lambda **kwargs: (_ for _ in ()).throw(AssertionError("short renderer called")))
    result = prayonit_social.cmd_run("morning")
    assert result == 0
    assert saved["path"] is not None
    assert "output/videos/long" in str(saved["path"])
