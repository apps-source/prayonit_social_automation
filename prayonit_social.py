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
import random
import re
import shutil
import subprocess
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
import platform_post_preparer
import prompt_builder
import resolved_content_brief
import tracking
import voice_provider
from engines import content_engine


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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "topic"


def _resolve_creator_search_topic(
    ad_copy: Dict[str, Any],
    selection: Dict[str, Any],
    brief: Optional[resolved_content_brief.ResolvedContentBrief] = None,
) -> str:
    if brief is not None and brief.creator_search_topic:
        return brief.creator_search_topic
    return (
        str(ad_copy.get("creator_search_topic", "")).strip()
        or str(selection.get("thread_topic", "")).strip()
        or _slugify(str(ad_copy.get("pain_headline", "")).strip()).replace("-", " ")
    )


def _select_long_form_scenic_assets(
    *,
    brief: resolved_content_brief.ResolvedContentBrief,
    narration_duration: Optional[float],
    planned_video_duration: float,
    run_row_id: int,
) -> list:
    """Select and persist long-form scenery without coupling it to rendering."""
    import long_form_renderer
    import scenic_asset_catalog
    import scenic_asset_selector

    try:
        selection_policy = scenic_asset_selector.load_selection_config(
            config.SCENIC_SELECTION_CONFIG_PATH
        )
        recent_window = int(selection_policy.get("recent_use_window", 10))
    except scenic_asset_selector.ScenicSelectionConfigError:
        selection_policy = None
        recent_window = 10
    recent_asset_ids = history_store.get_recent_scenic_asset_ids(
        limit_runs=recent_window,
        exclude_statuses=("dry_run",),
    )
    context = scenic_asset_selector.build_selection_context(
        brief,
        narration_duration_seconds=narration_duration,
        planned_video_duration_seconds=planned_video_duration,
        recent_asset_ids=recent_asset_ids,
    )
    diagnostic_name = "selection-{0}.json".format(_slugify(brief.run_id))

    try:
        result = scenic_asset_selector.load_and_select_scenic_assets(
            context,
            catalog_path=config.SCENIC_ASSET_CATALOG_PATH,
            video_dir=config.LONG_FORM_VIDEO_DIR,
            selection_config_path=config.SCENIC_SELECTION_CONFIG_PATH,
            crossfade_seconds=config.LONG_FORM_CROSSFADE_SECONDS,
        )
        selected_assets = [
            asset.to_metadata_dict() for asset in result.selected_assets
        ]
        selection_metadata = result.to_metadata_dict()
        print(
            "Scenic selection: category={0} time={1} emotion={2} "
            "requested={3} eligible={4}/{5}".format(
                context.prayer_category_id,
                context.time_of_day,
                context.emotional_tone,
                result.requested_clip_count,
                result.eligible_after_hard_filters,
                result.eligible_catalog_count,
            )
        )
        for asset in result.selected_assets:
            print(
                "Scenic selection {0}: {1} score={2:.1f} family={3} "
                "duplicate_group={4} estimated_stretch={5:.2f}x".format(
                    asset.selection_order,
                    asset.filename,
                    asset.selection_score,
                    asset.visual_family,
                    asset.duplicate_group or "none",
                    asset.estimated_stretch_ratio,
                )
            )
        for step in result.relaxation_steps:
            print("Scenic selection relaxation: {0}".format(step))
        for warning in result.warnings:
            print("Scenic selection WARNING: {0}".format(warning))
        selected_video_assets = result.paths
        try:
            scenic_asset_selector.write_selection_diagnostic(
                context,
                result,
                output_dir=config.SCENIC_SELECTION_DIAGNOSTIC_DIR,
                filename=diagnostic_name,
            )
        except OSError as exc:
            print("Scenic selection diagnostic write failed: {0}".format(exc))
    except Exception as exc:
        primary_candidates = scenic_asset_catalog.list_eligible_video_filenames(
            config.LONG_FORM_VIDEO_DIR
        )
        error_text = str(exc).lower()
        if not primary_candidates:
            failure_kind = "primary_library_absence"
        elif (
            isinstance(exc, scenic_asset_catalog.CatalogValidationError)
            and "missing from video library" in error_text
        ):
            failure_kind = "selected_file_missing"
        elif isinstance(exc, scenic_asset_catalog.CatalogValidationError):
            failure_kind = "catalog_validation_failure"
        elif isinstance(
            exc, scenic_asset_selector.InsufficientCompatibleAssets
        ):
            failure_kind = "insufficient_compatible_assets"
        elif isinstance(exc, FileNotFoundError):
            failure_kind = "primary_library_absence_or_selected_file_missing"
        else:
            failure_kind = "scenic_selection_failure"
        print(
            "Scenic selection {0}: {1}. Falling back to legacy random selector.".format(
                failure_kind,
                exc,
            )
        )
        legacy_assets = long_form_renderer.select_long_form_video_assets(
            target_count=scenic_asset_selector.requested_clip_count(
                context.narration_duration_seconds,
                selection_policy
                or {
                    "long_video_threshold_seconds": 42,
                    "short_video_clip_count": 5,
                    "long_video_clip_count": 6,
                },
            ),
            long_video_dir=config.LONG_FORM_VIDEO_DIR,
            fallback_dir=config.MOTION_BACKGROUNDS_DIR,
        )
        selected_assets = [
            {
                "asset_id": "legacy_filename:{0}".format(spec.path.name),
                "filename": spec.path.name,
                "visual_family": "legacy_unknown",
                "duplicate_group": None,
                "selection_order": index,
                "selection_score": None,
                "selection_reasons": ["legacy_random_fallback", failure_kind],
            }
            for index, spec in enumerate(legacy_assets, start=1)
        ]
        fallback_library_used = any(
            spec.path.parent.resolve()
            == Path(config.MOTION_BACKGROUNDS_DIR).resolve()
            for spec in legacy_assets
        )
        print(
            "Scenic selection fallback library used: {0}".format(
                str(fallback_library_used).lower()
            )
        )
        selection_metadata = {
            "selected_assets": selected_assets,
            "requested_clip_count": len(legacy_assets),
            "selected_clip_count": len(legacy_assets),
            "fallback_used": True,
            "fallback_reason": failure_kind,
            "fallback_library_used": fallback_library_used,
            "relaxation_steps": [],
            "recent_use_handling": "not_applied_to_legacy_fallback",
            "warnings": [str(exc)],
        }
        selected_video_assets = legacy_assets
        try:
            scenic_asset_selector.write_fallback_diagnostic(
                context,
                selection_metadata,
                output_dir=config.SCENIC_SELECTION_DIAGNOSTIC_DIR,
                filename=diagnostic_name,
            )
        except OSError as diagnostic_exc:
            print(
                "Scenic selection diagnostic write failed: {0}".format(
                    diagnostic_exc
                )
            )

    history_store.merge_run_resolved_brief_metadata(
        run_row_id,
        {
            "selected_scenic_assets": selected_assets,
            "scenic_selection": {
                key: value
                for key, value in selection_metadata.items()
                if key != "selected_assets"
            },
        },
    )
    return selected_video_assets


def build_tiktok_caption(
    ad_copy: Dict[str, Any],
    selection: Dict[str, Any],
    brief: resolved_content_brief.ResolvedContentBrief,
) -> str:
    """Return TikTok-native copy without inheriting Instagram by default."""
    dedicated = str(ad_copy.get("tiktok_caption", "")).strip()
    if dedicated:
        caption = dedicated
    else:
        parts = [
            str(ad_copy.get("opening_hook", "")).strip(),
            str(brief.life_moment_text or ad_copy.get("pain_headline", "")).strip(),
            "Come pray with me.",
        ]
        caption = "\n\n".join(dict.fromkeys(part for part in parts if part))

    if not config.TIKTOK_INCLUDE_LINK_IN_BIO:
        caption = re.sub(r"\s*link in bio\.?", "", caption, flags=re.IGNORECASE).strip()

    campaign = selection.get("campaign") or {}
    hashtags = campaign.get("tiktok_hashtags") or campaign.get("instagram_hashtags") or ["#Prayonit", "#Prayer"]
    clean_hashtags = []
    for hashtag in hashtags:
        value = str(hashtag).strip()
        if value and value not in clean_hashtags:
            clean_hashtags.append(value if value.startswith("#") else "#" + value)
    if "#Prayonit" not in clean_hashtags:
        clean_hashtags.insert(0, "#Prayonit")
    return "{0}\n\n{1}".format(caption, " ".join(clean_hashtags)).strip()


# Deprecated legacy handoff helpers. They have no CLI entry point, runtime
# call site, or active configuration and are retained temporarily only so
# historical local packages remain diagnosable outside normal runs.
def _load_tiktok_handoff_manifest(manifest_path: Path) -> Dict[str, Any]:
    if not manifest_path.exists():
        return {"imports": {}}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"imports": {}}
    if not isinstance(data, dict):
        return {"imports": {}}
    data.setdefault("imports", {})
    return data


def _save_tiktok_handoff_manifest(manifest_path: Path, manifest: Dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _split_tiktok_caption(caption: str) -> Dict[str, str]:
    tokens = str(caption or "").split()
    hashtag_tokens = [token for token in tokens if token.startswith("#")]
    hashtag_text = " ".join(hashtag_tokens).strip()
    body_lines = []
    for line in str(caption or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if all(token.startswith("#") for token in stripped.split()):
            continue
        body_lines.append(stripped)
    body_text = "\n".join(body_lines).strip()
    full_caption = body_text
    if hashtag_text:
        full_caption = f"{body_text}\n\n{hashtag_text}" if body_text else hashtag_text
    return {
        "body": body_text,
        "hashtags": hashtag_text,
        "full_caption": full_caption,
    }


def _build_tiktok_handoff_note(
    *,
    title: str,
    creator_search_topic: str,
    full_caption: str,
    hashtags: str,
    opening_hook: str,
    genre_label: str,
    slot: str,
    content_type: str,
    video_filename: str,
) -> str:
    return (
        f"Creator Search Insights Topic:\n{creator_search_topic or 'Not selected'}\n\n"
        f"Caption:\n{full_caption}\n\n"
        f"Hashtags:\n{hashtags}\n\n"
        f"Opening Hook:\n{opening_hook}\n\n"
        f"Genre Label:\n{genre_label}\n\n"
        f"Slot:\n{slot}\n\n"
        f"Content Type:\n{content_type}\n\n"
        f"Video Filename:\n{video_filename}\n\n"
        f"Photos Album:\n{config.TIKTOK_PHOTOS_ALBUM_NAME}\n\n"
        "Status:\nReady for manual TikTok upload\n"
    )


def _applescript_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str, *, app_label: str, phase: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"{app_label} osascript return code: {result.returncode}")
        print(f"{app_label} osascript stdout: {result.stdout.strip()}")
        print(f"{app_label} osascript stderr: {result.stderr.strip()}")
        print(f"{app_label} failure phase: {phase}")
        detail = result.stderr.strip() or result.stdout.strip() or f"osascript exited with {result.returncode}"
        raise RuntimeError(f"{app_label} failure phase {phase}: {detail}")
    return result


def _build_photos_direct_import_script(video_path: Path, album_name: str) -> str:
    escaped_video_path = _applescript_escape(str(video_path))
    escaped_album_name = _applescript_escape(album_name)
    return f"""
set targetFile to POSIX file "{escaped_video_path}"
set albumName to "{escaped_album_name}"
tell application "Photos"
    activate
    set targetAlbum to missing value
    repeat with existingAlbum in albums
        if name of existingAlbum is albumName then
            set targetAlbum to existingAlbum
            exit repeat
        end if
    end repeat
    if targetAlbum is missing value then
        set targetAlbum to make new album named albumName
    end if
    import {{targetFile}} into targetAlbum skip check duplicates yes
end tell
"""


def _build_photos_returned_items_script(video_path: Path, album_name: str) -> str:
    escaped_album_name = _applescript_escape(album_name)
    return f"""
set targetFile to POSIX file "{_applescript_escape(str(video_path))}"
set albumName to "{escaped_album_name}"
tell application "Photos"
    activate
    set targetAlbum to missing value
    repeat with existingAlbum in albums
        if name of existingAlbum is albumName then
            set targetAlbum to existingAlbum
            exit repeat
        end if
    end repeat
    if targetAlbum is missing value then
        set targetAlbum to make new album named albumName
    end if
    set importedItems to import {{targetFile}} skip check duplicates yes
    if importedItems is missing value then error "Photos import returned no media items."
    add importedItems to targetAlbum
end tell
"""


def _import_video_to_apple_photos(video_path: Path, album_name: str) -> Dict[str, Any]:
    direct_script = _build_photos_direct_import_script(video_path, album_name)
    try:
        _run_osascript(
            direct_script,
            app_label="Apple Photos",
            phase="import_into_album",
        )
        return {
            "attempted": True,
            "succeeded": True,
            "album_added": True,
            "fallback_used": None,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"Apple Photos direct album import failed; trying returned-items fallback: {exc}")

    fallback_script = _build_photos_returned_items_script(video_path, album_name)
    _run_osascript(
        fallback_script,
        app_label="Apple Photos",
        phase="import_returned_items_then_add_to_album",
    )
    return {
        "attempted": True,
        "succeeded": True,
        "album_added": True,
        "fallback_used": "returned_items",
    }


def _create_apple_note(*, folder_name: str, title: str, body: str) -> Dict[str, Any]:
    html_body = _applescript_escape(body.replace("\n", "<br>"))
    script = f'''
tell application "Notes"
    activate
    set targetFolder to missing value
    repeat with existingFolder in folders
        if name of existingFolder is "{_applescript_escape(folder_name)}" then
            set targetFolder to existingFolder
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then
        set targetFolder to make new folder with properties {{name:"{_applescript_escape(folder_name)}"}}
    end if
    make new note at targetFolder with properties {{name:"{_applescript_escape(title)}", body:"{html_body}"}}
end tell
'''
    _run_osascript(
        script,
        app_label="Apple Notes",
        phase="create_note",
    )
    return {"attempted": True, "succeeded": True}


def _find_tiktok_handoff_entry(
    manifest: Dict[str, Any],
    *,
    backup_path: Path,
    notes_path: Optional[Path] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    backup_resolved = str(backup_path.resolve())
    notes_resolved = str(notes_path.resolve()) if notes_path else None
    for source_key, entry in manifest.get("imports", {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("backup_path") == backup_resolved:
            return source_key, entry
        if notes_resolved and entry.get("notes_path") == notes_resolved:
            return source_key, entry
    return None, {}


def _retry_tiktok_handoff_package(*, video_path: Path, notes_path: Path) -> Dict[str, Any]:
    handoff_dir = config.OUTPUT_TIKTOK_HANDOFF_DIR
    manifest_path = handoff_dir / "photos_import_manifest.json"
    manifest = _load_tiktok_handoff_manifest(manifest_path)
    source_key, existing_entry = _find_tiktok_handoff_entry(
        manifest,
        backup_path=video_path,
        notes_path=notes_path,
    )
    if source_key is None:
        source_key = str(video_path.resolve())

    photos_status = {
        "attempted": False,
        "succeeded": bool(existing_entry.get("succeeded")),
        "already_imported": bool(existing_entry.get("succeeded")),
        "album_added": bool(existing_entry.get("succeeded")),
        "recovery_guidance": "",
        "fallback_used": existing_entry.get("photos_fallback_used"),
    }
    note_status = {
        "attempted": False,
        "succeeded": bool(existing_entry.get("apple_note_created")),
        "already_created": bool(existing_entry.get("apple_note_created")),
        "recovery_guidance": "",
    }

    if config.TIKTOK_IMPORT_TO_PHOTOS and not photos_status["already_imported"]:
        photos_status["attempted"] = True
        try:
            photos_status.update(_import_video_to_apple_photos(video_path, config.TIKTOK_PHOTOS_ALBUM_NAME))
        except Exception as exc:  # noqa: BLE001
            photos_status["succeeded"] = False
            photos_status["album_added"] = False
            photos_status["recovery_guidance"] = (
                "Open Photos on this Mac, import the backup MP4 manually, "
                "and add it to the Prayonit TikTok Ready album."
            )
            print(f"TikTok handoff retry; Apple Photos import failed: {exc}")
            print(photos_status["recovery_guidance"])

    note_title = str(existing_entry.get("apple_note_title", "")).strip() or f"Prayonit TikTok — {video_path.stem}"
    if config.TIKTOK_CREATE_APPLE_NOTE and not note_status["already_created"]:
        note_status["attempted"] = True
        try:
            _create_apple_note(
                folder_name=config.TIKTOK_NOTES_FOLDER_NAME,
                title=note_title,
                body=notes_path.read_text(encoding="utf-8"),
            )
            note_status["succeeded"] = True
        except Exception as exc:  # noqa: BLE001
            note_status["succeeded"] = False
            note_status["recovery_guidance"] = (
                "Open Apple Notes on this Mac and create the handoff note manually "
                f"in the {config.TIKTOK_NOTES_FOLDER_NAME} folder."
            )
            print(f"TikTok handoff retry; Apple Note creation failed: {exc}")
            print(note_status["recovery_guidance"])

    manifest["imports"][source_key] = {
        **existing_entry,
        "backup_path": str(video_path.resolve()),
        "notes_path": str(notes_path.resolve()),
        "succeeded": photos_status["succeeded"],
        "already_imported": photos_status["already_imported"],
        "photos_fallback_used": photos_status.get("fallback_used"),
        "apple_note_created": note_status["succeeded"],
        "apple_note_title": note_title,
    }
    _save_tiktok_handoff_manifest(manifest_path, manifest)
    return {
        "photos_status": photos_status,
        "note_status": note_status,
        "manifest_path": manifest_path,
    }


def _create_tiktok_manual_handoff(
    *,
    video_local_path: Path,
    ad_copy: Dict[str, Any],
    selection: Dict[str, Any],
    presentation_config: Dict[str, Any],
    due_at_iso: str,
    slot: str,
    run_row_id: int,
) -> Dict[str, Any]:
    import long_form_renderer

    handoff_dir = config.OUTPUT_TIKTOK_HANDOFF_DIR
    handoff_dir.mkdir(parents=True, exist_ok=True)
    creator_search_topic = _resolve_creator_search_topic(ad_copy, selection)
    scheduled_date = due_at_iso[:10]
    content_slug = str(presentation_config.get("video_template", "video")).replace("_", "-")
    topic_slug = _slugify(creator_search_topic)
    base_filename = f"{scheduled_date}_{slot}_{content_slug}_{topic_slug}"
    backup_path = handoff_dir / f"{base_filename}.mp4"
    notes_path = handoff_dir / f"{base_filename}.txt"
    manifest_path = handoff_dir / "photos_import_manifest.json"
    shutil.copy2(video_local_path, backup_path)

    manifest = _load_tiktok_handoff_manifest(manifest_path)
    source_key = str(video_local_path.resolve())
    existing_entry = manifest["imports"].get(source_key, {})
    already_imported = bool(existing_entry.get("succeeded"))
    photos_status = {
        "attempted": False,
        "succeeded": False,
        "already_imported": already_imported,
        "album_added": False,
        "recovery_guidance": "",
    }
    note_status = {
        "attempted": False,
        "succeeded": bool(existing_entry.get("apple_note_created")),
        "already_created": bool(existing_entry.get("apple_note_created")),
        "recovery_guidance": "",
    }

    if config.TIKTOK_IMPORT_TO_PHOTOS and not already_imported:
        photos_status["attempted"] = True
        try:
            import_result = _import_video_to_apple_photos(backup_path, config.TIKTOK_PHOTOS_ALBUM_NAME)
            photos_status.update(import_result)
        except Exception as exc:  # noqa: BLE001
            photos_status["recovery_guidance"] = (
                "Open Photos on this Mac, import the backup MP4 manually, "
                "and add it to the Prayonit TikTok Ready album."
            )
            print(f"TikTok handoff created locally; Apple Photos import failed: {exc}")
            print(photos_status["recovery_guidance"])
    elif already_imported:
        photos_status["attempted"] = False
        photos_status["succeeded"] = True
        photos_status["album_added"] = True

    genre_label = long_form_renderer._content_label(presentation_config)
    caption_parts = _split_tiktok_caption(ad_copy.get("tiktok_caption") or ad_copy.get("instagram_caption") or "")
    note_title = "Prayonit TikTok — {0} {1}".format(
        scheduled_date,
        slot.capitalize(),
    )
    note_body = _build_tiktok_handoff_note(
        title=note_title,
        creator_search_topic=creator_search_topic,
        full_caption=caption_parts["full_caption"],
        hashtags=caption_parts["hashtags"],
        opening_hook=str(ad_copy.get("opening_hook", "")).strip(),
        genre_label=genre_label,
        slot=slot,
        content_type=content_slug,
        video_filename=backup_path.name,
    )

    if config.TIKTOK_CREATE_APPLE_NOTE and not note_status["already_created"]:
        note_status["attempted"] = True
        try:
            _create_apple_note(
                folder_name=config.TIKTOK_NOTES_FOLDER_NAME,
                title=note_title,
                body=note_body,
            )
            note_status["succeeded"] = True
        except Exception as exc:  # noqa: BLE001
            note_status["recovery_guidance"] = (
                "Open Apple Notes on this Mac and create the handoff note manually "
                f"in the {config.TIKTOK_NOTES_FOLDER_NAME} folder."
            )
            print(f"TikTok handoff local text created; Apple Note creation failed: {exc}")
            print(note_status["recovery_guidance"])

    manifest["imports"][source_key] = {
        "backup_path": str(backup_path.resolve()),
        "notes_path": str(notes_path.resolve()),
        "succeeded": photos_status["succeeded"],
        "already_imported": photos_status["already_imported"],
        "photos_fallback_used": photos_status.get("fallback_used"),
        "creator_search_topic": creator_search_topic,
        "apple_note_created": note_status["succeeded"],
        "apple_note_title": note_title,
    }
    _save_tiktok_handoff_manifest(manifest_path, manifest)

    notes = [
        f"Creator Search Insights target phrase: {creator_search_topic}",
        f"TikTok caption: {caption_parts['full_caption']}",
        f"hashtags: {caption_parts['hashtags']}",
        f"scheduled date and slot: {scheduled_date} {slot}",
        f"content type: {content_slug}",
        f"opening hook: {str(ad_copy.get('opening_hook', '')).strip()}",
        f"genre label: {genre_label}",
        f"source production MP4 path: {video_local_path.resolve()}",
        f"Photos import status: {'succeeded' if photos_status['succeeded'] else 'failed' if photos_status['attempted'] else 'not_attempted'}",
        f"Apple Note status: {'succeeded' if note_status['succeeded'] else 'failed' if note_status['attempted'] else 'not_attempted'}",
    ]
    notes_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    return {
        "creator_search_topic": creator_search_topic,
        "backup_path": backup_path,
        "notes_path": notes_path,
        "photos_status": photos_status,
        "note_status": note_status,
        "note_title": note_title,
    }


def _log_preview_narration_debug(ad_copy: Dict[str, Any], narration_text: str) -> None:
    if not config.PREVIEW_MODE:
        return
    units = voice_provider.build_narration_segments(ad_copy)
    bridge_line = str(ad_copy.get("bridge_line", "")).strip()
    closing_line = str(ad_copy.get("closing_line", "")).strip()
    script_segments = [
        str(segment).strip()
        for segment in ad_copy.get("script_segments", [])
        if str(segment).strip()
    ]
    print("Narration units:")
    print(f"- bridge_line: {bridge_line}")
    for index, segment in enumerate(script_segments):
        print(f"- script_segments[{index}]: {segment}")
    print(f"- closing_line: {closing_line}")
    print(f"Final narration transcript character count: {len(narration_text)}")
    print(f"Final narration transcript sentence count: {voice_provider._count_sentences(narration_text)}")
    voice_provider.validate_narration_transcript(units, narration_text)


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


def _caption_profile_preview_override():
    return config.CAPTION_PROFILE_PREVIEW_OVERRIDE or None


def _resolve_run_weekly_content(slot, now=None):
    run_started_at = now or datetime.now(timezone.utc)
    return run_started_at, content_engine.get_todays_content(
        slot=slot, now=run_started_at
    )


def cmd_run(slot) -> int:
    config.require_env(config.TEST_MODE, preview_mode=config.PREVIEW_MODE)
    config.validate_destination_config()
    history_store.initialize_database()
    # TEST_MODE retains its established static-preview coverage. Production
    # and PREVIEW_MODE honor an explicit reels-only environment override.
    output_mode = "full" if config.TEST_MODE else config.get_social_output_mode()
    reels_only_output = output_mode == "reels_only"

    run_id = str(uuid.uuid4())
    run_started_at, weekly_content = _resolve_run_weekly_content(slot)
    due_at = next_slot_datetime_utc(slot, now=run_started_at)
    due_at_iso = to_iso8601_utc(due_at)
    print("Run ID: {0}".format(run_id))
    print("TEST_MODE: {0}".format(config.TEST_MODE))
    print("PREVIEW_MODE: {0}".format(config.PREVIEW_MODE))
    print("SOCIAL_OUTPUT_MODE: {0}".format(output_mode))

    selection = campaign_engine.choose_selection(slot)
    campaign_candidates = campaign_engine.load_campaigns()
    caption_profile_override = _caption_profile_preview_override()
    if caption_profile_override:
        print(
            "Explicit caption profile override: {0}".format(
                caption_profile_override
            )
        )
    brief = resolved_content_brief.resolve_content_brief(
        run_id=run_id,
        slot=slot,
        post_date=run_started_at.astimezone(config.EASTERN_TZ).date().isoformat(),
        platform_mode=output_mode,
        candidate_campaign=selection["campaign"],
        campaigns=campaign_candidates,
        weekly_content=weekly_content,
        caption_profile_override=caption_profile_override,
    )
    brief_report = resolved_content_brief.validate_resolved_content_brief(brief)
    resolved_content_brief.log_resolved_content_brief(brief, brief_report)
    for item in brief_report:
        print("Resolved brief validation [{0}]: {1}".format(item["status"], item["message"]))
    if resolved_content_brief.has_critical_failure(brief_report):
        raise RuntimeError("Resolved Content Brief has a critical identity mismatch.")

    campaign = next(
        (candidate for candidate in campaign_candidates if candidate.get("_key") == brief.campaign_id),
        None,
    )
    if campaign is None:
        campaign = {"_key": "", "name": "", "pain_point": "", "goal": ""}
    selection["campaign"] = campaign
    selection["hook"] = brief.hook_style_label or ""
    selection["cta"] = brief.cta_text
    selection["thread_topic"] = brief.creator_search_topic or ""
    formula = selection["formula"]
    persona = selection["persona"]

    # TEST_MODE uses the same read-only Supabase background source and
    # selection logic as production (list + download), but still exits
    # before any upload/posting steps.
    supabase = get_supabase_client()
    backgrounds = list_backgrounds(supabase)

    try:
        background_choice = campaign_engine.choose_background(
            backgrounds,
            slot=slot,
            campaign=campaign,
            formula=formula,
            persona=persona,
            resolved_brief=brief,
        )
    except TypeError as exc:
        if "resolved_brief" not in str(exc):
            raise
        # Existing extension points may still provide the legacy selector.
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
    asset_report = resolved_content_brief.validate_asset_metadata(brief, background_choice.get("metadata") or {})
    for item in asset_report:
        print("Resolved asset validation [{0}]: {1}".format(item["status"], item["message"]))
    if (
        background_choice.get("resolved_brief_applied")
        and resolved_content_brief.has_critical_failure(asset_report)
    ):
        raise RuntimeError("Resolved Content Brief asset requirements conflict with the selected background.")
    if not background_choice.get("resolved_brief_applied") and resolved_content_brief.has_critical_failure(asset_report):
        print("Resolved asset validation [warning]: legacy background selector did not apply the canonical brief.")

    # Creative Engine v2: pick an approved spiritual-action sentence from
    # brand/theology_actions.json, matched to this campaign and slot.
    selection["spiritual_action"] = campaign_engine.pick_spiritual_action(campaign, slot)
    print("Selected spiritual action: {0}".format(selection["spiritual_action"]))

    print("Selected campaign: {0}".format(campaign.get("name") or "none"))
    print("Selected formula: {0}".format(formula["name"]))
    print("Selected persona: {0}".format(persona["name"] if persona else "none"))
    if selection.get("seasonal_context"):
        print("Seasonal context: {0}".format(selection["seasonal_context"]))
    for rule in selection.get("relaxed_rules", []):
        print("NOTE: relaxed rule -> {0}".format(rule))
    print("Selected hook: {0}".format(selection["hook"]))
    print("Selected CTA: {0}".format(selection["cta"]))
    print("Selected Creator Search topic: {0}".format(brief.creator_search_topic or "none"))
    print("Selected background: {0}".format(chosen_background))
    print("Selected Supabase background filename: {0}".format(Path(chosen_background).name))

    print("Selected slot: {0} -> dueAt (UTC): {1}".format(slot, due_at_iso))

    run_row_id = history_store.create_run_record(
        run_id=run_id,
        slot=slot,
        campaign_name=brief.campaign_name or "",
        formula_name=formula["name"],
        persona_name=persona["name"] if persona else None,
        seasonal_context=selection.get("seasonal_context"),
        selected_hook=brief.hook_style_label,
        selected_body_angle=selection["body_angle"],
        selected_cta=brief.cta_text,
        selected_thread_topic=None,
        selected_creator_search_topic=_resolve_creator_search_topic({}, selection, brief),
        background_object_path=chosen_background,
        resolved_brief=brief.to_history_dict(),
        status="dry_run" if (config.TEST_MODE or config.PREVIEW_MODE) else "in_progress",
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
    if config.TEST_MODE or config.PREVIEW_MODE:
        fallback_url = config.DEFAULT_DESTINATION_URL or "https://example.com/prayonit"
        tracked_urls = {
            "facebook": fallback_url,
            "instagram": fallback_url,
        }
        mode_label = "TEST_MODE" if config.TEST_MODE else "PREVIEW_MODE"
        print("{0}: tracking calls skipped; using fallback URL.".format(mode_label))
    else:
        for platform in ("facebook", "instagram"):
            tracked_urls[platform] = tracking.create_tracked_link(
                run_id=run_id,
                campaign_name=brief.campaign_name or "",
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
            try:
                ad_copy = prompt_builder.generate_local_ad_copy(
                    selection=selection, slot=slot, resolved_brief=brief
                )
            except TypeError as exc:
                if "resolved_brief" not in str(exc):
                    raise
                ad_copy = prompt_builder.generate_local_ad_copy(selection=selection, slot=slot)
        else:
            ad_copy = prompt_builder.generate_ad_copy(
                post_type=post_type_hint,
                selection=selection,
                slot=slot,
                tracked_url=tracked_urls["facebook"],
                resolved_brief=brief,
            )
    except Exception as exc:
        history_store.update_run_record(run_row_id, status="failed", error_message=str(exc))
        raise

    # The handoff note and future analytics consume this canonical topic;
    # generated copy must not replace it with a campaign-derived topic.
    ad_copy["creator_search_topic"] = brief.creator_search_topic

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
                original_headline=original_headline,
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

    legacy_platform_captions = prompt_builder.build_platform_captions(
        ad_copy, selection, tracked_urls
    )
    legacy_tiktok_caption = build_tiktok_caption(ad_copy, selection, brief)
    platform_caption_sources = {
        "facebook": legacy_platform_captions["facebook"],
        "instagram": legacy_platform_captions["instagram"],
        "tiktok": legacy_tiktok_caption,
    }
    prepared_platform_bases = {}
    preparation_errors = {}
    for platform, base_caption in platform_caption_sources.items():
        try:
            prepared_platform_bases[platform] = (
                platform_post_preparer.prepare_platform_post(
                    platform=platform,
                    base_caption=base_caption,
                    brief=brief,
                    scheduled_at=due_at_iso,
                    post_type="video" if platform == "tiktok" else "reel",
                    direct_url=(
                        tracked_urls["facebook"]
                        if platform == "facebook"
                        else None
                    ),
                )
            )
        except platform_post_preparer.PlatformPostPreparationError as exc:
            preparation_errors[platform] = str(exc)
            print(
                "Platform preparation failed for {0}: {1}".format(
                    platform, exc
                ),
                file=sys.stderr,
            )
    platform_captions = {
        platform: (
            prepared_platform_bases[platform].public_caption
            if platform in prepared_platform_bases
            else legacy_platform_captions[platform]
        )
        for platform in ("facebook", "instagram")
    }
    tiktok_caption = (
        prepared_platform_bases["tiktok"].public_caption
        if "tiktok" in prepared_platform_bases
        else legacy_tiktok_caption
    )
    history_store.merge_run_resolved_brief_metadata(
        run_row_id,
        {
            "prepared_platform_posts": {
                platform: post.to_persistence_dict()
                for platform, post in prepared_platform_bases.items()
            },
            "platform_preparation_errors": preparation_errors,
        },
    )
    print("Facebook caption: {0}".format(platform_captions["facebook"]))
    print("Instagram caption: {0}".format(platform_captions["instagram"]))
    print("TikTok caption: {0}".format(tiktok_caption))

    # Enforce locked benefit text before any optional static rendering/QA so
    # all downstream paths see the final approved values.
    ad_copy["app_benefit"] = image_renderer.EXACT_BENEFIT_TEXT if hasattr(image_renderer, "EXACT_BENEFIT_TEXT") else "Get a guided, personalized prayer based on your mood right now."
    ad_copy["story_app_benefit"] = ad_copy["app_benefit"]
    qa_report = None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    feed_local_path = None
    story_local_path = None
    if not reels_only_output:
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

        feed_local_path = config.OUTPUT_IMAGES_FEED_DIR / "prayonit-feed-{0}.jpg".format(timestamp)
        story_local_path = config.OUTPUT_IMAGES_STORY_DIR / "prayonit-story-{0}.jpg".format(timestamp)
        feed_image.save(feed_local_path, quality=95)
        story_image.save(story_local_path, quality=95)
        print("Saved feed preview: {0}".format(feed_local_path.resolve()))
        print("Saved story preview: {0}".format(story_local_path.resolve()))
    else:
        print("Static feed/story rendering skipped by SOCIAL_OUTPUT_MODE=reels_only")

    # Optional local-only video rendering. Short formats keep using the
    # existing 8-second motion renderer; long-form prayer/devotional/
    # encouragement formats route to the long-form compositor.
    video_local_path = None
    video_generation_error = None
    if config.VIDEO_ENABLED:
        import long_form_renderer
        import motion_renderer

        try:
            presentation_config = {
                **content_engine.get_presentation_config(weekly_content),
                "slot": slot,
            }
            video_template = presentation_config.get("video_template", "short_promo")
            if video_template in ("long_prayer", "long_devotional", "long_encouragement"):
                filename_suffix = video_template.replace("long_", "")
                narration_audio_path = None
                narration_duration = None
                narration_segment_timeline = None
                narration_text = voice_provider.build_narration_text(ad_copy)
                _log_preview_narration_debug(ad_copy, narration_text)
                if config.VOICE_ENABLED and narration_text:
                    audio_filename = config.OUTPUT_AUDIO_DIR / "prayonit-{0}-voice-{1}.wav".format(
                        filename_suffix,
                        timestamp,
                    )
                    hook_window = long_form_renderer.OPENING_HOOK_DURATION if ad_copy.get("opening_hook") else 0.0
                    if config.TEST_MODE:
                        narration_duration = float(
                            max(8, min(35, int(ad_copy.get("estimated_spoken_seconds", 30) or 30)))
                        )
                        narration_audio_path = voice_provider.create_silent_wav(
                            audio_filename,
                            narration_duration,
                        )
                    else:
                        narration_audio_path = voice_provider.generate_voiceover(
                            narration_text,
                            voice_provider.select_default_voice(ad_copy),
                            voice_provider.select_style_instruction(ad_copy),
                            audio_filename,
                            copy=ad_copy,
                            delivery_context={
                                "slot": brief.slot,
                                "content_type": brief.content_type,
                                "prayer_category_id": brief.prayer_category_id,
                            },
                        )
                        if narration_audio_path is not None:
                            narration_duration = voice_provider.measure_audio_duration(narration_audio_path)
                    if narration_duration is not None:
                        narration_segment_timeline = voice_provider.build_narration_segment_timeline(
                            ad_copy,
                            narration_duration,
                            hook_window=hook_window,
                        )

                candidate_video_path = config.OUTPUT_VIDEOS_LONG_DIR / "prayonit-long-{0}-{1}.mp4".format(
                    filename_suffix,
                    timestamp,
                )
                planned_video_duration = long_form_renderer.resolve_long_form_duration(
                    ad_copy,
                    presentation_config,
                    narration_duration=narration_duration,
                )[0]
                selected_video_assets = _select_long_form_scenic_assets(
                    brief=brief,
                    narration_duration=narration_duration,
                    planned_video_duration=planned_video_duration,
                    run_row_id=run_row_id,
                )
                video_local_path = long_form_renderer.render_long_form_video(
                    copy=ad_copy,
                    presentation_config=presentation_config,
                    video_assets=selected_video_assets,
                    output_path=candidate_video_path,
                    narration_audio_path=narration_audio_path,
                    narration_duration=narration_duration,
                    narration_segment_timeline=narration_segment_timeline,
                    caption_profile_id=brief.caption_profile_id,
                    creative_policy_version=brief.creative_policy_version,
                )
                print("Saved long-form video preview: {0}".format(video_local_path.resolve()))
            else:
                motion_backgrounds = sorted(config.MOTION_BACKGROUNDS_DIR.glob("*.mp4"))
                if not motion_backgrounds:
                    print(
                        "VIDEO_ENABLED=true but no .mp4 files found in {0}; skipping video.".format(
                            config.MOTION_BACKGROUNDS_DIR
                        )
                    )
                else:
                    motion_background_path = random.choice(motion_backgrounds)
                    candidate_video_path = config.OUTPUT_VIDEOS_DIR / "prayonit-reel-{0}.mp4".format(timestamp)
                    motion_renderer.render_motion_ad(
                        ad_copy=ad_copy,
                        background_path=motion_background_path,
                        output_path=candidate_video_path,
                    )
                    video_local_path = candidate_video_path
                    print("Saved motion video preview: {0}".format(video_local_path.resolve()))
        except Exception as exc:
            # Video generation is best-effort and local-only in this phase;
            # it must never block static full-output runs, but reels-only
            # production depends on a valid final video.
            video_generation_error = exc
            print("Motion video generation skipped due to error: {0}".format(exc), file=sys.stderr)

    history_store.update_run_record(
        run_row_id,
        headline=ad_copy["pain_headline"],
        story_headline=ad_copy["story_headline"],
        status="dry_run" if (config.TEST_MODE or config.PREVIEW_MODE) else "in_progress",
    )

    if config.TEST_MODE or config.PREVIEW_MODE:
        mode_label = "TEST_MODE" if config.TEST_MODE else "PREVIEW_MODE"
        if config.PREVIEW_MODE:
            print("TikTok scheduling payload: {0}".format(json.dumps({
                "channel_id": config.TIKTOK_CHANNEL_ID,
                "service": "tiktok",
                "post_type": "video",
                "due_at_iso": due_at_iso,
                "caption": tiktok_caption,
                "platform_options": (
                    prepared_platform_bases["tiktok"].platform_options
                    if "tiktok" in prepared_platform_bases
                    else {"isAiGenerated": True}
                ),
            })))
        print("{0}=true, so nothing was uploaded or posted.".format(mode_label))
        return 0

    if reels_only_output and video_local_path is None:
        reason = "Video-specific failure: no final video was produced"
        if video_generation_error is not None:
            reason = "Video-specific failure: {0}".format(video_generation_error)
        history_store.update_run_record(run_row_id, status="failed", error_message=reason)
        print(reason)
        print("BLOCKED: slot={0} video-specific failure".format(slot))
        return 2

    if qa_report is not None and creative_engine_v3.should_block_buffer(qa_report):
        reason = "QA critical failure(s): " + ", ".join(qa_report.get("critical_failures", []))
        history_store.update_run_record(run_row_id, status="failed", error_message=reason)
        print(reason)
        print("Buffer queue skipped due to QA failure.")
        print("BLOCKED: slot={0} QA failures: {1}".format(slot, qa_report.get("critical_failures", [])))
        return 2

    feed_remote_path = None
    feed_url = None
    story_remote_path = None
    story_url = None
    if not reels_only_output:
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

    # Phase 2A: optional video upload + publish. Only runs when both
    # VIDEO_ENABLED produced a local video AND VIDEO_PUBLISH_ENABLED=true.
    # TEST_MODE already returned before this point (see above), so this
    # code path only ever runs in production, matching the existing
    # image-publishing safety behavior.
    video_url = None
    if config.VIDEO_PUBLISH_ENABLED and video_local_path is not None:
        video_remote_path, video_url = image_renderer.upload_generated_video(
            video_local_path, config.GENERATED_VIDEO_PREFIX, supabase
        )
        print("Uploaded video: {0}".format(video_remote_path))
        print("Video public URL: {0}".format(video_url))
        history_store.update_run_record(
            run_row_id,
            generated_video_object_path=video_remote_path,
        )

    history_store.update_run_record(
        run_row_id,
        generated_feed_object_path=feed_remote_path,
        generated_story_object_path=story_remote_path,
        status="prepared",
    )

    buffer_job_specs = []
    if not reels_only_output:
        buffer_job_specs.extend([
            ("facebook", "post", config.FACEBOOK_CHANNEL_ID, feed_url, None, tracked_urls["facebook"]),
            ("instagram", "post", config.INSTAGRAM_CHANNEL_ID, feed_url, None, tracked_urls["instagram"]),
            ("facebook", "story", config.FACEBOOK_CHANNEL_ID, story_url, None, None),
            ("instagram", "story", config.INSTAGRAM_CHANNEL_ID, story_url, None, None),
        ])

    if video_url is not None:
        # The same generated MP4 is reused for all automatic video destinations.
        buffer_job_specs.extend([
            ("facebook", "reel", config.FACEBOOK_CHANNEL_ID, None, video_url, None),
            ("instagram", "reel", config.INSTAGRAM_CHANNEL_ID, None, video_url, None),
            ("tiktok", "video", config.TIKTOK_CHANNEL_ID, None, video_url, None),
        ])

    successes = []
    failures = []
    skipped_successes = []
    prepared_jobs = []
    platform_post_records = {}
    run_metadata = history_store.get_run_resolved_brief_metadata(run_row_id)
    selected_asset_ids = [
        str(asset.get("asset_id", ""))
        for asset in run_metadata.get("selected_scenic_assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    ]

    for (
        service,
        item_post_type,
        channel_id,
        image_url,
        job_video_url,
        tracked_url,
    ) in buffer_job_specs:
        label = "{0} {1}".format(service, item_post_type)
        media_reference = image_url or job_video_url
        try:
            if service in preparation_errors:
                raise platform_post_preparer.PlatformPostPreparationError(
                    preparation_errors[service]
                )
            prepared = platform_post_preparer.prepare_platform_post(
                platform=service,
                base_caption=platform_caption_sources[service],
                brief=brief,
                scheduled_at=due_at_iso,
                post_type=item_post_type,
                media_reference=media_reference,
                direct_url=(
                    tracked_urls["facebook"]
                    if service == "facebook"
                    else None
                ),
                selected_asset_ids=selected_asset_ids,
            )
            prepared = prepared.with_delivery(
                post_type=item_post_type,
                media_reference=media_reference,
            )
            prepared.validate()
            prepared_jobs.append(
                (
                    prepared,
                    channel_id,
                    image_url,
                    job_video_url,
                    tracked_url,
                )
            )
            platform_post_records[label] = {
                **prepared.to_persistence_dict(),
                "publication_status": "prepared",
                "buffer_post_id": None,
                "published_url": None,
                "failure_message": None,
                "attempt_timestamp": None,
            }
        except Exception as exc:
            print("FAILED preparing {0}: {1}".format(label, exc), file=sys.stderr)
            history_store.save_post_error(
                run_id=run_id,
                platform=service,
                post_type=item_post_type,
                campaign_name=campaign["name"],
                formula_name=formula["name"],
                persona_name=persona["name"] if persona else None,
                slot=slot,
                error_message=str(exc),
                caption=platform_caption_sources.get(service),
                image_url=media_reference,
            )
            platform_post_records[label] = {
                "platform": service,
                "post_type": item_post_type,
                "publication_status": "failed",
                "failure_message": str(exc),
                "attempt_timestamp": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
            failures.append(label)

    history_store.merge_run_resolved_brief_metadata(
        run_row_id,
        {
            "prepared_platform_posts": platform_post_records,
            "publishing_summary": {
                "intended_count": len(buffer_job_specs),
                "prepared_count": len(prepared_jobs),
                "preparation_failure_count": len(failures),
            },
        },
    )
    if not buffer_job_specs:
        print("No Buffer publishing jobs were requested; run remains prepared.")
        return 0

    history_store.update_run_record(run_row_id, status="publishing")
    for (
        prepared,
        channel_id,
        image_url,
        job_video_url,
        tracked_url,
    ) in prepared_jobs:
        service = prepared.platform
        item_post_type = prepared.post_type
        caption = prepared.public_caption
        label = "{0} {1}".format(service, item_post_type)
        existing_delivery = history_store.get_successful_platform_delivery_state(
            run_id=run_id, platform=service, post_type=item_post_type
        )
        if existing_delivery:
            print(
                "Already completed {0} as Buffer post {1}; skipping duplicate.".format(
                    label,
                    existing_delivery["buffer_post_id"],
                )
            )
            successes.append(label)
            skipped_successes.append(label)
            platform_post_records[label].update(
                {
                    "publication_status": "scheduled",
                    "buffer_post_id": existing_delivery["buffer_post_id"],
                    "attempt_timestamp": existing_delivery["created_at_utc"],
                    "retry_action": "skipped_existing_success",
                }
            )
            continue
        try:
            result = buffer_client.buffer_create_post(
                channel_id=channel_id,
                caption=caption,
                image_url=image_url,
                video_url=job_video_url,
                service=service,
                post_type=item_post_type,
                due_at_iso=due_at_iso,
                link=tracked_url,
                platform_options=prepared.platform_options,
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
                image_url=image_url or job_video_url,
                buffer_status="scheduled",
            )
            successes.append(label)
            platform_post_records[label].update(
                {
                    "publication_status": "scheduled",
                    "buffer_post_id": buffer_post_id,
                    "attempt_timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "retry_action": "submitted",
                }
            )
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
                image_url=image_url or job_video_url,
            )
            failures.append(label)
            platform_post_records[label].update(
                {
                    "publication_status": "failed",
                    "failure_message": str(exc),
                    "attempt_timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "retry_action": "failed",
                }
            )

    final_status = platform_post_preparer.resolve_publishing_status(
        intended_count=len(buffer_job_specs),
        success_count=len(successes),
        failure_count=len(failures),
    )
    history_store.update_run_record(
        run_row_id,
        status=final_status,
        error_message=(
            "Buffer queue failures: {0}".format(", ".join(failures))
            if failures
            else None
        ),
    )
    history_store.merge_run_resolved_brief_metadata(
        run_row_id,
        {
            "prepared_platform_posts": platform_post_records,
            "publishing_summary": {
                "intended_count": len(buffer_job_specs),
                "success_count": len(successes),
                "failure_count": len(failures),
                "skipped_existing_successes": skipped_successes,
                "final_status": final_status,
            },
        },
    )

    print("\n--- Run summary ---")
    print("Delivery Summary:")
    for label, job_label in (
        ("Facebook Reel", "facebook reel"),
        ("Instagram Reel", "instagram reel"),
        ("TikTok", "tiktok video"),
    ):
        state = "queued" if job_label in successes else "failed" if job_label in failures else "not requested"
        print("- {0}: {1}".format(label, state))
    print("- Manual TikTok handoff: disabled")
    if reels_only_output:
        print("Skipped by output mode: Facebook feed, Instagram feed, Facebook story, Instagram story")
    print("Succeeded ({0}): {1}".format(len(successes), ", ".join(successes) if successes else "none"))
    print("Failed ({0}): {1}".format(len(failures), ", ".join(failures) if failures else "none"))
    if failures:
        print(
            "FAILED: slot={0} status={1} Buffer queue failures: {2}".format(
                slot,
                final_status,
                failures,
            )
        )
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
