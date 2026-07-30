import json
import math
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import config
import direct_marketing
import direct_marketing_renderer
import platform_post_preparer
import prompt_builder
import resolved_content_brief
import voice_provider
from engines import content_engine


def _resolved_brief(now: datetime, slot: str = "morning"):
    weekly = content_engine.get_todays_content(slot=slot, now=now)
    return resolved_content_brief.resolve_content_brief(
        run_id=f"direct-{now.date()}-{slot}",
        slot=slot,
        post_date=content_engine.get_current_weekday(now=now)
        and now.astimezone(config.EASTERN_TZ).date().isoformat(),
        platform_mode="reels_only",
        candidate_campaign=None,
        campaigns=[],
        weekly_content=weekly,
    )


def _direct_copy(family="product_demo"):
    return direct_marketing.normalize_direct_marketing_copy(
        {
            "opening_hook": "See what this prayer app does.",
            "follow_up_card": "Choose how you feel.",
            "app_benefit": (
                "Receive Scripture, a devotional, and a guided prayer "
                "based on your mood."
            ),
        },
        marketing_family=family,
        direct_cta=direct_marketing.DIRECT_MARKETING_CTA,
    )


def _platform_brief():
    return SimpleNamespace(
        run_id="direct-platform",
        prayer_category_id="general_prayer",
        life_moment_text="Not knowing what to pray",
        hook_profile_id="gentle_invitation",
        voice_profile_id="natural_conversational",
        body_profile_id="general_prayer",
        caption_profile_id="current_default",
        scene_profile_id="current_default",
        cta_profile_id="current_default",
        hashtag_profile_id="direct_marketing",
        creative_policy_version="1",
        marketing_family="product_demo",
    )


def _tone_wav(
    path: Path,
    *,
    seconds: float = 6.0,
    frequency: float = 660.0,
    amplitude: int = 12000,
    rate: int = 24000,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = bytearray()
        for index in range(int(seconds * rate)):
            sample = int(
                amplitude
                * math.sin(2 * math.pi * frequency * (index / rate))
            )
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return path


def _segmented_tone_wav(path: Path, *, rate: int = 24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        frames = bytearray()
        for segment_index, seconds in enumerate((1.1, 0.9, 1.2, 1.1)):
            for index in range(int(seconds * rate)):
                sample = int(
                    12000
                    * math.sin(
                        2
                        * math.pi
                        * (520 + segment_index * 70)
                        * (index / rate)
                    )
                )
                frames.extend(struct.pack("<h", sample))
            if segment_index < 3:
                frames.extend(b"\x00\x00" * int(0.35 * rate))
        wav_file.writeframes(bytes(frames))
    return path


def test_tuesday_and_thursday_resolve_to_direct_marketing():
    tuesday = content_engine.get_todays_content(
        slot="morning",
        now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )
    thursday = content_engine.get_todays_content(
        slot="evening",
        now=datetime(2026, 7, 30, 23, 0, tzinfo=timezone.utc),
    )
    for content in (tuesday, thursday):
        assert content["content_type"] == "direct_marketing"
        assert content["video_template"] == "direct_marketing_short"
        assert content["marketing_enabled"] is True
        assert content["show_app_benefit"] is True
        assert content["hashtag_profile"] == "direct_marketing"


def test_other_weekdays_keep_existing_content_types():
    expected = {
        27: "prayer_read",
        29: "devotional_read",
        31: "hope_encouragement",
        1: "gratitude_reflection",
        2: "night_prayer_or_rest",
    }
    for day, content_type in expected.items():
        month = 7 if day >= 27 else 8
        content = content_engine.get_todays_content(
            slot="morning",
            now=datetime(2026, month, day, 12, 0, tzinfo=timezone.utc),
        )
        assert content["content_type"] == content_type


def test_resolver_owns_family_and_direct_hashtag_profile():
    brief = _resolved_brief(
        datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    )
    assert brief.marketing_family in direct_marketing.TUESDAY_FAMILIES
    assert brief.hashtag_profile_id == "direct_marketing"
    assert brief.video_template == "direct_marketing_short"


def test_screenshot_mode_is_limited_to_tuesday_product_demo(monkeypatch):
    monkeypatch.setattr(config, "DIRECT_MARKETING_SCREENSHOT_MODE", True)
    briefs = [
        _resolved_brief(
            datetime(2026, 8, day, 12, 0, tzinfo=timezone.utc),
            slot="morning",
        )
        for day in (4, 11, 18)
    ]
    assert {brief.marketing_family for brief in briefs} == set(
        direct_marketing.TUESDAY_FAMILIES
    )
    for brief in briefs:
        assert brief.direct_marketing_screenshot_mode is (
            brief.marketing_family == "product_demo"
        )


def test_tuesday_and_thursday_families_rotate_deterministically():
    tuesday_choices = {
        direct_marketing.resolve_marketing_family(
            post_date=f"2026-08-{day:02d}",
            slot="morning",
            configured_families=direct_marketing.TUESDAY_FAMILIES,
        )
        for day in (4, 11, 18)
    }
    thursday_choices = {
        direct_marketing.resolve_marketing_family(
            post_date=f"2026-08-{day:02d}",
            slot="evening",
            configured_families=direct_marketing.THURSDAY_FAMILIES,
        )
        for day in (6, 13, 20)
    }
    assert tuesday_choices == set(direct_marketing.TUESDAY_FAMILIES)
    assert thursday_choices == set(direct_marketing.THURSDAY_FAMILIES)


def test_testimonial_curiosity_rejects_fabricated_customer_evidence():
    copy = _direct_copy("testimonial_curiosity")
    copy["opening_hook"] = "Thousands of users say this changed their life."
    assert "fabricated_testimonial_claim" in (
        direct_marketing.validate_direct_marketing_copy(copy)
    )
    copy["opening_hook"] = "I didn't expect a prayer app to do this."
    assert "fabricated_testimonial_claim" not in (
        direct_marketing.validate_direct_marketing_copy(copy)
    )


def test_direct_narration_uses_card_order_and_names_prayonit():
    copy = _direct_copy("product_demo")
    segments = direct_marketing.build_direct_marketing_narration_segments(copy)
    transcript = direct_marketing.build_direct_marketing_narration_text(copy)
    assert [segment.source_field for segment in segments] == [
        "opening_hook",
        "follow_up_card",
        "app_benefit",
        "direct_cta",
    ]
    assert [segment.start for segment in segments] == [0.0, 1.5, 3.0, 6.5]
    assert "Prayonit" in segments[-1].text
    assert 16 <= len(transcript.split()) <= 22
    assert (
        direct_marketing.validate_direct_marketing_narration(
            copy,
            transcript,
            segments,
        )
        == []
    )


def test_direct_narration_shortens_deterministically_to_configured_limit():
    copy = _direct_copy("testimonial_curiosity")
    copy["opening_hook"] = (
        "I genuinely did not expect this particular prayer application "
        "to make starting feel this simple today."
    )
    first = direct_marketing.build_direct_marketing_narration_text(
        copy,
        word_limit=16,
    )
    second = direct_marketing.build_direct_marketing_narration_text(
        copy,
        word_limit=16,
    )
    assert first == second
    assert len(first.split()) <= 16
    assert "Prayonit. Link in bio." in first


def test_testimonial_narration_never_creates_customer_evidence():
    copy = _direct_copy("testimonial_curiosity")
    copy["opening_hook"] = "I didn't expect a prayer app to do this."
    transcript = direct_marketing.build_direct_marketing_narration_text(copy)
    assert transcript.startswith("This prayer app surprised me.")
    assert not direct_marketing.has_fabricated_testimonial_claim(transcript)
    assert "users say" not in transcript.lower()


def test_direct_marketing_delivery_profile_uses_orus_and_temperature(monkeypatch):
    monkeypatch.setattr(
        voice_provider.config,
        "DIRECT_MARKETING_TTS_PROFILE",
        "direct_marketing_clear",
    )
    monkeypatch.setattr(
        voice_provider.config,
        "DIRECT_MARKETING_TTS_TEMPERATURE",
        0.9,
    )
    profile = voice_provider.select_tts_delivery_profile(
        _direct_copy(),
        {
            "slot": "morning",
            "content_type": "direct_marketing",
            "prayer_category_id": "anxiety",
        },
    )
    assert profile == "direct_marketing_clear"
    assert voice_provider._resolve_voice_temperature(profile) == 0.9
    assert config.DIRECT_MARKETING_TTS_VOICE == "Orus"
    assert "not overly excited, salesy" in (
        voice_provider.TTS_DELIVERY_PROFILES[profile]["scene"]
    )


def test_devotional_delivery_profiles_remain_unchanged():
    assert (
        voice_provider.select_tts_delivery_profile(
            {"long_form_type": "devotional"},
            {
                "slot": "evening",
                "content_type": "devotional_read",
                "prayer_category_id": "devotional",
            },
        )
        == "evening_reflective"
    )
    assert voice_provider._resolve_voice_temperature("evening_reflective") == 0.8


def test_direct_cards_include_benefit_brand_and_direct_cta():
    copy = _direct_copy()
    cards = direct_marketing.build_direct_marketing_cards(copy)
    assert len(cards) == 4
    assert cards[0].start == 0.0
    assert cards[0].end == 1.5
    assert cards[2].source_field == "app_benefit"
    assert "Prayonit" in cards[2].text
    assert cards[2].end <= cards[3].start
    assert cards[-1].text == "Prayonit · Link in bio"
    assert "Come pray with me" not in " ".join(card.text for card in cards)


def test_direct_copy_qa_blocks_app_less_benefit_less_copy():
    copy = _direct_copy()
    copy["opening_hook"] = "Pause and bring your worry here."
    copy["follow_up_card"] = "Take a quiet breath."
    copy["app_benefit"] = ""
    failures = direct_marketing.validate_direct_marketing_copy(copy)
    assert "opening_hook_is_devotional_only" in failures
    assert "app_benefit_missing_or_vague" in failures


def test_direct_prompt_uses_marketing_strategy_not_devotional_arc():
    brief = _resolved_brief(
        datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    )
    prompt = prompt_builder.build_prompt(
        post_type="direct marketing short",
        selection={"spiritual_action": "Bring it to God."},
        slot="morning",
        tracked_url="https://example.test",
        resolved_brief=brief,
    )
    assert "This post is intentionally clear product marketing" in prompt
    assert "The primary goal is NOT to advertise the app" not in prompt
    assert "Prayonit · Link in bio" in prompt
    assert f"Direct Marketing Family:\n{brief.marketing_family}" in prompt


def test_devotional_prompt_keeps_existing_non_marketing_strategy():
    brief = _resolved_brief(
        datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    )
    prompt = prompt_builder.build_prompt(
        post_type="devotional",
        selection={"spiritual_action": "Bring it to God."},
        slot="morning",
        tracked_url="https://example.test",
        resolved_brief=brief,
    )
    assert "The primary goal is NOT to advertise the app" in prompt
    assert "This post is intentionally clear product marketing" not in prompt


def test_approved_screenshot_sequence_is_loaded_in_required_order(tmp_path):
    asset_dir = tmp_path / "screens"
    asset_dir.mkdir()
    entries = []
    for order, screen_type in enumerate(
        direct_marketing_renderer.SCREEN_TYPES,
        start=1,
    ):
        filename = f"{order}.png"
        Image.new("RGB", (200, 400), "white").save(asset_dir / filename)
        entries.append(
            {
                "filename": filename,
                "screen_type": screen_type,
                "display_order": order,
                "active": True,
                "last_verified_date": "2026-07-30",
                "app_version": "test",
            }
        )
    catalog = asset_dir / "catalog.json"
    catalog.write_text(json.dumps({"screenshots": entries}), encoding="utf-8")
    assert [
        path.name
        for path in direct_marketing_renderer.resolve_screenshot_sequence(
            catalog_path=catalog,
            asset_dir=asset_dir,
        )
    ] == ["1.png", "2.png", "3.png"]


def test_missing_screenshots_use_safe_empty_sequence(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"screenshots": []}', encoding="utf-8")
    assert (
        direct_marketing_renderer.resolve_screenshot_sequence(
            catalog_path=catalog,
            asset_dir=tmp_path,
        )
        == []
    )


def test_direct_hashtags_and_captions_are_product_specific():
    copy = _direct_copy()
    for platform in ("tiktok", "instagram", "facebook"):
        base = direct_marketing.build_direct_marketing_caption(copy, platform)
        prepared = platform_post_preparer.prepare_platform_post(
            platform=platform,
            base_caption=base,
            brief=_platform_brief(),
            scheduled_at="2026-07-30T12:00:00Z",
            post_type="video" if platform == "tiktok" else "reel",
            media_reference="https://cdn.example/direct.mp4",
            direct_url=(
                "https://prayonit.app" if platform == "facebook" else None
            ),
        )
        assert "Prayonit" in prepared.public_caption
        assert "guided prayer" in prepared.public_caption
        assert "#PrayerApp" in prepared.hashtags
        assert "Come pray with me" not in prepared.public_caption
    assert "Prayonit · Learn more" in (
        platform_post_preparer.prepare_platform_post(
            platform="facebook",
            base_caption=direct_marketing.build_direct_marketing_caption(
                copy, "facebook"
            ),
            brief=_platform_brief(),
            scheduled_at="2026-07-30T12:00:00Z",
            post_type="reel",
            media_reference="https://cdn.example/direct.mp4",
            direct_url="https://prayonit.app",
        ).public_caption
    )


def test_direct_renderer_outputs_audio_stream_with_scenic_fallback(tmp_path):
    background = next(config.MOTION_BACKGROUNDS_DIR.glob("*.mp4"))
    output = tmp_path / "direct.mp4"
    result = direct_marketing_renderer.render_direct_marketing_short(
        ad_copy=_direct_copy(),
        background_path=background,
        output_path=output,
        screenshot_mode=True,
        audio_enabled=True,
        tts_enabled=False,
        tts_required=False,
        seed="audio-test",
    )
    diagnostics = direct_marketing_renderer.verify_direct_marketing_video(
        result,
        audio_required=True,
    )
    assert diagnostics["audio_stream_detected"] is True
    assert diagnostics["audio_duration"] > 0
    assert diagnostics["audio_signal_peak"] > 0.00001
    assert diagnostics["duration"] >= 7.9


def test_video_qa_blocks_silent_video_when_audio_is_required(tmp_path):
    background = next(config.MOTION_BACKGROUNDS_DIR.glob("*.mp4"))
    output = direct_marketing_renderer.render_direct_marketing_short(
        ad_copy=_direct_copy(),
        background_path=background,
        output_path=tmp_path / "silent.mp4",
        screenshot_mode=False,
        audio_enabled=False,
        tts_enabled=False,
        tts_required=False,
    )
    try:
        direct_marketing_renderer.verify_direct_marketing_video(
            output,
            audio_required=True,
        )
    except RuntimeError as exc:
        assert "required audio is missing or silent" in str(exc)
    else:
        raise AssertionError("Silent direct-marketing video passed audio QA")


def test_direct_renderer_mixes_narration_above_music(tmp_path):
    copy = _direct_copy("pain_to_product")
    narration_text = direct_marketing.build_direct_marketing_narration_text(copy)
    narration = _segmented_tone_wav(tmp_path / "narration.wav")
    music_path, _ = direct_marketing_renderer.select_audio_asset(
        profile_id="current_default",
        seed="mix-test",
    )
    source_diagnostics = (
        direct_marketing_renderer.validate_direct_marketing_audio_sources(
            narration_path=narration,
            music_path=music_path,
            music_db=-18.0,
            narration_lead_seconds=0.0,
        )
    )
    assert abs(source_diagnostics["voice_to_bed_db"] - 18.0) < 0.01
    output = direct_marketing_renderer.render_direct_marketing_short(
        ad_copy=copy,
        background_path=next(config.MOTION_BACKGROUNDS_DIR.glob("*.mp4")),
        output_path=tmp_path / "narrated.mp4",
        screenshot_mode=False,
        audio_enabled=True,
        narration_audio_path=narration,
        narration_text=narration_text,
        tts_enabled=True,
        tts_required=True,
        seed="mix-test",
    )
    final = direct_marketing_renderer.verify_direct_marketing_video(
        output,
        audio_required=True,
    )
    assert final["duration"] == 8.0
    assert final["audio_duration"] == 8.0
    assert 0.00001 < final["audio_signal_peak"] < 0.999


def test_narration_phrase_alignment_preserves_visual_card_regions(tmp_path):
    source = _segmented_tone_wav(tmp_path / "source.wav")
    prepared = direct_marketing_renderer.prepare_direct_marketing_narration(
        source,
        tmp_path / "aligned.wav",
    )
    diagnostics = prepared["diagnostics"]
    assert diagnostics["target_starts"] == [0.0, 1.5, 3.0, 6.0]
    assert diagnostics["phrase_starts"] == [0.0, 1.5, 3.0, 6.0]
    assert diagnostics["duration"] < 7.85
    cards = direct_marketing_renderer.align_cards_to_narration(
        direct_marketing.build_direct_marketing_cards(_direct_copy()),
        diagnostics["phrase_starts"],
    )
    assert [card.start for card in cards] == diagnostics["phrase_starts"]
    assert all(
        left.end <= right.start
        for left, right in zip(cards, cards[1:])
    )


def test_missing_required_tts_blocks_before_render(tmp_path):
    copy = _direct_copy()
    try:
        direct_marketing_renderer.render_direct_marketing_short(
            ad_copy=copy,
            background_path=None,
            output_path=tmp_path / "missing.mp4",
            narration_text=(
                direct_marketing.build_direct_marketing_narration_text(copy)
            ),
            tts_enabled=True,
            tts_required=True,
        )
    except RuntimeError as exc:
        assert "required narration is missing" in str(exc)
    else:
        raise AssertionError("Missing required direct narration passed QA")


def test_text_music_fallback_requires_explicit_configuration(tmp_path):
    copy = _direct_copy()
    background = next(config.MOTION_BACKGROUNDS_DIR.glob("*.mp4"))
    try:
        direct_marketing_renderer.render_direct_marketing_short(
            ad_copy=copy,
            background_path=background,
            output_path=tmp_path / "blocked-fallback.mp4",
            screenshot_mode=False,
            tts_enabled=True,
            tts_required=False,
            text_music_fallback_enabled=False,
        )
    except RuntimeError as exc:
        assert "fallback is not explicitly enabled" in str(exc)
    else:
        raise AssertionError("Implicit text-plus-music fallback passed QA")

    output = direct_marketing_renderer.render_direct_marketing_short(
        ad_copy=copy,
        background_path=background,
        output_path=tmp_path / "allowed-fallback.mp4",
        screenshot_mode=False,
        audio_enabled=True,
        tts_enabled=True,
        tts_required=False,
        text_music_fallback_enabled=True,
    )
    assert (
        direct_marketing_renderer.verify_direct_marketing_video(
            output,
            audio_required=True,
        )["audio_stream_detected"]
        is True
    )


def test_overlong_or_silent_narration_fails_audio_qa(tmp_path):
    music_path, _ = direct_marketing_renderer.select_audio_asset(
        profile_id="current_default",
        seed="qa-test",
    )
    overlong = _tone_wav(tmp_path / "overlong.wav", seconds=8.0)
    try:
        direct_marketing_renderer.validate_direct_marketing_audio_sources(
            narration_path=overlong,
            music_path=music_path,
            music_db=-18.0,
            narration_lead_seconds=0.0,
        )
    except RuntimeError as exc:
        assert "narration_longer_than_video" in str(exc)
    else:
        raise AssertionError("Overlong narration passed direct audio QA")

    silent = voice_provider.create_silent_wav(tmp_path / "silent.wav", 4.0)
    try:
        direct_marketing_renderer.validate_direct_marketing_audio_sources(
            narration_path=silent,
            music_path=music_path,
            music_db=-18.0,
            narration_lead_seconds=0.0,
        )
    except RuntimeError as exc:
        assert "narration_is_silent" in str(exc)
    else:
        raise AssertionError("Silent narration passed direct audio QA")
