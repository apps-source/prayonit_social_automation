"""Tests for buffer_client.py: post creation success/failure, fully mocked HTTP."""
from unittest.mock import MagicMock, patch

import pytest

import buffer_client
import config


def _mock_response(json_payload, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_payload
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


def test_buffer_create_post_success():
    payload = {"data": {"createPost": {"post": {"id": "post-123", "text": "hi", "dueAt": "2026-07-10T13:00:00Z"}}}}
    with patch("buffer_client.requests.post", return_value=_mock_response(payload)):
        result = buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="Test caption",
            image_url="https://example.com/image.jpg",
            service="facebook",
            post_type="post",
            due_at_iso="2026-07-10T13:00:00Z",
        )
    assert result["post"]["id"] == "post-123"


def test_buffer_create_post_graphql_error_raises():
    payload = {"errors": [{"message": "bad channel"}]}
    with patch("buffer_client.requests.post", return_value=_mock_response(payload)):
        with pytest.raises(RuntimeError):
            buffer_client.buffer_create_post(
                channel_id="chan-1",
                caption="Test caption",
                image_url="https://example.com/image.jpg",
                service="facebook",
                post_type="post",
                due_at_iso="2026-07-10T13:00:00Z",
            )


def test_buffer_create_post_mutation_error_raises():
    payload = {"data": {"createPost": {"message": "rejected"}}}
    with patch("buffer_client.requests.post", return_value=_mock_response(payload)):
        with pytest.raises(RuntimeError):
            buffer_client.buffer_create_post(
                channel_id="chan-1",
                caption="Test caption",
                image_url="https://example.com/image.jpg",
                service="instagram",
                post_type="story",
                due_at_iso="2026-07-10T13:00:00Z",
            )


def test_instagram_story_metadata_shape():
    payload = {"data": {"createPost": {"post": {"id": "abc"}}}}
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["input"] = json["variables"]["input"]
        return _mock_response(payload)

    with patch("buffer_client.requests.post", side_effect=fake_post):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="",
            image_url="https://example.com/story.jpg",
            service="instagram",
            post_type="story",
            due_at_iso="2026-07-10T13:00:00Z",
        )

    assert captured["input"]["metadata"]["instagram"]["type"] == "story"
    assert captured["input"]["metadata"]["instagram"]["shouldShareToFeed"] is False
    assert captured["input"]["mode"] == "customScheduled"


# ---------- Buffer schedulingType/mode/dueAt fix ----------

def _capture_input(service, post_type, due_at_iso="2026-07-10T13:00:00Z"):
    payload = {"data": {"createPost": {"post": {"id": "abc"}}}}
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["input"] = json["variables"]["input"]
        return _mock_response(payload)

    with patch("buffer_client.requests.post", side_effect=fake_post):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="caption text",
            image_url="https://example.com/image.jpg",
            service=service,
            post_type=post_type,
            due_at_iso=due_at_iso,
        )
    return captured["input"]


def test_scheduling_type_is_automatic():
    input_data = _capture_input("facebook", "post")
    assert input_data["schedulingType"] == "automatic"


def test_mode_is_custom_scheduled():
    input_data = _capture_input("facebook", "post")
    assert input_data["mode"] == "customScheduled"


def test_due_at_is_included_and_matches_input():
    due_at = "2026-07-10T13:00:00Z"
    input_data = _capture_input("facebook", "post", due_at_iso=due_at)
    assert input_data["dueAt"] == due_at


@pytest.mark.parametrize(
    "service,post_type",
    [
        ("facebook", "post"),
        ("instagram", "post"),
        ("facebook", "story"),
        ("instagram", "story"),
        ("threads", "post"),
    ],
)
def test_all_five_item_types_use_corrected_scheduling_fields(service, post_type):
    input_data = _capture_input(service, post_type)
    assert input_data["schedulingType"] == "automatic"
    assert input_data["mode"] == "customScheduled"
    assert input_data["dueAt"] == "2026-07-10T13:00:00Z"


# ---------- Instagram/Threads Buffer metadata placement (this change) ----------

def _capture_input_with_link(service, post_type, link, monkeypatch=None):
    payload = {"data": {"createPost": {"post": {"id": "abc"}}}}
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["input"] = json["variables"]["input"]
        return _mock_response(payload)

    with patch("buffer_client.requests.post", side_effect=fake_post):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="caption text",
            image_url="https://example.com/image.jpg",
            service=service,
            post_type=post_type,
            due_at_iso="2026-07-10T13:00:00Z",
            link=link,
        )
    return captured["input"]


def test_instagram_feed_metadata_includes_link():
    input_data = _capture_input_with_link("instagram", "post", "https://example.com/app")
    assert input_data["metadata"]["instagram"]["link"] == "https://example.com/app"


def test_instagram_feed_link_equals_default_destination_url_when_tracking_disabled(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "https://example.com/app")
    # Simulates the value tracking.create_tracked_link() returns when disabled.
    input_data = _capture_input_with_link("instagram", "post", config.DEFAULT_DESTINATION_URL)
    assert input_data["metadata"]["instagram"]["link"] == "https://example.com/app"


def test_instagram_feed_link_equals_tracked_url_when_tracking_enabled(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", True)
    tracked_url = "https://prayonit.example.com/download?t=ig123"
    input_data = _capture_input_with_link("instagram", "post", tracked_url)
    assert input_data["metadata"]["instagram"]["link"] == tracked_url


def test_instagram_feed_metadata_preserves_should_share_to_feed():
    input_data = _capture_input_with_link("instagram", "post", "https://example.com/app")
    assert input_data["metadata"]["instagram"]["shouldShareToFeed"] is True
    assert input_data["metadata"]["instagram"]["type"] == "post"


def test_instagram_story_behavior_unchanged_no_link_added():
    input_data = _capture_input_with_link("instagram", "story", "https://example.com/app")
    assert "link" not in input_data["metadata"]["instagram"]
    assert input_data["metadata"]["instagram"]["shouldShareToFeed"] is False
    assert input_data["metadata"]["instagram"]["type"] == "story"


def test_facebook_metadata_unchanged_by_this_change():
    input_data = _capture_input_with_link("facebook", "post", "https://example.com/app")
    assert input_data["metadata"]["facebook"] == {"type": "post"}
    assert "instagram" not in input_data["metadata"]


def test_threads_metadata_includes_location_name_when_configured(monkeypatch):
    monkeypatch.setattr(config, "THREADS_LOCATION_NAME", "United States of America")
    monkeypatch.setattr(config, "THREADS_LOCATION_ID", "")
    input_data = _capture_input_with_link("threads", "post", None)
    assert input_data["metadata"]["threads"]["locationName"] == "United States of America"
    assert "locationId" not in input_data["metadata"]["threads"]
    assert input_data["metadata"]["threads"]["type"] == "post"


def test_threads_metadata_includes_location_id_when_configured(monkeypatch):
    monkeypatch.setattr(config, "THREADS_LOCATION_NAME", "")
    monkeypatch.setattr(config, "THREADS_LOCATION_ID", "12345")
    input_data = _capture_input_with_link("threads", "post", None)
    assert input_data["metadata"]["threads"]["locationId"] == "12345"
    assert "locationName" not in input_data["metadata"]["threads"]


def test_threads_metadata_omits_empty_location_values(monkeypatch):
    monkeypatch.setattr(config, "THREADS_LOCATION_NAME", "")
    monkeypatch.setattr(config, "THREADS_LOCATION_ID", "")
    input_data = _capture_input_with_link("threads", "post", None)
    assert "locationName" not in input_data["metadata"]["threads"]
    assert "locationId" not in input_data["metadata"]["threads"]
    assert input_data["metadata"]["threads"] == {"type": "post"}


# ---------- Phase 2A: video (Reel/TikTok) payload tests (schema-verified, mocked HTTP only) ----------

def _capture_video_input(service, post_type, video_url="https://cdn.example.com/reel.mp4", link=None):
    payload = {"data": {"createPost": {"post": {"id": "vid-post"}}}}
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["input"] = json["variables"]["input"]
        return _mock_response(payload)

    with patch("buffer_client.requests.post", side_effect=fake_post):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="caption text",
            service=service,
            post_type=post_type,
            due_at_iso="2026-07-10T13:00:00Z",
            video_url=video_url,
            link=link,
        )
    return captured["input"]


def test_facebook_reel_uses_video_asset_not_image():
    input_data = _capture_video_input("facebook", "reel", video_url="https://cdn.example.com/reel.mp4")
    assert input_data["assets"] == [{"video": {"url": "https://cdn.example.com/reel.mp4"}}]
    assert not any("image" in asset for asset in input_data["assets"])


def test_facebook_reel_metadata_type_is_reel():
    input_data = _capture_video_input("facebook", "reel")
    assert input_data["metadata"]["facebook"] == {"type": "reel"}


def test_facebook_reel_sends_no_link_attachment():
    input_data = _capture_video_input("facebook", "reel", link="https://example.com/app")
    assert "linkAttachment" not in input_data["metadata"]["facebook"]
    assert "link" not in input_data["metadata"]["facebook"]


def test_instagram_reel_uses_video_asset_not_image():
    input_data = _capture_video_input("instagram", "reel", video_url="https://cdn.example.com/reel.mp4")
    assert input_data["assets"] == [{"video": {"url": "https://cdn.example.com/reel.mp4"}}]
    assert not any("image" in asset for asset in input_data["assets"])


def test_instagram_reel_metadata_type_is_reel():
    input_data = _capture_video_input("instagram", "reel")
    assert input_data["metadata"]["instagram"]["type"] == "reel"


def test_instagram_reel_sends_no_link_attachment():
    input_data = _capture_video_input("instagram", "reel", link="https://example.com/app")
    assert "link" not in input_data["metadata"]["instagram"]
    assert "linkAttachment" not in input_data["metadata"]["instagram"]


def test_tiktok_uses_video_asset_not_image():
    input_data = _capture_video_input("tiktok", "video", video_url="https://cdn.example.com/reel.mp4")
    assert input_data["assets"] == [{"video": {"url": "https://cdn.example.com/reel.mp4"}}]
    assert not any("image" in asset for asset in input_data["assets"])


def test_tiktok_metadata_has_only_ai_generated_flag():
    input_data = _capture_video_input("tiktok", "video")
    # TikTokPostMetadataInput (schema-confirmed) has only "title" and
    # "isAiGenerated" -- no "type" field, since TikTok channels only
    # accept video posts. Assert no unsupported/invented fields exist.
    assert input_data["metadata"]["tiktok"] == {"isAiGenerated": True}


def test_tiktok_verified_title_is_serialized_with_ai_disclosure():
    input_data = buffer_client.build_create_post_input(
        channel_id="chan-1",
        caption="caption text",
        service="tiktok",
        post_type="video",
        due_at_iso="2026-07-10T13:00:00Z",
        video_url="https://cdn.example.com/reel.mp4",
        platform_options={
            "title": "A prayer for today",
            "isAiGenerated": True,
        },
    )
    assert input_data["metadata"]["tiktok"] == {
        "title": "A prayer for today",
        "isAiGenerated": True,
    }


def test_tiktok_unverified_metadata_fields_are_rejected():
    with pytest.raises(ValueError, match="Unsupported TikTok Buffer options"):
        buffer_client.build_create_post_input(
            channel_id="chan-1",
            caption="caption text",
            service="tiktok",
            post_type="video",
            due_at_iso="2026-07-10T13:00:00Z",
            video_url="https://cdn.example.com/reel.mp4",
            platform_options={"disableComments": True},
        )


def test_tiktok_sends_no_link_attachment():
    input_data = _capture_video_input("tiktok", "video", link="https://example.com/app")
    assert "link" not in input_data["metadata"]["tiktok"]
    assert "linkAttachment" not in input_data["metadata"]["tiktok"]


def test_image_and_video_url_both_supplied_raises():
    with pytest.raises(ValueError):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="caption text",
            service="facebook",
            post_type="reel",
            due_at_iso="2026-07-10T13:00:00Z",
            image_url="https://example.com/image.jpg",
            video_url="https://cdn.example.com/reel.mp4",
        )


def test_neither_image_nor_video_url_supplied_raises():
    with pytest.raises(ValueError):
        buffer_client.buffer_create_post(
            channel_id="chan-1",
            caption="caption text",
            service="facebook",
            post_type="reel",
            due_at_iso="2026-07-10T13:00:00Z",
        )


def test_same_uploaded_video_url_reused_across_three_calls():
    video_url = "https://cdn.example.com/same-reel.mp4"
    fb_input = _capture_video_input("facebook", "reel", video_url=video_url)
    ig_input = _capture_video_input("instagram", "reel", video_url=video_url)
    tiktok_input = _capture_video_input("tiktok", "video", video_url=video_url)

    assert fb_input["assets"] == [{"video": {"url": video_url}}]
    assert ig_input["assets"] == [{"video": {"url": video_url}}]
    assert tiktok_input["assets"] == [{"video": {"url": video_url}}]
