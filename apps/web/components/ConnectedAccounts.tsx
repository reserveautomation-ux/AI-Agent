"use client";

import { useCallback, useEffect, useState } from "react";
import { api, post, TIMEZONES, type Me, type ProviderConnections } from "@/lib/api";

const ICON: Record<string, string> = { gmail: "✉️", google_calendar: "📅" };

function resultText(name: string, outcome: string): string {
  return (
    {
      connected: `✅ ${name} connected.`,
      cancelled: `${name} wasn't connected (you cancelled).`,
      missing_permission: `Please allow every permission ${name} asks for on Google's screen, then try again.`,
    }[outcome] ?? `${name} couldn't be connected. Please try again.`
  );
}

export function ConnectedAccounts() {
  const [providers, setProviders] = useState<ProviderConnections[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<ProviderConnections[]>("/connections").then(setProviders).catch((e) => setError(e.message));
    api<Me>("/me").then(setMe).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    // Coming back from Google: ?connected=<service> or ?connect=<service>&status=...
    const q = new URLSearchParams(window.location.search);
    const service = q.get("connected") ?? q.get("connect");
    if (service) {
      const name = service === "google_calendar" ? "Google Calendar" : "Gmail";
      setNotice(resultText(name, q.get("connected") ? "connected" : q.get("status") ?? "error"));
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [load]);

  const connect = async (provider: string) => {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await post<{ auth_url: string }>(`/connections/${provider}/start`, {
        redirect_to: `${window.location.origin}/integrations`,
      });
      window.location.href = auth_url; // Google's own sign-in page
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const disconnect = async (id: string, name: string | null) => {
    if (!confirm(`Disconnect ${name ?? "this account"}? Agents won't be able to use it until you reconnect.`)) return;
    setBusy(true);
    try {
      await post(`/connections/${id}/disconnect`);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const setTimezone = async (zone: string) => {
    try {
      const ws = await post<Me["workspace"]>("/workspace/timezone", { timezone: zone });
      if (me) setMe({ ...me, workspace: ws });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>Connected accounts</h2>
        {me && (
          <label className="check">
            Time zone
            <select
              value={me.workspace.timezone}
              onChange={(e) => setTimezone(e.target.value)}
              aria-label="Time zone"
              disabled={!["owner", "admin"].includes(me.workspace.role)}
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
      {notice && <p className="notice">{notice}</p>}
      {!providers ? (
        <p className="muted">Loading…</p>
      ) : (
        providers.map((p) => {
          const active = p.accounts.some((a) => a.status === "active");
          return (
            <div key={p.provider} className="row connected service">
              <div>
                <strong>
                  {ICON[p.provider] ?? "🔗"} {p.name}
                </strong>
                <p className="muted small" style={{ margin: "4px 0 0" }}>
                  {p.description}
                </p>
                {p.accounts.map((a) => (
                  <p key={a.id} className="small" style={{ margin: "8px 0 0" }}>
                    {a.status === "active" ? "🟢" : "🟠"} {a.display_name}
                    {a.status !== "active" && " — access expired, please reconnect"}
                    {a.last_used_at && (
                      <span className="muted"> · last used {new Date(a.last_used_at).toLocaleString()}</span>
                    )}{" "}
                    <button className="ghost small" onClick={() => disconnect(a.id, a.display_name)} disabled={busy}>
                      Disconnect
                    </button>
                  </p>
                ))}
              </div>
              {p.configured ? (
                <button className={active ? "ghost" : ""} onClick={() => connect(p.provider)} disabled={busy}>
                  {active ? "Reconnect" : `Connect ${p.name}`}
                </button>
              ) : (
                <span className="muted small">Not set up on the server yet (see the deployment guide).</span>
              )}
            </div>
          );
        })
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
