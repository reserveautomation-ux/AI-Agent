"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Minimal typings for the Web Speech API (Chrome, Edge, Safari, Android, iOS 14.5+).
interface SpeechRecognitionResultLike {
  readonly isFinal: boolean;
  readonly 0: { transcript: string };
}
interface SpeechRecognitionEventLike {
  readonly results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const VOICE_LANGUAGES: { code: string; label: string }[] = [
  { code: "en-IN", label: "English (India)" },
  { code: "hi-IN", label: "हिन्दी" },
  { code: "mr-IN", label: "मराठी" },
  { code: "gu-IN", label: "ગુજરાતી" },
  { code: "bn-IN", label: "বাংলা" },
  { code: "ta-IN", label: "தமிழ்" },
  { code: "te-IN", label: "తెలుగు" },
  { code: "kn-IN", label: "ಕನ್ನಡ" },
  { code: "ml-IN", label: "മലയാളം" },
  { code: "pa-IN", label: "ਪੰਜਾਬੀ" },
  { code: "en-US", label: "English (US)" },
  { code: "en-GB", label: "English (UK)" },
];

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone permission was denied. Allow it in your browser settings.",
  "service-not-allowed": "Voice input is blocked in this browser.",
  "no-speech": "Didn't catch that. Tap the mic and try again.",
  "audio-capture": "No microphone found.",
  network: "Voice recognition needs an internet connection.",
};

interface Options {
  lang: string;
  /** Called with the full transcript so far (interim results included). */
  onTranscript: (text: string) => void;
  /** Called once when listening stops, with the final transcript. */
  onDone?: (text: string) => void;
  /** Keep listening through pauses (dictation). False: stop when the person stops talking. */
  continuous?: boolean;
}

export function useSpeech({ lang, onTranscript, onDone, continuous = true }: Options) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const textRef = useRef("");
  const cbRef = useRef({ onTranscript, onDone });
  cbRef.current = { onTranscript, onDone };

  useEffect(() => {
    setSupported(getCtor() !== null);
    return () => recRef.current?.abort();
  }, []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor || recRef.current) return;
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = continuous; // dictation keeps listening through short pauses
    rec.interimResults = true; // show words as they are spoken
    textRef.current = "";
    rec.onresult = (e) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      textRef.current = text.trim();
      cbRef.current.onTranscript(textRef.current);
    };
    rec.onerror = (e) => {
      if (e.error !== "aborted") setError(ERRORS[e.error] ?? `Voice error: ${e.error}`);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      cbRef.current.onDone?.(textRef.current);
    };
    setError(null);
    recRef.current = rec;
    rec.start();
    setListening(true);
  }, [lang, continuous]);

  const stop = useCallback(() => recRef.current?.stop(), []);

  return { supported, listening, error, start, stop };
}
