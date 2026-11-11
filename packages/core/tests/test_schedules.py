from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from workforce_core.schedules import ScheduleError, describe, next_run, parse_local

IST = "Asia/Kolkata"
NOW = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)  # 11:30 in India


def test_parse_local_time_in_owner_zone():
    when = parse_local("2026-11-11T18:00", IST, NOW)
    assert when.utcoffset().total_seconds() == 5.5 * 3600 and when.hour == 18
    for bad, msg in (
        ("tomorrow", "like 2026"),
        ("2026-11-11T09:00", "already passed"),
        ("2030-01-01T09:00", "too far"),
    ):
        with pytest.raises(ScheduleError, match=msg):
            parse_local(bad, IST, NOW)


def test_next_runs():
    fri = datetime(2026, 11, 13, 9, 0, tzinfo=ZoneInfo(IST))
    assert next_run(fri, "none", IST, "09:00") is None
    assert next_run(fri, "daily", IST, "09:00") == datetime(
        2026, 11, 14, 9, 0, tzinfo=ZoneInfo(IST)
    )
    assert next_run(fri, "weekdays", IST, "09:00") == datetime(
        2026, 11, 16, 9, 0, tzinfo=ZoneInfo(IST)
    )
    assert next_run(fri, "weekly", IST, "09:00").day == 20
    jan31 = datetime(2027, 1, 31, 9, 0, tzinfo=ZoneInfo(IST))
    assert next_run(jan31, "monthly", IST, "09:00").date().isoformat() == "2027-02-28"
    # Daylight saving: stays 09:00 on the wall clock in London.
    lon = "Europe/London"
    before = datetime(2027, 3, 27, 9, 0, tzinfo=ZoneInfo(lon))
    after = next_run(before, "daily", lon, "09:00")
    assert after.hour == 9 and after.utcoffset() != before.utcoffset()


def test_describe():
    when = datetime(2026, 11, 16, 9, 0, tzinfo=ZoneInfo(IST))
    assert describe(when, "none", IST) == "Mon 16 Nov, 09:00"
    assert describe(when, "weekdays", IST) == "every weekday at 09:00, starting Mon 16 Nov, 09:00"
