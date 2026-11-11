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

export interface TaskDetail extends Task {
  events: TaskEvent[];
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
  access: "official_api" | "partner_required" | "deep_link" | "internal";
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
