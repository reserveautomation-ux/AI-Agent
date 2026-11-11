import { supabase } from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Not signed in");

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// --- Types mirroring apps/api/src/workforce_api/schemas.py ---------------------

export type TaskStatus =
  | "draft"
  | "planned"
  | "queued"
  | "running"
  | "waiting_for_tool"
  | "waiting_for_approval"
  | "verifying"
  | "completed"
  | "blocked"
  | "failed"
  | "cancelled"
  | "expired";

export interface Task {
  id: string;
  title: string;
  objective: string;
  status: TaskStatus;
  priority: number;
  deadline: string | null;
  budget_limit_usd: string | null;
  result_summary: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cost_usd: string;
}

export interface TaskEvent {
  id: number;
  from_status: TaskStatus | null;
  to_status: TaskStatus;
  actor_type: string;
  actor_id: string | null;
  reason: string | null;
  created_at: string;
}

export interface TaskStep {
  sequence: number;
  title: string | null;
  status: string;
  agent_id: string | null;
  agent_name: string | null;
  summary: string | null;
  result: string | null;
  limitations: string[];
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface Artifact {
  id: string;
  name: string;
  file_type: string;
  size_bytes: number;
  preview: string | null;
  created_at: string;
}

export interface Approval {
  id: string;
  action: string;
  action_payload: Record<string, unknown>;
  amount: string | null;
  currency: string | null;
  recipient: string | null;
  risk_tier: number;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface TaskDetail extends Task {
  events: TaskEvent[];
  plan: { understanding?: string; assumptions?: string[]; success_criteria?: string[] } | null;
  verification: {
    passed?: boolean;
    score?: number;
    issues?: string[];
    criteria?: { criterion: string; met: boolean; note: string }[];
  } | null;
  last_error: string | null;
  steps: TaskStep[];
  artifacts: Artifact[];
  approvals: Approval[];
}

/** Download a file through the authenticated API. */
export async function downloadArtifact(a: Artifact) {
  const { data } = await supabase().auth.getSession();
  const res = await fetch(`${API_URL}/artifacts/${a.id}`, {
    headers: { Authorization: `Bearer ${data.session?.access_token ?? ""}` },
  });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = a.name;
  link.click();
  URL.revokeObjectURL(url);
}

export interface Me {
  user_id: string;
  email: string | null;
  workspace: { id: string; name: string; role: string; kill_switch: boolean };
}

export interface Agent {
  id: string;
  name: string;
  role: "chief" | "department_head" | "specialist" | "verifier";
  status: "sandbox" | "active" | "suspended" | "retired";
  version: number;
  template_key: string | null;
  model_profile: string;
  department_id: string | null;
  parent_agent_id: string | null;
  lineage_id: string | null;
  cloned_from: string | null;
  allowed_tools: string[];
  description: string | null;
  latest_evaluation: {
    sample_size: number;
    success_rate: number | null;
    quality_score: number | null;
  } | null;
}

export interface Department {
  id: string;
  key: string | null;
  name: string;
  manager_agent_id: string | null;
}

export interface Workforce {
  departments: Department[];
  agents: Agent[];
}

export interface LifecycleDecision {
  agent_id: string;
  agent_name: string;
  action: "keep" | "insufficient_data" | "clone" | "suspend" | "retire";
  reason: string;
  applied: boolean;
  new_agent_id: string | null;
}

export interface Integration {
  key: string;
  name: string;
  category: string;
  access: "official_api" | "partner_required" | "deep_link" | "internal" | "browser";
  notes: string;
  tools: string[];
}

export interface AuditEvent {
  id: number;
  actor_type: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  event_json: Record<string, unknown>;
  created_at: string;
}

export interface Capability {
  key: string;
  area: string;
  title: string;
  example: string;
  handling: "automatic" | "asks_approval" | "owner_approval" | "you_confirm_in_app";
}

export interface Memory {
  id: string;
  owner_scope: "workspace" | "agent";
  agent_id: string | null;
  agent_name: string | null;
  memory_type: "preference" | "fact" | "contact" | "instruction" | "learning" | "episode";
  content: string;
  trusted: boolean;
  importance: number;
  pinned: boolean;
  source_type: "user" | "agent" | "system";
  source_ref: string | null;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface ApprovalItem {
  id: string;
  task_id: string;
  task_title: string;
  action: string;
  action_payload: Record<string, unknown>;
  action_hash: string;
  amount: string | null;
  currency: string | null;
  recipient: string | null;
  item: string | null;
  risk_tier: number;
  status: "pending" | "approved" | "rejected" | "expired" | "consumed" | "invalidated";
  expires_at: string;
  created_at: string;
  decided_at: string | null;
  execution_status: string | null;
  execution_result: string | null;
  owner_only: boolean;
}

export const ACTION_LABEL: Record<string, string> = {
  send_email: "Send email",
  send_whatsapp: "Send WhatsApp",
  calendar_create_event: "Create calendar event",
  post_social: "Publish post",
  deploy_web: "Deploy website",
  book_flight: "Book flight",
  place_stock_order: "Place stock order",
  play_store_release: "Release on Play Store",
  app_store_submit: "Submit to App Store",
  browser_submit_form: "Submit web form",
};

const FIELD_LABEL: Record<string, string> = {
  to: "To", subject: "Subject", body: "Message", message: "Message", text: "Text",
  network: "Network", title: "Title", start: "Starts", end: "Ends", symbol: "Stock",
  side: "Buy/Sell", quantity: "Quantity", order_type: "Order type", amount: "Amount",
  currency: "Currency", url: "Website", fields: "Form details", offer_id: "Offer",
};

export const fieldLabel = (k: string) => FIELD_LABEL[k] ?? k.replaceAll("_", " ");

export function fieldValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (v && typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, val]) => `${k}: ${String(val)}`)
      .join("\n");
  }
  return String(v);
}

export function expiresIn(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return h >= 1 ? `${h}h ${m}m left` : `${m}m left`;
}

export function formatMoney(amount: string, currency: string | null): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return `${amount} ${currency ?? ""}`.trim();
  try {
    return currency
      ? new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(n)
      : new Intl.NumberFormat("en-IN").format(n);
  } catch {
    return `${n.toLocaleString("en-IN")} ${currency ?? ""}`.trim();
  }
}

/** Payload fields to list (amount/currency are shown separately, large). */
export function detailEntries(payload: Record<string, unknown>, hasAmount: boolean): [string, unknown][] {
  return Object.entries(payload).filter(([k]) => !(hasAmount && (k === "amount" || k === "currency")));
}

/** Text fields the owner may reword before approving (matches the API). */
export const EDITABLE_FIELDS = new Set(["subject", "body", "message", "text", "title", "caption", "description"]);

/** Badge for a decided approval, honest about whether the action actually happened. */
export function decidedBadge(status: string, execution: string | null): [string, "ok" | "warn" | "info" | "muted" | "bad"] {
  if (status === "rejected") return ["Declined", "muted"];
  if (status === "expired") return ["Expired", "bad"];
  if (status === "invalidated") return ["Cancelled (changed)", "bad"];
  if (status === "approved") return ["Approved · running", "info"];
  return execution === "succeeded" ? ["Approved · done", "ok"] : ["Approved · not done", "warn"];
}

export interface ConnectedAccount {
  id: string;
  display_name: string | null;
  status: "active" | "expired" | "error" | "revoked";
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  last_error: string | null;
}

export interface ProviderConnections {
  provider: string;
  name: string;
  configured: boolean;
  accounts: ConnectedAccount[];
}
