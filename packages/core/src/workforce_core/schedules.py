"""Reminders and repeating jobs: parsing times, working out the next run, saving them.

Times are the owner's wall-clock time in their time zone, so "every day at 9:00" stays
at 9:00 across daylight-saving changes.
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection

REPEATS = ("none", "daily", "weekdays", "weekly", "monthly")
REPEAT_TEXT = {
    "none": "",
    "daily": "every day",
    "weekdays": "every weekday",
    "weekly": "every week",
    "monthly": "every month",
}


class ScheduleError(ValueError):
    pass


def parse_local(at: str, tz: str, now: datetime | None = None) -> datetime:
    """'2026-11-20T16:00' (or '...16:00:00') in the owner's zone -> aware datetime."""
    try:
        naive = datetime.fromisoformat(at.strip().replace(" ", "T"))
    except ValueError as exc:
        raise ScheduleError("give the time like 2026-11-20T16:00") from exc
    zone = ZoneInfo(tz)
    when = naive.replace(tzinfo=zone) if naive.tzinfo is None else naive.astimezone(zone)
    now = now or datetime.now(UTC)
    if when <= now - timedelta(minutes=1):
        raise ScheduleError("that time has already passed")
    if when > now + timedelta(days=366 * 2):
        raise ScheduleError("that is too far ahead (max 2 years)")
    return when


def next_run(previous: datetime, repeat: str, tz: str, local_time: str) -> datetime | None:
    """The next time after `previous` for a repeating schedule (None for one-off)."""
    if repeat == "none":
        return None
    zone = ZoneInfo(tz)
    prev = previous.astimezone(zone)
    hh, mm = (int(x) for x in local_time.split(":"))
    if repeat == "monthly":
        year, month = (prev.year + 1, 1) if prev.month == 12 else (prev.year, prev.month + 1)
        day = min(prev.day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day, hh, mm, tzinfo=zone)
    step = 7 if repeat == "weekly" else 1
    nxt = prev.date() + timedelta(days=step)
    if repeat == "weekdays":
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, hh, mm, tzinfo=zone)


def describe(when: datetime, repeat: str, tz: str) -> str:
    local = when.astimezone(ZoneInfo(tz))
    first = f"{local:%a %d %b, %H:%M}"
    return (
        f"{REPEAT_TEXT[repeat]} at {local:%H:%M}, starting {first}" if repeat != "none" else first
    )


@dataclass
class Scheduled:
    id: str
    title: str
    kind: str
    repeat: str
    next_run_at: datetime
    text: str  # human description of when


async def create_schedule(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str,
    kind: str,
    what: str,
    at: str,
    repeat: str = "none",
    title: str | None = None,
    conversation_id: str | None = None,
) -> Scheduled:
    if kind not in ("reminder", "task"):
        raise ScheduleError("kind must be 'reminder' or 'task'")
    if repeat not in REPEATS:
        raise ScheduleError(f"repeat must be one of {', '.join(REPEATS)}")
    what = " ".join((what or "").split()) if kind == "reminder" else (what or "").strip()
    if not what:
        raise ScheduleError("say what the reminder or job is")
    tz_row = await (
        await conn.execute("select timezone from public.workspaces where id = %s", (workspace_id,))
    ).fetchone()
    tz = (tz_row["timezone"] if isinstance(tz_row, dict) else tz_row[0]) or "Asia/Kolkata"
    when = parse_local(at, tz)
    active = await (
        await conn.execute(
            "select count(*) as n from public.schedules where user_id = %s and active",
            (user_id,),
        )
    ).fetchone()
    if (active["n"] if isinstance(active, dict) else active[0]) >= 100:
        raise ScheduleError("you already have 100 active reminders and jobs; cancel some first")
    title = (title or what.splitlines()[0])[:80]
    row = await (
        await conn.execute(
            """insert into public.schedules
                   (workspace_id, user_id, conversation_id, kind, title, what, repeat, timezone,
                    local_time, next_run_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id::text""",
            (
                workspace_id,
                user_id,
                conversation_id,
                kind,
                title,
                what[:4000],
                repeat,
                tz,
                f"{when.astimezone(ZoneInfo(tz)):%H:%M}",
                when,
            ),
        )
    ).fetchone()
    sid = row["id"] if isinstance(row, dict) else row[0]
    return Scheduled(sid, title, kind, repeat, when, describe(when, repeat, tz))
