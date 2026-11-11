/// <reference lib="webworker" />
// Runs the open-source Kokoro voice in a background thread so the page never freezes.
// The model is downloaded once and kept in the browser's cache; after that it works offline.
import { KokoroTTS } from "kokoro-js";

const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
let tts: Promise<KokoroTTS> | null = null;

type In =
  | { type: "load" }
  | { type: "speak"; id: number; text: string; voice: string; speed: number };

function load(): Promise<KokoroTTS> {
  if (!tts) {
    const files = new Map<string, { loaded: number; total: number }>();
    tts = KokoroTTS.from_pretrained(MODEL, {
      dtype: "q8",
      device: "wasm",
      progress_callback: (p: { status: string; file?: string; loaded?: number; total?: number }) => {
        if (p.status !== "progress" || !p.file) return;
        files.set(p.file, { loaded: p.loaded ?? 0, total: p.total ?? 0 });
        let loaded = 0;
        let total = 0;
        for (const f of files.values()) {
          loaded += f.loaded;
          total += f.total;
        }
        postMessage({ type: "progress", loaded, total });
      },
    });
    tts.then(
      () => postMessage({ type: "ready" }),
      (e: unknown) => {
        tts = null;
        postMessage({ type: "failed", message: String((e as Error)?.message ?? e) });
      },
    );
  }
  return tts;
}

self.onmessage = async (e: MessageEvent<In>) => {
  const msg = e.data;
  if (msg.type === "load") {
    void load().catch(() => {});
    return;
  }
  try {
    const model = await load();
    const audio = await model.generate(msg.text, {
      voice: msg.voice as "af_heart", // one of NATURAL_VOICES

      speed: msg.speed,
    });
    const wav = audio.toWav();
    postMessage({ type: "audio", id: msg.id, wav }, [wav]);
  } catch (err) {
    postMessage({ type: "error", id: msg.id, message: String((err as Error)?.message ?? err) });
  }
};
