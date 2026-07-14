"""Tests for analytics.py: cooldown behavior with mocked Buffer calls."""
from unittest.mock import patch

import analytics
import history_store


def test_run_analytics_reports_no_verified_schema(isolated_database, capsys):
    history_store.initialize_database()
    with patch("buffer_client.build_metrics_query_from_schema", return_value=None):
        analytics.run_analytics(days=7)
    captured = capsys.readouterr()
    assert "No verified Buffer metrics query" in captured.out


def test_cooldown_excludes_recently_checked_posts(isolated_database):
    history_store.initialize_database()
    history_store.save_published_post(
        run_id="run-1",
        scheduled_at_utc="2026-07-10T13:00:00Z",
        platform="facebook",
        post_type="post",
        buffer_post_id="buf-cooldown",
        campaign_name="Anxiety",
        formula_name=None,
        persona_name=None,
        slot="morning",
        headline="H",
        caption="C",
        tracked_url=None,
        image_url=None,
    )
    history_store.save_metrics(
        buffer_post_id="buf-cooldown",
        platform="facebook",
        metrics={"impressions": 10.0},
        raw_metrics={"impressions": 10},
    )
    due_immediately = history_store.get_posts_missing_metrics(cooldown_hours=12)
    assert len(due_immediately) == 0

    due_with_zero_cooldown = history_store.get_posts_missing_metrics(cooldown_hours=0)
    # Even with 0-hour cooldown, "just measured" should not be strictly before cutoff=now.
    assert len(due_with_zero_cooldown) == 0
