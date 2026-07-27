from pathlib import Path
from unittest.mock import MagicMock

import prayonit_social
import voice_provider


def _long_copy(long_form_type="prayer", **overrides):
    copy = {
        "long_form_type": long_form_type,
        "brand_header": "PRAYONIT",
        "pain_headline": "Feeling overwhelmed today?",
        "spiritual_action": "Bring it to God in prayer.",
        "bridge_line": "Let this prayer meet you right where you are.",
        "script_segments": [
            "Lord, steady my heart today.",
            "Give me peace and strength for what is ahead.",
        ],
        "closing_line": "Amen.",
        "opening_hook": "God sees your burden.",
        "engagement_line": "Save this prayer for tomorrow morning.",
        "cta_text": "Come pray with me.",
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
    }
    copy.update(overrides)
    return copy


def test_prayer_selects_charon_by_default(monkeypatch):
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME", "")
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME_PRAYER", "Orus")
    assert voice_provider.select_default_voice(_long_copy("prayer")) == "Orus"


def test_devotional_selects_orus_by_default(monkeypatch):
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME", "")
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME_DEVOTIONAL", "Orus")
    assert voice_provider.select_default_voice(_long_copy("devotional")) == "Orus"


def test_encouragement_selects_orus_by_default(monkeypatch):
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME", "")
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME_ENCOURAGEMENT", "Orus")
    assert voice_provider.select_default_voice(_long_copy("encouragement")) == "Orus"


def test_natural_conversational_profile_exists():
    assert "natural_conversational" in voice_provider.STYLE_PROFILES


def test_ordinary_devotional_selects_natural_conversational():
    assert (
        voice_provider.select_style_profile(
            _long_copy(
                "devotional",
                theme="morning reflection",
                emotion="steady",
                script_segments=["Take a steady breath and notice God's kindness in this ordinary day."],
            )
        )
        == "natural_conversational"
    )


def test_prayer_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("prayer")) == "natural_conversational"


def test_devotional_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("devotional")) == "natural_conversational"


def test_encouragement_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("encouragement")) == "natural_conversational"


def test_morning_prayer_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("prayer", theme="morning prayer")) == "natural_conversational"


def test_evening_prayer_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("prayer", theme="evening prayer")) == "natural_conversational"


def test_gratitude_reflection_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("devotional", theme="gratitude reflection")) == "natural_conversational"


def test_parenting_content_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("devotional", theme="parenting")) == "natural_conversational"


def test_anxiety_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("encouragement", emotion="anxiety")) == "natural_conversational"


def test_protection_selects_natural_conversational():
    assert voice_provider.select_style_profile(_long_copy("prayer", theme="protection")) == "natural_conversational"


def test_creative_brief_tone_does_not_change_production_profile():
    assert (
        voice_provider.select_style_profile(
            _long_copy(
                "prayer",
                theme="protection",
                emotion="anxiety",
                creative_brief_tone="urgent bold declaration",
            )
        )
        == "natural_conversational"
    )


def test_explicit_valid_override_wins():
    assert (
        voice_provider.select_style_profile(
            _long_copy("devotional", theme="gratitude reflection", voice_style_profile="devotional_teacher")
        )
        == "devotional_teacher"
    )


def test_invalid_override_logs_warning_and_falls_back_safely(capsys):
    profile = voice_provider.select_style_profile(_long_copy("devotional", voice_style_profile="dramatic_preacher"))
    assert profile == "natural_conversational"
    out = capsys.readouterr().out
    assert "invalid voice_style_profile override" in out.lower()


def test_default_style_fallback_is_natural_conversational():
    assert voice_provider.select_style_profile({"long_form_type": "unknown"}) == "natural_conversational"


def test_charon_remains_available_through_override(monkeypatch):
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME", "")
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME_PRAYER", "Charon")
    monkeypatch.setattr(voice_provider.config, "VOICE_NAME_ALTERNATE", "Charon")
    assert voice_provider.select_default_voice(_long_copy("prayer")) == "Charon"


def test_narration_text_excludes_branding_cta_and_engagement_lines():
    text = voice_provider.build_narration_text(_long_copy())
    lower = text.lower()
    assert "prayonit" not in lower
    assert "come pray with me" not in lower
    assert "save this prayer" not in lower
    assert "guided, personalized prayer" not in lower
    assert "amen." in lower


def test_narration_preserves_segment_order():
    segments = voice_provider.build_narration_segments(_long_copy())
    assert segments == [
        "God sees your burden.",
        "Let this prayer meet you right where you are.",
        "Lord, steady my heart today.",
        "Give me peace and strength for what is ahead.",
        "Amen.",
    ]


def test_narration_text_includes_bridge_every_script_segment_and_closing_line():
    text = voice_provider.build_narration_text(_long_copy())
    assert text == (
        "God sees your burden.\n\n"
        "Let this prayer meet you right where you are.\n\n"
        "Lord, steady my heart today.\n\n"
        "Give me peace and strength for what is ahead.\n\n"
        "Amen."
    )


def test_multi_sentence_script_segment_remains_intact():
    text = voice_provider.build_narration_text(
        _long_copy(
            script_segments=[
                "When you start your morning carrying the weight of scarcity, it's hard to settle your mind. "
                "You wonder if what you have will be enough for today."
            ]
        )
    )
    assert (
        "When you start your morning carrying the weight of scarcity, it's hard to settle your mind. "
        "You wonder if what you have will be enough for today."
    ) in text


def test_unicode_punctuation_is_preserved_in_narration_text():
    text = voice_provider.build_narration_text(
        _long_copy(
            bridge_line="It’s easy for an unsettled mind to overshadow a quiet morning.",
            script_segments=["Don’t lose heart. God’s peace is near."],
            closing_line="Amen…",
        )
    )
    assert "It’s easy for an unsettled mind to overshadow a quiet morning." in text
    assert "Don’t lose heart. God’s peace is near." in text
    assert text.endswith("Amen…")


def test_validate_narration_transcript_requires_units_once_and_in_order():
    units = [
        "Bridge line.",
        "Second sentence stays here. Third sentence stays too.",
        "Amen.",
    ]
    transcript = "\n\n".join(units)
    voice_provider.validate_narration_transcript(units, transcript)


def test_validate_narration_transcript_fails_when_unit_is_missing():
    units = ["Bridge line.", "Missing middle sentence.", "Amen."]
    transcript = "Bridge line.\n\nAmen."
    try:
        voice_provider.validate_narration_transcript(units, transcript)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "validation failed" in str(exc).lower()


def test_prayer_director_note_includes_conviction_authority_and_no_whisper():
    scene = voice_provider.PRAYER_STYLE_INSTRUCTION
    lower = scene.lower()
    assert "strong, full speaking voice" in lower
    assert "conviction" in lower
    assert "authority" in lower
    assert "do not whisper" in lower


def test_devotional_direction_is_strong_but_less_preacher_like():
    scene = voice_provider.DEVOTIONAL_STYLE_INSTRUCTION
    lower = scene.lower()
    assert "confident christian teacher" in lower
    assert "strong, full voice" in lower
    assert "commercial-announcer" in lower
    assert "charismatic christian preacher" not in lower


def test_encouragement_direction_uses_confident_hopeful_energy():
    scene = voice_provider.ENCOURAGEMENT_STYLE_INSTRUCTION
    lower = scene.lower()
    assert "confident christian encouragement" in lower
    assert "hopeful energy" in lower
    assert "do not whisper" in lower


def test_natural_conversational_direction_is_grounded_and_not_theatrical():
    scene = voice_provider.NATURAL_CONVERSATIONAL_STYLE_INSTRUCTION
    lower = scene.lower()
    assert "steady, natural, conversational voice" in lower
    assert "calm, clear, sincere, and grounded" in lower
    assert "do not sound theatrical" in lower
    assert "do not shout, yell, strain" in lower


def test_sample_context_is_dynamically_derived_and_not_hardcoded():
    copy = _long_copy(
        opening_hook="God is still leading you.",
        bridge_line="Trust Him with the next step.",
    )
    context = voice_provider.build_sample_context(copy)
    assert context == "God is still leading you.\nTrust Him with the next step."
    assert "decisions" not in context.lower()


def test_sample_context_falls_back_to_bridge_line_then_script_then_generic():
    assert voice_provider.build_sample_context(_long_copy(opening_hook="", bridge_line="Hold onto hope.")) == "Hold onto hope."
    assert voice_provider.build_sample_context(_long_copy(opening_hook="", bridge_line="", script_segments=["Stay steady today."])) == "Stay steady today."
    generic = voice_provider.build_sample_context(_long_copy(opening_hook="", bridge_line="", script_segments=[], long_form_type="devotional"))
    assert "devotional" in generic.lower() or "spiritual takeaway" in generic.lower()


def test_sample_context_is_not_part_of_narrated_transcript():
    copy = _long_copy(
        opening_hook="God sees your burden.",
        bridge_line="Let this prayer meet you right where you are.",
    )
    prompt = voice_provider.build_tts_prompt(
        voice_provider.build_narration_text(copy),
        "charismatic_prayer",
        copy,
    )
    transcript = prompt.split("## Transcript:\n", 1)[1]
    assert "God sees your burden." in transcript
    assert "Let this prayer meet you right where you are." in transcript
    assert transcript.startswith("God sees your burden.")


def test_director_note_headings_are_not_narrated():
    copy = _long_copy()
    prompt = voice_provider.build_tts_prompt(
        voice_provider.build_narration_text(copy),
        "charismatic_prayer",
        copy,
    )
    transcript = prompt.split("## Transcript:\n", 1)[1]
    assert "# Director's note" not in transcript
    assert "## Scene:" not in transcript
    assert "## Sample Context:" not in transcript


def test_tts_prompt_instructs_gemini_not_to_skip_or_omit_sentences():
    prompt = voice_provider.build_tts_prompt(
        voice_provider.build_narration_text(_long_copy()),
        "charismatic_prayer",
        _long_copy(),
    )
    assert "Read every sentence in the Transcript exactly once, in order." in prompt
    assert "Do not skip, summarize, paraphrase, or omit any sentence." in prompt


def test_transcript_is_final_section_of_tts_prompt():
    prompt = voice_provider.build_tts_prompt(
        voice_provider.build_narration_text(_long_copy()),
        "charismatic_prayer",
        _long_copy(),
    )
    before, transcript = prompt.split("## Transcript:\n", 1)
    assert "## Sample Context:" in before
    assert transcript == voice_provider.build_narration_text(_long_copy())


def test_sample_context_does_not_replace_transcript_content():
    copy = _long_copy(
        opening_hook="It is easy for an unsettled mind to overshadow a quiet morning.",
        bridge_line="When you start your morning carrying the weight of scarcity, it's hard to settle your mind.",
        script_segments=["You wonder if what you have will be enough for today."],
    )
    prompt = voice_provider.build_tts_prompt(
        voice_provider.build_narration_text(copy),
        "charismatic_prayer",
        copy,
    )
    transcript = prompt.split("## Transcript:\n", 1)[1]
    assert "It is easy for an unsettled mind to overshadow a quiet morning." in transcript
    assert "When you start your morning carrying the weight of scarcity, it's hard to settle your mind." in transcript
    assert "You wonder if what you have will be enough for today." in transcript


def test_temperature_defaults_to_one(monkeypatch):
    monkeypatch.setattr(voice_provider.config, "VOICE_TEMPERATURE", 1.0)
    assert voice_provider._resolve_voice_temperature() == 1.0


def test_retry_occurs_for_temporary_errors(monkeypatch, tmp_path):
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("503 temporarily unavailable")
        return voice_provider.create_silent_wav(tmp_path / "ok.wav", 1.0)

    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_PRIMARY", "gemini-3.1-flash-tts-preview")
    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_SECONDARY", "gemini-2.5-flash-preview-tts")
    monkeypatch.setattr(voice_provider, "_generate_with_gemini", flaky)
    path = voice_provider.generate_voiceover(
        "Hello world.",
        "Charon",
        voice_provider.PRAYER_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        provider="gemini",
        fallback_enabled=False,
    )
    assert calls["count"] == 2
    assert path is not None


def test_macos_fallback_is_used_only_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_PRIMARY", "gemini-3.1-flash-tts-preview")
    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_SECONDARY", "gemini-2.5-flash-preview-tts")
    monkeypatch.setattr(voice_provider, "_generate_with_gemini", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("503 temporarily unavailable")))
    called = {"macos": 0}

    def fake_macos(text, output_path, voice_name):
        called["macos"] += 1
        return voice_provider.create_silent_wav(output_path, 1.0)

    monkeypatch.setattr(voice_provider, "_generate_with_macos_say", fake_macos)

    path = voice_provider.generate_voiceover(
        "Hello world.",
        "Charon",
        voice_provider.PRAYER_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        provider="gemini",
        fallback_enabled=True,
    )
    assert called["macos"] == 1
    assert path is not None

    called["macos"] = 0
    path2 = voice_provider.generate_voiceover(
        "Hello world.",
        "Charon",
        voice_provider.PRAYER_STYLE_INSTRUCTION,
        tmp_path / "voice2.wav",
        provider="gemini",
        fallback_enabled=False,
    )
    assert called["macos"] == 0
    assert path2 is None


def test_secondary_gemini_model_is_attempted_before_macos_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_PRIMARY", "gemini-3.1-flash-tts-preview")
    monkeypatch.setattr(voice_provider.config, "VOICE_MODEL_SECONDARY", "gemini-2.5-flash-preview-tts")
    model_calls = []

    def always_fail(text, voice_name, style_instruction, output_path, *, copy=None, model_name=None):
        model_calls.append(model_name)
        raise RuntimeError("503 temporarily unavailable")

    macos_calls = {"count": 0}

    def fake_macos(text, output_path, voice_name):
        macos_calls["count"] += 1
        return voice_provider.create_silent_wav(output_path, 1.0)

    monkeypatch.setattr(voice_provider, "_generate_with_gemini", always_fail)
    monkeypatch.setattr(voice_provider, "_generate_with_macos_say", fake_macos)

    result = voice_provider.generate_voiceover(
        "Hello world.",
        "Charon",
        voice_provider.PRAYER_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        provider="gemini",
        fallback_enabled=True,
    )
    assert result is not None
    assert model_calls == [
        "gemini-3.1-flash-tts-preview",
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-flash-preview-tts",
    ]
    assert macos_calls["count"] == 1


def test_generate_with_gemini_uses_primary_key_and_temperature(monkeypatch, tmp_path):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.candidates[0].content.parts = [MagicMock()]
    fake_response.candidates[0].content.parts[0].inline_data.data = b"\x00\x00" * 24000
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response
    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider, "_get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(voice_provider.config, "VOICE_TEMPERATURE", 1.0)

    voice_provider._generate_with_gemini(
        voice_provider.build_narration_text(_long_copy()),
        "Orus",
        voice_provider.PRAYER_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        copy=_long_copy(),
        model_name="gemini-3.1-flash-tts-preview",
    )

    kwargs = fake_client.models.generate_content.call_args.kwargs
    assert kwargs["config"].temperature == 1.0
    assert "## Transcript:" in kwargs["contents"]
    assert "God sees your burden." in kwargs["contents"]
    assert "Come pray with me." not in kwargs["contents"]
    assert "Read every sentence in the Transcript exactly once, in order." in kwargs["contents"]


def test_generate_with_gemini_logs_style_selection_reason(monkeypatch, tmp_path, capsys):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.candidates[0].content.parts = [MagicMock()]
    fake_response.candidates[0].content.parts[0].inline_data.data = b"\x00\x00" * 24000
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider, "_get_gemini_client", lambda: fake_client)

    voice_provider._generate_with_gemini(
        voice_provider.build_narration_text(_long_copy("devotional", theme="gratitude reflection")),
        "Orus",
        voice_provider.DEVOTIONAL_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        copy=_long_copy("devotional", theme="gratitude reflection"),
        model_name="gemini-3.1-flash-tts-preview",
    )

    out = capsys.readouterr().out
    assert "Gemini TTS style profile: natural_conversational" in out
    assert "Style selection reason: unified production narration profile" in out


def test_generate_with_gemini_logs_explicit_manual_override_reason(monkeypatch, tmp_path, capsys):
    fake_response = MagicMock()
    fake_response.candidates = [MagicMock()]
    fake_response.candidates[0].content.parts = [MagicMock()]
    fake_response.candidates[0].content.parts[0].inline_data.data = b"\x00\x00" * 24000
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider, "_get_gemini_client", lambda: fake_client)

    voice_provider._generate_with_gemini(
        voice_provider.build_narration_text(_long_copy("devotional", voice_style_profile="devotional_teacher")),
        "Orus",
        voice_provider.DEVOTIONAL_STYLE_INSTRUCTION,
        tmp_path / "voice.wav",
        copy=_long_copy("devotional", voice_style_profile="devotional_teacher"),
        model_name="gemini-3.1-flash-tts-preview",
    )

    out = capsys.readouterr().out
    assert "Gemini TTS style profile: devotional_teacher" in out
    assert "Style selection reason: explicit manual override" in out


def test_generate_with_gemini_raises_before_api_call_when_transcript_is_missing_a_unit(monkeypatch, tmp_path):
    fake_client = MagicMock()
    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider, "_get_gemini_client", lambda: fake_client)

    try:
        voice_provider._generate_with_gemini(
            "Let this prayer meet you right where you are.\n\nAmen.",
            "Orus",
            voice_provider.PRAYER_STYLE_INSTRUCTION,
            tmp_path / "voice.wav",
            copy=_long_copy(),
            model_name="gemini-3.1-flash-tts-preview",
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "validation failed" in str(exc).lower()
    assert fake_client.models.generate_content.call_count == 0


def test_gemini_tts_uses_primary_key_when_legacy_key_is_absent(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider.config, "get_gemini_primary_api_key", lambda: "primary-only-key")
    monkeypatch.setattr(voice_provider.genai, "Client", lambda api_key: fake_client if api_key == "primary-only-key" else None)

    client = voice_provider._get_gemini_client()

    assert client is fake_client


def test_gemini_tts_still_supports_legacy_key(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(voice_provider, "_gemini_client", None)
    monkeypatch.setattr(voice_provider.config, "get_gemini_primary_api_key", lambda: "legacy-key")
    monkeypatch.setattr(voice_provider.genai, "Client", lambda api_key: fake_client if api_key == "legacy-key" else None)

    client = voice_provider._get_gemini_client()

    assert client is fake_client


def test_test_mode_makes_no_gemini_tts_call(isolated_database, monkeypatch, tmp_path):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", False)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(prayonit_social.config, "VOICE_ENABLED", True)
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
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _long_copy())
    monkeypatch.setattr(prayonit_social.prompt_builder, "build_platform_captions", lambda *args, **kwargs: {"facebook": "f", "instagram": "i", "threads": "t"})
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: __import__("PIL").Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: __import__("PIL").Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: __import__("PIL").Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": [], "pass": True, "score": 100})
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: (_ for _ in ()).throw(AssertionError("tracking called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("video upload called")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "strength",
            "emotion": "overwhelmed",
            "hook_style": "recognition",
            "objective": "obj",
            "video_template": "long_prayer",
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
        },
    )
    motion_dir = tmp_path / "motion_backgrounds"
    motion_dir.mkdir()
    (motion_dir / "bg1.mp4").write_bytes(b"fake")
    monkeypatch.setattr(prayonit_social.config, "MOTION_BACKGROUNDS_DIR", motion_dir)
    monkeypatch.setattr(voice_provider, "generate_voiceover", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini TTS called in TEST_MODE")))
    def fake_render_long_form_video(**kwargs):
        out_path = Path(kwargs["output_path"])
        out_path.write_bytes(b"x")
        return out_path

    monkeypatch.setattr("long_form_renderer.render_long_form_video", fake_render_long_form_video)

    result = prayonit_social.cmd_run("morning")
    assert result == 0


def test_preview_mode_logs_narration_units_without_calling_tts(isolated_database, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(prayonit_social.config, "TEST_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "PREVIEW_MODE", True)
    monkeypatch.setattr(prayonit_social.config, "VIDEO_ENABLED", True)
    monkeypatch.setattr(prayonit_social.config, "VOICE_ENABLED", False)
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
    monkeypatch.setattr(prayonit_social.prompt_builder, "generate_local_ad_copy", lambda selection, slot: _long_copy())
    monkeypatch.setattr(prayonit_social.prompt_builder, "build_platform_captions", lambda *args, **kwargs: {"facebook": "f", "instagram": "i"})
    monkeypatch.setattr(prayonit_social.image_renderer, "load_background", lambda path: __import__("PIL").Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "crop_to_canvas", lambda image, canvas_size=(1080, 1350): image)
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_ad", lambda background, copy: __import__("PIL").Image.new("RGB", (1080, 1350), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compose_story_ad", lambda background, copy: __import__("PIL").Image.new("RGB", (1080, 1920), (0, 0, 0)))
    monkeypatch.setattr(prayonit_social.image_renderer, "compute_local_contrast_metrics", lambda image, kind: {"overall_pass": True, "zones": {}})
    monkeypatch.setattr(prayonit_social.creative_engine_v3, "build_prepublish_qa_report", lambda **kwargs: {"critical_failures": [], "pass": True, "score": 100})
    monkeypatch.setattr(prayonit_social.tracking, "create_tracked_link", lambda **kwargs: (_ for _ in ()).throw(AssertionError("tracking called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("upload called")))
    monkeypatch.setattr(prayonit_social.image_renderer, "upload_generated_video", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("video upload called")))
    monkeypatch.setattr(prayonit_social.buffer_client, "buffer_create_post", lambda **kwargs: (_ for _ in ()).throw(AssertionError("buffer called")))
    monkeypatch.setattr(
        prayonit_social.content_engine,
        "get_todays_content",
        lambda slot, now=None, weekly_rhythm=None: {
            "content_type": "prayer_read",
            "theme": "strength",
            "emotion": "overwhelmed",
            "hook_style": "recognition",
            "objective": "obj",
            "video_template": "long_prayer",
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
        },
    )
    motion_dir = tmp_path / "motion_backgrounds"
    motion_dir.mkdir()
    (motion_dir / "bg1.mp4").write_bytes(b"fake")
    monkeypatch.setattr(prayonit_social.config, "MOTION_BACKGROUNDS_DIR", motion_dir)

    def fake_render_long_form_video(**kwargs):
        out_path = Path(kwargs["output_path"])
        out_path.write_bytes(b"x")
        return out_path

    monkeypatch.setattr("long_form_renderer.render_long_form_video", fake_render_long_form_video)

    result = prayonit_social.cmd_run("morning")
    out = capsys.readouterr().out

    assert result == 0
    assert "Narration units:" in out
    assert "- bridge_line: Let this prayer meet you right where you are." in out
    assert "- script_segments[0]: Lord, steady my heart today." in out
    assert "- script_segments[1]: Give me peace and strength for what is ahead." in out
    assert "- closing_line: Amen." in out
    assert "Final narration transcript character count:" in out
    assert "Final narration transcript sentence count:" in out
