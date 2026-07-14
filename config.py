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

load_dotenv()

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

# ---------- Phase 1B: locked invitation-first Prayonit CTA copy ----------
# Loaded from brands/<brand>/brand.yaml "copy" section. These are the only
# approved CTA strings for the visual Feed/Story button and per-platform
# caption endings. reel_cta/tiktok_cta are stored for future use only;
# Reels/TikTok publishing is not implemented in this phase.
PRIMARY_CTA = _copy_section.get("primary_cta", "COME PRAY WITH ME")
FACEBOOK_CTA = _copy_section.get("facebook_cta", "Come pray with me.")
INSTAGRAM_CTA = _copy_section.get("instagram_cta", "Come pray with me.\nLink in bio.")
THREADS_CTA = _copy_section.get("threads_cta", "Come pray with me.")
STORY_CTA = _copy_section.get("story_cta", "COME PRAY WITH ME")
REEL_CTA = _copy_section.get("reel_cta", "Come pray with me.\nLink in bio.")
TIKTOK_CTA = _copy_section.get("tiktok_cta", "Come pray with me.\nLink in bio.")

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
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ---------- Buffer ----------
BUFFER_API_KEY = os.getenv("BUFFER_API_KEY", "")
BUFFER_ENDPOINT = "https://api.buffer.com"

FACEBOOK_CHANNEL_ID = os.getenv("BUFFER_FACEBOOK_CHANNEL_ID", "")
INSTAGRAM_CHANNEL_ID = os.getenv("BUFFER_INSTAGRAM_CHANNEL_ID", "")
THREADS_CHANNEL_ID = os.getenv("BUFFER_THREADS_CHANNEL_ID", "")

# Optional Threads post metadata (Buffer GraphQL ThreadsPostMetadataInput).
# Left blank by default; only included in the Buffer payload when non-empty.
THREADS_LOCATION_NAME = os.getenv("THREADS_LOCATION_NAME", "")
THREADS_LOCATION_ID = os.getenv("THREADS_LOCATION_ID", "")

# Metrics retrieval cooldown, in hours, before re-checking a post's metrics.
METRICS_COOLDOWN_HOURS = int(os.getenv("METRICS_COOLDOWN_HOURS", "12"))

# ---------- Safety switch ----------
# Start safely. TEST_MODE=true creates images but does not publish or upload.
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

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
OUTPUT_PREVIEWS_DIR = OUTPUT_DIR / "previews"
OUTPUT_TEMP_DIR = OUTPUT_DIR / "temp"
for _generated_output_dir in (
    OUTPUT_IMAGES_FEED_DIR,
    OUTPUT_IMAGES_STORY_DIR,
    OUTPUT_VIDEOS_DIR,
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


def require_env(test_mode: bool) -> None:
    """Raise if required environment variables are missing for the current mode."""
    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "GEMINI_API_KEY",
    ]
    if not test_mode:
        required += [
            "BUFFER_API_KEY",
            "BUFFER_FACEBOOK_CHANNEL_ID",
            "BUFFER_INSTAGRAM_CHANNEL_ID",
            "BUFFER_THREADS_CHANNEL_ID",
        ]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))


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
