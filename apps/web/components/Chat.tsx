"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Markdown } from "@/components/Markdown";
import {
  api,
  ApiError,
  joinNames,
  serviceName,
  streamChat,
  type ChatMessage,
  type ChatTaskRef,
  type Conversation,
  type ConversationDetail,
  type Me,
} from "@/lib/api";
import { useSpeak } from "@/lib/useSpeak";
import { useSpeech, VOICE_LANGUAGES } from "@/lib/useSpeech";

const SUGGESTIONS = [
  "Email Rahul that tomorrow's demo moves to 4pm",
  "Make a one-page website for my café and publish it",
  "Find 20 fitness creators in Pune as a spreadsheet",
  "WhatsApp my team that standup is at 11 today",
  "What's free on my calendar on Friday?",
  "Explain mutual funds vs index funds simply",
];

const ACTIVE = new Set(["draft", "planned", "queued", "running", "verifying", "waiting_for_approval", "blocked"]);
const STATUS_TEXT: Record<string, string> = {
  draft: "Starting",
  planned: "Planned",
  queued: "Queued",
  running: "Working",
  verifying: "Checking",
  waiting_for_approval: "Needs your approval",
  blocked: "Waiting for you",
  completed: "Done",
  failed: "Couldn't finish",
  cancelled: "Cancelled",
  expired: "Expired",
};

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

type VoiceState = "off" | "listening" | "thinking" | "speaking" | "paused";

export function Chat() {
  const [me, setMe] = useState<Me | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tasks, setTasks] = useState<Record<string, ChatTaskRef>>({});
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState("en-IN");
  const [readAloud, setReadAloud] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [voice, setVoice] = useState<VoiceState>("off");
  const [heard, setHeard] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const activeRef = useRef<string | null>(null);
  const voiceRef = useRef<VoiceState>("off");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const baseRef = useRef("");
  activeRef.current = activeId;
  voiceRef.current = voice;

  const tts = useSpeak();
  const { speak, stop: stopSpeaking } = tts;

  useEffect(() => {
    setLang(load("voice.lang", "en-IN"));
    setReadAloud(load("chat.readAloud", false));
    api<Me>("/me").then(setMe).catch(() => {});
    api<Conversation[]>("/conversations").then(setConversations).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const openConversation = useCallback(async (id: string | null) => {
    abortRef.current?.abort();
    setActiveId(id);
    setSidebar(false);
    setError(null);
    if (!id) {
      setMessages([]);
      setTasks({});
      inputRef.current?.focus();
      return;
    }
    try {
      const d = await api<ConversationDetail>(`/conversations/${id}`);
      if (activeRef.current !== id) return;
      setMessages(d.messages);
      setTasks(d.tasks);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // While the workforce is busy on something from this chat, pick up its progress.
  const busyTasks = Object.values(tasks).some((t) => ACTIVE.has(t.status));
  useEffect(() => {
    if (!activeId || !busyTasks || streaming) return;
    const t = setInterval(async () => {
      try {
        const d = await api<ConversationDetail>(`/conversations/${activeId}`);
        if (activeRef.current !== activeId) return;
        setMessages((old) => {
          const fresh = d.messages.slice(old.length).filter((m) => m.meta.kind === "task_update");
          // Task news is read aloud too when "Read replies aloud" is on (not mid voice chat).
          if (fresh.length && readAloud && voiceRef.current === "off") {
            speak(fresh.map((m) => m.content).join(" "), lang, fresh.at(-1)!.id);
          }
          return d.messages;
        });
        setTasks(d.tasks);
      } catch {
        /* try again next tick */
      }
    }, 5000);
    return () => clearInterval(t);
  }, [activeId, busyTasks, streaming, readAloud, lang, speak]);

  const send = useCallback(
    async (text: string, via: "text" | "voice" = "text"): Promise<string> => {
      const content = text.trim();
      if (!content || streaming) return "";
      setError(null);
      setInput("");
      stopSpeaking();
      const now = new Date().toISOString();
      const replyId = `pending-${Date.now()}`;
      setMessages((m) => [
        ...m,
        { id: `u-${Date.now()}`, role: "user", content, via, meta: {}, created_at: now },
        { id: replyId, role: "assistant", content: "", via, meta: { kind: "reply", tasks: [] }, created_at: now },
      ]);
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      let reply = "";
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((ms) => ms.map((m) => (m.id === replyId ? fn(m) : m)));
      try {
        await streamChat(
          { content, conversation_id: activeRef.current, via },
          (e) => {
            if (e.type === "conversation") {
              if (!activeRef.current) {
                activeRef.current = e.id;
                setActiveId(e.id);
              }
              setConversations((cs) => [
                { id: e.id, title: e.title, created_at: now, updated_at: now },
                ...cs.filter((c) => c.id !== e.id),
              ]);
            } else if (e.type === "text") {
              reply += e.text;
              patch((m) => ({ ...m, content: m.content + e.text }));
            } else if (e.type === "task") {
              setTasks((t) => ({ ...t, [e.task.id]: e.task }));
              patch((m) => ({ ...m, meta: { ...m.meta, tasks: [...(m.meta.tasks ?? []), e.task] } }));
            } else if (e.type === "memory") {
              patch((m) => ({ ...m, meta: { ...m.meta, memories: [...(m.meta.memories ?? []), e.content] } }));
            } else if (e.type === "done") {
              reply = e.text;
              patch((m) => ({ ...m, id: e.message_id, content: e.text }));
            } else if (e.type === "error") {
              setError(e.message);
            }
          },
          controller.signal,
        );
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError(e instanceof ApiError ? e.message : "Couldn't reach your assistant. Check your connection.");
          setMessages((ms) => ms.filter((m) => m.id !== replyId || m.content));
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
      return reply;
    },
    [streaming, stopSpeaking],
  );

  // --- typing + dictation ---------------------------------------------------------
  const dictation = useSpeech({
    lang,
    onTranscript: (t) => setInput(baseRef.current ? `${baseRef.current} ${t}` : t),
  });
  const toggleDictation = () => {
    if (dictation.listening) return dictation.stop();
    baseRef.current = input.trim();
    dictation.start();
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (dictation.listening) dictation.stop();
      void send(input).then((r) => readAloud && r && tts.speak(r, lang, "last"));
    }
  };

  // --- voice conversation: listen → reply → speak → listen ----------------------------
  const listenRef = useRef<() => void>(() => {});
  const conversation = useSpeech({
    lang,
    continuous: false,
    onTranscript: setHeard,
    onDone: async (said) => {
      if (voiceRef.current !== "listening") return;
      if (!said.trim()) {
        setVoice("paused");
        return;
      }
      setVoice("thinking");
      const reply = await send(said, "voice");
      if ((voiceRef.current as VoiceState) === "off") return;
      if (!reply) {
        setVoice("paused");
        return;
      }
      setVoice("speaking");
      tts.speak(reply, lang, "voice", () => {
        if (voiceRef.current === "speaking") listenRef.current();
      });
    },
  });
  listenRef.current = () => {
    setHeard("");
    setVoice("listening");
    conversation.start();
  };
  const startVoice = () => {
    dictation.stop();
    tts.stop();
    listenRef.current();
  };
  const endVoice = () => {
    setVoice("off");
    conversation.stop();
    tts.stop();
    abortRef.current?.abort();
  };
  const tapOrb = () => {
    if (voice === "speaking") {
      tts.stop();
      listenRef.current(); // interrupt and talk
    } else if (voice === "listening") conversation.stop();
    else if (voice === "paused") listenRef.current();
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this chat?")) return;
    try {
      await api(`/conversations/${id}`, { method: "DELETE" });
      setConversations((cs) => cs.filter((c) => c.id !== id));
      if (activeId === id) void openConversation(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const name = me?.email?.split("@")[0]?.split(/[._-]/)[0];
  const greeting = name ? `How can I help, ${name[0].toUpperCase()}${name.slice(1)}?` : "How can I help?";

  return (
    <div className="chat">
      <aside className={`chat-side ${sidebar ? "open" : ""}`}>
        <button className="new-chat" onClick={() => openConversation(null)}>
          ＋ New chat
        </button>
        <nav aria-label="Chats">
          {conversations.length === 0 && <p className="muted small">Your chats appear here.</p>}
          {conversations.map((c) => (
            <div key={c.id} className={`chat-link ${c.id === activeId ? "active" : ""}`}>
              <button onClick={() => openConversation(c.id)} title={c.title}>
                {c.title}
              </button>
              <button className="chat-del" onClick={() => remove(c.id)} aria-label={`Delete ${c.title}`}>
                ×
              </button>
            </div>
          ))}
        </nav>
        <div className="chat-side-foot">
          <label className="check">
            Voice
            <select
              value={lang}
              onChange={(e) => {
                setLang(e.target.value);
                save("voice.lang", e.target.value);
              }}
              aria-label="Voice language"
            >
              {VOICE_LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          {tts.supported && (
            <label className="check">
              <input
                type="checkbox"
                checked={readAloud}
                onChange={(e) => {
                  setReadAloud(e.target.checked);
                  save("chat.readAloud", e.target.checked);
                  if (!e.target.checked) tts.stop();
                }}
              />
              Read replies aloud
            </label>
          )}
        </div>
      </aside>
      {sidebar && <div className="chat-scrim" onClick={() => setSidebar(false)} />}

      <section className="chat-main-col">
        <div className="chat-top">
          <button className="ghost small chat-menu" onClick={() => setSidebar(true)} aria-label="Show chats">
            ☰ Chats
          </button>
          <span className="muted small">
            {conversations.find((c) => c.id === activeId)?.title ?? "New chat"}
          </span>
        </div>

        <div className="chat-scroll">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <h1>{greeting}</h1>
              <p className="muted">
                Ask anything, or tell me what to get done. I remember what you tell me, and my
                workforce handles the real work. Nothing is sent, booked or paid without your OK.
              </p>
              <div className="suggest">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-log">
              {messages.map((m, idx) => (
                <MessageView
                  key={m.id}
                  m={m}
                  tasks={tasks}
                  typing={streaming && idx === messages.length - 1 && m.role === "assistant"}
                  speaking={tts.speakingId === m.id}
                  onSpeak={tts.supported ? () => (tts.speakingId === m.id ? tts.stop() : tts.speak(m.content, lang, m.id)) : undefined}
                />
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {error && <p className="error-text chat-error">{error}</p>}
        {dictation.error && <p className="error-text chat-error">{dictation.error}</p>}

        <div className="composer">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder={dictation.listening ? "Listening… speak now" : "Message your assistant"}
            aria-label="Message"
          />
          <div className="composer-actions">
            {dictation.supported && (
              <button
                className={`icon-btn ${dictation.listening ? "rec" : ""}`}
                onClick={toggleDictation}
                aria-label={dictation.listening ? "Stop dictation" : "Dictate"}
                title="Dictate"
                disabled={voice !== "off"}
              >
                🎙
              </button>
            )}
            {streaming ? (
              <button className="icon-btn send" onClick={() => abortRef.current?.abort()} aria-label="Stop">
                ■
              </button>
            ) : input.trim() ? (
              <button
                className="icon-btn send"
                onClick={() => {
                  if (dictation.listening) dictation.stop();
                  void send(input).then((r) => readAloud && r && tts.speak(r, lang, "last"));
                }}
                aria-label="Send"
              >
                ↑
              </button>
            ) : (
              conversation.supported &&
              tts.supported && (
                <button className="icon-btn send" onClick={startVoice} aria-label="Talk to your assistant" title="Voice conversation">
                  ◉
                </button>
              )
            )}
          </div>
        </div>
        <p className="muted small composer-note">
          Enter to send · Shift+Enter for a new line · ◉ for a voice conversation
        </p>
      </section>

      {voice !== "off" && (
        <div className="voice-mode" role="dialog" aria-label="Voice conversation">
          <button className={`orb ${voice}`} onClick={tapOrb} aria-label="Tap to talk or interrupt">
            <span />
          </button>
          <p className="voice-state">
            {
              {
                listening: "Listening…",
                thinking: "Thinking…",
                speaking: "Speaking · tap to interrupt",
                paused: "Tap the circle to talk",
                off: "",
              }[voice]
            }
          </p>
          <p className="voice-heard">{voice === "listening" ? heard : ""}</p>
          {conversation.error && <p className="error-text">{conversation.error}</p>}
          <button className="ghost" onClick={endVoice}>
            End voice
          </button>
        </div>
      )}
    </div>
  );
}

function MessageView({
  m,
  tasks,
  typing,
  speaking,
  onSpeak,
}: {
  m: ChatMessage;
  tasks: Record<string, ChatTaskRef>;
  typing: boolean;
  speaking: boolean;
  onSpeak?: () => void;
}) {
  if (m.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">
          {m.via === "voice" && <span className="via">🎙 </span>}
          {m.content}
        </div>
      </div>
    );
  }
  const update = m.meta.kind === "task_update" && m.meta.task_id ? tasks[m.meta.task_id] : undefined;
  return (
    <div className={`msg assistant ${m.meta.kind === "task_update" ? "update" : ""}`}>
      {update && <TaskChip t={update} label="Task update" />}
      {m.content ? <Markdown text={m.content} /> : typing ? <span className="typing" aria-label="Thinking"><i /><i /><i /></span> : null}
      {(m.meta.tasks ?? []).map((t) => (
        <TaskChip key={t.id} t={tasks[t.id] ?? t} label="Started a task" />
      ))}
      {(m.meta.memories ?? []).map((x) => (
        <p key={x} className="muted small memory-note">
          💾 Remembered: {x}
        </p>
      ))}
      {m.meta.interrupted && <p className="muted small">(reply was cut off)</p>}
      {!typing && m.content && (
        <div className="msg-tools">
          <button className="ghost small" onClick={() => navigator.clipboard?.writeText(m.content)} title="Copy">
            Copy
          </button>
          {onSpeak && (
            <button className="ghost small" onClick={onSpeak} title="Read aloud">
              {speaking ? "■ Stop" : "🔊 Listen"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TaskChip({ t, label }: { t: ChatTaskRef; label: string }) {
  const waiting = t.status === "blocked" ? (t.waiting_for_connection ?? []) : [];
  const tone =
    t.status === "completed" ? "ok" : t.status === "failed" ? "bad" : ACTIVE.has(t.status) && t.status !== "blocked" && t.status !== "waiting_for_approval" ? "info" : "warn";
  return (
    <div className="task-chip">
      <span className="muted small">{label}</span>
      <Link href={`/tasks/${t.id}`} className="task-chip-title">
        {t.title}
      </Link>
      <span className={`badge ${tone}`}>{STATUS_TEXT[t.status] ?? t.status}</span>
      {t.status === "waiting_for_approval" && (
        <Link className="button small-link" href="/approvals">
          Review & approve
        </Link>
      )}
      {waiting.length > 0 && (
        <Link className="button small-link" href={`/connections?need=${waiting.join(",")}`}>
          Connect {joinNames(waiting.map(serviceName))}
        </Link>
      )}
    </div>
  );
}
