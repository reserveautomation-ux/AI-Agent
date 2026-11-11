"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Memory } from "@/lib/api";

const TYPES: { value: Memory["memory_type"]; label: string; hint: string }[] = [
  { value: "preference", label: "Preference", hint: "I prefer aisle seats" },
  { value: "fact", label: "Fact", hint: "My office is in Andheri East" },
  { value: "contact", label: "Contact", hint: "Rahul (designer) — rahul@example.com" },
  {
    value: "instruction",
    label: "Standing instruction",
    hint: "Never book flights before 8am",
  },
];

function MemoryItem({
  m,
  onChange,
}: {
  m: Memory;
  onChange: (fn: () => Promise<unknown>) => void;
}) {
  return (
    <li className="memory">
      <div className="memory-body">
        <p>{m.content}</p>
        <div className="muted small">
          {m.memory_type === "instruction" ? "Standing instruction" : m.memory_type}
          {m.agent_name ? ` · ${m.agent_name}` : ""}
          {m.use_count > 0 ? ` · used ${m.use_count}×` : ""}
          {!m.trusted && " · unverified"}
        </div>
      </div>
      <div className="actions">
        {!m.trusted && (
          <button className="ghost small" onClick={() => onChange(() => api(`/memories/${m.id}/confirm`, { method: "POST" }))}>
            Confirm
          </button>
        )}
        <button
          className="ghost small"
          title={m.pinned ? "Unpin" : "Pin: agents always see pinned memories"}
          onClick={() =>
            onChange(() =>
              api(`/memories/${m.id}/pin`, { method: "POST", body: JSON.stringify({ pinned: !m.pinned }) }),
            )
          }
        >
          {m.pinned ? "★ Pinned" : "☆ Pin"}
        </button>
        <button className="ghost small danger-text" onClick={() => onChange(() => api(`/memories/${m.id}`, { method: "DELETE" }))}>
          Forget
        </button>
      </div>
    </li>
  );
}

export default function MemoryPage() {
  const [items, setItems] = useState<Memory[] | null>(null);
  const [q, setQ] = useState("");
  const [content, setContent] = useState("");
  const [type, setType] = useState<Memory["memory_type"]>("preference");
  const [pinned, setPinned] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((query: string) => {
    const path = query.trim() ? `/memories?q=${encodeURIComponent(query)}` : "/memories";
    api<Memory[]>(path)
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(q), 250);
    return () => clearTimeout(t);
  }, [q, load]);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      load(q);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    await run(async () => {
      await api("/memories", {
        method: "POST",
        body: JSON.stringify({ content, memory_type: type, pinned }),
      });
      setContent("");
      setPinned(false);
    });
    setBusy(false);
  };

  const yours = items?.filter((m) => m.owner_scope === "workspace" && m.trusted) ?? [];
  const noted = items?.filter((m) => m.owner_scope === "workspace" && !m.trusted) ?? [];
  const learned = items?.filter((m) => m.owner_scope === "agent") ?? [];

  return (
    <>
      <h1>Memory</h1>
      <p className="muted">
        What your workforce remembers. Agents use this to personalise every task. Passwords, OTPs,
        card and Aadhaar numbers are never stored.
      </p>

      <form className="card command" onSubmit={add}>
        <label htmlFor="memory">Teach it something</label>
        <textarea
          id="memory"
          rows={2}
          value={content}
          placeholder={TYPES.find((t) => t.value === type)?.hint}
          onChange={(e) => setContent(e.target.value)}
        />
        <div className="row">
          <div className="voice-options">
            <select value={type} onChange={(e) => setType(e.target.value as Memory["memory_type"])} aria-label="Memory type">
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <label className="check">
              <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
              Always use (pin)
            </label>
          </div>
          <button type="submit" disabled={busy || !content.trim()}>
            Remember
          </button>
        </div>
      </form>

      <input
        type="search"
        placeholder="Search memories…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        aria-label="Search memories"
      />
      {error && <p className="error-text">{error}</p>}

      {items === null ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="muted">{q ? "Nothing matches." : "Nothing remembered yet."}</p>
      ) : (
        <>
          {yours.length > 0 && (
            <>
              <h2>About you</h2>
              <ul className="memory-list">
                {yours.map((m) => (
                  <MemoryItem key={m.id} m={m} onChange={run} />
                ))}
              </ul>
            </>
          )}
          {noted.length > 0 && (
            <>
              <h2>Noted by agents</h2>
              <p className="muted small">
                Agents picked these up while working. Confirm the ones that are right; unconfirmed
                notes are never treated as instructions.
              </p>
              <ul className="memory-list">
                {noted.map((m) => (
                  <MemoryItem key={m.id} m={m} onChange={run} />
                ))}
              </ul>
            </>
          )}
          {learned.length > 0 && (
            <>
              <h2>Agents&apos; own learnings</h2>
              <p className="muted small">Each agent&apos;s private notes on how to do its job better.</p>
              <ul className="memory-list">
                {learned.map((m) => (
                  <MemoryItem key={m.id} m={m} onChange={run} />
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </>
  );
}
