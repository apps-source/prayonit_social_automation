"""Central configuration for the Prayonit Marketing Engine.

Loads environment variables once and exposes them as module-level constants.
Never print or log secret values (API keys, service-role keys, tracking secret)
from this module or anywhere else in the project.

---------------------------------------------------------------------------
Phase 1A brand configuration loader
---------------------------------------------------------------------------
This module also loads a brand configuration YAML file (see
brands/<brand>/brand.yaml) selected via the BRAND environment variable
(defaulting to "prayonit"). This is intentionally a thin loading layer only:
every existing public constant below (LOGO_PATH, BRAND_DIR, CAMPAIGNS_DIR,
SUPABASE_BUCKET, DATABASE_PATH, TRACKING_BASE_URL, etc.) still resolves to
exactly the same values as before this change, since brands/prayonit/
brand.yaml simply points at the existing, unmoved project locations
(brand/, campaigns/, formulas/, personas/, seasonality/, assets/). No
existing files or folders were moved as part of this phase. Secrets and
Buffer channel IDs are never read from brand.yaml; they remain
environment-variable-only.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Do not let .env override variables supplied by the invoking command.
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parent
BRANDS_DIR = PROJECT_ROOT / "brands"


def _resolve_path(relative_or_absolute: str) -> Path:
    """Resolve a brand.yaml path value against PROJECT_ROOT.

    Absolute paths are returned as-is (resolved); relative paths are
    resolved relative to the project root, matching every other path
    constant already defined in this module.
    """
    p = Path(relative_or_absolute)
    if p.is_absolute():
        return p
    return (PROJECT_ROOT / p).resolve()


def load_brand_config(brand_id: str) -> Dict[str, Any]:
    """Load and parse brands/<brand_id>/brand.yaml.

    Raises RuntimeError with a clear message if the brand configuration
    file does not exist. Never silently falls back to another brand.
    """
    brand_yaml_path = BRANDS_DIR / brand_id / "brand.yaml"
    if not brand_yaml_path.exists():
        raise RuntimeError(f"Unknown brand configuration: {brand_id}")
    with open(brand_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Unknown brand configuration: {brand_id}")
    return data


BRAND_ID = os.getenv("BRAND", "prayonit").strip() or "prayonit"
BRAND_CONFIG: Dict[str, Any] = load_brand_config(BRAND_ID)

_brand_section = BRAND_CONFIG.get("brand", {}) or {}
_assets_section = BRAND_CONFIG.get("assets", {}) or {}
_content_section = BRAND_CONFIG.get("content", {}) or {}
_storage_section = BRAND_CONFIG.get("storage", {}) or {}
_database_section = BRAND_CONFIG.get("database", {}) or {}
_tracking_section = BRAND_CONFIG.get("tracking", {}) or {}
_output_section = BRAND_CONFIG.get("output", {}) or {}
_copy_section = BRAND_CONFIG.get("copy", {}) or {}

BRAND_NAME = _brand_section.get("name", "Prayonit")
BRAND_FILENAME_PREFIX = _brand_section.get("filename_prefix", "prayonit")

# ---------- Phase 1B/1C: locked invitation-first Prayonit CTA copy ----------
# Loaded from brands/<brand>/brand.yaml "copy" section. These are the only
# approved CTA strings for the visual Feed/Story button and per-platform
# caption endings. The primary funnel is now website-first: social post ->
# interactive prayer website (prayonit.app) -> app download later.
# reel_cta/tiktok_cta are stored for future use only; Reels/TikTok
# publishing is not implemented in this phase.
PRIMARY_CTA = _copy_section.get("primary_cta", "COME PRAY WITH ME")
VISUAL_DESTINATION_TEXT = _copy_section.get("visual_destination_text", "Start your prayer at\nprayonit.app")
FACEBOOK_CTA = _copy_section.get("facebook_cta", "Come pray with me.")
INSTAGRAM_CTA = _copy_section.get("instagram_cta", "Come pray with me.\nLink in bio.")
THREADS_CTA = _copy_section.get("threads_cta", "Come pray with me.")
STORY_CTA = _copy_section.get("story_cta", "COME PRAY WITH ME")
STORY_DESTINATION_TEXT = _copy_section.get("story_destination_text", "Start your prayer at\nprayonit.app")
REEL_CTA = _copy_section.get("reel_cta", "COME PRAY WITH ME")
REEL_DESTINATION_TEXT = _copy_section.get("reel_destination_text", "Link in bio")
TIKTOK_CTA = _copy_section.get("tiktok_cta", "COME PRAY WITH ME")
TIKTOK_DESTINATION_TEXT = _copy_section.get("tiktok_destination_text", "Link in bio")
DESTINATION_URL = _copy_section.get("destination_url", "https://prayonit.app")

# ---------- Brand content locations (from brand.yaml, resolved to absolute paths) ----------
BRAND_RULES_PATH = _resolve_path(_content_section.get("brand_rules_path", "brand/brand_rules.json"))
BRAND_DIR = BRAND_RULES_PATH.parent
THEOLOGY_ACTIONS_PATH = _resolve_path(_content_section.get("theology_actions_path", "brand/theology_actions.json"))

CAMPAIGNS_DIR = _resolve_path(_content_section.get("campaigns_dir", "campaigns"))
FORMULAS_DIR = _resolve_path(_content_section.get("formulas_dir", "formulas"))
PERSONAS_DIR = _resolve_path(_content_section.get("personas_dir", "personas"))
SEASONALITY_DIR = _resolve_path(_content_section.get("seasonality_dir", "seasonality"))

# ---------- Creative Engine v2: brand assets ----------
# See docs/CREATIVE_ENGINE_V2.md for recommended asset requirements
# (PNG, transparent background, high resolution, official badge artwork).
# Missing files never crash rendering: image_renderer.py falls back to a
# text-only representation and logs a warning instead.
BRAND_ASSETS_DIR = PROJECT_ROOT / "assets" / "branding"
LOGO_PATH = _resolve_path(_assets_section.get("logo_path", "assets/branding/prayonit_logo.png"))
APP_STORE_BADGE_PATH = _resolve_path(_assets_section.get("app_store_badge_path", "assets/branding/app_store_badge.png"))
GOOGLE_PLAY_BADGE_PATH = _resolve_path(_assets_section.get("google_play_badge_path", "assets/branding/google_play_badge.png"))
MOTION_BACKGROUNDS_DIR = _resolve_path(_assets_section.get("motion_backgrounds_path", "assets/motion_backgrounds"))
LONG_FORM_VIDEO_DIR = _resolve_path(_assets_section.get("long_form_videos_path", "assets/videos/long"))

# ---------- Creative Engine v2: component recency tracking ----------
# Lightweight local recency tracker for theology_actions.json component
# choices, kept separate from the SQLite history database (data/*.db) so
# no existing schema, migration, or table is touched.
RECENT_THEOLOGY_COMPONENTS_PATH = None  # set below once DATA_DIR exists

# ---------- Supabase ----------
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
# Env var override takes precedence (unchanged behavior); brand.yaml supplies
# the default that previously lived directly in this module.
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", _storage_section.get("supabase_bucket", "prayonit-social-backgrounds"))

# ---------- Gemini ----------
LEGACY_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_API_KEY_PRIMARY = os.getenv("GEMINI_API_KEY_PRIMARY", "").strip() or LEGACY_GEMINI_API_KEY
GEMINI_API_KEY = GEMINI_API_KEY_PRIMARY
GEMINI_API_KEY_SECONDARY = os.getenv("GEMINI_API_KEY_SECONDARY", "").strip() or GEMINI_API_KEY_PRIMARY
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CONTENT_MODEL_PRIMARY = os.getenv("CONTENT_MODEL_PRIMARY", GEMINI_MODEL).strip() or GEMINI_MODEL
CONTENT_MODEL_SECONDARY = os.getenv("CONTENT_MODEL_SECONDARY", "gemini-2.5-flash").strip()
CONTENT_MODEL_TERTIARY = os.getenv("CONTENT_MODEL_TERTIARY", "gemini-3.1-flash-lite").strip()

# ---------- Buffer ----------
BUFFER_API_KEY = os.getenv("BUFFER_API_KEY", "")
BUFFER_ENDPOINT = "https://api.buffer.com"

FACEBOOK_CHANNEL_ID = os.getenv("BUFFER_FACEBOOK_CHANNEL_ID", "")
INSTAGRAM_CHANNEL_ID = os.getenv("BUFFER_INSTAGRAM_CHANNEL_ID", "")
THREADS_CHANNEL_ID = os.getenv("BUFFER_THREADS_CHANNEL_ID", "")
TIKTOK_CHANNEL_ID = os.getenv("BUFFER_TIKTOK_CHANNEL_ID", "")

# Optional Threads post metadata (Buffer GraphQL ThreadsPostMetadataInput).
# Left blank by default; only included in the Buffer payload when non-empty.
THREADS_LOCATION_NAME = os.getenv("THREADS_LOCATION_NAME", "")
THREADS_LOCATION_ID = os.getenv("THREADS_LOCATION_ID", "")

# Metrics retrieval cooldown, in hours, before re-checking a post's metrics.
METRICS_COOLDOWN_HOURS = int(os.getenv("METRICS_COOLDOWN_HOURS", "12"))

# ---------- Safety switch ----------
# Start safely. TEST_MODE=true creates images but does not publish or upload.
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

# ---------- Preview mode ----------
# PREVIEW_MODE=true uses the real Gemini generation path (generate_ad_copy(),
# including the full Creative Brief / Weekly Rhythm / creative library) to
# produce the exact content production would create, and renders local
# preview images/videos exactly like TEST_MODE -- but never uploads to
# Supabase, never calls Buffer, never publishes or schedules posts, and
# never writes production tracking records. Has no effect when TEST_MODE is
# true (TEST_MODE's offline generate_local_ad_copy() path always takes
# priority). Defaults to false so existing behavior is unchanged unless
# explicitly opted in.
PREVIEW_MODE = os.getenv("PREVIEW_MODE", "false").strip().lower() == "true"
CAPTION_PROFILE_PREVIEW_OVERRIDE = os.getenv(
    "CAPTION_PROFILE_PREVIEW_OVERRIDE", ""
).strip()


# ---------- Motion video (Phase: dynamic-video integration, local-only) ----------
# VIDEO_ENABLED=true generates a local motion video (using the same ad_copy
# as Feed/Story) in addition to the existing images. Video is never
# uploaded or queued to Buffer in this phase, in either TEST_MODE or
# production. Defaults to false so existing behavior is unchanged unless
# explicitly opted in.
VIDEO_ENABLED = os.getenv("VIDEO_ENABLED", "false").strip().lower() == "true"

# ---------- Phase 2A: video publishing (Facebook Reel / Instagram Reel / TikTok) ----------
# VIDEO_PUBLISH_ENABLED=true additionally uploads the generated motion video
# and queues Facebook Reel, Instagram Reel, and TikTok posts to Buffer.
# Has no effect unless VIDEO_ENABLED is also true (no video is generated to
# publish otherwise). TEST_MODE=true always prevents any upload/Buffer call
# regardless of this flag, identical to the existing image-publishing
# safety behavior. Defaults to false so existing behavior is unchanged
# unless explicitly opted in.
VIDEO_PUBLISH_ENABLED = os.getenv("VIDEO_PUBLISH_ENABLED", "false").strip().lower() == "true"
SOCIAL_OUTPUT_MODE = os.getenv("SOCIAL_OUTPUT_MODE", "reels_only").strip().lower() or "reels_only"
TIKTOK_INCLUDE_LINK_IN_BIO = os.getenv("TIKTOK_INCLUDE_LINK_IN_BIO", "false").strip().lower() == "true"


def get_social_output_mode() -> str:
    """Resolve the current process override before falling back to config."""
    return os.getenv("SOCIAL_OUTPUT_MODE", SOCIAL_OUTPUT_MODE).strip().lower() or "reels_only"

# ---------- Long-form voiceover (Phase: Gemini TTS / local-only rollout) ----------
# Voice is disabled by default so the existing long-form compositor stays
# silent unless explicitly opted in. Short-form rendering is unaffected.
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").strip().lower() == "true"
VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "gemini").strip().lower() or "gemini"
VOICE_MODEL = os.getenv("VOICE_MODEL", "gemini-3.1-flash-tts-preview").strip() or "gemini-3.1-flash-tts-preview"
VOICE_MODEL_PRIMARY = os.getenv("VOICE_MODEL_PRIMARY", "gemini-3.1-flash-tts-preview").strip() or "gemini-3.1-flash-tts-preview"
VOICE_MODEL_SECONDARY = os.getenv("VOICE_MODEL_SECONDARY", "gemini-2.5-flash-preview-tts").strip() or "gemini-2.5-flash-preview-tts"
VOICE_NAME = os.getenv("VOICE_NAME", "").strip()
VOICE_NAME_PRAYER = os.getenv("VOICE_NAME_PRAYER", "Orus").strip() or "Orus"
VOICE_NAME_DEVOTIONAL = os.getenv("VOICE_NAME_DEVOTIONAL", "Orus").strip() or "Orus"
VOICE_NAME_ENCOURAGEMENT = os.getenv("VOICE_NAME_ENCOURAGEMENT", "Orus").strip() or "Orus"
VOICE_NAME_ALTERNATE = os.getenv("VOICE_NAME_ALTERNATE", "Charon").strip() or "Charon"
try:
    VOICE_TEMPERATURE = float(os.getenv("VOICE_TEMPERATURE", "1").strip() or "1")
except ValueError:
    VOICE_TEMPERATURE = 1.0
VOICE_FALLBACK_ENABLED = os.getenv("VOICE_FALLBACK_ENABLED", "true").strip().lower() == "true"

# ---------- Paths ----------
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Organized generated-output subfolders ----------
# Existing files directly under OUTPUT_DIR from before this change are left
# in place untouched (historical files). All newly generated static images
# and videos are written into these organized subfolders instead.
OUTPUT_IMAGES_DIR = OUTPUT_DIR / "images"
OUTPUT_IMAGES_FEED_DIR = OUTPUT_IMAGES_DIR / "feed"
OUTPUT_IMAGES_STORY_DIR = OUTPUT_IMAGES_DIR / "story"
OUTPUT_VIDEOS_DIR = OUTPUT_DIR / "videos"
OUTPUT_VIDEOS_LONG_DIR = OUTPUT_VIDEOS_DIR / "long"
OUTPUT_AUDIO_DIR = OUTPUT_DIR / "audio"
OUTPUT_PREVIEWS_DIR = OUTPUT_DIR / "previews"
OUTPUT_TEMP_DIR = OUTPUT_DIR / "temp"
for _generated_output_dir in (
    OUTPUT_IMAGES_FEED_DIR,
    OUTPUT_IMAGES_STORY_DIR,
    OUTPUT_VIDEOS_DIR,
    OUTPUT_VIDEOS_LONG_DIR,
    OUTPUT_AUDIO_DIR,
    OUTPUT_PREVIEWS_DIR,
    OUTPUT_TEMP_DIR,
):
    _generated_output_dir.mkdir(parents=True, exist_ok=True)

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / _database_section.get("path", "prayonit_marketing.db")
BUFFER_METRICS_SCHEMA_PATH = DATA_DIR / "buffer_metrics_schema.json"
RECENT_THEOLOGY_COMPONENTS_PATH = DATA_DIR / "recent_theology_components.json"

# ---------- Image canvases ----------
CANVAS_SIZE = (1080, 1350)
STORY_CANVAS_SIZE = (1080, 1920)

# ---------- Supabase object storage layout ----------
BACKGROUND_PREFIX = os.getenv("BACKGROUND_PREFIX", "")
# Preferred local raw background directory for TEST_MODE (optional).
# If empty or missing, discovery falls back to known project paths.
LOCAL_BACKGROUND_DIR = os.getenv("LOCAL_BACKGROUND_DIR", "").strip()
GENERATED_PREFIX = os.getenv("GENERATED_PREFIX", "generated")
GENERATED_FEED_PREFIX = f"{GENERATED_PREFIX}/feed"
GENERATED_STORY_PREFIX = f"{GENERATED_PREFIX}/story"
GENERATED_VIDEO_PREFIX = f"{GENERATED_PREFIX}/video"

# ---------- Scheduling ----------
EASTERN_TZ = ZoneInfo("America/New_York")
SLOT_TIMES = {
    "morning": (8, 0),
    "evening": (19, 0),
}

# ---------- Tracked links (Layer 1) ----------
# TRACKING_ENABLED controls whether captions/Buffer posts use the tracked
# /download?t=<id> URL (requires the Layer 2 Edge Function to be deployed,
# see docs/TRACKING.md) or the plain DEFAULT_DESTINATION_URL. Tracking IDs
# are always generated and stored locally either way, so tracking can be
# switched on later without any code changes.
TRACKING_ENABLED = os.getenv("TRACKING_ENABLED", "false").strip().lower() == "true"
TRACKING_BASE_URL = os.getenv(
    "TRACKING_BASE_URL",
    _tracking_section.get("base_url", "https://prayonit.nextwavestudiosapp.com"),
)
IOS_DESTINATION_URL = os.getenv("IOS_DESTINATION_URL", "")
ANDROID_DESTINATION_URL = os.getenv("ANDROID_DESTINATION_URL", "")
DEFAULT_DESTINATION_URL = os.getenv("DEFAULT_DESTINATION_URL", "")
# TRACKING_SECRET is read only where strictly needed (tracking.py) and is
# never logged, printed, or returned in any function result.
TRACKING_SECRET = os.getenv("TRACKING_SECRET", "")

# ---------- Non-repetition defaults (Part 10) ----------
HISTORY_BACKGROUND_DAYS = int(os.getenv("HISTORY_BACKGROUND_DAYS", "30"))
HISTORY_HEADLINE_DAYS = int(os.getenv("HISTORY_HEADLINE_DAYS", "90"))
HISTORY_CAMPAIGN_RUNS = int(os.getenv("HISTORY_CAMPAIGN_RUNS", "3"))
HISTORY_FORMULA_RUNS = int(os.getenv("HISTORY_FORMULA_RUNS", "2"))
HISTORY_PERSONA_RUNS = int(os.getenv("HISTORY_PERSONA_RUNS", "2"))
HISTORY_CAMPAIGN_FORMULA_DAYS = int(os.getenv("HISTORY_CAMPAIGN_FORMULA_DAYS", "30"))


def require_env(test_mode: bool, preview_mode: bool = False) -> None:
    """Raise if required environment variables are missing for the current mode.

    preview_mode=True still requires a Gemini API key since PREVIEW_MODE uses the real Gemini
    generation path, but -- like TEST_MODE -- never requires Buffer
    credentials, since PREVIEW_MODE never calls Buffer.
    """
    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    ]
    if not test_mode and not preview_mode:
        required += [
            "BUFFER_API_KEY",
            "BUFFER_FACEBOOK_CHANNEL_ID",
            "BUFFER_INSTAGRAM_CHANNEL_ID",
        ]
        # TikTok is an automatic video destination alongside Facebook Reel
        # and Instagram Reel in both full and reels-only production modes.
        if VIDEO_PUBLISH_ENABLED:
            required.append("BUFFER_TIKTOK_CHANNEL_ID")
    missing = [name for name in required if not os.getenv(name)]
    if not get_gemini_primary_api_key():
        missing.append("Gemini API key")
    if missing:
        if missing == ["Gemini API key"]:
            raise RuntimeError(
                "Missing Gemini API key. Set GEMINI_API_KEY_PRIMARY or legacy GEMINI_API_KEY."
            )
        if "Gemini API key" in missing:
            missing.remove("Gemini API key")
            missing.append("Gemini API key (set GEMINI_API_KEY_PRIMARY or legacy GEMINI_API_KEY)")
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))


def get_gemini_primary_api_key() -> str:
    if "GEMINI_API_KEY_PRIMARY" in os.environ:
        primary_override = os.getenv("GEMINI_API_KEY_PRIMARY", "").strip()
    else:
        primary_override = GEMINI_API_KEY_PRIMARY
    if "GEMINI_API_KEY" in os.environ:
        legacy_key = os.getenv("GEMINI_API_KEY", "").strip()
    else:
        legacy_key = LEGACY_GEMINI_API_KEY
    return primary_override or legacy_key


def get_gemini_secondary_api_key() -> str:
    if "GEMINI_API_KEY_SECONDARY" in os.environ:
        secondary_override = os.getenv("GEMINI_API_KEY_SECONDARY", "").strip()
    else:
        secondary_override = GEMINI_API_KEY_SECONDARY
    return secondary_override or get_gemini_primary_api_key()


def validate_destination_config() -> None:
    """Validate destination-URL configuration before any Gemini call or
    image generation happens.

    When TRACKING_ENABLED=false, DEFAULT_DESTINATION_URL must be present and
    non-empty, since it is used directly (with no tracked-link fallback) in
    every feed caption. Failing fast here prevents blank URLs from ever
    reaching a caption or the Gemini prompt.
    """
    if not TRACKING_ENABLED and not DEFAULT_DESTINATION_URL.strip():
        raise RuntimeError(
            "DEFAULT_DESTINATION_URL is required when tracking is disabled."
        )


# ---------- Brand Brain ----------
def load_brand_rules() -> Dict[str, Any]:
    """Load and return the parsed brand/brand_rules.json object.

    This is the single source of truth for brand voice, approved CTAs,
    approved language, forbidden claims/phrases, and allowed features. It is
    read fresh from disk each call (the file is small and rarely changes),
    so edits to brand_rules.json take effect without restarting anything
    that calls this function per-run.
    """
    with open(BRAND_RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_theology_actions() -> Dict[str, Any]:
    """Load and return brand/theology_actions.json: approved, reusable
    spiritual-action component pools (surrender_actions, guidance_actions,
    etc.). Read fresh from disk each call so edits take effect immediately.
    """
    with open(THEOLOGY_ACTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# Loaded once at import time for convenience; callers needing the freshest
# on-disk copy can still call load_brand_rules() directly.
BRAND_RULES = load_brand_rules()
print("Brand Brain loaded successfully.")
print("Preferred CTA:")
print(BRAND_RULES.get("preferred_cta", ""))
