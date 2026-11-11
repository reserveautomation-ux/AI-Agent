from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator
from workforce_core.task_states import TaskStatus


class TaskCreate(BaseModel):
    objective: str = Field(min_length=1, max_length=10_000)
    title: str | None = Field(default=None, max_length=200)
    priority: int = Field(default=2, ge=0, le=4)
    deadline: datetime | None = None
    budget_limit_usd: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)

    @field_validator("objective")
    @classmethod
    def objective_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("objective must not be blank")
        return v

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    def resolved_title(self) -> str:
        if self.title:
            return self.title
        first_line = self.objective.splitlines()[0]
        return first_line if len(first_line) <= 80 else first_line[:77].rstrip() + "..."


class TaskOut(BaseModel):
    id: str
    title: str
    objective: str
    status: TaskStatus
    priority: int
    deadline: datetime | None
    budget_limit_usd: Decimal | None
    result_summary: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskEventOut(BaseModel):
    id: int
    from_status: TaskStatus | None
    to_status: TaskStatus
    actor_type: str
    actor_id: str | None
    reason: str | None
    created_at: datetime


class TaskDetail(TaskOut):
    events: list[TaskEventOut]


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: str
    kill_switch: bool


class MeOut(BaseModel):
    user_id: str
    email: str | None
    workspace: WorkspaceOut


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class AuditEventOut(BaseModel):
    id: int
    actor_type: str
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    event_json: dict[str, Any]
    created_at: datetime
