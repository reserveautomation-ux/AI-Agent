import { fetch as expoFetch } from "expo/fetch";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { Platform } from "react-native";

import { supabase } from "./supabase";

export const API_URL = (
  process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function token(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  const t = data.session?.access_token;
  if (!t) throw new ApiError(401, "Not signed in");
  return t;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${await token()}`,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const del = (path: string) => api<void>(path, { method: "DELETE" });

/** Download a task file and open the phone's share sheet (save, WhatsApp, Drive…). */
export async function shareArtifact(a: Artifact): Promise<void> {
  const auth = { Authorization: `Bearer ${await token()}` };
  if (Platform.OS === "web") {
    const res = await fetch(`${API_URL}/artifacts/${a.id}`, { headers: auth });
    if (!res.ok) throw new ApiError(res.status, "Download failed");
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = a.name;
    link.click();
    URL.revokeObjectURL(url);
    return;
  }
  const res = await expoFetch(`${API_URL}/artifacts/${a.id}`, {
    headers: auth,
  });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const file = new File(Paths.cache, a.name);
  if (file.exists) file.delete();
  file.create();
  file.write(await res.bytes());
  if (!(await Sharing.isAvailableAsync()))
    throw new ApiError(0, "Sharing is not available");
  await Sharing.shareAsync(file.uri, {
    mimeType: a.file_type,
    dialogTitle: a.name,
  });
}

// --- Types mirroring apps/api/src/workforce_api/schemas.py -------------------------

/** Something ready for you to do in another app: a WhatsApp message to send, or a UPI payment
 * to approve with your PIN. */
export type ChatAction = {
  kind: "whatsapp" | "upi";
  url: string;
  to: string;
  name?: string;
  text: string;
  amount?: string;
};

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
  reason: string | null;
  created_at: string;
}

export interface TaskStep {
  sequence: number;
  title: string | null;
  status: string;
  agent_name: string | null;
  summary: string | null;
  result: string | null;
  limitations: string[];
  error: string | null;
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
}

export interface TaskDetail extends Task {
  events: TaskEvent[];
  plan: { understanding?: string; assumptions?: string[] } | null;
  verification: {
    passed?: boolean;
    criteria?: { criterion: string; met: boolean; note: string }[];
  } | null;
  last_error: string | null;
  steps: TaskStep[];
  artifacts: Artifact[];
  approvals: Approval[];
}

export interface Me {
  user_id: string;
  email: string | null;
  workspace: {
    id: string;
    name: string;
    role: string;
    kill_switch: boolean;
    timezone: string;
  };
  /** What this person named their assistant. */
  assistant_name: string;
}

export interface Capability {
  key: string;
  area: string;
  title: string;
  example: string;
  handling:
    | "automatic"
    | "asks_approval"
    | "owner_approval"
    | "you_confirm_in_app";
}

export interface Agent {
  id: string;
  name: string;
  role: "chief" | "department_head" | "specialist" | "verifier";
  status: "sandbox" | "active" | "suspended" | "retired";
  template_key: string | null;
  department_id: string | null;
  allowed_tools: string[];
  description: string | null;
  latest_evaluation: {
    sample_size: number;
    success_rate: number | null;
    quality_score: number | null;
  } | null;
  lessons: string[];
  generation: number;
}

export interface Department {
  id: string;
  key: string | null;
  name: string;
}

export interface Workforce {
  departments: Department[];
  agents: Agent[];
  auto_improve: boolean;
  last_improved_at: string | null;
}

export interface LifecycleDecision {
  agent_id: string;
  agent_name: string;
  action: "keep" | "insufficient_data" | "clone" | "suspend" | "retire";
  reason: string;
  applied: boolean;
}

export interface Memory {
  id: string;
  owner_scope: "workspace" | "agent";
  agent_name: string | null;
  memory_type:
    | "preference"
    | "fact"
    | "contact"
    | "instruction"
    | "learning"
    | "episode";
  content: string;
  trusted: boolean;
  pinned: boolean;
  use_count: number;
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
  status:
    | "pending"
    | "approved"
    | "rejected"
    | "expired"
    | "consumed"
    | "invalidated";
  expires_at: string;
  created_at: string;
  decided_at: string | null;
  execution_status: string | null;
  execution_result: string | null;
  owner_only: boolean;
}

export interface ConnectedAccount {
  id: string;
  display_name: string | null;
  status: "active" | "expired" | "error" | "revoked";
  scopes: string[];
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
    attachments?: {
      id: string;
      name: string;
      media_type: string;
      preview?: string;
    }[];
    actions?: ChatAction[];
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
  | { type: "action"; action: ChatAction }
  | { type: "done"; message_id: string; text: string }
  | { type: "error"; message: string };

/** Send a message and receive the reply as it is written (Server-Sent Events over expo/fetch). */
export async function streamChat(
  body: {
    content: string;
    conversation_id?: string | null;
    via: "text" | "voice";
    attachments?: string[];
  },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await expoFetch(`${API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${await token()}`,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      const b = await res.json();
      detail =
        typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
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
        if (line.startsWith("data: "))
          onEvent(JSON.parse(line.slice(6)) as ChatEvent);
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
