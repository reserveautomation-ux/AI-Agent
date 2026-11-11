"use client";

import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { api, post, type Agent, type LifecycleDecision, type Workforce } from "@/lib/api";

function pct(v: number | null | undefined) {
  return v == null ? "–" : `${Math.round(v * 100)}%`;
}

function AgentCard({ agent, onAction }: { agent: Agent; onAction: (a: Agent, op: string) => void }) {
  const ev = agent.latest_evaluation;
  const removable = agent.role !== "chief" && agent.status !== "retired";
  return (
    <div className={`agent ${agent.status}`}>
      <div className="row">
        <strong>{agent.name}</strong>
        <StatusBadge status={agent.status} />
      </div>
      {agent.description && <p className="muted small">{agent.description}</p>}
      {agent.allowed_tools.length > 0 && (
        <div className="tools">
          {agent.allowed_tools.map((t) => (
            <code key={t}>{t}</code>
          ))}
        </div>
      )}
      <div className="muted small">
        {ev
          ? `Success ${pct(ev.success_rate)} · Quality ${pct(ev.quality_score)} · ${ev.sample_size} tasks`
          : "Not evaluated yet"}
        {agent.generation > 1 && ` · generation ${agent.generation}`}
        {agent.status === "sandbox" && " · on trial (gets some work, fully checked)"}
      </div>
      {agent.lessons.length > 0 && (
        <details className="small">
          <summary>Lessons learned ({agent.lessons.length})</summary>
          <ul className="lessons">
            {agent.lessons.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="actions">
        {agent.status === "active" && agent.role !== "chief" && (
          <button className="ghost small" onClick={() => onAction(agent, "clone")}>
            Clone
          </button>
        )}
        {agent.status === "sandbox" && (
          <button className="ghost small" onClick={() => onAction(agent, "promote")}>
            Promote
          </button>
        )}
        {removable && agent.status !== "suspended" && (
          <button className="ghost small" onClick={() => onAction(agent, "suspend")}>
            Suspend
          </button>
        )}
        {removable && (
          <button className="ghost small danger-text" onClick={() => onAction(agent, "retire")}>
            Retire
          </button>
        )}
      </div>
    </div>
  );
}

export default function WorkforcePage() {
  const [wf, setWf] = useState<Workforce | null>(null);
  const [review, setReview] = useState<LifecycleDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Workforce>("/workforce")
      .then(setWf)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onAction = (agent: Agent, op: string) => {
    if (op === "retire" && !confirm(`Retire ${agent.name}? It stops receiving work; history is kept.`))
      return;
    run(() => post(`/agents/${agent.id}/${op}`));
  };

  if (!wf) return error ? <p className="error-text">{error}</p> : <p className="muted">Loading…</p>;

  if (wf.agents.length === 0) {
    return (
      <div className="card center-text">
        <h1>Hire your AI workforce</h1>
        <p className="muted">
          Creates the Chief AI Executive, a QA verifier, and seven departments with their specialist
          agents. Each agent only gets the tools its job needs.
        </p>
        <button disabled={busy} onClick={() => run(() => post("/workforce/bootstrap"))}>
          Hire initial workforce
        </button>
        {error && <p className="error-text">{error}</p>}
      </div>
    );
  }

  const chief = wf.agents
    .filter((a) => a.role === "chief" || a.role === "verifier")
    .sort((a) => (a.role === "chief" ? -1 : 1));
  const active = wf.agents.filter((a) => a.status !== "retired");
  const retired = wf.agents.filter((a) => a.status === "retired");

  return (
    <>
      <div className="row">
        <h1>Workforce</h1>
        <div className="actions">
          <button
            className="ghost"
            disabled={busy}
            onClick={() =>
              run(async () => setReview(await post<LifecycleDecision[]>("/workforce/lifecycle-review")))
            }
          >
            Review performance
          </button>
        </div>
      </div>
      {error && <p className="error-text">{error}</p>}

      <div className="card evolve-card">
        <label className="check">
          <input
            type="checkbox"
            checked={wf.auto_improve}
            disabled={busy}
            onChange={(e) =>
              run(async () =>
                setWf(await post<Workforce>("/workforce/auto-improve", { enabled: e.target.checked })),
              )
            }
          />
          <strong>🧬 Let the workforce improve itself every night</strong>
        </label>
        <p className="muted small">
          Strong agents are cloned, and each clone learns from the checker&apos;s feedback, then proves
          itself on supervised trial work before it&apos;s promoted. Weak agents are paused, then
          retired (their history is kept). A job is never left without an agent, the Chief is never
          changed automatically, and approvals still apply to everything.
          {wf.last_improved_at && ` Last review: ${new Date(wf.last_improved_at).toLocaleString()}.`}
        </p>
      </div>

      {review && (
        <div className="card">
          <h3>Performance review</h3>
          <p className="muted small">
            Strong agents get a sandbox clone that must pass evaluation before taking work. Weak
            agents are suspended, then retired if they stay weak. Nothing is deleted.
          </p>
          <ul className="review">
            {review
              .filter((d) => d.action !== "keep" && d.action !== "insufficient_data")
              .map((d) => (
                <li key={d.agent_id}>
                  <strong>{d.agent_name}</strong>: {d.action} — {d.reason}
                  {d.applied && " ✓"}
                </li>
              ))}
          </ul>
          {review.every((d) => d.action === "keep" || d.action === "insufficient_data") ? (
            <p className="muted">No changes recommended yet (agents need evaluated tasks first).</p>
          ) : (
            <button
              disabled={busy}
              onClick={() =>
                run(async () =>
                  setReview(await post<LifecycleDecision[]>("/workforce/lifecycle-review?apply=true")),
                )
              }
            >
              Apply recommendations
            </button>
          )}
        </div>
      )}

      <section className="grid">
        {chief.map((a) => (
          <AgentCard key={a.id} agent={a} onAction={onAction} />
        ))}
      </section>

      {wf.departments.map((d) => {
        const members = active.filter((a) => a.department_id === d.id);
        return (
          <section key={d.id}>
            <h2>{d.name}</h2>
            <div className="grid">
              {members
                .sort((a, b) => (a.role === "department_head" ? -1 : b.role === "department_head" ? 1 : 0))
                .map((a) => (
                  <AgentCard key={a.id} agent={a} onAction={onAction} />
                ))}
            </div>
          </section>
        );
      })}

      {retired.length > 0 && (
        <details>
          <summary>Retired agents ({retired.length})</summary>
          <div className="grid">
            {retired.map((a) => (
              <AgentCard key={a.id} agent={a} onAction={onAction} />
            ))}
          </div>
        </details>
      )}
    </>
  );
}
