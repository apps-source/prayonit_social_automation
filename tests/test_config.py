"""Tests for config.py destination-URL validation (safety-critical)."""
import pytest

import config


def test_validate_destination_config_raises_when_tracking_disabled_and_no_destination(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "")
    with pytest.raises(RuntimeError) as exc_info:
        config.validate_destination_config()
    assert "DEFAULT_DESTINATION_URL is required when tracking is disabled." in str(exc_info.value)


def test_validate_destination_config_raises_on_whitespace_only_destination(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "   ")
    with pytest.raises(RuntimeError):
        config.validate_destination_config()


def test_validate_destination_config_passes_when_tracking_disabled_and_destination_present(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", False)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "https://example.com/app")
    config.validate_destination_config()  # should not raise


def test_validate_destination_config_passes_when_tracking_enabled_even_without_destination(monkeypatch):
    monkeypatch.setattr(config, "TRACKING_ENABLED", True)
    monkeypatch.setattr(config, "DEFAULT_DESTINATION_URL", "")
    config.validate_destination_config()  # should not raise; tracking supplies the URL


def test_threads_location_name_defaults_to_empty_string():
    assert isinstance(config.THREADS_LOCATION_NAME, str)


def test_threads_location_id_defaults_to_empty_string():
    assert isinstance(config.THREADS_LOCATION_ID, str)
