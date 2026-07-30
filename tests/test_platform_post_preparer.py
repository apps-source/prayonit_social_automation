from dataclasses import replace
from types import SimpleNamespace

import pytest

import buffer_client
import platform_post_preparer


def _brief(category="general_prayer", profile="current_default", run_id="run-1"):
    return SimpleNamespace(
        run_id=run_id,
        prayer_category_id=category,
        life_moment_text="Carrying a heavy day",
        hook_profile_id="gentle_invitation",
        voice_profile_id="natural_conversational",
        body_profile_id="general_prayer",
        caption_profile_id="rolling_short",
        scene_profile_id="current_default",
        cta_profile_id="current_default",
        hashtag_profile_id=profile,
        creative_policy_version="1",
    )


def _prepare(platform, *, category="general_prayer", caption=None, run_id="run-1"):
    base_caption = caption or "God is near in this moment."
    return platform_post_preparer.prepare_platform_post(
        platform=platform,
        base_caption=base_caption,
        brief=_brief(category=category, run_id=run_id),
        scheduled_at="2026-07-30T12:00:00Z",
        post_type="video" if platform == "tiktok" else "reel",
        media_reference="https://cdn.example/video.mp4",
        direct_url=(
            "https://prayonit.app" if platform == "facebook" else None
        ),
        selected_asset_ids=("asset-1", "asset-2"),
    )


def test_resolved_hashtag_profile_id_is_consumed():
    with pytest.raises(
        platform_post_preparer.PlatformPostPreparationError,
        match="Unknown hashtag profile",
    ):
        platform_post_preparer.prepare_platform_post(
            platform="tiktok",
            base_caption="Pray with me.",
            brief=_brief(profile="unknown_profile"),
            scheduled_at="2026-07-30T12:00:00Z",
            post_type="video",
            media_reference="https://cdn.example/video.mp4",
        )


def test_tiktok_hashtags_are_category_relevant_and_limited():
    post = _prepare("tiktok", category="anxiety")
    assert "#AnxietyPrayer" in post.hashtags or "#PrayerForPeace" in post.hashtags
    assert 4 <= len(post.hashtags) <= 6
    assert "#Prayonit" in post.hashtags


def test_instagram_hashtags_are_category_relevant_and_limited():
    post = _prepare("instagram", category="protection")
    assert "#PrayerForProtection" in post.hashtags
    assert 4 <= len(post.hashtags) <= 7


def test_facebook_hashtags_remain_limited():
    post = _prepare("facebook", category="bible_verse")
    assert "#BibleVerse" in post.hashtags
    assert len(post.hashtags) <= 3


@pytest.mark.parametrize(
    "variant",
    [
        "Come pray with me.",
        "Come pray with us!",
        "Join me in prayer.",
        "Pray with me today.",
        "Download Prayonit and pray with me.",
    ],
)
def test_semantically_equivalent_cta_is_retained_exactly_once(variant):
    post = _prepare(
        "facebook",
        caption=f"God is near today.\n\n{variant}\n\nCome pray with me.",
    )
    assert (
        len(
            platform_post_preparer.CTA_EQUIVALENT_PATTERN.findall(
                post.public_caption
            )
        )
        == 1
    )
    assert post.cta_diagnostics["cta_duplicates_removed"] >= 2


def test_unrelated_prayer_language_is_not_removed():
    post = _prepare(
        "facebook",
        caption="Prayer can make room for honest reflection.",
    )
    assert "Prayer can make room" in post.public_caption


def test_duplicate_link_in_bio_is_removed_and_appended_once():
    post = _prepare(
        "instagram",
        caption="A quiet encouragement.\nLink in bio.\nLINK IN THE BIO!",
    )
    assert (
        len(
            platform_post_preparer.LINK_IN_BIO_PATTERN.findall(
                post.public_caption
            )
        )
        == 1
    )
    assert post.cta_diagnostics["link_in_bio_duplicates_removed"] == 2


def test_duplicate_direct_urls_are_removed_and_one_approved_url_is_appended():
    post = _prepare(
        "facebook",
        caption=(
            "A quiet encouragement. https://wrong.example "
            "https://wrong.example"
        ),
    )
    assert platform_post_preparer.URL_PATTERN.findall(post.public_caption) == [
        "https://prayonit.app"
    ]
    assert post.cta_diagnostics["url_duplicates_removed"] == 2


def test_internal_profile_ids_never_appear_publicly():
    post = _prepare("tiktok", category="morning_prayer")
    public = post.public_caption + " " + str(post.platform_options)
    for key, value in post.internal_metadata.items():
        if key.endswith("_profile_id") and value:
            assert value not in public
    assert post.internal_metadata["selected_asset_ids"] == [
        "asset-1",
        "asset-2",
    ]


def test_tiktok_preserves_ai_disclosure_and_uses_only_supported_options():
    post = _prepare("tiktok", category="morning_prayer")
    assert post.platform_options["isAiGenerated"] is True
    assert set(post.platform_options) <= {"title", "isAiGenerated"}


def test_unsupported_tiktok_option_fails_validation():
    post = _prepare("tiktok")
    unsafe = replace(
        post,
        platform_options={
            **post.platform_options,
            "disableDuet": True,
        },
    )
    with pytest.raises(
        platform_post_preparer.PlatformPostPreparationError,
        match="unsupported TikTok options",
    ):
        unsafe.validate()


def test_facebook_never_receives_link_in_bio_wording():
    post = _prepare("facebook", caption="Encouragement. Link in bio.")
    assert "link in bio" not in post.public_caption.lower()
    assert "https://prayonit.app" in post.public_caption


def test_instagram_never_receives_raw_facebook_url():
    post = _prepare(
        "instagram",
        caption="Encouragement. https://prayonit.app",
    )
    assert "https://" not in post.public_caption
    assert "Link in bio." in post.public_caption


def test_hashtag_selection_is_deterministic_for_same_run():
    first = _prepare("instagram", category="morning_prayer", run_id="same")
    second = _prepare("instagram", category="morning_prayer", run_id="same")
    assert first.hashtags == second.hashtags


def test_prepared_post_rejects_absolute_media_path():
    with pytest.raises(
        platform_post_preparer.PlatformPostPreparationError,
        match="media URL",
    ):
        platform_post_preparer.prepare_platform_post(
            platform="facebook",
            base_caption="A prayer for today.",
            brief=_brief(),
            scheduled_at="2026-07-30T12:00:00Z",
            post_type="reel",
            media_reference="/Users/example/video.mp4",
            direct_url="https://prayonit.app",
        )


def test_publishing_status_outcomes():
    assert platform_post_preparer.resolve_publishing_status(
        intended_count=3, success_count=3, failure_count=0
    ) == "published"
    assert platform_post_preparer.resolve_publishing_status(
        intended_count=3, success_count=2, failure_count=1
    ) == "partially_published"
    assert platform_post_preparer.resolve_publishing_status(
        intended_count=3, success_count=0, failure_count=3
    ) == "failed"
    assert platform_post_preparer.resolve_publishing_status(
        intended_count=0, success_count=0, failure_count=0
    ) == "prepared"


def test_pure_buffer_payload_contains_no_internal_metadata():
    post = _prepare("tiktok", category="bible_verse")
    payload = buffer_client.build_create_post_input(
        channel_id="channel",
        caption=post.public_caption,
        service=post.platform,
        post_type=post.post_type,
        due_at_iso=post.scheduled_at,
        video_url=post.media_reference,
        platform_options=post.platform_options,
    )
    serialized = str(payload)
    assert payload["metadata"]["tiktok"]["isAiGenerated"] is True
    assert set(payload["metadata"]["tiktok"]) == {"title", "isAiGenerated"}
    assert "body_profile_id" not in serialized
    assert "selected_asset_ids" not in serialized


def test_buffer_serializer_rejects_unverified_tiktok_fields():
    with pytest.raises(ValueError, match="Unsupported TikTok Buffer options"):
        buffer_client.build_create_post_input(
            channel_id="channel",
            caption="Caption",
            service="tiktok",
            post_type="video",
            due_at_iso="2026-07-30T12:00:00Z",
            video_url="https://cdn.example/video.mp4",
            platform_options={"privacy": "public"},
        )
