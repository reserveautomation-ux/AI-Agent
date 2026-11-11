"use client";

import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";

interface Link {
  bot: string | null;
  linked: boolean;
  link_url: string | null;
  available: boolean;
  reason: string | null;
}

/** Chat with your assistant from Telegram (free): link your Telegram chat once. */
export function TelegramChat() {
  const [link, setLink] = useState<Link | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Link>("/telegram/link").then(setLink).catch(() => {});
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const l = await post<Link>("/telegram/link");
      setLink(l);
      if (l.link_url) window.open(l.link_url, "_blank", "noopener");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const unlink = async () => {
    setBusy(true);
    try {
      setLink(await post<Link>("/telegram/unlink"));
    } finally {
      setBusy(false);
    }
  };

  if (!link) return null;
  return (
    <div className="tg-box">
      <strong>Chat with your assistant on Telegram</strong>
      {link.linked ? (
        <p className="small">
          <span className="ok-text">● Linked.</span> Message your bot any time; task updates, reminders and
          important-email alerts arrive there too.{" "}
          <button className="ghost small" onClick={unlink} disabled={busy}>
            Unlink
          </button>
        </p>
      ) : !link.available ? (
        <p className="muted small">{link.reason ?? "Not set up on the server yet (PUBLIC_API_URL)."}</p>
      ) : (
        <>
          <p className="muted small">Free. Opens Telegram; tap Start to link your chat (the link works once, for 30 minutes).</p>
          <div>
            <button onClick={start} disabled={busy}>
              {busy ? "Opening…" : "Link Telegram chat"}
            </button>
          </div>
          {link.link_url && (
            <p className="small">
              Didn&apos;t open?{" "}
              <a href={link.link_url} target="_blank" rel="noreferrer">
                Open {link.bot} in Telegram
              </a>
            </p>
          )}
        </>
      )}
      {error && <p className="error-text small">{error}</p>}
    </div>
  );
}
