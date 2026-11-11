"use client";

import { useState, type FormEvent } from "react";
import { post } from "@/lib/api";
import { useSpeak, useVoiceList, voicesFor, type VoicePrefs } from "@/lib/useSpeak";
import { VOICE_LANGUAGES } from "@/lib/useSpeech";

const NAME_IDEAS = ["Maya", "Aria", "Jarvis", "Kabir", "Ira", "Nova"];

/** Name your assistant and choose how it sounds. */
export function AssistantSettings({
  name,
  lang,
  prefs,
  onClose,
  onSaved,
}: {
  name: string;
  lang: string;
  prefs: VoicePrefs;
  onClose: () => void;
  onSaved: (name: string, lang: string, prefs: VoicePrefs) => void;
}) {
  const [draftName, setDraftName] = useState(name === "AI Assistant" ? "" : name);
  const [draftLang, setDraftLang] = useState(lang);
  const [draft, setDraft] = useState<VoicePrefs>(prefs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useVoiceList(); // re-render once the browser has loaded its voices
  const voices = voicesFor(draftLang);
  const preview = useSpeak(draft);
  const shownName = draftName.trim() || "AI Assistant";

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (shownName !== name) await post("/me/assistant", { name: shownName });
      preview.stop();
      onSaved(shownName, draftLang, draft);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sample =
    draftLang.startsWith("hi")
      ? `नमस्ते, मैं ${shownName} हूँ। आज मैं आपकी क्या मदद करूँ?`
      : `Hi, I'm ${shownName}. What can I do for you today?`;

  return (
    <div className="settings-scrim" onClick={onClose}>
      <form className="settings-card paper" onSubmit={save} onClick={(e) => e.stopPropagation()} aria-label="Name and voice">
        <p className="mono-label ruled">Your assistant</p>
        <h2>Name &amp; voice</h2>

        <label className="field">
          <span className="mono-label">Name</span>
          <input
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            placeholder="AI Assistant"
            maxLength={40}
            autoFocus
          />
        </label>
        <div className="name-ideas">
          {NAME_IDEAS.map((n) => (
            <button type="button" key={n} className="suggest-chip" onClick={() => setDraftName(n)}>
              {n}
            </button>
          ))}
        </div>

        <label className="field">
          <span className="mono-label">Language</span>
          <select
            value={draftLang}
            onChange={(e) => {
              setDraftLang(e.target.value);
              setDraft((d) => ({ ...d, voiceURI: "" }));
            }}
          >
            {VOICE_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="mono-label">Voice</span>
          <select value={draft.voiceURI} onChange={(e) => setDraft((d) => ({ ...d, voiceURI: e.target.value }))}>
            <option value="">Automatic (best for this language)</option>
            {voices.map((v) => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name} · {v.lang}
              </option>
            ))}
          </select>
          {voices.length === 0 && (
            <span className="hint">This browser has no voice for this language yet; it will use its default.</span>
          )}
        </label>

        <div className="sliders">
          <label className="field">
            <span className="mono-label">Speed · {draft.rate.toFixed(2)}×</span>
            <input type="range" min={0.6} max={1.6} step={0.05} value={draft.rate} onChange={(e) => setDraft((d) => ({ ...d, rate: Number(e.target.value) }))} />
          </label>
          <label className="field">
            <span className="mono-label">Pitch · {draft.pitch.toFixed(2)}</span>
            <input type="range" min={0.5} max={1.6} step={0.05} value={draft.pitch} onChange={(e) => setDraft((d) => ({ ...d, pitch: Number(e.target.value) }))} />
          </label>
        </div>

        <p className="hint">
          Voices come from this device, so each phone or computer can sound different. More natural
          voices can be added in your device&apos;s settings (iPhone: Settings › Accessibility ›
          Spoken Content › Voices; Android: Settings › Text-to-speech).
        </p>
        {error && <p className="chat-error">{error}</p>}

        <div className="settings-actions">
          <button type="button" className="text-btn" onClick={() => (preview.speakingId ? preview.stop() : preview.speak(sample, draftLang, "preview"))}>
            {preview.speakingId ? "■ Stop" : "▶ Preview voice"}
          </button>
          <span style={{ flex: 1 }} />
          <button type="button" className="end-voice" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="save-btn" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
