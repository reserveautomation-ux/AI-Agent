"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ACTION_LABEL,
  EDITABLE_FIELDS,
  decidedBadge,
  detailEntries,
  expiresIn,
  formatMoney,
  fieldLabel,
  fieldValue,
  post,
  type ApprovalItem,
} from "@/lib/api";


export function ApprovalCard({
  item,
  onDecided,
  showTask = true,
}: {
  item: ApprovalItem;
  onDecided: (updated: ApprovalItem) => void;
  showTask?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = item.status === "pending";
  const textFields = Object.entries(item.action_payload).filter(
    ([k, v]) => EDITABLE_FIELDS.has(k) && typeof v === "string",
  );
  const label = ACTION_LABEL[item.action] ?? item.action;

  const decide = async (kind: "approve" | "reject") => {
    setError(null);
    if (kind === "approve" && item.owner_only) {
      const what = `${label}${item.amount ? ` for ${formatMoney(item.amount, item.currency)}` : ""}`;
      if (!confirm(`Approve: ${what}?`)) return;
    }
    if (kind === "reject" && !confirm("Decline this? It will not be done.")) return;
    const changes = editing
      ? Object.fromEntries(Object.entries(draft).filter(([k, v]) => v !== item.action_payload[k]))
      : {};
    setBusy(true);
    try {
      const updated = await post<ApprovalItem>(`/approvals/${item.id}/${kind}`, {
        action_hash: item.action_hash,
        ...(kind === "approve" && Object.keys(changes).length ? { changes } : {}),
      });
      setEditing(false);
      onDecided(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const [doneLabel, doneTone] = decidedBadge(item.status, item.execution_status);

  return (
    <div className={`agent approval-card ${pending ? (item.owner_only ? "owner" : "pending") : ""}`}>
      <div className="row">
        <strong>{label}</strong>
        {pending ? (
          <span className={`badge ${item.owner_only ? "bad" : "warn"}`}>
            {item.owner_only ? "🔒 Owner only" : "Needs approval"}
          </span>
        ) : (
          <span className={`badge ${doneTone}`}>{doneLabel}</span>
        )}
      </div>
      {showTask && (
        <Link href={`/tasks/${item.task_id}`} className="small task-link">
          For: {item.task_title}
        </Link>
      )}
      {item.amount && (
        <div className="amount">
          {formatMoney(item.amount, item.currency)}
        </div>
      )}
      <dl className="fields">
        {editing
          ? textFields.map(([k]) => (
              <div key={k}>
                <dt>{fieldLabel(k)}</dt>
                <dd>
                  <textarea
                    aria-label={fieldLabel(k)}
                    rows={(draft[k] ?? "").length > 60 ? 4 : 1}
                    value={draft[k] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
                  />
                </dd>
              </div>
            ))
          : detailEntries(item.action_payload, !!item.amount).map(([k, v]) => (
              <div key={k}>
                <dt>{fieldLabel(k)}</dt>
                <dd className="pre">{fieldValue(v)}</dd>
              </div>
            ))}
      </dl>
      {pending ? (
        <>
          <span className="muted small">⏳ {expiresIn(item.expires_at)} · nothing happens until you approve</span>
          <div className="actions">
            <button onClick={() => decide("approve")} disabled={busy}>
              {editing ? "Save & approve" : "Approve"}
            </button>
            {textFields.length > 0 &&
              (editing ? (
                <button className="ghost" onClick={() => setEditing(false)} disabled={busy}>
                  Undo edits
                </button>
              ) : (
                <button
                  className="ghost"
                  onClick={() => {
                    setDraft(Object.fromEntries(textFields.map(([k, v]) => [k, v as string])));
                    setEditing(true);
                  }}
                  disabled={busy}
                >
                  Edit
                </button>
              ))}
            <button className="ghost" onClick={() => decide("reject")} disabled={busy}>
              Decline
            </button>
          </div>
        </>
      ) : (
        item.execution_result && (
          <p className={`small ${item.execution_status === "succeeded" ? "ok-text" : "muted"}`}>
            {item.execution_status === "succeeded" ? "✅ " : ""}
            {item.execution_result}
          </p>
        )
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
