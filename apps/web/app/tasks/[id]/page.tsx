"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { api, post, type TaskDetail } from "@/lib/api";

const TERMINAL = new Set(["completed", "cancelled", "expired"]);

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<TaskDetail>(`/tasks/${id}`)
      .then(setTask)
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const cancel = async () => {
    const reason = prompt("Why cancel? (optional)") ?? undefined;
    try {
      await post(`/tasks/${id}/cancel`, { reason });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (error && !task) return <p className="error-text">{error}</p>;
  if (!task) return <p className="muted">Loading…</p>;

  return (
    <>
      <p>
        <Link href="/">← All tasks</Link>
      </p>
      <div className="card">
        <div className="row">
          <h1>{task.title}</h1>
          <StatusBadge status={task.status} />
        </div>
        <p className="pre">{task.objective}</p>
        <dl className="meta">
          <dt>Created</dt>
          <dd>{new Date(task.created_at).toLocaleString()}</dd>
          {task.budget_limit_usd && (
            <>
              <dt>Budget</dt>
              <dd>${task.budget_limit_usd}</dd>
            </>
          )}
          {task.completed_at && (
            <>
              <dt>Completed</dt>
              <dd>{new Date(task.completed_at).toLocaleString()}</dd>
            </>
          )}
        </dl>
        {task.result_summary && (
          <>
            <h3>Result</h3>
            <p className="pre">{task.result_summary}</p>
          </>
        )}
        {!TERMINAL.has(task.status) && (
          <button className="ghost" onClick={cancel}>
            Cancel task
          </button>
        )}
        {error && <p className="error-text">{error}</p>}
      </div>

      <h2>Timeline</h2>
      <ol className="timeline">
        {task.events.map((ev) => (
          <li key={ev.id}>
            <StatusBadge status={ev.to_status} />
            <span className="muted small">
              {new Date(ev.created_at).toLocaleString()} · {ev.actor_type}
              {ev.reason ? ` · ${ev.reason}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
