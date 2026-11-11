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
  /** Services to connect before the task can continue (it then resumes by itself). */
  waiting_for_connection?: string[];
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
/** A picture made in a task, as a temporary object URL (needs the sign-in token). */
export async function artifactImageUrl(a: Artifact): Promise<string> {
  const { data } = await supabase().auth.getSession();
  const res = await fetch(`${API_URL}/artifacts/${a.id}`, {
    headers: { Authorization: `Bearer ${data.session?.access_token ?? ""}` },
  });
  if (!res.ok) throw new ApiError(res.status, "Couldn't load the picture");
  return URL.createObjectURL(await res.blob());
}

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
  workspace: { id: string; name: string; role: string; kill_switch: boolean; timezone: string };
  /** What this person named their assistant. */
  assistant_name: string;
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
  attendees: "Invites", location: "Location", description: "Notes",
  duration_minutes: "Duration (minutes)", timezone: "Time zone",
};

export const fieldLabel = (k: string) => FIELD_LABEL[k] ?? k.replaceAll("_", " ");

const WHEN_FIELDS = new Set(["start", "end"]);

export function fieldValue(v: unknown, key?: string): string {
  if (typeof v === "string" && key && WHEN_FIELDS.has(key)) {
    const d = new Date(v);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    }
  }
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
const FIELD_ORDER = ["title", "to", "subject", "start", "end", "duration_minutes", "timezone", "location", "attendees", "network", "message", "text", "body", "description"];

export function detailEntries(payload: Record<string, unknown>, hasAmount: boolean): [string, unknown][] {
  const rank = (k: string) => (FIELD_ORDER.includes(k) ? FIELD_ORDER.indexOf(k) : FIELD_ORDER.length);
  return Object.entries(payload)
    .filter(([k]) => !(hasAmount && (k === "amount" || k === "currency")))
    .sort(([a], [b]) => rank(a) - rank(b));
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
  description: string;
  configured: boolean;
  accounts: ConnectedAccount[];
}

/** Which connected service an approved action needs. */
export const ACTION_SERVICE: Record<string, { provider: string; name: string }> = {
  send_email: { provider: "gmail", name: "Gmail" },
  calendar_create_event: { provider: "google_calendar", name: "Google Calendar" },
  send_whatsapp: { provider: "whatsapp", name: "WhatsApp" },
  send_telegram: { provider: "telegram", name: "Telegram" },
  post_slack: { provider: "slack", name: "Slack" },
  github_save_files: { provider: "github", name: "GitHub" },
  deploy_web: { provider: "vercel", name: "Vercel" },
};

export interface ConnectorField {
  key: string;
  label: string;
  secret: boolean;
  help: string;
  placeholder: string;
}

/** One service in the Connections catalog. */
export interface Connector {
  key: string;
  name: string;
  category: string;
  icon: string;
  description: string;
  /** oauth2: sign in · api_key: paste a key · deep_link: opens their app · builtin: nothing to do */
  auth: "oauth2" | "api_key" | "deep_link" | "builtin";
  live: boolean;
  /** Can be connected on this server right now. */
  available: boolean;
  plan: string;
  note: string;
  how_to_get: string;
  open_url: string;
  /** Everyday words for search ("cab", "food"). */
  keywords: string;
  fields: ConnectorField[];
  accounts: ConnectedAccount[];
}

export type ConnectorState = "connected" | "expired" | "ready" | "unavailable" | "soon" | "app" | "builtin";

export function connectorState(c: Connector): ConnectorState {
  if (c.auth === "builtin") return "builtin";
  if (c.auth === "deep_link") return "app";
  if (!c.live) return "soon";
  if (c.accounts.some((a) => a.status === "active")) return "connected";
  if (c.accounts.length) return "expired";
  return c.available ? "ready" : "unavailable";
}

export const STATE_BADGE: Record<ConnectorState, [string, "ok" | "warn" | "info" | "muted" | "bad"]> = {
  connected: ["Connected", "ok"],
  expired: ["Reconnect", "warn"],
  ready: ["Not connected", "muted"],
  unavailable: ["Not set up on server", "muted"],
  soon: ["Coming soon", "muted"],
  app: ["Opens their app", "info"],
  builtin: ["Built in", "ok"],
};

const SERVICE_NAMES: Record<string, string> = Object.fromEntries(
  Object.values(ACTION_SERVICE).map((s) => [s.provider, s.name]),
);

/** Display name for a service key (gmail → Gmail, google_calendar → Google Calendar). */
export function serviceName(key: string): string {
  return SERVICE_NAMES[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

/** Human list: "Gmail", "Gmail and Slack", "Gmail, Slack and GitHub". */
export function joinNames(names: string[]): string {
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

export const TIMEZONES: { zone: string; label: string }[] = [
  { zone: "Asia/Kolkata", label: "India (IST)" },
  { zone: "Asia/Dubai", label: "Dubai (GST)" },
  { zone: "Asia/Singapore", label: "Singapore" },
  { zone: "Europe/London", label: "London" },
  { zone: "Europe/Berlin", label: "Berlin / Paris" },
  { zone: "America/New_York", label: "New York" },
  { zone: "America/Los_Angeles", label: "Los Angeles" },
  { zone: "Australia/Sydney", label: "Sydney" },
  { zone: "UTC", label: "UTC" },
];

// --- Chat ----------------------------------------------------------------------

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatTaskRef {
  id: string;
  title: string;
  status: TaskStatus;
  waiting_for_connection?: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  via: "text" | "voice";
  meta: {
    kind?: "reply" | "task_update" | "reminder";
    task_id?: string;
    status?: TaskStatus;
    waiting_for_connection?: string[];
    tasks?: ChatTaskRef[];
    memories?: string[];
    schedules?: ScheduleRef[];
    attachments?: ChatFile[];
    interrupted?: boolean;
  };
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  tasks: Record<string, ChatTaskRef>;
}

export type ChatEvent =
  | { type: "conversation"; id: string; title: string }
  | { type: "text"; text: string }
  | { type: "task"; task: ChatTaskRef }
  | { type: "memory"; content: string }
  | { type: "schedule"; schedule: ScheduleRef }
  | { type: "done"; message_id: string; text: string }
  | { type: "error"; message: string };

/** Send a message and receive the assistant's reply as it is written (Server-Sent Events). */
export async function streamChat(
  body: { content: string; conversation_id?: string | null; via: "text" | "voice"; attachments?: string[] },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Not signed in");
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as ChatEvent);
      }
    }
  }
}

export interface ScheduleRef {
  id: string;
  title: string;
  kind: "reminder" | "task";
  repeat: string;
  next_run_at: string;
  text: string;
}

export interface Schedule {
  id: string;
  kind: "reminder" | "task";
  title: string;
  what: string;
  repeat: "none" | "daily" | "weekdays" | "weekly" | "monthly";
  timezone: string;
  next_run_at: string | null;
  active: boolean;
  runs: number;
  last_run_at: string | null;
}

export const REPEAT_LABEL: Record<string, string> = {
  none: "Once",
  daily: "Every day",
  weekdays: "Every weekday",
  weekly: "Every week",
  monthly: "Every month",
};

export interface ChatFile {
  id: string;
  name: string;
  media_type: string;
  size_bytes?: number;
  /** Local preview while composing (not from the server). */
  preview?: string;
}

const MAX_IMAGE = 5 * 1024 * 1024;
const MAX_PDF = 10 * 1024 * 1024;

/** Phone photos are big: shrink to at most 2048 px as JPEG before uploading. */
async function shrinkImage(file: File): Promise<Blob> {
  if (file.type === "image/gif" || (file.size < 1.5 * 1024 * 1024 && file.type !== "image/heic")) return file;
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return await new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("couldn't read the photo"))), "image/jpeg", 0.85),
  );
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(new Error("couldn't read the file"));
    r.readAsDataURL(blob);
  });
}

/** Upload a photo or PDF for the assistant to read. */
export async function uploadChatFile(file: File): Promise<ChatFile> {
  const isPdf = file.type === "application/pdf";
  if (!isPdf && !file.type.startsWith("image/")) throw new Error(`${file.name}: send a photo or a PDF`);
  let blob: Blob = file;
  let type = file.type;
  if (!isPdf) {
    blob = await shrinkImage(file);
    type = blob.type || file.type;
  }
  if (blob.size > (isPdf ? MAX_PDF : MAX_IMAGE)) {
    throw new Error(`${file.name} is too big (max ${isPdf ? 10 : 5} MB)`);
  }
  const name = type === "image/jpeg" && !/\.jpe?g$/i.test(file.name) ? file.name.replace(/\.[^.]+$/, "") + ".jpg" : file.name;
  const out = await post<ChatFile>("/chat/files", { name, media_type: type, data: await toBase64(blob) });
  return { ...out, preview: isPdf ? undefined : URL.createObjectURL(blob) };
}

/** Load an attached photo (needs the sign-in token, so it can't be a plain <img src>). */
export async function chatFileUrl(id: string): Promise<string> {
  const { data } = await supabase().auth.getSession();
  const res = await fetch(`${API_URL}/chat/files/${id}`, {
    headers: { Authorization: `Bearer ${data.session?.access_token ?? ""}` },
  });
  if (!res.ok) throw new ApiError(res.status, "file not found");
  return URL.createObjectURL(await res.blob());
}
