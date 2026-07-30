"""SQLite-backed history store for the Prayonit Marketing Engine.

Uses only the standard-library sqlite3 module (no ORM). All timestamps are
stored as ISO 8601 UTC strings.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import config

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS campaigns_used (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        slot TEXT NOT NULL,
        campaign_name TEXT NOT NULL,
        formula_name TEXT,
        persona_name TEXT,
        seasonal_context TEXT,
        selected_hook TEXT,
        selected_body_angle TEXT,
        selected_cta TEXT,
        selected_thread_topic TEXT,
        selected_creator_search_topic TEXT,
        resolved_brief_json TEXT,
        pain_point_id TEXT,
        life_moment_id TEXT,
        life_moment_text TEXT,
        hook_style TEXT,
        content_type TEXT,
        campaign_id TEXT,
        cta_text TEXT,
        destination_url TEXT,
        voice_style_profile TEXT,
        engagement_prompt_type TEXT,
        resolved_engagement_prompt TEXT,
        engagement_selection_reason TEXT,
        background_object_path TEXT,
        generated_feed_object_path TEXT,
        generated_story_object_path TEXT,
        generated_video_object_path TEXT,
        headline TEXT,
        story_headline TEXT,
        status TEXT NOT NULL,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS published_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        scheduled_at_utc TEXT,
        platform TEXT NOT NULL,
        post_type TEXT NOT NULL,
        buffer_post_id TEXT,
        buffer_status TEXT,
        campaign_name TEXT NOT NULL,
        formula_name TEXT,
        persona_name TEXT,
        slot TEXT NOT NULL,
        headline TEXT,
        caption TEXT,
        tracked_url TEXT,
        image_url TEXT,
        error_message TEXT,
        metrics_last_checked_at_utc TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS post_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buffer_post_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        measured_at_utc TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        raw_metrics_json TEXT,
        UNIQUE(buffer_post_id, measured_at_utc, metric_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tracking_clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_id TEXT NOT NULL,
        clicked_at_utc TEXT NOT NULL,
        campaign_name TEXT,
        formula_name TEXT,
        persona_name TEXT,
        platform TEXT,
        post_type TEXT,
        slot TEXT,
        destination TEXT,
        user_agent TEXT,
        referrer TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tracking_links (
        tracking_id TEXT PRIMARY KEY,
        created_at_utc TEXT NOT NULL,
        run_id TEXT,
        campaign_name TEXT,
        formula_name TEXT,
        persona_name TEXT,
        platform TEXT,
        post_type TEXT,
        slot TEXT,
        destination TEXT,
        scheduled_at_utc TEXT,
        tracked_url TEXT
    )
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect():
    conn = sqlite3.connect(str(config.DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> None:
    """Create all tables if they do not already exist."""
    with _connect() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        # Lightweight migration: add columns introduced after initial release
        # to any pre-existing campaigns_used table (CREATE TABLE IF NOT EXISTS
        # above will not alter an already-created table).
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(campaigns_used)")
        }
        if "generated_video_object_path" not in existing_columns:
            conn.execute(
                "ALTER TABLE campaigns_used ADD COLUMN generated_video_object_path TEXT"
            )
        if "selected_creator_search_topic" not in existing_columns:
            conn.execute(
                "ALTER TABLE campaigns_used ADD COLUMN selected_creator_search_topic TEXT"
            )
        for column_name in (
            "resolved_brief_json",
            "pain_point_id",
            "life_moment_id",
            "life_moment_text",
            "hook_style",
            "content_type",
            "campaign_id",
            "cta_text",
            "destination_url",
            "voice_style_profile",
            "engagement_prompt_type",
            "resolved_engagement_prompt",
            "engagement_selection_reason",
        ):
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE campaigns_used ADD COLUMN {column_name} TEXT")


def create_run_record(
    *,
    run_id: str,
    slot: str,
    campaign_name: str,
    formula_name: Optional[str] = None,
    persona_name: Optional[str] = None,
    seasonal_context: Optional[str] = None,
    selected_hook: Optional[str] = None,
    selected_body_angle: Optional[str] = None,
    selected_cta: Optional[str] = None,
    selected_thread_topic: Optional[str] = None,
    selected_creator_search_topic: Optional[str] = None,
    background_object_path: Optional[str] = None,
    resolved_brief: Optional[Dict[str, Any]] = None,
    status: str = "in_progress",
) -> int:
    """Insert a new campaigns_used row and return its id."""
    if resolved_brief and selected_creator_search_topic is None:
        selected_creator_search_topic = resolved_brief.get("creator_search_topic")
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO campaigns_used (
                run_id, created_at_utc, slot, campaign_name, formula_name,
                persona_name, seasonal_context, selected_hook,
                selected_body_angle, selected_cta, selected_thread_topic,
                selected_creator_search_topic, background_object_path,
                resolved_brief_json, pain_point_id, life_moment_id,
                life_moment_text, hook_style, content_type, campaign_id,
                cta_text, destination_url, voice_style_profile,
                engagement_prompt_type, resolved_engagement_prompt,
                engagement_selection_reason, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _now_iso(),
                slot,
                campaign_name,
                formula_name,
                persona_name,
                seasonal_context,
                selected_hook,
                selected_body_angle,
                selected_cta,
                selected_thread_topic,
                selected_creator_search_topic,
                background_object_path,
                json.dumps(resolved_brief) if resolved_brief else None,
                (resolved_brief or {}).get("pain_point_id"),
                (resolved_brief or {}).get("life_moment_id"),
                (resolved_brief or {}).get("life_moment_text"),
                (resolved_brief or {}).get("hook_style_label"),
                (resolved_brief or {}).get("content_type"),
                (resolved_brief or {}).get("campaign_id"),
                (resolved_brief or {}).get("cta_text"),
                (resolved_brief or {}).get("destination_url"),
                (resolved_brief or {}).get("voice_style_profile"),
                (resolved_brief or {}).get("engagement_prompt_type"),
                (resolved_brief or {}).get("engagement_prompt"),
                (resolved_brief or {}).get("engagement_selection_reason"),
                status,
            ),
        )
        return cursor.lastrowid


def update_run_record(
    run_row_id: int,
    *,
    generated_feed_object_path: Optional[str] = None,
    generated_story_object_path: Optional[str] = None,
    generated_video_object_path: Optional[str] = None,
    headline: Optional[str] = None,
    story_headline: Optional[str] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update fields on an existing campaigns_used row."""
    fields = {
        "generated_feed_object_path": generated_feed_object_path,
        "generated_story_object_path": generated_story_object_path,
        "generated_video_object_path": generated_video_object_path,
        "headline": headline,
        "story_headline": story_headline,
        "status": status,
        "error_message": error_message,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return

    set_clause = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [run_row_id]

    with _connect() as conn:
        conn.execute(f"UPDATE campaigns_used SET {set_clause} WHERE id = ?", values)


def merge_run_resolved_brief_metadata(
    run_row_id: int,
    metadata: Dict[str, Any],
) -> None:
    """Merge additive orchestration metadata into the existing run JSON."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT resolved_brief_json FROM campaigns_used WHERE id = ?",
            (run_row_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown campaign run row: {run_row_id}")
        existing: Dict[str, Any] = {}
        raw = row["resolved_brief_json"]
        if raw:
            try:
                decoded = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                decoded = {}
            if isinstance(decoded, dict):
                existing = decoded
        existing.update(metadata)
        conn.execute(
            "UPDATE campaigns_used SET resolved_brief_json = ? WHERE id = ?",
            (json.dumps(existing), run_row_id),
        )


def get_run_resolved_brief_metadata(run_row_id: int) -> Dict[str, Any]:
    """Return one run's additive JSON metadata without exposing other rows."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT resolved_brief_json FROM campaigns_used WHERE id = ?",
            (run_row_id,),
        ).fetchone()
    if row is None or not row["resolved_brief_json"]:
        return {}
    try:
        payload = json.loads(row["resolved_brief_json"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_recent_scenic_asset_ids(
    *,
    limit_runs: int = 10,
    exclude_statuses: Optional[Iterable[str]] = None,
) -> List[str]:
    """Read prior scenic selections from existing run JSON, newest first."""
    if limit_runs <= 0:
        return []
    params: List[Any] = []
    sql = (
        "SELECT resolved_brief_json FROM campaigns_used "
        "WHERE resolved_brief_json IS NOT NULL"
    )
    statuses = list(exclude_statuses or ())
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        sql += f" AND status NOT IN ({placeholders})"
        params.extend(statuses)
    sql += " ORDER BY created_at_utc DESC, id DESC LIMIT ?"
    params.append(limit_runs)

    seen: set[str] = set()
    recent_ids: List[str] = []
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["resolved_brief_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        assets = payload.get("selected_scenic_assets", [])
        if not isinstance(assets, list):
            continue
        for asset in assets:
            asset_id = (
                str(asset.get("asset_id", "")).strip()
                if isinstance(asset, dict)
                else ""
            )
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                recent_ids.append(asset_id)
    return recent_ids


def save_published_post(
    *,
    run_id: str,
    scheduled_at_utc: Optional[str],
    platform: str,
    post_type: str,
    buffer_post_id: Optional[str],
    campaign_name: str,
    formula_name: Optional[str],
    persona_name: Optional[str],
    slot: str,
    headline: Optional[str],
    caption: Optional[str],
    tracked_url: Optional[str],
    image_url: Optional[str],
    buffer_status: str = "scheduled",
) -> int:
    """Record a successfully-scheduled Buffer post."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO published_posts (
                run_id, created_at_utc, scheduled_at_utc, platform, post_type,
                buffer_post_id, buffer_status, campaign_name, formula_name,
                persona_name, slot, headline, caption, tracked_url, image_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _now_iso(),
                scheduled_at_utc,
                platform,
                post_type,
                buffer_post_id,
                buffer_status,
                campaign_name,
                formula_name,
                persona_name,
                slot,
                headline,
                caption,
                tracked_url,
                image_url,
            ),
        )
        return cursor.lastrowid


def save_post_error(
    *,
    run_id: str,
    platform: str,
    post_type: str,
    campaign_name: str,
    formula_name: Optional[str],
    persona_name: Optional[str],
    slot: str,
    error_message: str,
    caption: Optional[str] = None,
    image_url: Optional[str] = None,
) -> int:
    """Record a failed Buffer post attempt. Never marks it as scheduled."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO published_posts (
                run_id, created_at_utc, scheduled_at_utc, platform, post_type,
                buffer_post_id, buffer_status, campaign_name, formula_name,
                persona_name, slot, headline, caption, tracked_url, image_url,
                error_message
            ) VALUES (?, ?, NULL, ?, ?, NULL, 'failed', ?, ?, ?, ?, NULL, ?, NULL, ?, ?)
            """,
            (
                run_id,
                _now_iso(),
                platform,
                post_type,
                campaign_name,
                formula_name,
                persona_name,
                slot,
                caption,
                image_url,
                error_message,
            ),
        )
        return cursor.lastrowid


def get_platform_delivery_state(
    *, run_id: str, platform: str, post_type: str
) -> Optional[sqlite3.Row]:
    """Return the latest delivery record for one idempotent platform job."""
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM published_posts
            WHERE run_id = ? AND platform = ? AND post_type = ?
            ORDER BY id DESC LIMIT 1
            """,
            (run_id, platform, post_type),
        ).fetchone()


def get_successful_platform_delivery_state(
    *, run_id: str, platform: str, post_type: str
) -> Optional[sqlite3.Row]:
    """Return any successful delivery so retries cannot duplicate it."""
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM published_posts
            WHERE run_id = ? AND platform = ? AND post_type = ?
              AND buffer_status = 'scheduled'
              AND buffer_post_id IS NOT NULL
            ORDER BY id ASC LIMIT 1
            """,
            (run_id, platform, post_type),
        ).fetchone()


def get_recent_campaign_history(days: int = 30, exclude_statuses: Optional[Iterable[str]] = None) -> List[sqlite3.Row]:
    """Return recent campaigns_used rows within `days`.

    If `exclude_statuses` is provided (e.g. ['dry_run']), rows with those
    statuses will be omitted. This allows TEST_MODE dry_run rows to be kept in
    the database but excluded from duplicate-headline checks used by QA.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect() as conn:
        if not exclude_statuses:
            cursor = conn.execute(
                "SELECT * FROM campaigns_used WHERE created_at_utc >= ? ORDER BY created_at_utc DESC",
                (cutoff,),
            )
        else:
            # Build a parameterized query to exclude the given statuses
            placeholders = ",".join("?" for _ in exclude_statuses)
            sql = (
                f"SELECT * FROM campaigns_used WHERE created_at_utc >= ? AND status NOT IN ({placeholders}) "
                "ORDER BY created_at_utc DESC"
            )
            params = [cutoff] + list(exclude_statuses)
            cursor = conn.execute(sql, params)
        return cursor.fetchall()


def get_recent_background_history(days: int = 30) -> List[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect() as conn:
        cursor = conn.execute(
            """
            SELECT DISTINCT background_object_path FROM campaigns_used
            WHERE created_at_utc >= ? AND background_object_path IS NOT NULL
            """,
            (cutoff,),
        )
        return [row["background_object_path"] for row in cursor.fetchall()]


def get_posts_missing_metrics(cooldown_hours: int = 12) -> List[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with _connect() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM published_posts
            WHERE buffer_post_id IS NOT NULL
              AND buffer_status = 'scheduled'
              AND (metrics_last_checked_at_utc IS NULL OR metrics_last_checked_at_utc < ?)
            """,
            (cutoff,),
        )
        return cursor.fetchall()


def save_metrics(
    *,
    buffer_post_id: str,
    platform: str,
    metrics: Dict[str, Optional[float]],
    raw_metrics: Any,
) -> None:
    """Persist one metrics observation (multiple metric_name rows) for a post."""
    measured_at = _now_iso()
    raw_json = json.dumps(raw_metrics)

    with _connect() as conn:
        for metric_name, metric_value in metrics.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO post_metrics (
                    buffer_post_id, platform, measured_at_utc, metric_name,
                    metric_value, raw_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (buffer_post_id, platform, measured_at, metric_name, metric_value, raw_json),
            )
        conn.execute(
            "UPDATE published_posts SET metrics_last_checked_at_utc = ? WHERE buffer_post_id = ?",
            (measured_at, buffer_post_id),
        )


def save_tracking_link(
    *,
    tracking_id: str,
    run_id: str,
    campaign_name: str,
    formula_name: Optional[str],
    persona_name: Optional[str],
    platform: str,
    post_type: str,
    slot: str,
    destination: str,
    scheduled_at_utc: Optional[str],
    tracked_url: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO tracking_links (
                tracking_id, created_at_utc, run_id, campaign_name, formula_name,
                persona_name, platform, post_type, slot, destination,
                scheduled_at_utc, tracked_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tracking_id,
                _now_iso(),
                run_id,
                campaign_name,
                formula_name,
                persona_name,
                platform,
                post_type,
                slot,
                destination,
                scheduled_at_utc,
                tracked_url,
            ),
        )


def export_performance_summary(days: int = 30) -> Dict[str, Any]:
    """Return a simple dict summary of posts/metrics over the trailing window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _connect() as conn:
        posts = conn.execute(
            "SELECT * FROM published_posts WHERE created_at_utc >= ?", (cutoff,)
        ).fetchall()
        metrics = conn.execute(
            "SELECT * FROM post_metrics WHERE measured_at_utc >= ?", (cutoff,)
        ).fetchall()

    return {
        "window_days": days,
        "posts_total": len(posts),
        "posts_scheduled": sum(1 for p in posts if p["buffer_status"] == "scheduled"),
        "posts_failed": sum(1 for p in posts if p["buffer_status"] == "failed"),
        "metrics_observations": len(metrics),
    }
