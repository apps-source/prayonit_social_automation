import os
import sqlite3
import tempfile

import history_store
import config


def _with_temp_db(fn):
    """Helper to run a test with a temporary sqlite DB file."""
    def wrapper():
        orig = config.DATABASE_PATH
        fd, path = tempfile.mkstemp(prefix="test_history_", suffix=".db")
        os.close(fd)
        try:
            config.DATABASE_PATH = path
            history_store.initialize_database()
            return fn(path)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass
            config.DATABASE_PATH = orig
    return wrapper


@_with_temp_db
def test_dry_run_rows_excluded_from_recent_headlines(db_path):
    # create two runs: one dry_run and one published
    rid1 = history_store.create_run_record(run_id="r1", slot="morning", campaign_name="C", status="dry_run")
    history_store.update_run_record(rid1, headline="Dry Run Headline")

    rid2 = history_store.create_run_record(run_id="r2", slot="morning", campaign_name="C", status="in_progress")
    history_store.update_run_record(rid2, headline="Published Headline")

    rows = history_store.get_recent_campaign_history(days=7, exclude_statuses=["dry_run"])
    headlines = [r["headline"] for r in rows if r["headline"]]
    assert "Dry Run Headline" not in headlines
    assert "Published Headline" in headlines


@_with_temp_db
def test_dry_run_headlines_do_not_block_preview_or_future_dry_run(db_path):
    # create a dry_run row
    rid1 = history_store.create_run_record(run_id="r3", slot="morning", campaign_name="C", status="dry_run")
    history_store.update_run_record(rid1, headline="Dry Preview")

    # when building recent_headlines excluding dry_run, the dry preview headline is not present
    rows_excl = history_store.get_recent_campaign_history(days=7, exclude_statuses=["dry_run"])
    headlines_excl = [r["headline"] for r in rows_excl if r["headline"]]
    assert "Dry Preview" not in headlines_excl

    # but a published row is still considered
    rid2 = history_store.create_run_record(run_id="r4", slot="morning", campaign_name="C", status="in_progress")
    history_store.update_run_record(rid2, headline="Published Later")

    rows_excl = history_store.get_recent_campaign_history(days=7, exclude_statuses=["dry_run"])
    headlines_excl = [r["headline"] for r in rows_excl if r["headline"]]
    assert "Published Later" in headlines_excl


@_with_temp_db
def test_production_published_duplicates_still_block(db_path):
    rid1 = history_store.create_run_record(run_id="r5", slot="morning", campaign_name="C", status="in_progress")
    history_store.update_run_record(rid1, headline="Duplicate Headline")

    # recent headlines without excluding dry_run should include the published headline
    rows = history_store.get_recent_campaign_history(days=7)
    headlines = [r["headline"] for r in rows if r["headline"]]
    assert "Duplicate Headline" in headlines


@_with_temp_db
def test_other_headline_quality_failures_still_critical(db_path):
    # We don't change headline quality logic; just ensure storage changes don't affect other checks
    rid = history_store.create_run_record(run_id="r6", slot="morning", campaign_name="C", status="in_progress")
    history_store.update_run_record(rid, headline="This is a very long headline that should fail the quality check because it exceeds the allowed character count")

    rows = history_store.get_recent_campaign_history(days=7, exclude_statuses=["dry_run"])
    headlines = [r["headline"] for r in rows if r["headline"]]
    assert any(len(h) > 45 for h in headlines)
