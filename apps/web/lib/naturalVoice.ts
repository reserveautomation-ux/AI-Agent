"use client";

import { useSyncExternalStore } from "react";

/**
 * The free natural voice that runs inside the app (open-source Kokoro, English).
 * One download (~90 MB) the first time; the browser keeps it, so later it starts quickly
 * and works offline. Nothing is sent to any voice service.
 */

export const NATURAL_VOICES: { id: string; label: string }[] = [
  { id: "af_heart", label: "Heart · US · female (warm)" },
  { id: "af_bella", label: "Bella · US · female" },
  { id: "af_nicole", label: "Nicole · US · female (soft)" },
  { id: "af_sarah", label: "Sarah · US · female" },
  { id: "af_sky", label: "Sky · US · female" },
  { id: "am_michael", label: "Michael · US · male" },
  { id: "am_fenrir", label: "Fenrir · US · male" },
  { id: "am_puck", label: "Puck · US · male" },
  { id: "bf_emma", label: "Emma · UK · female" },
  { id: "bf_isabella", label: "Isabella · UK · female" },
  { id: "bm_george", label: "George · UK · male" },
  { id: "bm_fable", label: "Fable · UK · male" },
];

export type NaturalStatus = "idle" | "downloading" | "ready" | "failed";

interface State {
  status: NaturalStatus;
  progress: number; // 0–1 while downloading
  error: string | null;
}

let worker: Worker | null = null;
let state: State = { status: "idle", progress: 0, error: null };
const listeners = new Set<(s: State) => void>();
const pending = new Map<number, { resolve: (b: Blob) => void; reject: (e: Error) => void }>();
let nextId = 1;

function set(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l(state));
}

function ensureWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL("./kokoro.worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (e: MessageEvent) => {
    const m = e.data;
    if (m.type === "progress") set({ status: "downloading", progress: m.total ? m.loaded / m.total : 0 });
    else if (m.type === "ready") set({ status: "ready", progress: 1, error: null });
    else if (m.type === "failed") set({ status: "failed", error: m.message });
    else if (m.type === "audio") {
      pending.get(m.id)?.resolve(new Blob([m.wav], { type: "audio/wav" }));
      pending.delete(m.id);
    } else if (m.type === "error") {
      pending.get(m.id)?.reject(new Error(m.message));
      pending.delete(m.id);
    }
  };
  return worker;
}

export const naturalVoice = {
  get state(): State {
    return state;
  },
  supported(): boolean {
    return typeof window !== "undefined" && typeof Worker !== "undefined" && typeof WebAssembly !== "undefined";
  },
  /** Download (first time) or load from the browser's cache. */
  load() {
    if (state.status === "ready" || state.status === "downloading") return;
    set({ status: "downloading", progress: 0, error: null });
    ensureWorker().postMessage({ type: "load" });
  },
  subscribe(fn: (s: State) => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  /** Speak-ready audio for one sentence. */
  synth(text: string, voice: string, speed: number): Promise<Blob> {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ensureWorker().postMessage({ type: "speak", id, text, voice, speed });
    });
  },
};

/** Natural voices cover English; other languages use the device's voices. */
export function naturalCovers(lang: string): boolean {
  return lang.toLowerCase().startsWith("en");
}

const SERVER_STATE: State = { status: "idle", progress: 0, error: null };

/** Live download/ready status for the settings screen. */
export function useNaturalVoice(): State {
  return useSyncExternalStore(
    (fn) => naturalVoice.subscribe(fn),
    () => naturalVoice.state,
    () => SERVER_STATE,
  );
}
