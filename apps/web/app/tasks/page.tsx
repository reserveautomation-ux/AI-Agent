"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Schedules } from "@/components/Schedules";
import { StatusBadge } from "@/components/StatusBadge";
import { api, post, type Capability, type Task } from "@/lib/api";
import { useSpeech, VOICE_LANGUAGES } from "@/lib/useSpeech";

const HANDLING: Record<Capability["handling"], [string, string]> = {
  automatic: ["Does it for you", "ok"],
  asks_approval: ["Asks before sending", "info"],
  owner_approval: ["Needs your approval", "warn"],
  you_confirm_in_app: ["You confirm in app", "muted"],
};

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

export default function CommandCenter() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [objective, setObjective] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState("en-IN");
  const [autoSend, setAutoSend] = useState(false);
  const baseRef = useRef("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setLang(load("voice.lang", "en-IN"));
    setAutoSend(load("voice.autoSend", false));
  }, []);

  const refresh = useCallback(() => {
    api<Task[]>("/tasks?limit=100")
      .then(setTasks)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    refresh();
    api<Capability[]>("/capabilities").then(setCapabilities).catch(() => {});
    // Tasks run in the background; refresh status while the page is open.
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await post<Task>("/tasks", { objective: text });
      setObjective("");
      setTasks((prev) => [task, ...(prev ?? [])]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const voice = useSpeech({
    lang,
    onTranscript: (spoken) => setObjective(baseRef.current + spoken),
    onDone: (spoken) => {
      if (autoSend && spoken) send(baseRef.current + spoken);
    },
  });

  const toggleVoice = () => {
    if (voice.listening) {
      voice.stop();
      return;
    }
    baseRef.current = objective.trim() ? objective.trim() + " " : "";
    voice.start();
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (voice.listening) voice.stop();
    send(objective);
  };

  const pickExample = (text: string) => {
    setObjective(text);
    inputRef.current?.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const areas = [...new Set(capabilities.map((c) => c.area))];

  return (
    <>
      <form className="card command" onSubmit={submit}>
        <label htmlFor="objective">What should your workforce do?</label>
        <div className={`input-wrap ${voice.listening ? "listening" : ""}`}>
          <textarea
            id="objective"
            ref={inputRef}
            rows={3}
            value={objective}
            placeholder={
              voice.listening
                ? "Listening… speak your instruction"
                : "Type here, or tap the mic and speak"
            }
            onChange={(e) => setObjective(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
            }}
          />
          <button
            type="button"
            className={`mic ${voice.listening ? "on" : ""}`}
            onClick={toggleVoice}
            disabled={!voice.supported}
            aria-pressed={voice.listening}
            aria-label={voice.listening ? "Stop listening" : "Speak your instruction"}
            title={
              voice.supported
                ? voice.listening
                  ? "Stop listening"
                  : "Speak your instruction"
                : "Voice input isn't supported in this browser. Try Chrome, Edge or Safari."
            }
          >
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
              <path
                fill="currentColor"
                d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z"
              />
            </svg>
          </button>
        </div>

        <div className="row">
          <div className="voice-options">
            <select
              aria-label="Voice language"
              value={lang}
              onChange={(e) => {
                setLang(e.target.value);
                save("voice.lang", e.target.value);
              }}
            >
              {VOICE_LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
            <label className="check">
              <input
                type="checkbox"
                checked={autoSend}
                onChange={(e) => {
                  setAutoSend(e.target.checked);
                  save("voice.autoSend", e.target.checked);
                }}
              />
              Send when I stop talking
            </label>
          </div>
          <button type="submit" disabled={busy || !objective.trim()}>
            {busy ? "Sending…" : "Give instruction"}
          </button>
        </div>
        {voice.listening && <p className="muted small">🎙 Listening… tap the mic again to stop.</p>}
        {voice.error && <p className="error-text">{voice.error}</p>}
        {error && <p className="error-text">{error}</p>}
      </form>

      <Schedules />

      <h2>Tasks</h2>
      {tasks === null ? (
        <p className="muted">Loading…</p>
      ) : tasks.length === 0 ? (
        <p className="muted">No tasks yet. Type or speak your first instruction above.</p>
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

      {areas.length > 0 && (
        <>
          <h2>What your workforce can do</h2>
          <p className="muted small">Tap any example to use it. These are only examples: ask for anything.</p>
          {areas.map((area) => (
            <section key={area} className="cap-area">
              <h3>{area}</h3>
              <div className="cap-grid">
                {capabilities
                  .filter((c) => c.area === area)
                  .map((c) => {
                    const [label, tone] = HANDLING[c.handling];
                    return (
                      <button
                        type="button"
                        key={c.key}
                        className="cap"
                        onClick={() => pickExample(c.example)}
                      >
                        <span className="cap-title">{c.title}</span>
                        <span className="cap-example">“{c.example}”</span>
                        <span className={`badge ${tone}`}>{label}</span>
                      </button>
                    );
                  })}
              </div>
            </section>
          ))}
        </>
      )}
    </>
  );
}
