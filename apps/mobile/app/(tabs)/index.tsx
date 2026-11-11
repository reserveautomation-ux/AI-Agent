import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Linking from "expo-linking";
import { router, useFocusEffect } from "expo-router";
import * as Clipboard from "expo-clipboard";
import * as Speech from "expo-speech";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Alert,
  Animated,
  Easing,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Switch,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  AssistantSettings,
  DEFAULT_VOICE,
  type VoicePrefs,
} from "@/components/AssistantSettings";
import {
  photoSource,
  pickPdfs,
  pickPhotos,
  takePhoto,
  type ChatFile,
} from "@/lib/attachments";
import { ChatText } from "@/components/ChatText";
import { Icon, type IconName } from "@/components/ui";
import {
  ApiError,
  api,
  streamChat,
  type ChatMessage,
  type ChatTaskRef,
  type Conversation,
  type ConversationDetail,
  type Me,
} from "@/lib/api";
import { confirmAsync } from "@/lib/confirm";
import { joinNames, serviceName } from "@/lib/labels";
import { Speaker, phoneVoices } from "@/lib/speaker";
import { FONTS, usePaper } from "@/lib/theme";
import { VOICE_LANGUAGES, useVoice } from "@/lib/useVoice";

const SUGGESTIONS = [
  "Email Rahul that tomorrow’s demo moves to 4pm",
  "Make a one-page website for my café and publish it",
  "WhatsApp my team that standup is at 11 today",
  "What’s free on my calendar on Friday?",
  "Explain index funds simply",
];
const ACTIVE = new Set([
  "draft",
  "planned",
  "queued",
  "running",
  "verifying",
  "waiting_for_approval",
  "blocked",
]);
const STATUS_TEXT: Record<string, string> = {
  draft: "Starting",
  planned: "Planned",
  queued: "Queued",
  running: "Working",
  verifying: "Checking",
  waiting_for_approval: "Needs your approval",
  blocked: "Waiting for you",
  completed: "Done",
  failed: "Couldn’t finish",
  cancelled: "Cancelled",
  expired: "Expired",
};

const I = {
  menu: { ios: "line.3.horizontal", android: "menu", web: "menu" },
  plus: { ios: "plus", android: "add", web: "add" },
  feather: { ios: "leaf", android: "history_edu", web: "history_edu" },
  check: { ios: "checkmark", android: "check", web: "check" },
  ban: { ios: "nosign", android: "block", web: "block" },
  plug: { ios: "powerplug", android: "power", web: "power" },
  pen: { ios: "pencil", android: "edit", web: "edit" },
  spark: { ios: "sparkles", android: "auto_awesome", web: "auto_awesome" },
  book: { ios: "book.closed", android: "menu_book", web: "menu_book" },
  clock: { ios: "alarm", android: "alarm", web: "alarm" },
  clip: { ios: "paperclip", android: "attach_file", web: "attach_file" },
  whatsapp: {
    ios: "bubble.left.and.text.bubble.right",
    android: "chat",
    web: "chat",
  },
  pay: {
    ios: "indianrupeesign.circle",
    android: "currency_rupee",
    web: "currency_rupee",
  },
  camera: { ios: "camera", android: "photo_camera", web: "photo_camera" },
  photo: {
    ios: "photo.on.rectangle",
    android: "photo_library",
    web: "photo_library",
  },
  doc: { ios: "doc.text", android: "description", web: "description" },
  mic: { ios: "mic.fill", android: "mic", web: "mic" },
  send: { ios: "arrow.up", android: "arrow_upward", web: "arrow_upward" },
  stop: { ios: "stop.fill", android: "stop", web: "stop" },
  wave: { ios: "waveform", android: "graphic_eq", web: "graphic_eq" },
} satisfies Record<string, IconName>;

type VoiceState = "off" | "listening" | "thinking" | "speaking" | "paused";

export default function ChatScreen() {
  const p = usePaper();
  const insets = useSafeAreaInsets();
  const [me, setMe] = useState<Me | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [listOpen, setListOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tasks, setTasks] = useState<Record<string, ChatTaskRef>>({});
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState("en-IN");
  const [readAloud, setReadAloud] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceState>("off");
  const [heard, setHeard] = useState("");
  const [voicePrefs, setVoicePrefs] = useState<VoicePrefs>(DEFAULT_VOICE);
  const [customize, setCustomize] = useState(false);

  const activeRef = useRef<string | null>(null);
  const voiceRef = useRef<VoiceState>("off");
  const modeRef = useRef<"dictate" | "converse">("dictate");
  const baseRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const [mode, setModeState] = useState<"dictate" | "converse">("dictate");
  useEffect(() => {
    activeRef.current = activeId;
  }, [activeId]);
  // State for rendering, ref for callbacks that run later (speech events, timers).
  const setVoiceBoth = (v: VoiceState) => {
    voiceRef.current = v;
    setVoice(v);
  };
  const setMode = (m: "dictate" | "converse") => {
    modeRef.current = m;
    setModeState(m);
  };

  useEffect(() => {
    AsyncStorage.multiGet(["voice.lang", "chat.readAloud", "voice.prefs"])
      .then(([[, l], [, r], [, v]]) => {
        if (l) setLang(l);
        setReadAloud(r === "1");
        if (v) setVoicePrefs({ ...DEFAULT_VOICE, ...JSON.parse(v) });
      })
      .catch(() => {});
    api<Me>("/me")
      .then(setMe)
      .catch(() => {});
  }, []);

  useFocusEffect(
    useCallback(() => {
      api<Conversation[]>("/conversations")
        .then(setConversations)
        .catch(() => {});
      return () => Speech.stop();
    }, []),
  );

  // --- the assistant's voice ------------------------------------------------------
  // The assistant's voice: speaks sentence by sentence, even while a reply is still arriving.
  const [speaker] = useState(() => new Speaker((id) => setSpeakingId(id)));
  useEffect(() => {
    void phoneVoices();
    return () => speaker.stop();
  }, [speaker]);
  const stopSpeaking = useCallback(() => speaker.stop(), [speaker]);
  const speak = useCallback(
    (text: string, id: string, onEnd?: () => void) =>
      speaker.speak(text, id, lang, voicePrefs, onEnd),
    [speaker, lang, voicePrefs],
  );

  const openConversation = useCallback(async (id: string | null) => {
    abortRef.current?.abort();
    setListOpen(false);
    setActiveId(id);
    setError(null);
    if (!id) {
      setMessages([]);
      setTasks({});
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

  // Pick up task progress (done, needs approval, waiting for a connection).
  const busy = Object.values(tasks).some((t) => ACTIVE.has(t.status));
  useEffect(() => {
    if (!activeId || !busy || streaming) return;
    const timer = setInterval(async () => {
      try {
        const d = await api<ConversationDetail>(`/conversations/${activeId}`);
        if (activeRef.current !== activeId) return;
        setMessages((old) => {
          const fresh = d.messages
            .slice(old.length)
            .filter((m) => m.meta.kind === "task_update");
          if (fresh.length && readAloud && voiceRef.current === "off") {
            speak(fresh.map((m) => m.content).join(" "), fresh.at(-1)!.id);
          }
          return d.messages;
        });
        setTasks(d.tasks);
      } catch {
        /* next tick */
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [activeId, busy, streaming, readAloud, speak]);

  const send = useCallback(
    async (
      text: string,
      via: "text" | "voice" = "text",
      onDelta?: (t: string) => void,
      atts: ChatFile[] = [],
    ): Promise<string> => {
      const content = text.trim();
      if ((!content && !atts.length) || streaming) return "";
      setError(null);
      setInput("");
      stopSpeaking();
      const now = new Date().toISOString();
      const replyId = `pending-${Date.now()}`;
      setMessages((m) => [
        ...m,
        {
          id: `u-${Date.now()}`,
          role: "user",
          content,
          via,
          meta: atts.length ? { attachments: atts } : {},
          created_at: now,
        },
        {
          id: replyId,
          role: "assistant",
          content: "",
          via,
          meta: { kind: "reply" },
          created_at: now,
        },
      ]);
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      let reply = "";
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((ms) => ms.map((m) => (m.id === replyId ? fn(m) : m)));
      try {
        await streamChat(
          {
            content,
            conversation_id: activeRef.current,
            via,
            attachments: atts.map((a) => a.id),
          },
          (e) => {
            if (e.type === "conversation") {
              if (!activeRef.current) {
                activeRef.current = e.id;
                setActiveId(e.id);
              }
              setConversations((cs) => [
                { id: e.id, title: e.title, created_at: now, updated_at: now },
                ...cs.filter((x) => x.id !== e.id),
              ]);
            } else if (e.type === "text") {
              reply += e.text;
              onDelta?.(e.text);
              patch((m) => ({ ...m, content: m.content + e.text }));
            } else if (e.type === "task") {
              setTasks((t) => ({ ...t, [e.task.id]: e.task }));
              patch((m) => ({
                ...m,
                meta: { ...m.meta, tasks: [...(m.meta.tasks ?? []), e.task] },
              }));
            } else if (e.type === "action") {
              patch((m) => ({
                ...m,
                meta: {
                  ...m.meta,
                  actions: [...(m.meta.actions ?? []), e.action],
                },
              }));
            } else if (e.type === "schedule") {
              patch((m) => ({
                ...m,
                meta: {
                  ...m.meta,
                  schedules: [...(m.meta.schedules ?? []), e.schedule],
                },
              }));
            } else if (e.type === "memory") {
              patch((m) => ({
                ...m,
                meta: {
                  ...m.meta,
                  memories: [...(m.meta.memories ?? []), e.content],
                },
              }));
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
          setError(
            e instanceof ApiError
              ? e.message
              : "Couldn’t reach your assistant. Check your connection.",
          );
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

  /** Send, and (in voice mode or with read-aloud on) speak the reply while it streams in. */
  const sendSpoken = async (
    text: string,
    via: "text" | "voice",
    onSpoken?: () => void,
    atts: ChatFile[] = [],
  ): Promise<string> => {
    const talk = via === "voice" || readAloud;
    const id = via === "voice" ? "voice" : "last";
    let begun = false;
    const reply = await send(
      text,
      via,
      talk
        ? (t) => {
            if (!begun) {
              begun = true;
              speaker.begin(id, lang, voicePrefs, onSpoken);
              if (via === "voice") setVoiceBoth("speaking");
            }
            speaker.push(t);
          }
        : undefined,
      atts,
    );
    if (!talk) return reply;
    if (!reply) {
      if (begun) speaker.stop();
      return reply;
    }
    if (begun) speaker.end();
    else {
      if (via === "voice") setVoiceBoth("speaking");
      speak(reply, id, onSpoken);
    }
    return reply;
  };

  // Photos & PDFs waiting to be sent with the next message.
  const [files, setFiles] = useState<ChatFile[]>([]);
  const [uploading, setUploading] = useState(0);
  const [attachOpen, setAttachOpen] = useState(false);
  const attach = async (
    pick: (limit: number) => Promise<Promise<ChatFile>[]>,
  ) => {
    setAttachOpen(false);
    try {
      const jobs = await pick(Math.max(1, 5 - files.length));
      setUploading((n) => n + jobs.length);
      await Promise.all(
        jobs.map((job) =>
          job
            .then((f) => setFiles((fs) => [...fs, f].slice(0, 5)))
            .catch((e) => setError((e as Error).message))
            .finally(() => setUploading((n) => n - 1)),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const sendTyped = async () => {
    if (mic.listening) mic.stop();
    if (uploading) return;
    const atts = files;
    setFiles([]);
    await sendSpoken(input, "text", undefined, atts);
  };

  // One recognizer for both dictation and voice conversation.
  const mic = useVoice({
    lang,
    onText: (t) =>
      modeRef.current === "dictate"
        ? setInput(baseRef.current ? `${baseRef.current} ${t}` : t)
        : setHeard(t),
    onEnd: (said) => {
      if (modeRef.current === "converse") void onHeard(said);
    },
  });

  const listen = () => {
    setMode("converse");
    setHeard("");
    setVoiceBoth("listening");
    void mic.start();
  };
  const onHeard = async (said: string) => {
    if (voiceRef.current !== "listening") return;
    if (!said.trim()) return setVoiceBoth("paused");
    setVoiceBoth("thinking");
    // Starts talking at the first full sentence, like a person would.
    const reply = await sendSpoken(said, "voice", () => {
      if (voiceRef.current === "speaking") listen();
    });
    if ((voiceRef.current as VoiceState) === "off") return speaker.stop();
    if (!reply) setVoiceBoth("paused");
  };
  const startVoice = () => {
    if (mic.listening) mic.stop();
    stopSpeaking();
    listen();
  };
  const endVoice = () => {
    setVoiceBoth("off");
    setMode("dictate");
    mic.stop();
    stopSpeaking();
    abortRef.current?.abort();
  };
  const tapOrb = () => {
    if (voice === "speaking") {
      stopSpeaking();
      listen();
    } else if (voice === "listening") mic.stop();
    else if (voice === "paused") listen();
  };
  const toggleDictation = () => {
    if (mic.listening) return mic.stop();
    setMode("dictate");
    baseRef.current = input.trim();
    void mic.start();
  };

  const removeConversation = async (conv: Conversation) => {
    if (!(await confirmAsync("Delete this chat?", conv.title, "Delete", true)))
      return;
    try {
      await api(`/conversations/${conv.id}`, { method: "DELETE" });
      setConversations((cs) => cs.filter((x) => x.id !== conv.id));
      if (conv.id === activeId) void openConversation(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setPref = (key: string, value: string) =>
    AsyncStorage.setItem(key, value).catch(() => {});
  const first = me?.email?.split("@")[0]?.split(/[._-]/)[0];
  const greeting = first
    ? `How can I help, ${first[0].toUpperCase()}${first.slice(1)}?`
    : "How can I help?";
  const title = conversations.find((x) => x.id === activeId)?.title;
  const assistantName = me?.assistant_name ?? "AI Assistant";

  return (
    <View style={{ flex: 1, backgroundColor: p.bg, paddingTop: insets.top }}>
      <Grid />
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 14,
          paddingHorizontal: 16,
          paddingVertical: 12,
          borderBottomWidth: 1,
          borderBottomColor: p.line,
        }}
      >
        <Pressable
          onPress={() => setCustomize(true)}
          accessibilityRole="button"
          accessibilityLabel={`Name and voice of ${assistantName}`}
          style={{
            flex: 1,
            minWidth: 0,
            flexDirection: "row",
            alignItems: "center",
            gap: 14,
          }}
        >
          <Avatar big />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text
              numberOfLines={1}
              style={{
                fontFamily: FONTS.serif,
                fontSize: 30,
                color: p.ink,
                lineHeight: 34,
              }}
            >
              {assistantName}
            </Text>
            <Mono numberOfLines={1}>{title ?? "Executive assistant"}</Mono>
          </View>
        </Pressable>
        <IconButton
          icon={I.plus}
          label="New conversation"
          onPress={() => openConversation(null)}
        />
        <IconButton
          icon={I.menu}
          label="Show conversations"
          onPress={() => setListOpen(true)}
        />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        {messages.length === 0 ? (
          <ScrollView
            contentContainerStyle={{
              flexGrow: 1,
              padding: 20,
              paddingTop: 28,
              gap: 10,
            }}
            keyboardShouldPersistTaps="handled"
          >
            <Ruled>Your assistant</Ruled>
            <Text
              style={{
                fontFamily: FONTS.serif,
                fontSize: 36,
                lineHeight: 40,
                color: p.ink,
              }}
            >
              {greeting}
            </Text>
            <Text
              style={{
                fontFamily: FONTS.sans,
                fontSize: 16,
                lineHeight: 24,
                color: p.muted,
                marginBottom: 14,
              }}
            >
              Ask anything or tell me what to get done. I remember you, and my
              workforce does the real work. Nothing is sent, booked or paid
              without your OK.
            </Text>
            {SUGGESTIONS.map((s) => (
              <Pressable
                key={s}
                onPress={() => send(s)}
                accessibilityRole="button"
                style={({ pressed }) => ({
                  borderWidth: 1,
                  borderColor: p.line,
                  backgroundColor: p.card,
                  borderRadius: 18,
                  paddingVertical: 14,
                  paddingHorizontal: 16,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <Text
                  style={{ fontFamily: FONTS.sans, fontSize: 15, color: p.ink }}
                >
                  {s}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        ) : (
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(m) => m.id}
            ListHeaderComponent={<Ruled>Conversation transcript</Ruled>}
            contentContainerStyle={{ padding: 16, paddingTop: 24, gap: 22 }}
            onContentSizeChange={() =>
              listRef.current?.scrollToEnd({ animated: true })
            }
            keyboardShouldPersistTaps="handled"
            renderItem={({ item, index }) => (
              <Message
                m={item}
                name={assistantName}
                tasks={tasks}
                typing={
                  streaming &&
                  index === messages.length - 1 &&
                  item.role === "assistant"
                }
                speaking={speakingId === item.id}
                onSpeak={() =>
                  speakingId === item.id
                    ? stopSpeaking()
                    : speak(item.content, item.id)
                }
              />
            )}
          />
        )}

        {!!(error ?? (mode === "dictate" ? mic.error : null)) && (
          <Text
            style={{
              color: p.bad,
              fontFamily: FONTS.sans,
              paddingHorizontal: 20,
              marginBottom: 6,
            }}
          >
            {error ?? mic.error}
          </Text>
        )}
        <View style={{ paddingHorizontal: 12, paddingBottom: 10 }}>
          {(files.length > 0 || uploading > 0) && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{
                gap: 8,
                paddingBottom: 8,
                alignItems: "center",
              }}
            >
              {files.map((f) => (
                <View
                  key={f.id}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    borderWidth: 1,
                    borderColor: p.line,
                    backgroundColor: p.card,
                    borderRadius: 14,
                    padding: 4,
                    paddingRight: 2,
                  }}
                >
                  {f.preview ? (
                    <Image
                      source={{ uri: f.preview }}
                      style={{ width: 40, height: 40, borderRadius: 10 }}
                    />
                  ) : (
                    <View
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 10,
                        backgroundColor: p.terraSoft,
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <Text
                        style={{
                          fontFamily: FONTS.mono,
                          fontSize: 11,
                          color: p.terra,
                        }}
                      >
                        PDF
                      </Text>
                    </View>
                  )}
                  <Text
                    numberOfLines={1}
                    style={{
                      maxWidth: 120,
                      fontFamily: FONTS.sans,
                      color: p.ink,
                    }}
                  >
                    {f.name}
                  </Text>
                  <Pressable
                    onPress={() =>
                      setFiles((fs) => fs.filter((x) => x.id !== f.id))
                    }
                    accessibilityRole="button"
                    accessibilityLabel={`Remove ${f.name}`}
                    hitSlop={8}
                    style={{ padding: 6 }}
                  >
                    <Text style={{ color: p.muted, fontSize: 16 }}>×</Text>
                  </Pressable>
                </View>
              ))}
              {uploading > 0 && <Mono>Uploading…</Mono>}
            </ScrollView>
          )}
          <View
            style={{
              flexDirection: "row",
              alignItems: "flex-end",
              gap: 6,
              padding: 8,
              paddingLeft: 8,
              borderRadius: 30,
              borderWidth: 1,
              borderColor:
                mic.listening && mode === "dictate" ? p.terra : p.line,
              backgroundColor: p.card,
              shadowColor: "#2f3b45",
              shadowOpacity: 0.08,
              shadowRadius: 16,
              shadowOffset: { width: 0, height: 8 },
              elevation: 2,
            }}
          >
            <Pressable
              onPress={() => setAttachOpen(true)}
              accessibilityRole="button"
              accessibilityLabel="Attach a photo or PDF"
              disabled={files.length >= 5}
              hitSlop={6}
              style={{
                height: 48,
                width: 36,
                alignItems: "center",
                justifyContent: "center",
                opacity: files.length >= 5 ? 0.4 : 1,
              }}
            >
              <Icon name={I.clip} color={p.ink} size={22} />
            </Pressable>
            <TextInput
              value={input}
              onChangeText={setInput}
              placeholder={
                mic.listening && mode === "dictate"
                  ? "Listening… speak now"
                  : "Write what you’re thinking…"
              }
              placeholderTextColor={p.muted}
              multiline
              style={{
                flex: 1,
                color: p.ink,
                fontFamily: FONTS.sans,
                fontSize: 17,
                maxHeight: 130,
                paddingTop: 13,
                paddingBottom: 13,
              }}
              accessibilityLabel="Message"
            />
            {mic.available && (
              <Pressable
                onPress={toggleDictation}
                accessibilityRole="button"
                accessibilityLabel={
                  mic.listening ? "Stop dictation" : "Dictate"
                }
                hitSlop={6}
                style={{
                  height: 48,
                  width: 40,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Icon
                  name={I.mic}
                  color={mic.listening && mode === "dictate" ? p.bad : p.ink}
                  size={22}
                />
              </Pressable>
            )}
            {streaming ? (
              <SendButton
                icon={I.stop}
                label="Stop"
                onPress={() => abortRef.current?.abort()}
                active
              />
            ) : input.trim() || files.length ? (
              <SendButton
                icon={I.send}
                label="Send"
                onPress={sendTyped}
                active
              />
            ) : mic.available ? (
              <SendButton
                icon={I.wave}
                label="Talk to your assistant"
                onPress={startVoice}
              />
            ) : (
              <SendButton icon={I.send} label="Send" onPress={() => {}} />
            )}
          </View>
        </View>
      </KeyboardAvoidingView>

      <Modal
        visible={attachOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setAttachOpen(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)" }}
          onPress={() => setAttachOpen(false)}
          accessibilityLabel="Close"
        />
        <View
          style={{
            backgroundColor: p.bg,
            borderTopLeftRadius: 24,
            borderTopRightRadius: 24,
            padding: 18,
            paddingBottom: insets.bottom + 18,
            gap: 4,
          }}
        >
          <Mono>Send to {assistantName}</Mono>
          {(
            [
              ["Take a photo", I.camera, takePhoto],
              ["Choose photos", I.photo, pickPhotos],
              ["PDF document", I.doc, pickPdfs],
            ] as const
          )
            .filter(
              ([label]) => Platform.OS !== "web" || label !== "Take a photo",
            )
            .map(([label, icon, pick]) => (
              <Pressable
                key={label}
                onPress={() => attach(pick)}
                accessibilityRole="button"
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 14,
                  paddingVertical: 14,
                }}
              >
                <Icon name={icon} color={p.teal} size={22} />
                <Text
                  style={{ fontFamily: FONTS.sans, fontSize: 17, color: p.ink }}
                >
                  {label}
                </Text>
              </Pressable>
            ))}
        </View>
      </Modal>

      <ChatList
        open={listOpen}
        onClose={() => setListOpen(false)}
        conversations={conversations}
        activeId={activeId}
        onOpen={openConversation}
        onDelete={removeConversation}
        lang={lang}
        onLang={(l) => {
          setLang(l);
          void setPref("voice.lang", l);
        }}
        assistantName={assistantName}
        onCustomize={() => {
          setListOpen(false);
          setCustomize(true);
        }}
        readAloud={readAloud}
        onReadAloud={(v) => {
          setReadAloud(v);
          void setPref("chat.readAloud", v ? "1" : "0");
          if (!v) stopSpeaking();
        }}
      />

      {customize && (
        <AssistantSettings
          open
          name={assistantName}
          style={me?.assistant_style ?? "friendly"}
          length={me?.reply_length ?? "short"}
          lang={lang}
          prefs={voicePrefs}
          onClose={() => setCustomize(false)}
          onSaved={(n, st, ln, l, v) => {
            if (me)
              setMe({
                ...me,
                assistant_name: n,
                assistant_style: st,
                reply_length: ln,
              });
            setLang(l);
            setVoicePrefs(v);
            void setPref("voice.lang", l);
            void setPref("voice.prefs", JSON.stringify(v));
            setCustomize(false);
          }}
        />
      )}

      <Modal
        visible={voice !== "off"}
        animationType="fade"
        onRequestClose={endVoice}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: p.bg,
            alignItems: "center",
            justifyContent: "center",
            gap: 18,
            padding: 24,
          }}
        >
          <Grid />
          <Mono>Voice conversation</Mono>
          <Orb state={voice} onPress={tapOrb} />
          <Text style={{ fontFamily: FONTS.serif, fontSize: 38, color: p.ink }}>
            {
              {
                listening: "Listening…",
                thinking: "Thinking…",
                speaking: "Speaking",
                paused: "Tap to talk",
                off: "",
              }[voice]
            }
          </Text>
          <Mono>
            {voice === "speaking"
              ? "Tap the circle to interrupt"
              : voice === "listening"
                ? "Go ahead, I’m listening"
                : " "}
          </Mono>
          <Text
            style={{
              fontFamily: FONTS.sans,
              fontSize: 17,
              color: p.muted,
              textAlign: "center",
              minHeight: 50,
            }}
          >
            {voice === "listening" ? heard : ""}
          </Text>
          {mode === "converse" && !!mic.error && (
            <Text style={{ color: p.bad, fontFamily: FONTS.sans }}>
              {mic.error}
            </Text>
          )}
          <Pressable
            onPress={endVoice}
            accessibilityRole="button"
            accessibilityLabel="End voice"
            style={{
              borderWidth: 1,
              borderColor: p.line,
              backgroundColor: p.card,
              borderRadius: 999,
              paddingVertical: 12,
              paddingHorizontal: 24,
            }}
          >
            <Mono color={p.ink}>End voice</Mono>
          </Pressable>
        </View>
      </Modal>
    </View>
  );
}

// --- pieces of the paper look ------------------------------------------------------------

/** An attached photo (loaded with the sign-in token) or a PDF chip. */
function Attached({
  file,
}: {
  file: { id: string; name: string; media_type: string; preview?: string };
}) {
  const p = usePaper();
  const [src, setSrc] = useState<{
    uri: string;
    headers?: Record<string, string>;
  } | null>(file.preview ? { uri: file.preview } : null);
  useEffect(() => {
    if (file.preview || file.media_type === "application/pdf") return;
    let gone = false;
    photoSource(file.id)
      .then((s) => !gone && setSrc(s))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [file.id, file.preview, file.media_type]);
  if (file.media_type === "application/pdf" || !src) {
    return (
      <View
        style={{
          borderWidth: 1,
          borderColor: p.line,
          backgroundColor: p.card,
          borderRadius: 14,
          paddingVertical: 8,
          paddingHorizontal: 12,
        }}
      >
        <Text style={{ fontFamily: FONTS.sans, color: p.ink }}>
          {file.media_type === "application/pdf" ? "📄 " : "🖼 "}
          {file.name}
        </Text>
      </View>
    );
  }
  return (
    <Image
      source={src}
      accessibilityLabel={file.name}
      style={{
        width: 200,
        height: 200,
        borderRadius: 18,
        borderWidth: 1,
        borderColor: p.line,
      }}
    />
  );
}

function Mono({
  children,
  color,
  numberOfLines,
}: {
  children: ReactNode;
  color?: string;
  numberOfLines?: number;
}) {
  const p = usePaper();
  return (
    <Text
      numberOfLines={numberOfLines}
      style={{
        fontFamily: FONTS.mono,
        fontSize: 11.5,
        letterSpacing: 2.6,
        textTransform: "uppercase",
        color: color ?? p.muted,
      }}
    >
      {children}
    </Text>
  );
}

function Ruled({ children }: { children: ReactNode }) {
  const p = usePaper();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 16,
        marginBottom: 18,
      }}
    >
      <View style={{ width: 44, height: 1.5, backgroundColor: p.terra }} />
      <Mono>{children}</Mono>
    </View>
  );
}

/** Faint graph-paper lines behind the conversation. */
function Grid() {
  const p = usePaper();
  const { width, height } = useWindowDimensions();
  const step = 42;
  return (
    <View
      pointerEvents="none"
      style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
    >
      {Array.from({ length: Math.ceil(width / step) }, (_, i) => (
        <View
          key={`v${i}`}
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: i * step,
            width: 1,
            backgroundColor: p.grid,
          }}
        />
      ))}
      {Array.from({ length: Math.ceil(height / step) }, (_, i) => (
        <View
          key={`h${i}`}
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: i * step,
            height: 1,
            backgroundColor: p.grid,
          }}
        />
      ))}
    </View>
  );
}

function Avatar({ big }: { big?: boolean }) {
  const p = usePaper();
  const size = big ? 52 : 40;
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: p.terraSoft,
        borderWidth: 1.5,
        borderColor: p.terra + "99",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Icon
        name={I.feather}
        color={big ? p.terra : p.teal}
        size={big ? 24 : 18}
      />
      {big && (
        <View
          style={{
            position: "absolute",
            top: 1,
            right: 1,
            width: 9,
            height: 9,
            borderRadius: 5,
            backgroundColor: p.terra,
          }}
        />
      )}
    </View>
  );
}

function IconButton({
  icon,
  label,
  onPress,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
}) {
  const p = usePaper();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      style={{ padding: 8 }}
    >
      <Icon name={icon} color={p.ink} size={24} />
    </Pressable>
  );
}

function SendButton({
  icon,
  label,
  onPress,
  active,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  active?: boolean;
}) {
  const p = usePaper();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => ({
        width: 48,
        height: 48,
        borderRadius: 24,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: active ? p.teal : p.sage,
        opacity: pressed ? 0.75 : 1,
      })}
    >
      <Icon name={icon} color="#ffffff" size={20} />
    </Pressable>
  );
}

function Message({
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
  onSpeak: () => void;
  name: string;
}) {
  const p = usePaper();
  if (m.role === "user") {
    return (
      <View style={{ alignItems: "flex-end", gap: 8 }}>
        {(m.meta.attachments ?? []).length > 0 && (
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 8,
              justifyContent: "flex-end",
              maxWidth: "86%",
            }}
          >
            {m.meta.attachments!.map((a) => (
              <Attached key={a.id} file={a} />
            ))}
          </View>
        )}
        {!!m.content && (
          <View
            style={{
              maxWidth: "86%",
              backgroundColor: p.teal,
              borderRadius: 24,
              borderBottomRightRadius: 6,
              paddingVertical: 14,
              paddingHorizontal: 18,
            }}
          >
            <Text
              style={{
                color: p.tealInk,
                fontFamily: FONTS.sans,
                fontSize: 16.5,
                lineHeight: 24,
              }}
            >
              {m.content}
            </Text>
          </View>
        )}
        <Mono>{m.via === "voice" ? "You · voice" : "You"}</Mono>
      </View>
    );
  }
  if (m.meta.kind === "reminder") {
    return (
      <View style={{ flexDirection: "row", gap: 10 }}>
        <Avatar />
        <View style={{ flex: 1, gap: 8 }}>
          <Card2
            icon={I.clock}
            iconColor={p.terra}
            title={m.content.replace(/^⏰ Reminder: /, "")}
            label={`Reminder · ${new Date(m.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`}
          />
          <Mono>{name} · reminder</Mono>
        </View>
      </View>
    );
  }
  if (m.meta.kind === "task_update" && m.meta.task_id) {
    const t = tasks[m.meta.task_id] ?? {
      id: m.meta.task_id,
      title: "Task",
      status: m.meta.status ?? "running",
    };
    return (
      <View style={{ flexDirection: "row", gap: 10 }}>
        <Avatar />
        <View style={{ flex: 1, gap: 8 }}>
          <ToolCard t={t} description={m.content} />
          <Mono>{name} · task update</Mono>
        </View>
      </View>
    );
  }
  return (
    <View style={{ flexDirection: "row", gap: 10 }}>
      <Avatar />
      <View style={{ flex: 1, gap: 8, alignItems: "flex-start" }}>
        <View
          style={{
            maxWidth: "100%",
            backgroundColor: p.card,
            borderColor: p.line,
            borderWidth: 1,
            borderRadius: 24,
            paddingVertical: 14,
            paddingHorizontal: 18,
          }}
        >
          {m.content ? (
            <ChatText
              text={m.content}
              color={p.ink}
              family={FONTS.sans}
              boldFamily={FONTS.sansBold}
            />
          ) : typing ? (
            <Text style={{ color: p.muted, fontSize: 20 }}>• • •</Text>
          ) : null}
          {m.meta.interrupted && (
            <Text
              style={{ color: p.muted, fontFamily: FONTS.sans, marginTop: 6 }}
            >
              Reply was cut off.
            </Text>
          )}
        </View>
        {(m.meta.tasks ?? []).map((t) => (
          <ToolCard
            key={t.id}
            t={tasks[t.id] ?? t}
            description="Handed to your workforce. Updates appear here."
          />
        ))}
        {(m.meta.actions ?? []).map((a) =>
          a.kind === "upi" ? (
            <Card2
              key={a.url}
              icon={I.pay}
              iconColor={p.teal}
              title={`Pay ${a.name || a.to}${a.amount ? ` ₹${a.amount}` : ""}`}
              label={`${a.to} · Approve with your UPI PIN`}
            >
              {!!a.text && (
                <Text
                  style={{
                    fontFamily: FONTS.sans,
                    fontSize: 15.5,
                    lineHeight: 22,
                    color: p.ink,
                    backgroundColor: p.bg,
                    borderRadius: 14,
                    padding: 12,
                  }}
                >
                  {a.text}
                </Text>
              )}
              <Pressable
                onPress={() =>
                  Linking.openURL(a.url).catch(() =>
                    Alert.alert(
                      "No UPI app found",
                      "Install GPay, PhonePe, Paytm or BHIM, then try again.",
                    ),
                  )
                }
                accessibilityRole="button"
                accessibilityLabel="Pay in UPI app"
                style={({ pressed }) => ({
                  alignSelf: "flex-start",
                  backgroundColor: p.teal,
                  borderRadius: 999,
                  paddingVertical: 10,
                  paddingHorizontal: 20,
                  opacity: pressed ? 0.8 : 1,
                })}
              >
                <Text
                  style={{
                    color: "#fff",
                    fontFamily: FONTS.sansBold,
                    fontSize: 16,
                  }}
                >
                  Pay in UPI app
                </Text>
              </Pressable>
            </Card2>
          ) : (
            <Card2
              key={a.url}
              icon={I.whatsapp}
              iconColor="#1f9d55"
              title={`WhatsApp to ${a.name || a.to || "a contact you pick"}`}
              label={`${a.to ? `${a.to} · ` : ""}Ready · tap send in WhatsApp`}
            >
              <Text
                style={{
                  fontFamily: FONTS.sans,
                  fontSize: 15.5,
                  lineHeight: 22,
                  color: p.ink,
                  backgroundColor: p.bg,
                  borderRadius: 14,
                  padding: 12,
                }}
              >
                {a.text}
              </Text>
              <Pressable
                onPress={() => Linking.openURL(a.url)}
                accessibilityRole="button"
                accessibilityLabel="Open WhatsApp"
                style={({ pressed }) => ({
                  alignSelf: "flex-start",
                  backgroundColor: "#1f9d55",
                  borderRadius: 999,
                  paddingVertical: 10,
                  paddingHorizontal: 20,
                  opacity: pressed ? 0.8 : 1,
                })}
              >
                <Text
                  style={{
                    color: "#fff",
                    fontFamily: FONTS.sansBold,
                    fontSize: 16,
                  }}
                >
                  Open WhatsApp
                </Text>
              </Pressable>
            </Card2>
          ),
        )}
        {(m.meta.schedules ?? []).map((sc) => (
          <Card2
            key={sc.id}
            icon={I.clock}
            iconColor={p.terra}
            title={sc.title}
            label={`${sc.kind === "reminder" ? "Reminder" : "Scheduled job"} · ${sc.text}`}
            onPress={() => router.push("/tasks")}
          />
        ))}
        {(m.meta.memories ?? []).map((x) => (
          <Card2
            key={x}
            icon={I.book}
            iconColor={p.terra}
            title={x}
            label="Saved to memory"
          />
        ))}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 14,
            flexWrap: "wrap",
          }}
        >
          <Mono>{m.via === "voice" ? `${name} · voice transcript` : name}</Mono>
          {!typing && !!m.content && (
            <>
              <Pressable
                onPress={() => Clipboard.setStringAsync(m.content)}
                accessibilityRole="button"
                accessibilityLabel="Copy"
                hitSlop={8}
              >
                <Mono color={p.teal}>Copy</Mono>
              </Pressable>
              <Pressable
                onPress={onSpeak}
                accessibilityRole="button"
                accessibilityLabel={speaking ? "Stop reading" : "Listen"}
                hitSlop={8}
              >
                <Mono color={p.teal}>{speaking ? "Stop" : "Listen"}</Mono>
              </Pressable>
            </>
          )}
        </View>
      </View>
    </View>
  );
}

function statusLine(
  t: ChatTaskRef,
): [string, "done" | "fail" | "wait" | "work"] {
  const waiting =
    t.status === "blocked" ? (t.waiting_for_connection ?? []) : [];
  if (waiting.length)
    return [`Waiting for ${joinNames(waiting.map(serviceName))}`, "wait"];
  const map: Record<string, [string, "done" | "fail" | "wait" | "work"]> = {
    waiting_for_approval: ["Needs your approval", "wait"],
    blocked: ["Needs your input", "wait"],
    completed: ["Done", "done"],
    failed: ["Couldn’t finish", "fail"],
    cancelled: ["Cancelled", "fail"],
    expired: ["Expired", "fail"],
    verifying: ["Checking the result", "work"],
  };
  return map[t.status] ?? [STATUS_TEXT[t.status] ?? t.status, "work"];
}

function Card2({
  icon,
  iconColor,
  title,
  label,
  onPress,
  children,
}: {
  icon: IconName;
  iconColor: string;
  title: string;
  label: string;
  onPress?: () => void;
  children?: ReactNode;
}) {
  const p = usePaper();
  return (
    <View
      style={{
        alignSelf: "stretch",
        backgroundColor: p.card,
        borderColor: p.line,
        borderWidth: 1,
        borderRadius: 24,
        padding: 16,
        gap: 10,
      }}
    >
      <Pressable
        onPress={onPress}
        disabled={!onPress}
        style={{ flexDirection: "row", alignItems: "center", gap: 14 }}
        accessibilityRole={onPress ? "link" : undefined}
      >
        <View
          style={{
            width: 44,
            height: 44,
            borderRadius: 22,
            backgroundColor: p.bg,
            alignItems: "center",
            justifyContent: "center",
            shadowColor: "#2f3b45",
            shadowOpacity: 0.12,
            shadowRadius: 6,
            shadowOffset: { width: 0, height: 3 },
            elevation: 2,
          }}
        >
          <Icon name={icon} color={iconColor} size={20} />
        </View>
        <View style={{ flex: 1, gap: 4 }}>
          <Text
            style={{ fontFamily: FONTS.sansMedium, fontSize: 17, color: p.ink }}
          >
            {title}
          </Text>
          <Mono>{label}</Mono>
        </View>
      </Pressable>
      {children}
    </View>
  );
}

function ToolCard({
  t,
  description,
}: {
  t: ChatTaskRef;
  description?: string;
}) {
  const p = usePaper();
  const [label, tone] = statusLine(t);
  const waiting =
    t.status === "blocked" ? (t.waiting_for_connection ?? []) : [];
  const icon = {
    done: I.check,
    fail: I.ban,
    wait: waiting.length ? I.plug : I.pen,
    work: I.spark,
  }[tone];
  const color = { done: p.ok, fail: p.muted, wait: p.terra, work: p.teal }[
    tone
  ];
  return (
    <Card2
      icon={icon}
      iconColor={color}
      title={t.title}
      label={label}
      onPress={() => router.push(`/tasks/${t.id}`)}
    >
      {!!description && (
        <ChatText
          text={description}
          color={p.muted}
          family={FONTS.sans}
          boldFamily={FONTS.sansBold}
          size={15.5}
        />
      )}
      {t.status === "waiting_for_approval" && (
        <Pressable
          onPress={() => router.push("/approvals")}
          accessibilityRole="button"
          hitSlop={6}
        >
          <Text
            style={{ color: p.teal, fontFamily: FONTS.sansBold, fontSize: 15 }}
          >
            Review & approve →
          </Text>
        </Pressable>
      )}
      {waiting.length > 0 && (
        <Pressable
          onPress={() =>
            router.push({
              pathname: "/connections",
              params: { need: waiting.join(",") },
            })
          }
          accessibilityRole="button"
          hitSlop={6}
        >
          <Text
            style={{ color: p.teal, fontFamily: FONTS.sansBold, fontSize: 15 }}
          >
            Connect {joinNames(waiting.map(serviceName))} →
          </Text>
        </Pressable>
      )}
    </Card2>
  );
}

function Orb({ state, onPress }: { state: VoiceState; onPress: () => void }) {
  const p = usePaper();
  const [scale] = useState(() => new Animated.Value(1));
  useEffect(() => {
    scale.stopAnimation();
    if (state === "listening" || state === "speaking" || state === "thinking") {
      const [to, ms] =
        state === "speaking"
          ? [1.06, 240]
          : state === "listening"
            ? [1.08, 800]
            : [0.94, 500];
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(scale, {
            toValue: to,
            duration: ms,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.timing(scale, {
            toValue: 1,
            duration: ms,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    }
    Animated.timing(scale, {
      toValue: state === "paused" ? 0.86 : 1,
      duration: 200,
      useNativeDriver: true,
    }).start();
  }, [state, scale]);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel="Tap to talk or interrupt"
      style={{
        width: 200,
        height: 200,
        alignItems: "center",
        justifyContent: "center",
        marginVertical: 6,
      }}
    >
      <View
        style={{
          position: "absolute",
          width: 200,
          height: 200,
          borderRadius: 100,
          borderWidth: 1.5,
          borderColor: p.terra + "99",
        }}
      />
      <Animated.View
        style={{
          width: 156,
          height: 156,
          borderRadius: 78,
          backgroundColor: state === "paused" ? p.sage : p.teal,
          alignItems: "center",
          justifyContent: "center",
          transform: [{ scale }],
        }}
      >
        <Icon name={I.feather} color={p.tealInk} size={44} />
      </Animated.View>
    </Pressable>
  );
}

function ChatList(props: {
  open: boolean;
  onClose: () => void;
  conversations: Conversation[];
  activeId: string | null;
  onOpen: (id: string | null) => void;
  onDelete: (c: Conversation) => void;
  lang: string;
  onLang: (l: string) => void;
  readAloud: boolean;
  onReadAloud: (v: boolean) => void;
  assistantName: string;
  onCustomize: () => void;
}) {
  const p = usePaper();
  const insets = useSafeAreaInsets();
  const [langOpen, setLangOpen] = useState(false);
  const body = { fontFamily: FONTS.sans, fontSize: 16, color: p.ink };
  return (
    <Modal
      visible={props.open}
      animationType="slide"
      transparent
      onRequestClose={props.onClose}
    >
      <View style={{ flex: 1, flexDirection: "row" }}>
        <View
          style={{
            width: "84%",
            maxWidth: 340,
            backgroundColor: p.card,
            paddingTop: insets.top + 16,
            paddingBottom: insets.bottom + 12,
            paddingHorizontal: 18,
            gap: 12,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Mono>Conversations</Mono>
            <Pressable
              onPress={() => props.onOpen(null)}
              accessibilityRole="button"
              hitSlop={8}
            >
              <Text
                style={{
                  fontFamily: FONTS.sansBold,
                  color: p.teal,
                  fontSize: 16,
                }}
              >
                + New
              </Text>
            </Pressable>
          </View>
          <ScrollView style={{ flex: 1 }}>
            {props.conversations.length === 0 && (
              <Text style={[body, { color: p.muted }]}>
                Your conversations appear here.
              </Text>
            )}
            {props.conversations.map((conv) => (
              <Pressable
                key={conv.id}
                onPress={() => props.onOpen(conv.id)}
                onLongPress={() => props.onDelete(conv)}
                accessibilityRole="button"
                accessibilityHint="Long-press to delete"
                style={{
                  paddingVertical: 11,
                  paddingHorizontal: 10,
                  borderRadius: 10,
                  backgroundColor:
                    conv.id === props.activeId ? p.bg : "transparent",
                }}
              >
                <Text numberOfLines={1} style={body}>
                  {conv.title}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
          <Mono>Long-press a chat to delete it</Mono>
          <View
            style={{
              borderTopWidth: 1,
              borderTopColor: p.line,
              paddingTop: 12,
              gap: 12,
            }}
          >
            <Pressable
              onPress={props.onCustomize}
              accessibilityRole="button"
              hitSlop={6}
            >
              <Text
                style={{
                  fontFamily: FONTS.sansBold,
                  color: p.teal,
                  fontSize: 16,
                }}
              >
                Name & voice of {props.assistantName}
              </Text>
            </Pressable>
            <Pressable
              onPress={() => setLangOpen((v) => !v)}
              accessibilityRole="button"
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <Mono>Voice</Mono>
              <Text style={[body, { fontFamily: FONTS.sansMedium }]}>
                {VOICE_LANGUAGES.find((l) => l.code === props.lang)?.label ??
                  props.lang}
              </Text>
            </Pressable>
            {langOpen &&
              VOICE_LANGUAGES.map((l) => (
                <Pressable
                  key={l.code}
                  onPress={() => {
                    props.onLang(l.code);
                    setLangOpen(false);
                  }}
                  style={{ paddingVertical: 5, paddingLeft: 10 }}
                >
                  <Text
                    style={[
                      body,
                      l.code === props.lang && { fontFamily: FONTS.sansBold },
                    ]}
                  >
                    {l.label}
                  </Text>
                </Pressable>
              ))}
            <View
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <Text style={body}>Read replies aloud</Text>
              <Switch
                value={props.readAloud}
                onValueChange={props.onReadAloud}
                accessibilityLabel="Read replies aloud"
                trackColor={{ true: p.teal }}
              />
            </View>
          </View>
        </View>
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)" }}
          onPress={props.onClose}
          accessibilityLabel="Close conversations"
        />
      </View>
    </Modal>
  );
}
