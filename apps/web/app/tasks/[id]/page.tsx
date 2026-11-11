"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { ApprovalCard } from "@/components/ApprovalCard";
import {
  api,
  downloadArtifact,
  joinNames,
  post,
  serviceName,
  type ApprovalItem,
  type Artifact,
  type TaskDetail,
} from "@/lib/api";

const TERMINAL = new Set(["completed", "cancelled", "expired"]);
const WORKING = new Set(["draft", "planned", "queued", "running", "verifying"]);


function CsvPreview({ text }: { text: string }) {
  const rows = text
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(0, 8)
    .map((line) => line.split(","));
  if (rows.length < 2) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {rows[0].map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(1).map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FileCard({ a, onError }: { a: Artifact; onError: (m: string) => void }) {
  return (
    <div className="agent">
      <div className="row">
        <strong>📄 {a.name}</strong>
        <button
          className="ghost small"
          onClick={() => downloadArtifact(a).catch((e) => onError(e.message))}
        >
          Download
        </button>
      </div>
      <span className="muted small">{(a.size_bytes / 1024).toFixed(1)} KB</span>
      {a.file_type === "text/csv" && a.preview ? (
        <CsvPreview text={a.preview} />
      ) : (
        a.preview && <pre className="preview">{a.preview.slice(0, 600)}</pre>
      )}
    </div>
  );
}

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);

  const load = useCallback(() => {
    Promise.all([
      api<TaskDetail>(`/tasks/${id}`),
      api<ApprovalItem[]>(`/approvals?state=all&task_id=${id}`),
    ])
      .then(([t, a]) => {
        setTask(t);
        setApprovals(a);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setAnswer("");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    const reason = prompt("Why cancel? (optional)") ?? undefined;
    act(() => post(`/tasks/${id}/cancel`, { reason }));
  };

  const retry = (e: FormEvent) => {
    e.preventDefault();
    act(() => post(`/tasks/${id}/retry`, answer.trim() ? { answer } : {}));
  };

  if (error && !task) return <p className="error-text">{error}</p>;
  if (!task) return <p className="muted">Loading…</p>;

  const pending = approvals.filter((a) => a.status === "pending");
  const waitingFor = task.status === "blocked" ? (task.waiting_for_connection ?? []) : [];
  const asking = task.status === "blocked" && task.steps.length === 0 && waitingFor.length === 0;

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
        <p className="pre muted">{task.objective}</p>
        {WORKING.has(task.status) && (
          <p className="working">
            <span className="dot" /> Your workforce is on it. You can close this page; work
            continues in the background.
          </p>
        )}
        {task.result_summary && waitingFor.length === 0 && (
          <div className={`result ${task.status}`}>
            <p className="pre">{task.result_summary}</p>
          </div>
        )}

        {waitingFor.length > 0 && (
          <div className="wait-card">
            <strong>Waiting for you to connect {joinNames(waitingFor.map(serviceName))}</strong>
            <span className="muted small">
              Once it&apos;s connected, this task carries on by itself. Nothing else is needed.
            </span>
            <div>
              <Link className="button" href={`/connections?need=${waitingFor.join(",")}`}>
                Connect {joinNames(waitingFor.map(serviceName))}
              </Link>
            </div>
          </div>
        )}

        {((task.status === "blocked" && waitingFor.length === 0) || task.status === "failed") && (
          <form className="command" onSubmit={retry}>
            <label htmlFor="answer">{asking ? "Answer the Chief's question" : "Add guidance (optional) and retry"}</label>
            <textarea
              id="answer"
              rows={2}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder={asking ? "Type your answer" : "Anything to change before retrying?"}
            />
            <div>
              <button type="submit" disabled={busy || (asking && !answer.trim())}>
                {asking ? "Answer and continue" : "Retry"}
              </button>
            </div>
          </form>
        )}

        <dl className="meta">
          <dt>Created</dt>
          <dd>{new Date(task.created_at).toLocaleString()}</dd>
          <dt>Cost so far</dt>
          <dd>${Number(task.cost_usd).toFixed(3)}{task.budget_limit_usd && ` of $${task.budget_limit_usd}`}</dd>
          {task.completed_at && (
            <>
              <dt>Completed</dt>
              <dd>{new Date(task.completed_at).toLocaleString()}</dd>
            </>
          )}
        </dl>
        {!TERMINAL.has(task.status) && (
          <button className="ghost" onClick={cancel} disabled={busy}>
            Cancel task
          </button>
        )}
        {error && <p className="error-text">{error}</p>}
      </div>

      {approvals.length > 0 && (
        <>
          <h2>{pending.length > 0 ? "Waiting for your approval" : "Approvals"}</h2>
          <div className="grid">
            {approvals.map((a) => (
              <ApprovalCard
                key={a.id}
                item={a}
                showTask={false}
                onDecided={(u) => {
                  setApprovals((list) => list.map((x) => (x.id === u.id ? u : x)));
                  load();
                }}
              />
            ))}
          </div>
        </>
      )}

      {task.artifacts.length > 0 && (
        <>
          <h2>Files</h2>
          <div className="grid">
            {task.artifacts.map((a) => (
              <FileCard key={a.id} a={a} onError={setError} />
            ))}
          </div>
        </>
      )}

      {task.plan?.understanding && (
        <>
          <h2>Plan</h2>
          <div className="card">
            <p>{task.plan.understanding}</p>
            {task.plan.assumptions && task.plan.assumptions.length > 0 && (
              <p className="muted small">Assumptions: {task.plan.assumptions.join("; ")}</p>
            )}
            <ol className="steps">
              {task.steps.map((s) => (
                <li key={s.sequence}>
                  <div className="row">
                    <strong>{s.title}</strong>
                    <StatusBadge status={s.status === "succeeded" ? "completed" : s.status} />
                  </div>
                  <div className="muted small">{s.agent_name ?? "Unassigned"}</div>
                  {s.summary && <p>{s.summary}</p>}
                  {s.result && s.result !== s.summary && (
                    <details>
                      <summary>Full output</summary>
                      <pre className="preview">{s.result}</pre>
                    </details>
                  )}
                  {s.limitations.length > 0 && (
                    <p className="small warn-text">Couldn&apos;t do: {s.limitations.join("; ")}</p>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </>
      )}

      {task.verification?.criteria && task.verification.criteria.length > 0 && (
        <>
          <h2>Quality check</h2>
          <ul className="review">
            {task.verification.criteria.map((c, i) => (
              <li key={i}>
                {c.met ? "✅" : "❌"} {c.criterion}
                {c.note && <span className="muted small"> — {c.note}</span>}
              </li>
            ))}
          </ul>
        </>
      )}

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
