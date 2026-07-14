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


def buffer_create_post(
    *,
    channel_id: str,
    caption: str,
    image_url: str,
    service: str,
    post_type: str,
    due_at_iso: str,
    link: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a single Buffer post. Raises on any failure.

    link: the exact destination URL for this platform item (tracked URL when
    TRACKING_ENABLED=true, otherwise DEFAULT_DESTINATION_URL), as returned by
    tracking.create_tracked_link(). Only used for Instagram feed posts
    (metadata.instagram.link); ignored for Instagram Stories and all other
    services/post types.
    """
    input_data: Dict[str, Any] = {
        "text": caption,
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_iso,
        "assets": [{"image": {"url": image_url}}],
        "source": "Prayonit Python Automation",
        "aiAssisted": True,
    }

    if service == "facebook":
        input_data["metadata"] = {"facebook": {"type": post_type}}
    elif service == "instagram":
        instagram_metadata: Dict[str, Any] = {
            "type": post_type,
            "shouldShareToFeed": post_type == "post",
        }
        # Only Instagram feed posts get a link. Stories are left unchanged
        # unless/until Buffer's schema is verified to support a link field
        # for InstagramStoryMetadataInput.
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
