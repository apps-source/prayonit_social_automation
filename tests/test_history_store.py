"""Tests for history_store.py (SQLite initialization, run/post recording)."""
import history_store


def test_initialize_database_creates_tables(isolated_database):
    history_store.initialize_database()
    assert isolated_database.exists()


def test_create_and_update_run_record():
    history_store.initialize_database()
    row_id = history_store.create_run_record(
        run_id="run-1",
        slot="morning",
        campaign_name="Anxiety",
        formula_name="problem_agitate_solution",
        persona_name="general_christian",
        status="dry_run",
    )
    assert row_id > 0

    history_store.update_run_record(row_id, headline="Test Headline", status="published")

    rows = history_store.get_recent_campaign_history(days=1)
    assert len(rows) == 1
    assert rows[0]["headline"] == "Test Headline"
    assert rows[0]["status"] == "published"


def test_save_published_post_and_missing_metrics():
    history_store.initialize_database()
    history_store.save_published_post(
        run_id="run-2",
        scheduled_at_utc="2026-07-10T12:00:00Z",
        platform="facebook",
        post_type="post",
        buffer_post_id="buf-123",
        campaign_name="Anxiety",
        formula_name="problem_agitate_solution",
        persona_name="general_christian",
        slot="morning",
        headline="Headline",
        caption="Caption",
        tracked_url="https://example.com/download?t=abc",
        image_url="https://example.com/image.jpg",
    )

    due = history_store.get_posts_missing_metrics(cooldown_hours=12)
    assert len(due) == 1
    assert due[0]["buffer_post_id"] == "buf-123"


def test_save_post_error_never_marks_scheduled():
    history_store.initialize_database()
    history_store.save_post_error(
        run_id="run-3",
        platform="threads",
        post_type="post",
        campaign_name="Anxiety",
        formula_name=None,
        persona_name=None,
        slot="evening",
        error_message="Buffer rejected the post",
    )
    due = history_store.get_posts_missing_metrics(cooldown_hours=12)
    assert len(due) == 0  # failed posts have no buffer_post_id, so not "due"


def test_save_metrics_respects_cooldown():
    history_store.initialize_database()
    history_store.save_published_post(
        run_id="run-4",
        scheduled_at_utc="2026-07-10T12:00:00Z",
        platform="instagram",
        post_type="post",
        buffer_post_id="buf-456",
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
        buffer_post_id="buf-456",
        platform="instagram",
        metrics={"impressions": 100.0},
        raw_metrics={"impressions": 100},
    )
    # Immediately after saving metrics, it should not be "due" again within cooldown.
    due = history_store.get_posts_missing_metrics(cooldown_hours=12)
    assert len(due) == 0
