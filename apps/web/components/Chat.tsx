"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Markdown } from "@/components/Markdown";
import {
  api,
  ApiError,
  post,
  joinNames,
  serviceName,
  streamChat,
  type ChatMessage,
  type ChatTaskRef,
  type Conversation,
  type ConversationDetail,
  type Me,
} from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { DEFAULT_VOICE, useSpeak, type VoicePrefs } from "@/lib/useSpeak";
import { AssistantSettings } from "@/components/AssistantSettings";
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

  const [voicePrefs, setVoicePrefs] = useState<VoicePrefs>(DEFAULT_VOICE);
  const [customize, setCustomize] = useState(false);
  const tts = useSpeak(voicePrefs);
  const { speak, stop: stopSpeaking } = tts;

  useEffect(() => {
    setLang(load("voice.lang", "en-IN"));
    setReadAloud(load("chat.readAloud", false));
    setVoicePrefs(load("voice.prefs", DEFAULT_VOICE));
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

  const stopAll = async () => {
    if (!me) return;
    const enabling = !me.workspace.kill_switch;
    if (enabling && !confirm("Stop all agents? New tasks are blocked until you resume.")) return;
    try {
      await post("/workspace/kill-switch", { enabled: enabling });
      window.location.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const title = conversations.find((c) => c.id === activeId)?.title;
  const assistantName = me?.assistant_name ?? "AI Assistant";

  return (
    <div className="chat paper">
      <aside className={`chat-side ${sidebar ? "open" : ""}`} aria-label="Conversations">
        <div className="side-head">
          <span className="mono-label">Conversations</span>
          <button className="text-btn" onClick={() => openConversation(null)}>
            + New
          </button>
        </div>
        <nav className="side-list">
          {conversations.length === 0 && <p className="side-empty">Your conversations appear here.</p>}
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
        <nav className="side-app" aria-label="App">
          <span className="mono-label">Workspace</span>
          {APP_LINKS.map((l) => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
          {me?.workspace.role === "owner" && (
            <button className="text-btn stop" onClick={stopAll}>
              {me.workspace.kill_switch ? "Resume agents" : "Stop all agents"}
            </button>
          )}
          <button className="text-btn" onClick={() => supabase().auth.signOut()}>
            Sign out
          </button>
        </nav>
        <div className="side-foot">
          <button className="text-btn" onClick={() => setCustomize(true)}>
            Name &amp; voice of {assistantName}
          </button>
          <label>
            <span className="mono-label">Voice</span>
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
            <label className="side-check">
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
        <header className="asst-head">
          <button className="avatar big" onClick={() => setCustomize(true)} aria-label={`Customize ${assistantName}`} title="Name and voice">
            <FeatherIcon />
            <i className="avatar-dot" />
          </button>
          <div className="asst-title">
            <h1>
              <button className="title-btn" onClick={() => setCustomize(true)} title="Name and voice">
                {assistantName}
              </button>
            </h1>
            <p className="mono-label">{title ? title : "Executive assistant"}</p>
          </div>
          <div className="asst-actions">
            <button className="icon-plain" onClick={() => openConversation(null)} aria-label="New conversation" title="New conversation">
              <PlusIcon />
            </button>
            <button className="icon-plain menu-btn" onClick={() => setSidebar(true)} aria-label="Show conversations">
              <MenuIcon />
            </button>
          </div>
        </header>

        <div className="chat-scroll">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <p className="mono-label ruled">Your assistant</p>
              <h2>{greeting}</h2>
              <p className="lede">
                Ask anything, or tell me what to get done. I remember what you tell me, and my
                workforce handles the real work. Nothing is sent, booked or paid without your OK.
              </p>
              <div className="suggest">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggest-card" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-log">
              <p className="mono-label ruled">Conversation transcript</p>
              {messages.map((m, idx) => (
                <MessageView
                  key={m.id}
                  m={m}
                  name={assistantName}
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

        {(error || dictation.error) && <p className="chat-error">{error ?? dictation.error}</p>}

        <div className="composer-wrap">
          <div className={`composer ${dictation.listening ? "listening" : ""}`}>
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder={dictation.listening ? "Listening… speak now" : "Write what you’re thinking…"}
              aria-label="Message"
            />
            {dictation.supported && (
              <button
                className={`icon-plain mic-btn ${dictation.listening ? "rec" : ""}`}
                onClick={toggleDictation}
                aria-label={dictation.listening ? "Stop dictation" : "Dictate"}
                title="Dictate"
                disabled={voice !== "off"}
              >
                <MicIcon />
              </button>
            )}
            {streaming ? (
              <button className="send-btn active" onClick={() => abortRef.current?.abort()} aria-label="Stop">
                <StopIcon />
              </button>
            ) : input.trim() ? (
              <button
                className="send-btn active"
                onClick={() => {
                  if (dictation.listening) dictation.stop();
                  void send(input).then((r) => readAloud && r && tts.speak(r, lang, "last"));
                }}
                aria-label="Send"
              >
                <ArrowIcon />
              </button>
            ) : conversation.supported && tts.supported ? (
              <button className="send-btn" onClick={startVoice} aria-label="Talk to your assistant" title="Voice conversation">
                <WaveIcon />
              </button>
            ) : (
              <button className="send-btn" disabled aria-label="Send">
                <ArrowIcon />
              </button>
            )}
          </div>
          <p className="mono-label composer-note">Shift + Enter for a new line</p>
        </div>
      </section>

      {customize && (
        <AssistantSettings
          name={assistantName}
          lang={lang}
          prefs={voicePrefs}
          onClose={() => setCustomize(false)}
          onSaved={(n, l, v) => {
            if (me) setMe({ ...me, assistant_name: n });
            setLang(l);
            save("voice.lang", l);
            setVoicePrefs(v);
            save("voice.prefs", v);
            setCustomize(false);
          }}
        />
      )}

      {voice !== "off" && (
        <div className="voice-mode paper" role="dialog" aria-label="Voice conversation">
          <p className="mono-label">Voice conversation</p>
          <button className={`orb ${voice}`} onClick={tapOrb} aria-label="Tap to talk or interrupt">
            <span className="orb-ring" />
            <span className="orb-core">
              <FeatherIcon />
            </span>
          </button>
          <p className="voice-state">
            {
              {
                listening: "Listening…",
                thinking: "Thinking…",
                speaking: "Speaking",
                paused: "Tap to talk",
                off: "",
              }[voice]
            }
          </p>
          <p className="mono-label">{voice === "speaking" ? "Tap the circle to interrupt" : voice === "listening" ? "Go ahead, I'm listening" : " "}</p>
          <p className="voice-heard">{voice === "listening" ? heard : ""}</p>
          {conversation.error && <p className="chat-error">{conversation.error}</p>}
          <button className="end-voice" onClick={endVoice}>
            End voice
          </button>
        </div>
      )}
    </div>
  );
}

const APP_LINKS = [
  { href: "/tasks", label: "Tasks" },
  { href: "/approvals", label: "Approvals" },
  { href: "/connections", label: "Connections" },
  { href: "/memory", label: "Memory" },
  { href: "/workforce", label: "Workforce" },
  { href: "/audit", label: "Audit log" },
];

function MessageView({
  m,
  tasks,
  typing,
  speaking,
  onSpeak,
  name,
}: {
  m: ChatMessage;
  tasks: Record<string, ChatTaskRef>;
  typing: boolean;
  speaking: boolean;
  onSpeak?: () => void;
  name: string;
}) {
  if (m.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{m.content}</div>
        <p className="mono-label who">{m.via === "voice" ? "You · voice" : "You"}</p>
      </div>
    );
  }
  if (m.meta.kind === "task_update" && m.meta.task_id) {
    const t = tasks[m.meta.task_id] ?? { id: m.meta.task_id, title: "Task", status: m.meta.status ?? "running" };
    return (
      <div className="msg assistant">
        <span className="avatar" aria-hidden>
          <FeatherIcon />
        </span>
        <div className="msg-body">
          <ToolCard t={t} description={m.content} />
          <p className="mono-label who">{name} · task update</p>
        </div>
      </div>
    );
  }
  return (
    <div className="msg assistant">
      <span className="avatar" aria-hidden>
        <FeatherIcon />
      </span>
      <div className="msg-body">
        <div className="bubble">
          {m.content ? (
            <Markdown text={m.content} />
          ) : typing ? (
            <span className="typing" aria-label="Thinking">
              <i />
              <i />
              <i />
            </span>
          ) : null}
          {m.meta.interrupted && <p className="cut">Reply was cut off.</p>}
        </div>
        {(m.meta.tasks ?? []).map((t) => (
          <ToolCard key={t.id} t={tasks[t.id] ?? t} description="Handed to your workforce. Updates appear here." />
        ))}
        {(m.meta.memories ?? []).map((x) => (
          <div key={x} className="tool-card memory">
            <div className="tool-head">
              <span className="tool-icon">
                <BookIcon />
              </span>
              <div>
                <p className="tool-title">{x}</p>
                <p className="mono-label">Saved to memory</p>
              </div>
            </div>
          </div>
        ))}
        <div className="who-row">
          <p className="mono-label who">{m.via === "voice" ? `${name} · voice transcript` : name}</p>
          {!typing && m.content && (
            <span className="msg-tools">
              <button onClick={() => navigator.clipboard?.writeText(m.content)}>Copy</button>
              {onSpeak && <button onClick={onSpeak}>{speaking ? "Stop" : "Listen"}</button>}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function statusLine(t: ChatTaskRef): [string, string] {
  const waiting = t.status === "blocked" ? (t.waiting_for_connection ?? []) : [];
  if (waiting.length) return [`Waiting for ${joinNames(waiting.map(serviceName))}`, "wait"];
  return (
    (
      {
        draft: ["Starting", "work"],
        planned: ["Queued", "work"],
        queued: ["Queued", "work"],
        running: ["Working", "work"],
        verifying: ["Checking the result", "work"],
        waiting_for_approval: ["Needs your approval", "wait"],
        blocked: ["Needs your input", "wait"],
        completed: ["Done", "done"],
        failed: ["Couldn't finish", "fail"],
        cancelled: ["Cancelled", "fail"],
        expired: ["Expired", "fail"],
      } as Record<string, [string, string]>
    )[t.status] ?? [STATUS_TEXT[t.status] ?? t.status, "work"]
  );
}

function ToolCard({ t, description }: { t: ChatTaskRef; description?: string }) {
  const [label, tone] = statusLine(t);
  const waiting = t.status === "blocked" ? (t.waiting_for_connection ?? []) : [];
  const Icon = { done: CheckIcon, fail: BanIcon, wait: waiting.length ? PlugIcon : PenIcon, work: SparkIcon }[tone] ?? SparkIcon;
  return (
    <div className={`tool-card ${tone}`}>
      <div className="tool-head">
        <span className="tool-icon">
          <Icon />
        </span>
        <div>
          <Link href={`/tasks/${t.id}`} className="tool-title">
            {t.title}
          </Link>
          <p className="mono-label">{label}</p>
        </div>
      </div>
      {description && (
        <div className="tool-desc">
          <Markdown text={description} />
        </div>
      )}
      {(t.status === "waiting_for_approval" || waiting.length > 0) && (
        <div className="tool-actions">
          {t.status === "waiting_for_approval" && <Link href="/approvals">Review & approve →</Link>}
          {waiting.length > 0 && (
            <Link href={`/connections?need=${waiting.join(",")}`}>Connect {joinNames(waiting.map(serviceName))} →</Link>
          )}
        </div>
      )}
    </div>
  );
}

// --- line icons (inherit the text colour) ---------------------------------------------

function Svg({ children, size = 20 }: { children: React.ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {children}
    </svg>
  );
}
const FeatherIcon = () => (
  <Svg>
    <path d="M20 4c-6 0-11 3.5-13 9.5L5.5 18.5" />
    <path d="M20 4c0 6-3 11-9.5 12.5L7 17" />
    <path d="M9 12.5h5.5" />
    <path d="M4 20l3.5-3.5" />
  </Svg>
);
const PlusIcon = () => (
  <Svg size={26}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);
const MenuIcon = () => (
  <Svg size={26}>
    <path d="M5 7h14M5 12h14M5 17h14" />
  </Svg>
);
const MicIcon = () => (
  <Svg size={22}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
  </Svg>
);
const ArrowIcon = () => (
  <Svg size={22}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Svg>
);
const StopIcon = () => (
  <Svg size={18}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" />
  </Svg>
);
const WaveIcon = () => (
  <Svg size={22}>
    <path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 11v2" />
  </Svg>
);
const CheckIcon = () => (
  <Svg>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Svg>
);
const BanIcon = () => (
  <Svg>
    <circle cx="12" cy="12" r="8" />
    <path d="M6.5 6.5l11 11" />
  </Svg>
);
const PlugIcon = () => (
  <Svg>
    <path d="M9 3v4M15 3v4M7 7h10v4a5 5 0 0 1-10 0V7zM12 16v5" />
  </Svg>
);
const PenIcon = () => (
  <Svg>
    <path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4" />
  </Svg>
);
const SparkIcon = () => (
  <Svg>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6" />
  </Svg>
);
const BookIcon = () => (
  <Svg>
    <path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4zM5 17a3 3 0 0 1 3-3h10" />
  </Svg>
);
