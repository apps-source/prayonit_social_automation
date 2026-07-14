"""Buffer metrics retrieval and reporting (Part 5 / Part 13 CLI: analytics, discover-buffer-metrics)."""
from collections import Counter
from typing import Any, Dict, List

import buffer_client
import config
import history_store


def run_discover_buffer_metrics() -> None:
    """CLI: python prayonit_social.py discover-buffer-metrics

    Introspects Buffer's live GraphQL schema and saves it locally. Does not
    call any metrics query and does not guess field names.
    """
    if not config.BUFFER_API_KEY:
        print("BUFFER_API_KEY is not set; cannot introspect Buffer's schema.")
        return

    print("Querying Buffer GraphQL schema (introspection only, no post data)...")
    try:
        buffer_client.discover_buffer_metrics_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"Schema introspection failed: {exc}")
        return

    print(f"Saved schema introspection to {config.BUFFER_METRICS_SCHEMA_PATH}")
    print(
        "Next step: open that file, locate the Post.metrics field and its "
        "result type, and use only confirmed field names in a metrics query "
        "before enabling live metrics retrieval."
    )


def run_analytics(days: int) -> None:
    """CLI: python prayonit_social.py analytics --days N

    Retrieves metrics for posts that are due (cooldown-respecting) and prints
    a report. If no verified Buffer metrics query has been built yet (see
    discover-buffer-metrics), this safely reports that state instead of
    guessing field names.
    """
    history_store.initialize_database()

    candidates = history_store.get_posts_missing_metrics(
        cooldown_hours=config.METRICS_COOLDOWN_HOURS
    )
    print(f"Posts eligible for metrics refresh (cooldown={config.METRICS_COOLDOWN_HOURS}h): {len(candidates)}")

    verified_query = buffer_client.build_metrics_query_from_schema()

    checked = 0
    updated = 0
    skipped = 0
    failures = 0

    if verified_query is None:
        print(
            "No verified Buffer metrics query is available yet. Run "
            "`python prayonit_social.py discover-buffer-metrics` first, then "
            "confirm the Post.metrics schema before metrics can be retrieved."
        )
        skipped = len(candidates)
    else:
        for row in candidates:
            checked += 1
            buffer_post_id = row["buffer_post_id"]
            try:
                payload = buffer_client.fetch_post_metrics(buffer_post_id, verified_query)
                # Only confirmed fields would be extracted here once the
                # schema has been verified; left intentionally minimal.
                history_store.save_metrics(
                    buffer_post_id=buffer_post_id,
                    platform=row["platform"],
                    metrics={},
                    raw_metrics=payload,
                )
                updated += 1
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED metrics for {buffer_post_id}: {exc}")
                failures += 1

    summary = history_store.export_performance_summary(days=days)

    print("\n--- Analytics report ---")
    print(f"Window: last {days} day(s)")
    print(f"Posts checked: {checked}")
    print(f"Posts updated: {updated}")
    print(f"Posts skipped: {skipped}")
    print(f"Failures: {failures}")
    print(f"Posts scheduled in window: {summary['posts_scheduled']}")
    print(f"Posts failed in window: {summary['posts_failed']}")
    print(f"Metrics observations in window: {summary['metrics_observations']}")
    print(
        "Top campaigns / top platforms / top headlines / morning vs evening "
        "breakdowns will populate once verified metric values are available."
    )
