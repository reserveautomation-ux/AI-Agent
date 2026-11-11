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

/** Voices this browser has, best first: the chosen language, then the same language family. */
export function voicesFor(lang: string): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !window.speechSynthesis) return [];
  const base = lang.split("-")[0];
  return window.speechSynthesis
    .getVoices()
    .filter((v) => v.lang.replace("_", "-").startsWith(base))
    .sort((a, b) => Number(b.lang.replace("_", "-") === lang) - Number(a.lang.replace("_", "-") === lang) || a.name.localeCompare(b.name));
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

/** The assistant's voice: the browser's built-in text-to-speech (free, works offline). */
export function useSpeak(prefs: VoicePrefs = DEFAULT_VOICE) {
  const prefsRef = useRef(prefs);
  useEffect(() => {
    prefsRef.current = prefs;
  }, [prefs]);
  const [supported, setSupported] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const runRef = useRef(0);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    };
  }, []);

  const stop = useCallback(() => {
    runRef.current += 1;
    window.speechSynthesis?.cancel();
    setSpeakingId(null);
  }, []);

  const speak = useCallback(
    (text: string, lang: string, id = "say", onEnd?: () => void) => {
      const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
      const clean = speakable(text);
      if (!synth || !clean) {
        onEnd?.();
        return;
      }
      synth.cancel();
      const run = ++runRef.current;
      const { voiceURI, rate, pitch } = prefsRef.current;
      const voices = synth.getVoices();
      const voice =
        (voiceURI && voices.find((v) => v.voiceURI === voiceURI)) ||
        voicesFor(lang)[0] ||
        null;
      // Short pieces: some browsers stop speaking long texts after ~15 seconds.
      const parts = clean.match(/[^.!?।]+[.!?।]*/g)?.map((p) => p.trim()).filter(Boolean) ?? [clean];
      const finish = () => {
        if (run !== runRef.current) return; // stopped or replaced
        setSpeakingId(null);
        onEnd?.();
      };
      parts.forEach((part, i) => {
        const u = new SpeechSynthesisUtterance(part);
        u.lang = voice?.lang ?? lang;
        if (voice) u.voice = voice;
        u.rate = rate;
        u.pitch = pitch;
        if (i === parts.length - 1) {
          u.onend = finish;
          u.onerror = finish;
        }
        synth.speak(u);
      });
      setSpeakingId(id);
    },
    [],
  );

  return { supported, speakingId, speak, stop };
}
