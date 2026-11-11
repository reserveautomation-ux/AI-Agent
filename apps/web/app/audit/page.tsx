"use client";

import { useEffect, useState } from "react";
import { api, type AuditEvent } from "@/lib/api";

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AuditEvent[]>("/audit?limit=200")
      .then(setEvents)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">Append-only record of every action. No agent can edit or delete it.</p>
      {error && <p className="error-text">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {events?.map((e) => (
              <tr key={e.id}>
                <td className="nowrap">{new Date(e.created_at).toLocaleString()}</td>
                <td>{e.actor_type}</td>
                <td>
                  <code>{e.action}</code>
                </td>
                <td className="small muted">{JSON.stringify(e.event_json)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
