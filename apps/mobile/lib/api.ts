import { fetch as expoFetch } from 'expo/fetch';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { Platform } from 'react-native';

import { supabase } from './supabase';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

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
  if (!t) throw new ApiError(401, 'Not signed in');
  return t;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${await token()}`,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const del = (path: string) => api<void>(path, { method: 'DELETE' });

/** Download a task file and open the phone's share sheet (save, WhatsApp, Drive…). */
export async function shareArtifact(a: Artifact): Promise<void> {
  const auth = { Authorization: `Bearer ${await token()}` };
  if (Platform.OS === 'web') {
    const res = await fetch(`${API_URL}/artifacts/${a.id}`, { headers: auth });
    if (!res.ok) throw new ApiError(res.status, 'Download failed');
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = a.name;
    link.click();
    URL.revokeObjectURL(url);
    return;
  }
  const res = await expoFetch(`${API_URL}/artifacts/${a.id}`, { headers: auth });
  if (!res.ok) throw new ApiError(res.status, 'Download failed');
  const file = new File(Paths.cache, a.name);
  if (file.exists) file.delete();
  file.create();
  file.write(await res.bytes());
  if (!(await Sharing.isAvailableAsync())) throw new ApiError(0, 'Sharing is not available');
  await Sharing.shareAsync(file.uri, { mimeType: a.file_type, dialogTitle: a.name });
}

// --- Types mirroring apps/api/src/workforce_api/schemas.py -------------------------

export type TaskStatus =
  | 'draft'
  | 'planned'
  | 'queued'
  | 'running'
  | 'waiting_for_tool'
  | 'waiting_for_approval'
  | 'verifying'
  | 'completed'
  | 'blocked'
  | 'failed'
  | 'cancelled'
  | 'expired';

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
  workspace: { id: string; name: string; role: string; kill_switch: boolean };
}

export interface Capability {
  key: string;
  area: string;
  title: string;
  example: string;
  handling: 'automatic' | 'asks_approval' | 'owner_approval' | 'you_confirm_in_app';
}

export interface Agent {
  id: string;
  name: string;
  role: 'chief' | 'department_head' | 'specialist' | 'verifier';
  status: 'sandbox' | 'active' | 'suspended' | 'retired';
  template_key: string | null;
  department_id: string | null;
  allowed_tools: string[];
  description: string | null;
  latest_evaluation: { sample_size: number; success_rate: number | null; quality_score: number | null } | null;
}

export interface Department {
  id: string;
  key: string | null;
  name: string;
}

export interface Workforce {
  departments: Department[];
  agents: Agent[];
}

export interface LifecycleDecision {
  agent_id: string;
  agent_name: string;
  action: 'keep' | 'insufficient_data' | 'clone' | 'suspend' | 'retire';
  reason: string;
  applied: boolean;
}

export interface Memory {
  id: string;
  owner_scope: 'workspace' | 'agent';
  agent_name: string | null;
  memory_type: 'preference' | 'fact' | 'contact' | 'instruction' | 'learning' | 'episode';
  content: string;
  trusted: boolean;
  pinned: boolean;
  use_count: number;
  created_at: string;
}
