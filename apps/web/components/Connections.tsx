"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api,
  connectorState,
  joinNames,
  post,
  STATE_BADGE,
  TIMEZONES,
  type Connector,
  type Me,
} from "@/lib/api";

function resultText(name: string, outcome: string): string {
  return (
    {
      connected: `✅ ${name} connected. Anything that was waiting for it carries on by itself.`,
      cancelled: `${name} wasn't connected (you cancelled).`,
      missing_permission: `Please allow every permission ${name} asks for, then try again.`,
    }[outcome] ?? `${name} couldn't be connected. Please try again.`
  );
}

/** The whole catalog: connect what you need, when you need it. */
export function Connections() {
  const [items, setItems] = useState<Connector[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [needed, setNeeded] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Connector[]>("/connectors").then(setItems).catch((e) => setError(e.message));
    api<Me>("/me").then(setMe).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    // ?need=gmail,slack (from a waiting task) · ?connected=x or ?connect=x&status=... (back from sign-in)
    const q = new URLSearchParams(window.location.search);
    const need = q.get("need");
    if (need) setNeeded(need.split(",").filter(Boolean));
    const service = q.get("connected") ?? q.get("connect");
    if (service) {
      setNotice(`${service}|${q.get("connected") ? "connected" : (q.get("status") ?? "error")}`);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [load]);

  const byKey = useMemo(() => new Map((items ?? []).map((c) => [c.key, c])), [items]);
  const categories = useMemo(
    () => ["All", ...new Set((items ?? []).map((c) => c.category))],
    [items],
  );
  const noticeText = notice
    ? resultText(byKey.get(notice.split("|")[0])?.name ?? "The service", notice.split("|")[1])
    : null;

  const q = query.trim().toLowerCase();
  const visible = (items ?? []).filter(
    (c) =>
      (category === "All" || c.category === category) &&
      (!q || `${c.name} ${c.description} ${c.category} ${c.keywords}`.toLowerCase().includes(q)),
  );
  const connected = visible.filter((c) => ["connected", "expired"].includes(connectorState(c)));
  const rest = visible.filter((c) => !connected.includes(c));
  const stillNeeded = needed.filter((k) => connectorState(byKey.get(k) ?? ({} as Connector)) !== "connected");
  const canManage = !me || ["owner", "admin"].includes(me.workspace.role);

  const setTimezone = async (zone: string) => {
    try {
      const ws = await post<Me["workspace"]>("/workspace/timezone", { timezone: zone });
      if (me) setMe({ ...me, workspace: ws });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      {noticeText && <p className="notice">{noticeText}</p>}
      {items && stillNeeded.length > 0 && (
        <div className="card approval">
          <strong>
            A task is waiting for {joinNames(stillNeeded.map((k) => byKey.get(k)?.name ?? k))}.
          </strong>{" "}
          Connect it below and the task continues by itself.
        </div>
      )}

      <div className="row conn-toolbar">
        <input
          type="search"
          placeholder="Search services: WhatsApp, GitHub, cab, food…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search services"
        />
        {me && (
          <label className="check">
            Time zone
            <select
              value={me.workspace.timezone}
              onChange={(e) => setTimezone(e.target.value)}
              aria-label="Time zone"
              disabled={!canManage}
            >
              {!TIMEZONES.some((z) => z.zone === me.workspace.timezone) && (
                <option value={me.workspace.timezone}>{me.workspace.timezone}</option>
              )}
              {TIMEZONES.map((z) => (
                <option key={z.zone} value={z.zone}>
                  {z.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="chips" role="tablist" aria-label="Categories">
        {categories.map((c) => (
          <button
            key={c}
            role="tab"
            aria-selected={category === c}
            className={`chip ${category === c ? "chip-on" : ""}`}
            onClick={() => setCategory(c)}
          >
            {c}
          </button>
        ))}
      </div>
      {error && <p className="error-text">{error}</p>}

      {!items ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {connected.length > 0 && (
            <>
              <h2>Your connections</h2>
              <div className="grid">
                {connected.map((c) => (
                  <ConnectorCard key={c.key} c={c} highlight={needed.includes(c.key)} canManage={canManage} onChange={load} />
                ))}
              </div>
            </>
          )}
          <h2>{connected.length ? "More services" : "Services"}</h2>
          {rest.length === 0 ? (
            <p className="muted">Nothing matches “{query}”.</p>
          ) : (
            <div className="grid">
              {[...rest]
                .sort((a, b) => Number(needed.includes(b.key)) - Number(needed.includes(a.key)))
                .map((c) => (
                  <ConnectorCard key={c.key} c={c} highlight={needed.includes(c.key)} canManage={canManage} onChange={load} />
                ))}
            </div>
          )}
        </>
      )}
    </>
  );
}

function ConnectorCard({
  c,
  highlight,
  canManage,
  onChange,
}: {
  c: Connector;
  highlight: boolean;
  canManage: boolean;
  onChange: () => void;
}) {
  const state = connectorState(c);
  const [label, tone] = STATE_BADGE[state];
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await post<{ auth_url: string }>(`/connections/${c.key}/start`, {
        redirect_to: `${window.location.origin}/connections`,
      });
      window.location.href = auth_url; // the provider's own sign-in page
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const saveKey = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post(`/connections/${c.key}/key`, { fields: values });
      setValues({});
      setOpen(false);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (id: string, name: string | null) => {
    if (!confirm(`Disconnect ${name ?? c.name}? Agents won't be able to use it until you reconnect.`)) return;
    setBusy(true);
    try {
      await post(`/connections/${id}/disconnect`);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const connectable = c.live && c.available && (c.auth === "oauth2" || c.auth === "api_key");
  const connectLabel =
    state === "connected" ? "Add another account" : state === "expired" ? `Reconnect ${c.name}` : `Connect ${c.name}`;

  return (
    <div className={`agent conn ${highlight ? "conn-needed" : ""}`} id={`svc-${c.key}`}>
      <div className="row">
        <strong>
          <span aria-hidden>{c.icon}</span> {c.name}
        </strong>
        <span className="actions">
          {c.plan !== "free" && <span className="badge info">{c.plan === "pro" ? "Pro" : c.plan}</span>}
          <span className={`badge ${tone}`}>{label}</span>
        </span>
      </div>
      <p className="muted small">{c.description}</p>
      {c.note && <p className="small">{c.note}</p>}

      {c.accounts.map((a) => (
        <p key={a.id} className="small" style={{ margin: "4px 0" }}>
          {a.status === "active" ? "🟢" : "🟠"} {a.display_name}
          {a.status !== "active" && " — access expired, please reconnect"}
          {a.last_used_at && <span className="muted"> · last used {new Date(a.last_used_at).toLocaleDateString()}</span>}{" "}
          {canManage && (
            <button className="ghost small" onClick={() => disconnect(a.id, a.display_name)} disabled={busy}>
              Disconnect
            </button>
          )}
        </p>
      ))}

      {c.auth === "deep_link" && c.open_url && (
        <p className="small">
          <a href={c.open_url} target="_blank" rel="noreferrer">
            Open {c.name} →
          </a>
        </p>
      )}
      {state === "unavailable" && (
        <p className="muted small">The server admin needs to switch this on first (see the deployment guide).</p>
      )}

      {connectable && canManage && !open && (
        <div>
          <button
            className={state === "connected" ? "ghost" : ""}
            disabled={busy}
            onClick={() => (c.auth === "oauth2" ? signIn() : setOpen(true))}
          >
            {connectLabel}
          </button>
        </div>
      )}
      {connectable && !canManage && state !== "connected" && (
        <p className="muted small">Ask the workspace owner to connect this.</p>
      )}

      {open && (
        <form className="fields" onSubmit={saveKey}>
          {c.how_to_get && <p className="small pre">{c.how_to_get}</p>}
          {c.fields.map((f) => (
            <label key={f.key} className="small">
              {f.label}
              <input
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                placeholder={f.placeholder}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                required
              />
              {f.help && <span className="muted"> {f.help}</span>}
            </label>
          ))}
          <p className="muted small">
            We check it with {c.name}, then store it encrypted. It is never shown again.
          </p>
          <div className="actions">
            <button type="submit" disabled={busy}>
              {busy ? "Checking…" : "Save and connect"}
            </button>
            <button type="button" className="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <p className="error-text small">{error}</p>}
    </div>
  );
}
