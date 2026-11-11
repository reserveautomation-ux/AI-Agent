const TONE: Record<string, string> = {
  completed: "ok",
  active: "ok",
  running: "info",
  verifying: "info",
  planned: "info",
  queued: "info",
  waiting_for_tool: "warn",
  waiting_for_approval: "warn",
  sandbox: "warn",
  blocked: "warn",
  suspended: "warn",
  failed: "bad",
  expired: "bad",
  retired: "muted",
  cancelled: "muted",
  draft: "muted",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${TONE[status] ?? "muted"}`}>{status.replaceAll("_", " ")}</span>;
}
