"""Shared pytest fixtures. Ensures tests never touch the real database file
or make live network calls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import config


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Point config.DATABASE_PATH at a throwaway file for every test."""
    test_db_path = tmp_path / "test_prayonit_marketing.db"
    monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)
    yield test_db_path
