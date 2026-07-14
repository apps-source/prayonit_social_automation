"""Prayonit Marketing Engine v1.0 - command-line entry point.

Preserves all previously working behavior:
  python prayonit_social.py --slot morning
  python prayonit_social.py --slot evening

Adds:
  python prayonit_social.py analytics --days 7
  python prayonit_social.py analytics --days 30
  python prayonit_social.py discover-buffer-metrics
  python prayonit_social.py history --days 30
  python prayonit_social.py campaigns
  python prayonit_social.py database-init

TEST_MODE=true: generates local previews only, never uploads or calls Buffer,
and never records a false "scheduled" Buffer post.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image
from supabase import Client, create_client

import analytics
import buffer_client
import campaign_engine
import creative_engine_v3
import config
import history_store
import image_renderer
import prompt_builder
import tracking


_LOCAL_BG_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_FORBIDDEN_BG_DIR_TOKENS = (
    "/output/",
    "/tests/",
    "/branding/",
    "/logos/",
    "/badges/",
    "/screenshots/",
    "/generated/",
    "/preview/",
)
_FORBIDDEN_BG_NAME_TOKENS = (
    "prayonit-feed-",
    "prayonit-story-",
    "prayonit-ad-",
    "preview",
    "screenshot",
    "rendered",
    "output",
)


def _is_valid_local_background(path: Path) -> bool:
    """Return True only for loadable local image files usable as backgrounds."""
    if not path.exists() or not path.is_file():
        return False
    if path.suffix.lower() not in _LOCAL_BG_EXTENSIONS:
        return False
    lower = str(path).lower()
    if any(token in lower for token in _FORBIDDEN_BG_DIR_TOKENS):
        return False
    if any(token in path.name.lower() for token in _FORBIDDEN_BG_NAME_TOKENS):
        return False
    if "/assets/branding/" in lower or lower.endswith("prayonit_logo.png"):
        return False
    if lower.endswith("app_store_badge.png") or lower.endswith("google_play_badge.png"):
        return False
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def discover_local_backgrounds() -> Dict[str, Any]:
    """Discover local, real background images for TEST_MODE.

    Prefers dedicated local background/cache folders. Falls back to synthetic
    only when no valid local image can be discovered.
    """
    candidates = []

    env_dir = (config.LOCAL_BACKGROUND_DIR or os.getenv("LOCAL_BACKGROUND_DIR", "")).strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    if config.BACKGROUND_PREFIX.strip():
        candidates.append(config.PROJECT_ROOT / config.BACKGROUND_PREFIX.strip().lstrip("/"))

    candidates.extend(
        [
            config.PROJECT_ROOT / "backgrounds",
            config.PROJECT_ROOT / "assets" / "backgrounds",
            config.PROJECT_ROOT / "data" / "backgrounds",
            config.PROJECT_ROOT / "data" / "background_cache",
            config.PROJECT_ROOT / "supabase" / "backgrounds",
            config.PROJECT_ROOT / "assets" / "images" / "backgrounds",
            config.PROJECT_ROOT / "cached_backgrounds",
        ]
    )

    valid_files: list[Path] = []
    used_directory: Optional[Path] = None

    for directory in candidates:
        if not directory.exists() or not directory.is_dir():
            continue
        d_lower = str(directory.resolve()).lower()
        if any(token in d_lower for token in _FORBIDDEN_BG_DIR_TOKENS):
            continue
        discovered = sorted(
            p for p in directory.rglob("*") if _is_valid_local_background(p)
        )
        if discovered:
            valid_files = discovered
            used_directory = directory
            break

    if valid_files:
        return {
            "backgrounds": [str(p.resolve()) for p in valid_files],
            "used_directory": str(used_directory.resolve()) if used_directory else None,
            "synthetic_fallback": False,
        }

    return {
        "backgrounds": [],
        "used_directory": None,
        "synthetic_fallback": True,
    }


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Prayonit Marketing Engine v1.0")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Generate and (if not TEST_MODE) publish a campaign run.")
    run_parser.add_argument(
        "--slot",
        choices=sorted(config.SLOT_TIMES.keys()),
        default="morning",
        help="Which daily campaign slot to schedule for (morning=8:00 AM, evening=7:00 PM Eastern).",
    )

    parser.add_argument(
        "--slot",
        choices=sorted(config.SLOT_TIMES.keys()),
        default=None,
        help=argparse.SUPPRESS,
    )

    analytics_parser = subparsers.add_parser("analytics", help="Retrieve and report Buffer metrics.")
    analytics_parser.add_argument("--days", type=int, default=7)

    subparsers.add_parser("discover-buffer-metrics", help="Introspect Buffer's GraphQL schema and save it locally.")

    history_parser = subparsers.add_parser("history", help="Print recent campaign run history.")
    history_parser.add_argument("--days", type=int, default=30)

    subparsers.add_parser("campaigns", help="List all available campaigns.")
    subparsers.add_parser("database-init", help="Initialize the local SQLite database.")

    return parser


def next_slot_datetime_utc(slot, now=None):
    hour, minute = config.SLOT_TIMES[slot]
    now_eastern = (now or datetime.now(timezone.utc)).astimezone(config.EASTERN_TZ)

    candidate = now_eastern.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_eastern:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def to_iso8601_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_supabase_client():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


def list_backgrounds(supabase):
    entries = supabase.storage.from_(config.SUPABASE_BUCKET).list(
        config.BACKGROUND_PREFIX,
        {"limit": 1000, "sortBy": {"column": "name", "order": "asc"}},
    )

    paths = []
    for entry in entries:
        name = entry.get("name", "")
        if not name:
            continue

        object_path = "{0}/{1}".format(config.BACKGROUND_PREFIX.rstrip("/"), name).lstrip("/")
        lower = object_path.lower()

        if object_path.startswith(config.GENERATED_PREFIX + "/"):
            continue
        if lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
            paths.append(object_path)

    if not paths:
        raise RuntimeError("No background images found in bucket '{0}'.".format(config.SUPABASE_BUCKET))
    return paths


def cmd_campaigns():
    campaigns = campaign_engine.load_campaigns()
    print("{0} active campaign(s):".format(len(campaigns)))
    for c in campaigns:
        print("  - {0}: {1} (weight={2})".format(c["_key"], c["name"], c.get("weight", 1.0)))


def cmd_database_init():
    history_store.initialize_database()
    print("Database initialized at {0}".format(config.DATABASE_PATH))


def cmd_history(days):
    history_store.initialize_database()
    rows = history_store.get_recent_campaign_history(days=days)
    print("{0} run(s) in the last {1} day(s):".format(len(rows), days))
    for row in rows:
        print(
            "  - {0} [{1}] {2} (formula={3}, persona={4}, status={5})".format(
                row["created_at_utc"], row["slot"], row["campaign_name"],
                row["formula_name"], row["persona_name"], row["status"],
            )
        )


def cmd_run(slot) -> int:
    config.require_env(config.TEST_MODE)
    config.validate_destination_config()
    history_store.initialize_database()

    run_id = str(uuid.uuid4())
    print("Run ID: {0}".format(run_id))
    print("TEST_MODE: {0}".format(config.TEST_MODE))

    selection = campaign_engine.choose_selection(slot)
    campaign = selection["campaign"]
    formula = selection["formula"]
    persona = selection["persona"]

    # TEST_MODE uses the same read-only Supabase background source and
    # selection logic as production (list + download), but still exits
    # before any upload/posting steps.
    supabase = get_supabase_client()
    backgrounds = list_backgrounds(supabase)

    background_choice = campaign_engine.choose_background(
        backgrounds,
        slot=slot,
        campaign=campaign,
        formula=formula,
        persona=persona,
    )
    chosen_background = background_choice["path"]
    if background_choice.get("_relaxed_rule"):
        print("NOTE: relaxed rule -> {0}".format(background_choice["_relaxed_rule"]))
    if background_choice.get("metadata"):
        print("Background metadata: {0}".format(json.dumps(background_choice["metadata"])))
    if background_choice.get("match_score") is not None:
        print("Background match score: {0}".format(background_choice["match_score"]))

    # Creative Engine v2: pick an approved spiritual-action sentence from
    # brand/theology_actions.json, matched to this campaign and slot.
    selection["spiritual_action"] = campaign_engine.pick_spiritual_action(campaign, slot)
    print("Selected spiritual action: {0}".format(selection["spiritual_action"]))

    print("Selected campaign: {0}".format(campaign["name"]))
    print("Selected formula: {0}".format(formula["name"]))
    print("Selected persona: {0}".format(persona["name"] if persona else "none"))
    if selection.get("seasonal_context"):
        print("Seasonal context: {0}".format(selection["seasonal_context"]))
    for rule in selection.get("relaxed_rules", []):
        print("NOTE: relaxed rule -> {0}".format(rule))
    print("Selected hook: {0}".format(selection["hook"]))
    print("Selected CTA: {0}".format(selection["cta"]))
    print("Selected thread topic: {0} (reserved for future use, not posted)".format(selection["thread_topic"]))
    print("Selected background: {0}".format(chosen_background))
    print("Selected Supabase background filename: {0}".format(Path(chosen_background).name))

    due_at = next_slot_datetime_utc(slot)
    due_at_iso = to_iso8601_utc(due_at)
    print("Selected slot: {0} -> dueAt (UTC): {1}".format(slot, due_at_iso))

    run_row_id = history_store.create_run_record(
        run_id=run_id,
        slot=slot,
        campaign_name=campaign["name"],
        formula_name=formula["name"],
        persona_name=persona["name"] if persona else None,
        seasonal_context=selection.get("seasonal_context"),
        selected_hook=selection["hook"],
        selected_body_angle=selection["body_angle"],
        selected_cta=selection["cta"],
        selected_thread_topic=selection["thread_topic"],
        background_object_path=chosen_background,
        status="dry_run" if config.TEST_MODE else "in_progress",
    )

    territory = background_choice.get("emotional_territory") or creative_engine_v3.classify_emotional_territory(
        campaign_name=campaign.get("name", ""),
        pain_point=campaign.get("pain_point", ""),
        goal=campaign.get("goal", ""),
    )
    # Exclude TEST_MODE dry_run rows from duplicate checks so preview runs do
    # not poison production duplicate history.
    exclude_statuses = ["dry_run"]
    recent_rows = history_store.get_recent_campaign_history(
        days=config.HISTORY_HEADLINE_DAYS,
        exclude_statuses=exclude_statuses,
    )
    recent_headlines = [row["headline"] for row in recent_rows if row["headline"]]

    tracked_urls = {}
    if config.TEST_MODE:
        fallback_url = config.DEFAULT_DESTINATION_URL or "https://example.com/prayonit"
        tracked_urls = {
            "facebook": fallback_url,
            "instagram": fallback_url,
            "threads": fallback_url,
        }
        print("TEST_MODE: tracking calls skipped; using fallback URL.")
    else:
        for platform in ("facebook", "instagram", "threads"):
            tracked_urls[platform] = tracking.create_tracked_link(
                run_id=run_id,
                campaign_name=campaign["name"],
                formula_name=formula["name"],
                persona_name=persona["name"] if persona else None,
                platform=platform,
                post_type="post",
                slot=slot,
                scheduled_at_utc=due_at_iso,
            )
            print("Tracked URL ({0}): {1}".format(platform, tracked_urls[platform]))

    post_type_hint = "download-focused {0} ad".format(slot)
    try:
        if config.TEST_MODE:
            ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot=slot)
        else:
            ad_copy = prompt_builder.generate_ad_copy(
                post_type=post_type_hint,
                selection=selection,
                slot=slot,
                tracked_url=tracked_urls["facebook"],
            )
    except Exception as exc:
        history_store.update_run_record(run_row_id, status="failed", error_message=str(exc))
        raise

    # Production-only: one deterministic recovery attempt before final QA if
    # headline quality fails. No additional Gemini call is made.
    if not config.TEST_MODE:
        initial_hq = creative_engine_v3.validate_headline_quality(
            ad_copy.get("pain_headline", ""),
            recent_headlines=recent_headlines,
        )
        if not initial_hq.get("accepted", False):
            original_headline = ad_copy.get("pain_headline", "")
            reason = creative_engine_v3.identify_headline_failure_reason(
                headline=original_headline,
                issues=initial_hq.get("issues", []),
                territory=territory,
            )
            print(
                "Headline recovery: original='{0}' reason={1}".format(
                    original_headline,
                    reason,
                )
            )

            recovered = creative_engine_v3.select_recovered_headline(
                slot=slot,
                territory=territory,
                date_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                run_id=run_id,
                recent_headlines=recent_headlines,
                max_chars=45,
            )
            if recovered:
                ad_copy["pain_headline"] = recovered
                ad_copy["story_headline"] = creative_engine_v3.deterministic_headline_shorten(
                    recovered,
                    max_chars=45,
                )
                print("Headline recovery: recovered='{0}'".format(recovered))
            else:
                print("Headline recovery: no valid fallback candidate passed quality checks.")

    print("Generated copy:")
    print(json.dumps(ad_copy, indent=2))

    platform_captions = prompt_builder.build_platform_captions(ad_copy, selection, tracked_urls)
    print("Facebook caption: {0}".format(platform_captions["facebook"]))
    print("Instagram caption: {0}".format(platform_captions["instagram"]))
    print("Threads caption: {0}".format(platform_captions["threads"]))

    background_image = image_renderer.load_background(chosen_background)
    feed_image = image_renderer.compose_ad(background_image, ad_copy)
    story_image = image_renderer.compose_story_ad(background_image, ad_copy)

    has_badges = config.APP_STORE_BADGE_PATH.exists() and config.GOOGLE_PLAY_BADGE_PATH.exists()
    # Render images (these functions produce the final composed images and
    # attach contrast and overlay debug info into image.info)
    background_for_feed = image_renderer.crop_to_canvas(background_image)
    feed_image = image_renderer.compose_ad(background_for_feed, ad_copy)
    background_for_story = image_renderer.crop_to_canvas(background_image, config.STORY_CANVAS_SIZE)
    story_image = image_renderer.compose_story_ad(background_for_story, ad_copy)

    # Prefer element-level contrast metrics computed during rendering (final treated image).
    # Fallback order: element_contrast_metrics -> effective_contrast_metrics -> contrast_metrics -> recompute.
    def _select_contrast_metrics(img: Image.Image, key: str, canvas_kind: str) -> Dict[str, Any]:
        # element_contrast_metrics stores a mapping like {"feed": {...}} or {"story": {...}}
        elem = img.info.get("element_contrast_metrics")
        if elem and isinstance(elem, dict) and key in elem:
            return elem[key]
        eff = img.info.get("effective_contrast_metrics")
        if eff and isinstance(eff, dict) and eff.get("canvas_kind") == canvas_kind:
            return eff
        cm = img.info.get("contrast_metrics")
        if cm and isinstance(cm, dict) and cm.get("canvas_kind") == canvas_kind:
            return cm
        # Last resort: recompute from the treated base image
        return image_renderer.compute_local_contrast_metrics(image_renderer.add_dark_gradient(img.convert("RGB")), canvas_kind)

    feed_contrast_metrics = _select_contrast_metrics(feed_image, "feed", "feed")
    story_contrast_metrics = _select_contrast_metrics(story_image, "story", "story")

    # Combined overall pass should reflect final treated result (element-level metrics if present)
    combined_contrast = {
        "overall_pass": bool(feed_contrast_metrics.get("overall_pass") and story_contrast_metrics.get("overall_pass")),
        "feed": feed_contrast_metrics,
        "story": story_contrast_metrics,
    }
    # Enforce locked benefit text *before* QA so QA sees final enforced values
    ad_copy["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT if hasattr(image_renderer, "EXACT_BENEFIT_TEXT") else "Get a guided, personalized prayer based on your mood right now."
    ad_copy["story_app_benefit"] = ad_copy["app_benefit"]

    qa_report = creative_engine_v3.build_prepublish_qa_report(
        ad_copy=ad_copy,
        slot=slot,
        campaign_name=campaign["name"],
        background_path=chosen_background,
        background_meta=background_choice.get("metadata") or creative_engine_v3.classify_background(chosen_background),
        territory=territory,
        recent_headlines=recent_headlines,
        has_badges=has_badges,
        contrast_metrics=combined_contrast,
        captions=platform_captions,
    )
    print("QA report:\n{0}".format(json.dumps(qa_report, indent=2)))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    feed_local_path = config.OUTPUT_IMAGES_FEED_DIR / "prayonit-feed-{0}.jpg".format(timestamp)
    story_local_path = config.OUTPUT_IMAGES_STORY_DIR / "prayonit-story-{0}.jpg".format(timestamp)
    feed_image.save(feed_local_path, quality=95)
    story_image.save(story_local_path, quality=95)
    print("Saved feed preview: {0}".format(feed_local_path.resolve()))
    print("Saved story preview: {0}".format(story_local_path.resolve()))

    history_store.update_run_record(
        run_row_id,
        headline=ad_copy["pain_headline"],
        story_headline=ad_copy["story_headline"],
        status="dry_run" if config.TEST_MODE else "in_progress",
    )

    if config.TEST_MODE:
        print("TEST_MODE=true, so nothing was uploaded or posted.")
        return 0

    if creative_engine_v3.should_block_buffer(qa_report):
        reason = "QA critical failure(s): " + ", ".join(qa_report.get("critical_failures", []))
        history_store.update_run_record(run_row_id, status="failed", error_message=reason)
        print(reason)
        print("Buffer queue skipped due to QA failure.")
        print("BLOCKED: slot={0} QA failures: {1}".format(slot, qa_report.get("critical_failures", [])))
        return 2

    feed_remote_path, feed_url = image_renderer.upload_generated(
        feed_local_path, config.GENERATED_FEED_PREFIX, supabase
    )
    print("Uploaded feed image: {0}".format(feed_remote_path))
    print("Feed public URL: {0}".format(feed_url))

    story_remote_path, story_url = image_renderer.upload_generated(
        story_local_path, config.GENERATED_STORY_PREFIX, supabase
    )
    print("Uploaded story image: {0}".format(story_remote_path))
    print("Story public URL: {0}".format(story_url))

    history_store.update_run_record(
        run_row_id,
        generated_feed_object_path=feed_remote_path,
        generated_story_object_path=story_remote_path,
        status="published",
    )

    buffer_jobs = [
        ("facebook", "post", config.FACEBOOK_CHANNEL_ID, platform_captions["facebook"], feed_url, tracked_urls["facebook"]),
        ("instagram", "post", config.INSTAGRAM_CHANNEL_ID, platform_captions["instagram"], feed_url, tracked_urls["instagram"]),
        ("facebook", "story", config.FACEBOOK_CHANNEL_ID, "", story_url, None),
        ("instagram", "story", config.INSTAGRAM_CHANNEL_ID, "", story_url, None),
        ("threads", "post", config.THREADS_CHANNEL_ID, platform_captions["threads"], feed_url, tracked_urls["threads"]),
    ]

    successes = []
    failures = []

    for service, item_post_type, channel_id, caption, image_url, tracked_url in buffer_jobs:
        label = "{0} {1}".format(service, item_post_type)
        try:
            result = buffer_client.buffer_create_post(
                channel_id=channel_id,
                caption=caption,
                image_url=image_url,
                service=service,
                post_type=item_post_type,
                due_at_iso=due_at_iso,
                link=tracked_url,
            )
            buffer_post_id = (result.get("post") or {}).get("id")
            print("Queued {0}: {1}".format(label, json.dumps(result, indent=2)))
            history_store.save_published_post(
                run_id=run_id,
                scheduled_at_utc=due_at_iso,
                platform=service,
                post_type=item_post_type,
                buffer_post_id=buffer_post_id,
                campaign_name=campaign["name"],
                formula_name=formula["name"],
                persona_name=persona["name"] if persona else None,
                slot=slot,
                headline=ad_copy["pain_headline"],
                caption=caption,
                tracked_url=tracked_url,
                image_url=image_url,
                buffer_status="scheduled",
            )
            successes.append(label)
        except Exception as exc:
            print("FAILED {0}: {1}".format(label, exc), file=sys.stderr)
            history_store.save_post_error(
                run_id=run_id,
                platform=service,
                post_type=item_post_type,
                campaign_name=campaign["name"],
                formula_name=formula["name"],
                persona_name=persona["name"] if persona else None,
                slot=slot,
                error_message=str(exc),
                caption=caption,
                image_url=image_url,
            )
            failures.append(label)

    print("\n--- Run summary ---")
    print("Succeeded ({0}): {1}".format(len(successes), ", ".join(successes) if successes else "none"))
    print("Failed ({0}): {1}".format(len(failures), ", ".join(failures) if failures else "none"))
    if failures:
        print("FAILED: slot={0} execution error: Buffer queue failures: {1}".format(slot, failures))
        return 1
    print("SUCCESS: slot={0} queued to Buffer".format(slot))
    return 0


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    command = args.command or "run"
    slot = getattr(args, "slot", None) or "morning"

    if command == "run":
        try:
            return cmd_run(slot)
        except Exception as exc:
            print("FAILED: slot={0} execution error: {1}".format(slot, exc), file=sys.stderr)
            return 1
    elif command == "analytics":
        analytics.run_analytics(days=args.days)
        return 0
    elif command == "discover-buffer-metrics":
        analytics.run_discover_buffer_metrics()
        return 0
    elif command == "history":
        cmd_history(days=args.days)
        return 0
    elif command == "campaigns":
        cmd_campaigns()
        return 0
    elif command == "database-init":
        cmd_database_init()
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
