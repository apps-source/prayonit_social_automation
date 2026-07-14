"""Tracked-link generation (Layer 1).

Layer 1 (implemented here): generate a unique short tracking ID per published
platform item, store its mapping locally in SQLite, and build a tracked URL
that points at TRACKING_BASE_URL. This does not assume a redirect endpoint
already exists.

Layer 2 (not deployed by this module): a future Supabase Edge Function
(see supabase/functions/track-download/) will resolve /download?t=<id> to the
correct App Store / Google Play destination and record the click. See
docs/TRACKING.md for deployment instructions.
"""
import hashlib
import secrets
import time
from typing import Optional

import config
import history_store


def _generate_tracking_id() -> str:
    """Generate a short, URL-safe, unique-enough tracking id.

    Combines a random token with a time-based component. TRACKING_SECRET (if
    set) is mixed in via a hash but is never included in, or derivable from,
    the output token, and is never logged.
    """
    random_part = secrets.token_urlsafe(6)
    time_part = str(int(time.time() * 1000))
    seed = f"{random_part}{time_part}{config.TRACKING_SECRET}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:6]
    return f"{random_part}{digest}"


def build_tracked_url(tracking_id: str) -> str:
    base = config.TRACKING_BASE_URL.rstrip("/")
    return f"{base}/download?t={tracking_id}"


def create_tracked_link(
    *,
    run_id: str,
    campaign_name: str,
    formula_name: Optional[str],
    persona_name: Optional[str],
    platform: str,
    post_type: str,
    slot: str,
    scheduled_at_utc: Optional[str],
    destination: Optional[str] = None,
) -> str:
    """Create (and always persist) a tracking id + tracked URL, then return
    the URL that should actually be used in captions/Buffer posts.

    A tracking id and its underlying tracked URL (pointing at
    TRACKING_BASE_URL) are ALWAYS generated and stored in SQLite, so that
    tracking can be switched on later (via TRACKING_ENABLED=true) without
    losing history or requiring code changes.

    However, the URL returned here (and thus the one that ends up in public
    captions) depends on config.TRACKING_ENABLED:

      - True:  returns the tracked URL (https://.../download?t=<id>).
      - False: returns the plain destination URL directly, with no
               /download or ?t= suffix, since the Layer 2 redirect endpoint
               is not deployed and would otherwise 404.
    """
    tracking_id = _generate_tracking_id()
    resolved_destination = destination or config.DEFAULT_DESTINATION_URL
    tracked_url = build_tracked_url(tracking_id)

    history_store.save_tracking_link(
        tracking_id=tracking_id,
        run_id=run_id,
        campaign_name=campaign_name,
        formula_name=formula_name,
        persona_name=persona_name,
        platform=platform,
        post_type=post_type,
        slot=slot,
        destination=resolved_destination,
        scheduled_at_utc=scheduled_at_utc,
        tracked_url=tracked_url,
    )

    if config.TRACKING_ENABLED:
        return tracked_url

    print("Tracking disabled — using direct destination URL.")
    return resolved_destination

