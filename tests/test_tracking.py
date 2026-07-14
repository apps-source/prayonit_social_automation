"""Tests for tracking.py (tracked ID + URL generation)."""
import config
import history_store
import tracking


def test_tracking_id_is_unique():
    ids = {tracking._generate_tracking_id() for _ in range(50)}
    assert len(ids) == 50


def test_build_tracked_url_format():
    url = tracking.build_tracked_url("abc123")
    assert url.startswith("https://")
    assert "t=abc123" in url


def test_create_tracked_link_returns_tracked_url_when_enabled(isolated_database, monkeypatch):
    history_store.initialize_database()
    monkeypatch.setattr(config, "TRACKING_ENABLED", True)
    url = tracking.create_tracked_link(
        run_id="run-1",
        campaign_name="Anxiety",
        formula_name="problem_agitate_solution",
        persona_name="general_christian",
        platform="facebook",
        post_type="post",
        slot="morning",
        scheduled_at_utc="2026-07-10T12:00:00Z",
    )
    assert "download?t=" in url


def test_create_tracked_link_returns_destination_when_disabled(isolated_database, monkeypatch, capsys):
    history_store.initialize_database()
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "https://example.com/app")
    url = tracking.create_tracked_link(
        run_id="run-2",
        campaign_name="Anxiety",
        formula_name="problem_agitate_solution",
        persona_name="general_christian",
        platform="facebook",
        post_type="post",
        slot="morning",
        scheduled_at_utc="2026-07-10T12:00:00Z",
    )
    assert url == "https://example.com/app"
    assert "download?t=" not in url
    captured = capsys.readouterr()
    assert "Tracking disabled" in captured.out


def test_create_tracked_link_always_persists_tracking_id_even_when_disabled(isolated_database, monkeypatch):
    history_store.initialize_database()
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "https://example.com/app")
    tracking.create_tracked_link(
        run_id="run-3",
        campaign_name="Anxiety",
        formula_name=None,
        persona_name=None,
        platform="instagram",
        post_type="post",
        slot="evening",
        scheduled_at_utc="2026-07-10T23:00:00Z",
    )
    summary = history_store.export_performance_summary(days=365)
    assert summary is not None

