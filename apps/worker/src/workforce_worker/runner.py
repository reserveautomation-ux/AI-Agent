"""Background worker: claims tasks, keeps a lease alive, advances them, retries safely.

Run with ``python -m workforce_worker``. Any number of workers can run; Postgres
row locks make sure each task is worked on by one worker at a time. If a worker
dies, its lease expires and another worker resumes the task from its last
checkpoint.
"""

import asyncio
import contextlib
import logging
import os
import signal
import socket
import uuid

import anthropic
from psycopg import AsyncConnection
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from pydantic_settings import BaseSettings, SettingsConfigDict
from workforce_core.db import sync_tool_definitions

from .agent_loop import AgentError
from .browser import BrowserService, DomainPolicy
from .llm import LLM, AnthropicLLM, BudgetExceeded, Refused
from .notify import ExpoPusher, Pusher, notify_task
from .pipeline import TaskStopped, advance, load_task, transition

log = logging.getLogger("workforce_worker")

LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
MAX_ATTEMPTS = 5

CLAIM_SQL = """
update public.tasks t
set lease_owner = %(worker)s,
    lease_expires_at = now() + make_interval(secs => %(lease)s),
    attempts = attempts + 1
where t.id = (
    select t2.id from public.tasks t2
    join public.workspaces w on w.id = t2.workspace_id
    where not w.kill_switch and w.status = 'active'
      and t2.run_after <= now()
      and t2.status in ('draft', 'planned', 'queued', 'running', 'verifying')
      and (t2.lease_expires_at is null or t2.lease_expires_at < now())
    order by t2.priority, t2.created_at
    for update of t2 skip locked
    limit 1
)
returning t.id::text, t.attempts
"""

TRANSIENT = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    TimeoutError,
)


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    worker_concurrency: int = 2
    poll_seconds: float = 2.0
    browser_enabled: bool = True


async def connect(database_url: str) -> AsyncConnection:
    """Autocommit connection that also works through Supabase's transaction pooler."""
    return await AsyncConnection.connect(
        database_url, autocommit=True, row_factory=dict_row, prepare_threshold=None
    )


async def claim(conn: AsyncConnection, worker_id: str) -> tuple[str, int] | None:
    row = await (
        await conn.execute(CLAIM_SQL, {"worker": worker_id, "lease": LEASE_SECONDS})
    ).fetchone()
    return (row["id"], row["attempts"]) if row else None


async def release(
    conn: AsyncConnection, task_id: str, *, delay_s: int = 0, error: str | None = None
):
    await conn.execute(
        """update public.tasks set lease_owner = null, lease_expires_at = null,
               run_after = now() + make_interval(secs => %s),
               last_error = coalesce(%s, last_error)
           where id = %s""",
        (delay_s, error, task_id),
    )


async def _heartbeat(database_url: str, task_id: str, worker_id: str) -> None:
    async with await connect(database_url) as hb:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await hb.execute(
                "update public.tasks set lease_expires_at = now() + make_interval(secs => %s)"
                " where id = %s and lease_owner = %s",
                (LEASE_SECONDS, task_id, worker_id),
            )


async def _stop_task(conn: AsyncConnection, task_id: str, status: str, reason: str) -> None:
    """Move a task to blocked/failed from wherever it is, if that's allowed."""
    task = await load_task(conn, task_id)
    targets = {
        ("blocked", "draft"): ("planned", "blocked"),
        ("blocked", "verifying"): ("failed",),
        ("failed", "queued"): ("running", "failed"),
    }.get((status, task.status), (status,))
    try:
        await transition(
            conn, task, *targets, reason=reason, last_error=reason, result_summary=reason
        )
    except (TaskStopped, pg_errors.CheckViolation):
        log.info("task %s could not move to %s from %s", task_id, status, task.status)


async def process_one(
    conn: AsyncConnection,
    llm: LLM,
    task_id: str,
    attempts: int,
    *,
    worker_id: str,
    database_url: str,
    browser: BrowserService | None = None,
    pusher: Pusher | None = None,
) -> str | None:
    heartbeat = asyncio.create_task(_heartbeat(database_url, task_id, worker_id))
    shutting_down = False
    try:
        return await _process(conn, llm, task_id, attempts, browser)
    except asyncio.CancelledError:
        # The worker is stopping (deploy/restart). Hand the task back now so another
        # worker resumes it from its last checkpoint instead of waiting for the lease.
        shutting_down = True
        with contextlib.suppress(Exception):
            async with await connect(database_url) as fresh:
                await release(fresh, task_id, error="worker restarted; resuming")
        raise
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat
        # Completed, blocked, failed or waiting for approval: tell the owner.
        if not shutting_down:
            with contextlib.suppress(Exception):
                await notify_task(conn, task_id, pusher)


async def _process(
    conn: AsyncConnection,
    llm: LLM,
    task_id: str,
    attempts: int,
    browser: BrowserService | None,
) -> str | None:
    try:
        status = await advance(conn, llm, task_id, browser)
        await release(conn, task_id)
        return status
    except TaskStopped as exc:
        await release(conn, task_id, error=str(exc))
    except BudgetExceeded as exc:
        await _stop_task(conn, task_id, "blocked", f"{exc}. Raise the budget to continue.")
        await release(conn, task_id)
    except Refused as exc:
        await _stop_task(conn, task_id, "failed", f"The AI declined this task: {exc}")
        await release(conn, task_id)
    except (*TRANSIENT, AgentError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if attempts >= MAX_ATTEMPTS:
            await _stop_task(
                conn, task_id, "failed", f"Gave up after {attempts} attempts: {reason}"
            )
            await release(conn, task_id)
        else:
            delay = min(600, 15 * 2 ** (attempts - 1))
            log.warning(
                "task %s attempt %s failed (%s); retrying in %ss", task_id, attempts, reason, delay
            )
            await release(conn, task_id, delay_s=delay, error=reason)
    except Exception as exc:  # unexpected bug: retry a few times, then dead-letter
        log.exception("task %s crashed", task_id)
        reason = f"{type(exc).__name__}: {exc}"
        if attempts >= MAX_ATTEMPTS:
            await _stop_task(conn, task_id, "failed", f"Internal error: {reason}")
            await release(conn, task_id)
        else:
            await release(conn, task_id, delay_s=30 * attempts, error=reason)
    return None


async def worker_loop(
    settings: WorkerSettings,
    llm: LLM,
    browser: BrowserService | None,
    stop: asyncio.Event,
    pusher: Pusher | None = None,
) -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    async with await connect(settings.database_url) as conn:
        while not stop.is_set():
            # Expire unanswered approvals and wake tasks whose approvals are all decided.
            with contextlib.suppress(Exception):
                await conn.execute("select public.expire_approvals()")
            claimed = await claim(conn, worker_id)
            if not claimed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), settings.poll_seconds)
                continue
            task_id, attempts = claimed
            log.info("worker %s took task %s (attempt %s)", worker_id, task_id, attempts)
            status = await process_one(
                conn,
                llm,
                task_id,
                attempts,
                worker_id=worker_id,
                database_url=settings.database_url,
                browser=browser,
                pusher=pusher,
            )
            log.info("task %s -> %s", task_id, status)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = WorkerSettings()  # type: ignore[call-arg]
    async with await connect(settings.database_url) as conn:
        await sync_tool_definitions(conn)
    llm = AnthropicLLM()
    stop = asyncio.Event()
    browser = None
    if settings.browser_enabled:
        browser = BrowserService(DomainPolicy())
        await browser.start()
    workers = [
        asyncio.create_task(worker_loop(settings, llm, browser, stop, ExpoPusher()))
        for _ in range(settings.worker_concurrency)
    ]

    def shutdown() -> None:
        if stop.is_set():
            return
        log.info("shutting down: handing in-progress tasks back")
        stop.set()
        for w in workers:
            w.cancel()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, shutdown)
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    finally:
        if browser:
            await browser.close()
