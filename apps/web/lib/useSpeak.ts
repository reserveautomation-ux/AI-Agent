"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Turn chat text into something pleasant to hear (no markdown symbols or long links). */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " (code) ")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "the link")
    .replace(/[*_`#>|]+/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

export interface VoicePrefs {
  /** A voice from speechSynthesis.getVoices(); empty: the best match for the language. */
  voiceURI: string;
  rate: number; // 0.5–2
  pitch: number; // 0–2
}
export const DEFAULT_VOICE: VoicePrefs = { voiceURI: "", rate: 1, pitch: 1 };

/** How natural a free voice sounds: Edge "Natural/Online", Chrome "Google", Safari "Premium/Enhanced". */
export function voiceScore(v: SpeechSynthesisVoice, lang: string): number {
  const n = v.name;
  let s = 0;
  if (/natural|neural/i.test(n)) s += 4;
  if (/premium/i.test(n)) s += 4;
  if (/enhanced/i.test(n)) s += 3;
  if (/online/i.test(n)) s += 2;
  if (/google/i.test(n)) s += 2;
  if (/compact|espeak|eloquence/i.test(n)) s -= 3;
  if (v.lang.replace("_", "-") === lang) s += 5;
  return s;
}

export function isNatural(v: SpeechSynthesisVoice): boolean {
  return /natural|neural|premium|enhanced|online|google/i.test(v.name) && !/compact/i.test(v.name);
}

/** Voices this browser has for a language, most natural first. */
export function voicesFor(lang: string): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  const base = lang.split("-")[0];
  return window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang.replace("_", "-").startsWith(base))
    .sort((a, b) => voiceScore(b, lang) - voiceScore(a, lang) || a.name.localeCompare(b.name));
}

/**
 * Split streamed text into whole sentences to speak now, keeping the unfinished tail.
 * Lets the assistant start talking while the rest of the reply is still being written.
 */
export function takeSentences(buffer: string, final = false): [string[], string] {
  const out: string[] = [];
  let rest = buffer;
  const boundary = /^([\s\S]*?(?:[.!?।…]["')\]]*(?=\s)|\n))\s*/;
  for (let m = boundary.exec(rest); m && m[0]; m = boundary.exec(rest)) {
    if (m[1].trim()) out.push(m[1].trim());
    rest = rest.slice(m[0].length);
  }
  if (!final && rest.length > 240) {
    const cut = Math.max(rest.lastIndexOf(", ", 200), rest.lastIndexOf(" ", 200));
    if (cut > 40) {
      out.push(rest.slice(0, cut + 1).trim());
      rest = rest.slice(cut + 1);
    }
  }
  if (final && rest.trim()) {
    out.push(rest.trim());
    rest = "";
  }
  return [out, rest];
}

/** The browser's voice list loads late; this re-renders once it is ready. */
export function useVoiceList(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth) return;
    const update = () => setN(synth.getVoices().length);
    update();
    synth.addEventListener?.("voiceschanged", update);
    return () => synth.removeEventListener?.("voiceschanged", update);
  }, []);
  return n;
}

/**
 * The assistant's voice: the browser's built-in text-to-speech (free; Edge, Chrome and Safari
 * include natural-sounding voices). `begin` / `push` / `end` speak a reply sentence by sentence
 * while it is still streaming in; `speak` reads a finished text.
 */
export function useSpeak(prefs: VoicePrefs = DEFAULT_VOICE) {
  const prefsRef = useRef(prefs);
  useEffect(() => {
    prefsRef.current = prefs;
  }, [prefs]);
  const [supported, setSupported] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const runRef = useRef(0);
  const q = useRef({
    queued: 0,
    done: 0,
    ended: true,
    buffer: "",
    inCode: false,
    lang: "en-IN",
    voice: null as SpeechSynthesisVoice | null,
    onAll: undefined as (() => void) | undefined,
  });

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    };
  }, []);

  const stop = useCallback(() => {
    runRef.current += 1;
    q.current.ended = true;
    window.speechSynthesis?.cancel();
    setSpeakingId(null);
  }, []);

  const finishIfDone = useCallback((run: number) => {
    const s = q.current;
    if (run !== runRef.current || !s.ended || s.done < s.queued) return;
    setSpeakingId(null);
    const cb = s.onAll;
    s.onAll = undefined;
    cb?.();
  }, []);

  const say = useCallback(
    (sentences: string[]) => {
      const synth = window.speechSynthesis;
      const s = q.current;
      const run = runRef.current;
      const { rate, pitch } = prefsRef.current;
      for (const raw of sentences) {
        const fences = (raw.match(/```/g) ?? []).length;
        const skip = s.inCode;
        if (fences % 2) s.inCode = !s.inCode;
        const text = skip || fences ? "" : speakable(raw);
        if (!text) continue;
        const u = new SpeechSynthesisUtterance(text);
        u.lang = s.voice?.lang ?? s.lang;
        if (s.voice) u.voice = s.voice;
        u.rate = rate;
        u.pitch = pitch;
        u.onend = u.onerror = () => {
          if (run !== runRef.current) return;
          s.done += 1;
          finishIfDone(run);
        };
        s.queued += 1;
        synth.speak(u);
      }
    },
    [finishIfDone],
  );

  /** Start speaking a reply that is still arriving. */
  const begin = useCallback((id: string, lang: string, onEnd?: () => void) => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth) return;
    synth.cancel();
    runRef.current += 1;
    const { voiceURI } = prefsRef.current;
    const voice = (voiceURI && synth.getVoices().find((v) => v.voiceURI === voiceURI)) || voicesFor(lang)[0] || null;
    q.current = { queued: 0, done: 0, ended: false, buffer: "", inCode: false, lang, voice, onAll: onEnd };
    setSpeakingId(id);
  }, []);

  const push = useCallback(
    (text: string) => {
      const s = q.current;
      if (s.ended || typeof window === "undefined" || !window.speechSynthesis) return;
      const [sentences, rest] = takeSentences(s.buffer + text);
      s.buffer = rest;
      say(sentences);
    },
    [say],
  );

  /** No more text is coming: speak what is left, then call onEnd when the last word is said. */
  const end = useCallback(() => {
    const s = q.current;
    if (s.ended) return;
    const [sentences] = takeSentences(s.buffer, true);
    s.buffer = "";
    if (typeof window !== "undefined" && window.speechSynthesis) say(sentences);
    s.ended = true;
    finishIfDone(runRef.current);
  }, [say, finishIfDone]);

  const speak = useCallback(
    (text: string, lang: string, id = "say", onEnd?: () => void) => {
      if (typeof window === "undefined" || !window.speechSynthesis || !speakable(text)) {
        onEnd?.();
        return;
      }
      begin(id, lang, onEnd);
      push(text);
      end();
    },
    [begin, push, end],
  );

  return { supported, speakingId, speak, stop, begin, push, end };
}
