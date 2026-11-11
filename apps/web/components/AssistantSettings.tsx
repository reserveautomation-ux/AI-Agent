"use client";

import { useState, type FormEvent } from "react";
import { post, STYLES, type AssistantStyle, type ReplyLength } from "@/lib/api";
import {
  isNatural,
  useSpeak,
  useVoiceList,
  voicesFor,
  type VoicePrefs,
} from "@/lib/useSpeak";
import { VOICE_LANGUAGES } from "@/lib/useSpeech";
import {
  NATURAL_VOICES,
  naturalCovers,
  naturalVoice,
  useNaturalVoice,
} from "@/lib/naturalVoice";

const NAME_IDEAS = ["Maya", "Aria", "Jarvis", "Kabir", "Ira", "Nova"];

/** Name your assistant and choose how it sounds. */
export function AssistantSettings({
  name,
  style,
  length,
  lang,
  prefs,
  onClose,
  onSaved,
}: {
  name: string;
  style: AssistantStyle;
  length: ReplyLength;
  lang: string;
  prefs: VoicePrefs;
  onClose: () => void;
  onSaved: (
    name: string,
    style: AssistantStyle,
    length: ReplyLength,
    lang: string,
    prefs: VoicePrefs,
  ) => void;
}) {
  const [draftName, setDraftName] = useState(
    name === "AI Assistant" ? "" : name,
  );
  const [draftStyle, setDraftStyle] = useState(style);
  const [draftLength, setDraftLength] = useState(length);
  const [draftLang, setDraftLang] = useState(lang);
  const [draft, setDraft] = useState<VoicePrefs>(prefs);
  const natural = useNaturalVoice();
  const canNatural = naturalVoice.supported();
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
      if (shownName !== name || draftStyle !== style || draftLength !== length)
        await post("/me/assistant", {
          name: shownName,
          style: draftStyle,
          length: draftLength,
        });
      preview.stop();
      onSaved(shownName, draftStyle, draftLength, draftLang, draft);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sample = draftLang.startsWith("hi")
    ? `नमस्ते, मैं ${shownName} हूँ। आज मैं आपकी क्या मदद करूँ?`
    : `Hi, I'm ${shownName}. What can I do for you today?`;

  return (
    <div className="settings-scrim" onClick={onClose}>
      <form
        className="settings-card paper"
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        aria-label="Name and voice"
      >
        <p className="mono-label ruled">Your assistant</p>
        <h2>Name, personality &amp; voice</h2>

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
            <button
              type="button"
              key={n}
              className="suggest-chip"
              onClick={() => setDraftName(n)}
            >
              {n}
            </button>
          ))}
        </div>

        <div className="field">
          <span className="mono-label">Personality</span>
          <div className="engine-pick style-pick">
            {STYLES.map((s) => (
              <button
                type="button"
                key={s.key}
                className={`engine ${draftStyle === s.key ? "on" : ""}`}
                aria-pressed={draftStyle === s.key}
                onClick={() => setDraftStyle(s.key)}
              >
                <strong>{s.label}</strong>
                <span>{s.hint}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span className="mono-label">Replies</span>
          <div className="name-ideas">
            {(["short", "detailed"] as const).map((l) => (
              <button
                type="button"
                key={l}
                className={`suggest-chip ${draftLength === l ? "on" : ""}`}
                aria-pressed={draftLength === l}
                onClick={() => setDraftLength(l)}
              >
                {l === "short" ? "Short & to the point" : "Detailed"}
              </button>
            ))}
          </div>
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

        <div className="field">
          <span className="mono-label">Voice type</span>
          <div className="engine-pick">
            {canNatural && (
              <button
                type="button"
                className={`engine ${draft.engine === "natural" ? "on" : ""}`}
                onClick={() => {
                  setDraft((d) => ({ ...d, engine: "natural" }));
                  naturalVoice.load();
                }}
              >
                <strong>Natural voice</strong>
                <span>
                  Built into the app · free · English · one-time download (~90
                  MB)
                </span>
              </button>
            )}
            <button
              type="button"
              className={`engine ${draft.engine !== "natural" ? "on" : ""}`}
              onClick={() => setDraft((d) => ({ ...d, engine: "device" }))}
            >
              <strong>Device voices</strong>
              <span>Already on this device · free · every language</span>
            </button>
          </div>
        </div>

        {draft.engine === "natural" ? (
          <>
            <label className="field">
              <span className="mono-label">Natural voice</span>
              <select
                value={draft.natural}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, natural: e.target.value }))
                }
              >
                {NATURAL_VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="natural-status">
              {natural.status === "ready" && (
                <span className="ok-dot">
                  Ready · works offline on this device
                </span>
              )}
              {natural.status === "downloading" && (
                <>
                  <span>
                    Downloading once… {Math.round(natural.progress * 100)}%
                  </span>
                  <progress max={1} value={natural.progress} />
                </>
              )}
              {natural.status === "failed" && (
                <span className="chat-error">
                  Couldn&apos;t load it ({natural.error}).{" "}
                  <button
                    type="button"
                    className="text-btn"
                    onClick={() => naturalVoice.load()}
                  >
                    Try again
                  </button>
                </span>
              )}
              {natural.status === "idle" && (
                <button
                  type="button"
                  className="text-btn"
                  onClick={() => naturalVoice.load()}
                >
                  Download the natural voice
                </button>
              )}
            </div>
            {!naturalCovers(draftLang) && (
              <span className="hint">
                The natural voice speaks English. For this language your
                device&apos;s voice is used.
              </span>
            )}
          </>
        ) : (
          <label className="field">
            <span className="mono-label">Voice</span>
            <select
              value={draft.voiceURI}
              onChange={(e) =>
                setDraft((d) => ({ ...d, voiceURI: e.target.value }))
              }
            >
              <option value="">
                {voices[0]
                  ? `Automatic: most natural (${voices[0].name})`
                  : "Automatic (best for this language)"}
              </option>
              {voices.map((v) => (
                <option key={v.voiceURI} value={v.voiceURI}>
                  {v.name} · {v.lang}
                  {isNatural(v) ? " · natural" : ""}
                </option>
              ))}
            </select>
            {voices.length === 0 && (
              <span className="hint">
                This browser has no voice for this language yet; it will use its
                default.
              </span>
            )}
          </label>
        )}

        <div className="sliders">
          <label className="field">
            <span className="mono-label">Speed · {draft.rate.toFixed(2)}×</span>
            <input
              type="range"
              min={0.6}
              max={1.6}
              step={0.05}
              value={draft.rate}
              onChange={(e) =>
                setDraft((d) => ({ ...d, rate: Number(e.target.value) }))
              }
            />
          </label>
          <label className="field">
            <span className="mono-label">Pitch · {draft.pitch.toFixed(2)}</span>
            <input
              type="range"
              min={0.5}
              max={1.6}
              step={0.05}
              value={draft.pitch}
              onChange={(e) =>
                setDraft((d) => ({ ...d, pitch: Number(e.target.value) }))
              }
            />
          </label>
        </div>

        <p className="hint">
          Free voices from this device; ones marked “natural” sound the most
          human. Microsoft Edge and Chrome include natural voices; on a phone,
          download better ones for free in Settings (iPhone: Accessibility ›
          Spoken Content › Voices; Android: Text-to-speech).
        </p>
        {error && <p className="chat-error">{error}</p>}

        <div className="settings-actions">
          <button
            type="button"
            className="text-btn"
            onClick={() =>
              preview.speakingId
                ? preview.stop()
                : preview.speak(sample, draftLang, "preview")
            }
          >
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
