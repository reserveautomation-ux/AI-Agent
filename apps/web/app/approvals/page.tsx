"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { api, type ApprovalItem, type ProviderConnections } from "@/lib/api";

export default function ApprovalsPage() {
  const [pending, setPending] = useState<ApprovalItem[] | null>(null);
  const [decided, setDecided] = useState<ApprovalItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [gmailReady, setGmailReady] = useState(true);

  const load = useCallback(async () => {
    try {
      const [p, d, conns] = await Promise.all([
        api<ApprovalItem[]>("/approvals"),
        api<ApprovalItem[]>("/approvals?state=decided&limit=20"),
        api<ProviderConnections[]>("/connections").catch(() => []),
      ]);
      setPending(p);
      setDecided(d);
      const gmail = conns.find((x) => x.provider === "gmail");
      setGmailReady(!gmail || gmail.accounts.some((a) => a.status === "active"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const onDecided = (u: ApprovalItem) => {
    setPending((list) => (list ?? []).filter((a) => a.id !== u.id));
    setDecided((list) => [u, ...list.filter((a) => a.id !== u.id)]);
  };

  return (
    <>
      <h1>Approvals</h1>
      <p className="muted">
        Your agents prepare emails, messages, bookings and orders. Nothing is sent, booked or paid
        until you approve the exact details. You can edit the text before approving.
      </p>
      {error && <p className="error-text">{error}</p>}
      {!gmailReady && pending?.some((a) => a.action === "send_email") && (
        <div className="card notice">
          <strong>Connect Gmail to send these emails.</strong> Without it, approved emails are
          recorded but not sent. <Link href="/integrations">Connect Gmail →</Link>
        </div>
      )}

      <h2>Waiting for you{pending?.length ? ` (${pending.length})` : ""}</h2>
      {pending === null ? (
        <p className="muted">Loading…</p>
      ) : pending.length === 0 ? (
        <div className="card center-text">
          <p>✅ All caught up</p>
          <p className="muted small">New approvals appear here and on your phone.</p>
        </div>
      ) : (
        <div className="grid">
          {pending.map((a) => (
            <ApprovalCard key={a.id} item={a} onDecided={onDecided} />
          ))}
        </div>
      )}

      {decided.length > 0 && (
        <>
          <h2>Recently decided</h2>
          <div className="grid">
            {decided.map((a) => (
              <ApprovalCard key={a.id} item={a} onDecided={onDecided} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
