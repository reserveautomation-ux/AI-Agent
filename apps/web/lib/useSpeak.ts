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

/** The assistant's voice: the browser's built-in text-to-speech (free, works offline). */
export function useSpeak() {
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
      const voices = synth.getVoices();
      const voice =
        voices.find((v) => v.lang === lang) ??
        voices.find((v) => v.lang.startsWith(lang.split("-")[0])) ??
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
        u.lang = lang;
        if (voice) u.voice = voice;
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
