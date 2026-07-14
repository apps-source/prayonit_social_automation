"""Tests for Buffer success/failure recording in history_store, and TEST_MODE
never falsely marking a post as scheduled."""
import history_store


def test_save_published_post_marks_scheduled(isolated_database):
    history_store.initialize_database()
    row_id = history_store.save_published_post(
        run_id="run-x",
        scheduled_at_utc="2026-07-10T13:00:00Z",
        platform="facebook",
        post_type="post",
        buffer_post_id="buf-1",
        campaign_name="Anxiety",
        formula_name="problem_agitate_solution",
        persona_name="general_christian",
        slot="morning",
        headline="H",
        caption="C",
        tracked_url="https://x/download?t=1",
        image_url="https://x/img.jpg",
    )
    rows = history_store.get_posts_missing_metrics(cooldown_hours=0)
    assert any(r["id"] == row_id and r["buffer_status"] == "scheduled" for r in rows)


def test_save_post_error_marks_failed_not_scheduled(isolated_database):
    history_store.initialize_database()
    history_store.save_post_error(
        run_id="run-y",
        platform="instagram",
        post_type="story",
        campaign_name="Anxiety",
        formula_name=None,
        persona_name=None,
        slot="evening",
        error_message="channel not found",
    )
    rows = history_store.get_posts_missing_metrics(cooldown_hours=0)
    assert all(r["buffer_post_id"] != None for r in rows)  # noqa: E711 - explicit None check
    assert len(rows) == 0


def test_dry_run_status_is_never_published(isolated_database):
    history_store.initialize_database()
    row_id = history_store.create_run_record(
        run_id="run-z",
        slot="morning",
        campaign_name="Anxiety",
        status="dry_run",
    )
    rows = history_store.get_recent_campaign_history(days=1)
    match = [r for r in rows if r["id"] == row_id][0]
    assert match["status"] == "dry_run"
    assert match["status"] != "published"
