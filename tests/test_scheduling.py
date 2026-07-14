"""Tests for morning/evening slot -> UTC datetime conversion."""
from datetime import datetime, timezone

import prayonit_social as ps


def test_morning_slot_before_8am_same_day():
    # 2026-07-09 06:00 Eastern (10:00 UTC) -> next occurrence should be 08:00 Eastern same day.
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    result = ps.next_slot_datetime_utc("morning", now=now)
    eastern = result.astimezone(ps.config.EASTERN_TZ)
    assert eastern.hour == 8
    assert eastern.date() == datetime(2026, 7, 9).date()


def test_morning_slot_after_8am_rolls_to_next_day():
    now = datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc)  # 4pm Eastern
    result = ps.next_slot_datetime_utc("morning", now=now)
    eastern = result.astimezone(ps.config.EASTERN_TZ)
    assert eastern.hour == 8
    assert eastern.date() == datetime(2026, 7, 10).date()


def test_evening_slot_time():
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    result = ps.next_slot_datetime_utc("evening", now=now)
    eastern = result.astimezone(ps.config.EASTERN_TZ)
    assert eastern.hour == 19
    assert eastern.date() == datetime(2026, 7, 9).date()


def test_to_iso8601_utc_format():
    dt = datetime(2026, 7, 10, 13, 8, 0, tzinfo=timezone.utc)
    assert ps.to_iso8601_utc(dt) == "2026-07-10T13:08:00Z"


def test_dst_boundary_does_not_crash():
    # Around US DST spring-forward (second Sunday of March).
    now = datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc)
    result = ps.next_slot_datetime_utc("morning", now=now)
    eastern = result.astimezone(ps.config.EASTERN_TZ)
    assert eastern.hour == 8
