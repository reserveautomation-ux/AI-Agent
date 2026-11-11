"use client";

import { useCallback, useEffect, useState } from "react";
import { api, post, type ProviderConnections } from "@/lib/api";

const RESULT: Record<string, string> = {
  connected: "✅ Gmail connected. Approved emails will now be sent from it.",
  cancelled: "Gmail wasn't connected (you cancelled).",
  missing_permission: "Gmail wasn't connected: please tick “Send email on your behalf” on Google's screen.",
  error: "Gmail couldn't be connected. Please try again.",
};

export function ConnectedAccounts() {
  const [providers, setProviders] = useState<ProviderConnections[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<ProviderConnections[]>("/connections")
      .then(setProviders)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    // Coming back from Google: ?connected=gmail or ?connect=gmail&status=...
    const q = new URLSearchParams(window.location.search);
    const result = q.get("connected") ? "connected" : q.get("status");
    if (result && RESULT[result]) {
      setNotice(RESULT[result]);
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [load]);

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await post<{ auth_url: string }>("/connections/gmail/start", {
        redirect_to: `${window.location.origin}/integrations`,
      });
      window.location.href = auth_url; // Google's own sign-in page
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const disconnect = async (id: string, name: string | null) => {
    if (!confirm(`Disconnect ${name ?? "this account"}? Agents won't be able to send email until you reconnect.`)) return;
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

  const gmail = providers?.find((p) => p.provider === "gmail");

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Connected accounts</h2>
      {notice && <p className="notice">{notice}</p>}
      {!gmail ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="row connected">
          <div>
            <strong>✉️ Gmail</strong>
            <p className="muted small" style={{ margin: "4px 0 0" }}>
              Lets agents send emails you approve. Permission: send only. It can&apos;t read or
              delete your mail.
            </p>
            {gmail.accounts.map((a) => (
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
          {gmail.configured ? (
            <button onClick={connect} disabled={busy}>
              {gmail.accounts.some((a) => a.status === "active") ? "Reconnect" : "Connect Gmail"}
            </button>
          ) : (
            <span className="muted small">Not set up on the server yet (see the deployment guide).</span>
          )}
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
