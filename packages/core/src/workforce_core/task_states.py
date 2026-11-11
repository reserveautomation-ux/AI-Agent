"""Task state machine.

The database enforces the same transitions (table ``task_status_transitions``
and trigger ``tasks_status_guard``); a test asserts both definitions match.
Checking here first lets the API return a clean 409 instead of a DB error.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


S = TaskStatus

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    S.DRAFT: frozenset({S.PLANNED, S.FAILED, S.CANCELLED}),
    S.PLANNED: frozenset({S.QUEUED, S.BLOCKED, S.FAILED, S.CANCELLED}),
    S.QUEUED: frozenset({S.RUNNING, S.CANCELLED, S.EXPIRED}),
    S.RUNNING: frozenset(
        {S.WAITING_FOR_TOOL, S.WAITING_FOR_APPROVAL, S.VERIFYING, S.BLOCKED, S.FAILED, S.CANCELLED}
    ),
    S.WAITING_FOR_TOOL: frozenset({S.RUNNING, S.FAILED, S.CANCELLED, S.EXPIRED}),
    S.WAITING_FOR_APPROVAL: frozenset({S.RUNNING, S.FAILED, S.CANCELLED, S.EXPIRED}),
    # A task reaches COMPLETED only through VERIFYING ("definition of done").
    S.VERIFYING: frozenset({S.COMPLETED, S.RUNNING, S.FAILED}),
    S.BLOCKED: frozenset({S.PLANNED, S.QUEUED, S.RUNNING, S.FAILED, S.CANCELLED}),
    S.FAILED: frozenset({S.QUEUED}),  # safe replay from dead-letter
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
    S.EXPIRED: frozenset(),
}

TERMINAL: frozenset[TaskStatus] = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)


def can_transition(current: TaskStatus | str, target: TaskStatus | str) -> bool:
    return TaskStatus(target) in TRANSITIONS[TaskStatus(current)]


def is_terminal(status: TaskStatus | str) -> bool:
    return TaskStatus(status) in TERMINAL
