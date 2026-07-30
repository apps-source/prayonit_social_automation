"""Buffer GraphQL client: post creation, schema introspection, and metrics.

Never logs BUFFER_API_KEY.
"""
import json
from typing import Any, Dict, Optional

import requests

import config

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
        dueAt
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

# A conservative, generic introspection query. Buffer's public GraphQL schema
# is not guaranteed to be identical to Buffer's older REST API, so this
# queries the live schema rather than guessing metric field names.
INTROSPECTION_QUERY = """
query IntrospectSchema {
  __schema {
    types {
      name
      kind
      fields {
        name
        type {
          name
          kind
          ofType {
            name
            kind
          }
        }
      }
    }
  }
}
"""


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {config.BUFFER_API_KEY}",
        "Content-Type": "application/json",
    }


def build_create_post_input(
    *,
    channel_id: str,
    caption: str,
    service: str,
    post_type: str,
    due_at_iso: str,
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    link: Optional[str] = None,
    platform_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one schema-conservative Buffer CreatePostInput value."""
    if bool(image_url) == bool(video_url):
        raise ValueError(
            "buffer_create_post requires exactly one of image_url or video_url."
        )

    input_data = {
        "text": caption,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_iso,
        "assets": [{"video": {"url": video_url}}] if video_url else [{"image": {"url": image_url}}],
        "source": "Prayonit Python Automation",
        "aiAssisted": True,
    }

    if service == "facebook":
        # PostTypeFacebook (confirmed via schema introspection) includes
        # "post", "story", and "reel" -- post_type="reel" is passed through
        # unchanged here, identical to the existing "post"/"story" handling.
        input_data["metadata"] = {"facebook": {"type": post_type}}
    elif service == "instagram":
        instagram_metadata: Dict[str, Any] = {
            "type": post_type,
            "shouldShareToFeed": post_type == "post",
        }
        # Only Instagram feed posts get a link. Stories and Reels are left
        # unchanged unless/until Buffer's schema is verified to support a
        # link field for those metadata shapes.
        if post_type == "post" and link:
            instagram_metadata["link"] = link
        input_data["metadata"] = {"instagram": instagram_metadata}
    elif service == "threads":
        threads_metadata: Dict[str, Any] = {"type": post_type}
        if config.THREADS_LOCATION_NAME.strip():
            threads_metadata["locationName"] = config.THREADS_LOCATION_NAME.strip()
        if config.THREADS_LOCATION_ID.strip():
            threads_metadata["locationId"] = config.THREADS_LOCATION_ID.strip()
        input_data["metadata"] = {"threads": threads_metadata}
    elif service == "tiktok":
        # TikTokPostMetadataInput (confirmed via schema introspection) has
        # only "title" and "isAiGenerated" fields -- no "type" enum, since
        # TikTok channels only accept video posts.
        options = dict(platform_options or {})
        unsupported = set(options) - {"title", "isAiGenerated"}
        if unsupported:
            raise ValueError(
                "Unsupported TikTok Buffer options: "
                + ", ".join(sorted(unsupported))
            )
        if options.get("isAiGenerated", True) is not True:
            raise ValueError(
                "TikTok isAiGenerated must remain enabled for Prayonit posts."
            )
        tiktok_metadata: Dict[str, Any] = {"isAiGenerated": True}
        title = str(options.get("title", "")).strip()
        if title:
            tiktok_metadata["title"] = title
        input_data["metadata"] = {"tiktok": tiktok_metadata}
    elif platform_options:
        raise ValueError(
            f"Platform options are not supported for {service}/{post_type}."
        )
    return input_data


def buffer_create_post(
    *,
    channel_id: str,
    caption: str,
    service: str,
    post_type: str,
    due_at_iso: str,
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    link: Optional[str] = None,
    platform_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a single Buffer post. Raises on any failure.

    Exactly one of image_url / video_url must be provided. The pure payload
    builder above keeps schema validation testable without a network call.
    """
    input_data = build_create_post_input(
        channel_id=channel_id,
        caption=caption,
        service=service,
        post_type=post_type,
        due_at_iso=due_at_iso,
        image_url=image_url,
        video_url=video_url,
        link=link,
        platform_options=platform_options,
    )

    response = requests.post(
        config.BUFFER_ENDPOINT,
        headers=_headers(),
        json={"query": CREATE_POST_MUTATION, "variables": {"input": input_data}},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error for {service}/{post_type}: {payload['errors']}")

    result = payload.get("data", {}).get("createPost", {})
    if result.get("message"):
        raise RuntimeError(f"Buffer rejected {service}/{post_type} post: {result['message']}")

    return result


def discover_buffer_metrics_schema() -> Dict[str, Any]:
    """Run a GraphQL introspection query and save the raw schema locally.

    Does not attempt to build a metrics query from this data automatically;
    it only captures ground truth for a human (or a later, careful change) to
    read before writing a metrics query against verified field names.
    """
    response = requests.post(
        config.BUFFER_ENDPOINT,
        headers=_headers(),
        json={"query": INTROSPECTION_QUERY},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    config.BUFFER_METRICS_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.BUFFER_METRICS_SCHEMA_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    return payload


def build_metrics_query_from_schema(schema_path=None) -> Optional[str]:
    """Attempt to build a metrics query using only field names confirmed to
    exist in the saved introspection schema. Returns None if the schema has
    not been discovered yet, or if a Post/metrics field cannot be located,
    rather than guessing.
    """
    path = schema_path or config.BUFFER_METRICS_SCHEMA_PATH
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)

    types = schema.get("data", {}).get("__schema", {}).get("types", [])
    post_type = next((t for t in types if t.get("name") == "Post"), None)
    if not post_type:
        return None

    fields = post_type.get("fields") or []
    metrics_field = next((f for f in fields if f.get("name") == "metrics"), None)
    if not metrics_field:
        return None

    # Field exists but we still do not assume its sub-fields without checking
    # the corresponding result type in the same schema dump. Callers should
    # inspect data/buffer_metrics_schema.json directly before relying on this.
    return None


def fetch_post_metrics(buffer_post_id: str, query: str) -> Dict[str, Any]:
    """Fetch metrics for one Buffer post using a caller-supplied, schema-verified query."""
    response = requests.post(
        config.BUFFER_ENDPOINT,
        headers=_headers(),
        json={"query": query, "variables": {"postId": buffer_post_id}},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Buffer metrics error for post {buffer_post_id}: {payload['errors']}")
    return payload
