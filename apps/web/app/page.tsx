"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { api, post, type Task } from "@/lib/api";

const EXAMPLES = [
  "Find 50 fitness creators in Mumbai with 10k+ followers and rank them by engagement",
  "Compare flights Delhi → Goa next Friday under ₹8,000 and hold the best two options",
  "Draft a follow-up email to everyone I met at yesterday's conference",
  "Research the top 5 mid-cap pharma stocks and summarise risks",
];

export default function CommandCenter() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Task[]>("/tasks?limit=100")
      .then(setTasks)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    // Tasks run in the background; refresh status while the page is open.
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!objective.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const task = await post<Task>("/tasks", { objective });
      setObjective("");
      setTasks((prev) => [task, ...(prev ?? [])]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <form className="card command" onSubmit={submit}>
        <label htmlFor="objective">What should your workforce do?</label>
        <textarea
          id="objective"
          rows={3}
          value={objective}
          placeholder={EXAMPLES[0]}
          onChange={(e) => setObjective(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />
        <div className="row">
          <div className="chips">
            {EXAMPLES.slice(1).map((ex) => (
              <button type="button" key={ex} className="chip" onClick={() => setObjective(ex)}>
                {ex.length > 48 ? ex.slice(0, 46) + "…" : ex}
              </button>
            ))}
          </div>
          <button type="submit" disabled={busy || !objective.trim()}>
            {busy ? "Submitting…" : "Give instruction"}
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </form>

      <h2>Tasks</h2>
      {tasks === null ? (
        <p className="muted">Loading…</p>
      ) : tasks.length === 0 ? (
        <p className="muted">No tasks yet. Give your first instruction above.</p>
      ) : (
        <ul className="list">
          {tasks.map((t) => (
            <li key={t.id}>
              <Link href={`/tasks/${t.id}`} className="list-item">
                <div>
                  <strong>{t.title}</strong>
                  <div className="muted small">{new Date(t.created_at).toLocaleString()}</div>
                </div>
                <StatusBadge status={t.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
