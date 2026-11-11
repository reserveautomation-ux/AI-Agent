"use client";

import { useCallback, useEffect, useState } from "react";
import { api, post, REPEAT_LABEL, type Schedule } from "@/lib/api";

/** Reminders and repeating jobs set from chat, with a way to cancel them. */
export function Schedules() {
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Schedule[]>("/schedules")
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const cancel = async (s: Schedule) => {
    if (!confirm(`Cancel "${s.title}"?`)) return;
    try {
      await post(`/schedules/${s.id}/cancel`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const [briefAt, setBriefAt] = useState("07:30");
  const [briefBusy, setBriefBusy] = useState(false);
  const setBriefing = async () => {
    setBriefBusy(true);
    setError(null);
    try {
      await post("/schedules/briefing", { time: briefAt });
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBriefBusy(false);
    }
  };

  const active = (items ?? []).filter((s) => s.active);
  const briefing = active.find(
    (s) => s.kind === "task" && s.title === "Morning briefing",
  );
  return (
    <section id="schedules">
      <h2>Reminders &amp; repeating jobs</h2>
      <div className="briefing-box">
        <span>
          ☀️ <strong>Morning briefing</strong>
          <span className="muted small">
            {" "}
            · calendar, important mail, weather, news and today&apos;s
            reminders, every day
          </span>
        </span>
        <input
          type="time"
          value={briefAt}
          onChange={(e) => setBriefAt(e.target.value)}
          aria-label="Briefing time"
        />
        <button
          className="ghost small"
          onClick={setBriefing}
          disabled={briefBusy || !briefAt}
        >
          {briefing ? "Change time" : "Turn on"}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {!items ? (
        <p className="muted">Loading…</p>
      ) : active.length === 0 ? (
        <p className="muted">
          None yet. Ask in chat: “remind me at 6pm to call mom” or “every Monday
          at 9 send me a summary of my unread email”.
        </p>
      ) : (
        <ul className="list">
          {active.map((s) => (
            <li key={s.id} className="list-item row">
              <div>
                <strong>
                  {s.kind === "reminder" ? "⏰ " : "🔁 "}
                  {s.title}
                </strong>
                <p className="muted small" style={{ margin: "4px 0 0" }}>
                  {s.kind === "reminder"
                    ? "Reminder"
                    : "Job for your workforce"}{" "}
                  · {REPEAT_LABEL[s.repeat]}
                  {s.next_run_at &&
                    ` · next ${new Date(s.next_run_at).toLocaleString([], {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                      timeZone: s.timezone,
                    })}`}
                  {s.runs > 0 && ` · ran ${s.runs}×`}
                </p>
              </div>
              <button className="ghost small" onClick={() => cancel(s)}>
                Cancel
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
