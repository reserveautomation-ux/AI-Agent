import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useFocusEffect } from 'expo-router';
import * as Clipboard from 'expo-clipboard';
import * as Speech from 'expo-speech';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Switch,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ChatText, speakable } from '@/components/ChatText';
import { Badge, Button, ErrorText, Icon, T, type IconName } from '@/components/ui';
import {
  ApiError,
  api,
  streamChat,
  type ChatMessage,
  type ChatTaskRef,
  type Conversation,
  type ConversationDetail,
  type Me,
} from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';
import { joinNames, serviceName } from '@/lib/labels';
import { useTheme } from '@/lib/theme';
import { VOICE_LANGUAGES, useVoice } from '@/lib/useVoice';

const SUGGESTIONS = [
  'Email Rahul that tomorrow’s demo moves to 4pm',
  'Make a one-page website for my café and publish it',
  'WhatsApp my team that standup is at 11 today',
  'What’s free on my calendar on Friday?',
  'Explain index funds simply',
];
const ACTIVE = new Set(['draft', 'planned', 'queued', 'running', 'verifying', 'waiting_for_approval', 'blocked']);
const STATUS_TEXT: Record<string, string> = {
  draft: 'Starting',
  planned: 'Planned',
  queued: 'Queued',
  running: 'Working',
  verifying: 'Checking',
  waiting_for_approval: 'Needs your approval',
  blocked: 'Waiting for you',
  completed: 'Done',
  failed: 'Couldn’t finish',
  cancelled: 'Cancelled',
  expired: 'Expired',
};

const I = {
  menu: { ios: 'line.3.horizontal', android: 'menu', web: 'menu' },
  edit: { ios: 'square.and.pencil', android: 'edit_square', web: 'edit_square' },
  mic: { ios: 'mic.fill', android: 'mic', web: 'mic' },
  send: { ios: 'arrow.up', android: 'arrow_upward', web: 'arrow_upward' },
  stop: { ios: 'stop.fill', android: 'stop', web: 'stop' },
  wave: { ios: 'waveform', android: 'graphic_eq', web: 'graphic_eq' },
} satisfies Record<string, IconName>;

type VoiceState = 'off' | 'listening' | 'thinking' | 'speaking' | 'paused';

export default function ChatScreen() {
  const c = useTheme();
  const insets = useSafeAreaInsets();
  const [me, setMe] = useState<Me | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [listOpen, setListOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tasks, setTasks] = useState<Record<string, ChatTaskRef>>({});
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState('en-IN');
  const [readAloud, setReadAloud] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceState>('off');
  const [heard, setHeard] = useState('');

  const activeRef = useRef<string | null>(null);
  const voiceRef = useRef<VoiceState>('off');
  const modeRef = useRef<'dictate' | 'converse'>('dictate');
  const baseRef = useRef('');
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const [mode, setModeState] = useState<'dictate' | 'converse'>('dictate');
  useEffect(() => {
    activeRef.current = activeId;
  }, [activeId]);
  // State for rendering, ref for callbacks that run later (speech events, timers).
  const setVoiceBoth = (v: VoiceState) => {
    voiceRef.current = v;
    setVoice(v);
  };
  const setMode = (m: 'dictate' | 'converse') => {
    modeRef.current = m;
    setModeState(m);
  };

  useEffect(() => {
    AsyncStorage.multiGet(['voice.lang', 'chat.readAloud'])
      .then(([[, l], [, r]]) => {
        if (l) setLang(l);
        setReadAloud(r === '1');
      })
      .catch(() => {});
    api<Me>('/me').then(setMe).catch(() => {});
  }, []);

  useFocusEffect(
    useCallback(() => {
      api<Conversation[]>('/conversations').then(setConversations).catch(() => {});
      return () => Speech.stop();
    }, []),
  );

  // --- the assistant's voice ------------------------------------------------------
  const stopSpeaking = useCallback(() => {
    Speech.stop();
    setSpeakingId(null);
  }, []);
  const speak = useCallback(
    (text: string, id: string, onEnd?: () => void) => {
      const clean = speakable(text);
      Speech.stop();
      if (!clean) return onEnd?.();
      setSpeakingId(id);
      Speech.speak(clean, {
        language: lang,
        onDone: () => {
          setSpeakingId(null);
          onEnd?.();
        },
        onStopped: () => setSpeakingId(null),
        onError: () => {
          setSpeakingId(null);
          onEnd?.();
        },
      });
    },
    [lang],
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
          const fresh = d.messages.slice(old.length).filter((m) => m.meta.kind === 'task_update');
          if (fresh.length && readAloud && voiceRef.current === 'off') {
            speak(fresh.map((m) => m.content).join(' '), fresh.at(-1)!.id);
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
    async (text: string, via: 'text' | 'voice' = 'text'): Promise<string> => {
      const content = text.trim();
      if (!content || streaming) return '';
      setError(null);
      setInput('');
      stopSpeaking();
      const now = new Date().toISOString();
      const replyId = `pending-${Date.now()}`;
      setMessages((m) => [
        ...m,
        { id: `u-${Date.now()}`, role: 'user', content, via, meta: {}, created_at: now },
        { id: replyId, role: 'assistant', content: '', via, meta: { kind: 'reply' }, created_at: now },
      ]);
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      let reply = '';
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((ms) => ms.map((m) => (m.id === replyId ? fn(m) : m)));
      try {
        await streamChat(
          { content, conversation_id: activeRef.current, via },
          (e) => {
            if (e.type === 'conversation') {
              if (!activeRef.current) {
                activeRef.current = e.id;
                setActiveId(e.id);
              }
              setConversations((cs) => [
                { id: e.id, title: e.title, created_at: now, updated_at: now },
                ...cs.filter((x) => x.id !== e.id),
              ]);
            } else if (e.type === 'text') {
              reply += e.text;
              patch((m) => ({ ...m, content: m.content + e.text }));
            } else if (e.type === 'task') {
              setTasks((t) => ({ ...t, [e.task.id]: e.task }));
              patch((m) => ({ ...m, meta: { ...m.meta, tasks: [...(m.meta.tasks ?? []), e.task] } }));
            } else if (e.type === 'memory') {
              patch((m) => ({ ...m, meta: { ...m.meta, memories: [...(m.meta.memories ?? []), e.content] } }));
            } else if (e.type === 'done') {
              reply = e.text;
              patch((m) => ({ ...m, id: e.message_id, content: e.text }));
            } else if (e.type === 'error') {
              setError(e.message);
            }
          },
          controller.signal,
        );
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setError(e instanceof ApiError ? e.message : 'Couldn’t reach your assistant. Check your connection.');
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

  const sendTyped = async () => {
    if (mic.listening) mic.stop();
    const reply = await send(input);
    if (reply && readAloud) speak(reply, 'last');
  };

  // One recognizer for both dictation and voice conversation.
  const mic = useVoice({
    lang,
    onText: (t) =>
      modeRef.current === 'dictate' ? setInput(baseRef.current ? `${baseRef.current} ${t}` : t) : setHeard(t),
    onEnd: (said) => {
      if (modeRef.current === 'converse') void onHeard(said);
    },
  });

  const listen = () => {
    setMode('converse');
    setHeard('');
    setVoiceBoth('listening');
    void mic.start();
  };
  const onHeard = async (said: string) => {
    if (voiceRef.current !== 'listening') return;
    if (!said.trim()) return setVoiceBoth('paused');
    setVoiceBoth('thinking');
    const reply = await send(said, 'voice');
    if ((voiceRef.current as VoiceState) === 'off') return;
    if (!reply) return setVoiceBoth('paused');
    setVoiceBoth('speaking');
    speak(reply, 'voice', () => {
      if (voiceRef.current === 'speaking') listen();
    });
  };
  const startVoice = () => {
    if (mic.listening) mic.stop();
    stopSpeaking();
    listen();
  };
  const endVoice = () => {
    setVoiceBoth('off');
    setMode('dictate');
    mic.stop();
    stopSpeaking();
    abortRef.current?.abort();
  };
  const tapOrb = () => {
    if (voice === 'speaking') {
      stopSpeaking();
      listen();
    } else if (voice === 'listening') mic.stop();
    else if (voice === 'paused') listen();
  };
  const toggleDictation = () => {
    if (mic.listening) return mic.stop();
    setMode('dictate');
    baseRef.current = input.trim();
    void mic.start();
  };

  const removeConversation = async (conv: Conversation) => {
    if (!(await confirmAsync('Delete this chat?', conv.title, 'Delete', true))) return;
    try {
      await api(`/conversations/${conv.id}`, { method: 'DELETE' });
      setConversations((cs) => cs.filter((x) => x.id !== conv.id));
      if (conv.id === activeId) void openConversation(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setPref = (key: string, value: string) => AsyncStorage.setItem(key, value).catch(() => {});
  const first = me?.email?.split('@')[0]?.split(/[._-]/)[0];
  const greeting = first ? `How can I help, ${first[0].toUpperCase()}${first.slice(1)}?` : 'How can I help?';
  const title = conversations.find((x) => x.id === activeId)?.title ?? 'New chat';

  return (
    <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, height: 50, borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surface }}>
        <IconButton icon={I.menu} label="Chats" onPress={() => setListOpen(true)} />
        <T bold numberOfLines={1} style={{ flex: 1, textAlign: 'center' }}>
          {title}
        </T>
        <IconButton icon={I.edit} label="New chat" onPress={() => openConversation(null)} />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {messages.length === 0 ? (
          <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 20, gap: 10 }} keyboardShouldPersistTaps="handled">
            <T bold size={26} style={{ textAlign: 'center' }}>
              {greeting}
            </T>
            <T muted style={{ textAlign: 'center', marginBottom: 10 }}>
              Ask anything or tell me what to get done. I remember you, and my workforce does the real work. Nothing is sent, booked or paid without your OK.
            </T>
            {SUGGESTIONS.map((s) => (
              <Pressable
                key={s}
                onPress={() => send(s)}
                accessibilityRole="button"
                style={({ pressed }) => ({ borderWidth: 1, borderColor: c.border, backgroundColor: c.surface, borderRadius: 14, padding: 12, opacity: pressed ? 0.7 : 1 })}>
                <T small>{s}</T>
              </Pressable>
            ))}
          </ScrollView>
        ) : (
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(m) => m.id}
            contentContainerStyle={{ padding: 16, gap: 16 }}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item, index }) => (
              <Bubble
                m={item}
                tasks={tasks}
                typing={streaming && index === messages.length - 1 && item.role === 'assistant'}
                speaking={speakingId === item.id}
                onSpeak={() => (speakingId === item.id ? stopSpeaking() : speak(item.content, item.id))}
              />
            )}
          />
        )}

        <View style={{ paddingHorizontal: 12 }}>
          <ErrorText>{error ?? (mode === 'dictate' ? mic.error : null)}</ErrorText>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: 8, margin: 10, padding: 6, paddingLeft: 14, borderRadius: 24, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface }}>
          <TextInput
            value={input}
            onChangeText={setInput}
            placeholder={mic.listening && mode === 'dictate' ? 'Listening… speak now' : 'Message your assistant'}
            placeholderTextColor={c.muted}
            multiline
            style={{ flex: 1, color: c.text, fontSize: 16, maxHeight: 120, paddingVertical: 8 }}
            accessibilityLabel="Message"
          />
          {mic.available && (
            <RoundButton
              icon={I.mic}
              label={mic.listening ? 'Stop dictation' : 'Dictate'}
              onPress={toggleDictation}
              tone={mic.listening && mode === 'dictate' ? c.bad : undefined}
            />
          )}
          {streaming ? (
            <RoundButton icon={I.stop} label="Stop" onPress={() => abortRef.current?.abort()} filled />
          ) : input.trim() ? (
            <RoundButton icon={I.send} label="Send" onPress={sendTyped} filled />
          ) : mic.available ? (
            <RoundButton icon={I.wave} label="Talk to your assistant" onPress={startVoice} filled />
          ) : null}
        </View>
      </KeyboardAvoidingView>

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
          void setPref('voice.lang', l);
        }}
        readAloud={readAloud}
        onReadAloud={(v) => {
          setReadAloud(v);
          void setPref('chat.readAloud', v ? '1' : '0');
          if (!v) stopSpeaking();
        }}
      />

      <Modal visible={voice !== 'off'} animationType="fade" onRequestClose={endVoice}>
        <View style={{ flex: 1, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center', gap: 24, padding: 24 }}>
          <Orb state={voice} onPress={tapOrb} />
          <T bold size={20}>
            {{ listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking · tap to interrupt', paused: 'Tap the circle to talk', off: '' }[voice]}
          </T>
          <T muted style={{ textAlign: 'center', minHeight: 48 }}>
            {voice === 'listening' ? heard : ''}
          </T>
          {mode === 'converse' && mic.error && <ErrorText>{mic.error}</ErrorText>}
          <Button title="End voice" variant="ghost" onPress={endVoice} />
        </View>
      </Modal>
    </View>
  );
}

function IconButton({ icon, label, onPress }: { icon: IconName; label: string; onPress: () => void }) {
  const c = useTheme();
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={8} style={{ padding: 10 }}>
      <Icon name={icon} color={c.text} size={22} />
    </Pressable>
  );
}

function RoundButton({ icon, label, onPress, filled, tone }: { icon: IconName; label: string; onPress: () => void; filled?: boolean; tone?: string }) {
  const c = useTheme();
  const bg = tone ?? (filled ? c.brand : 'transparent');
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => ({ width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: bg, borderWidth: filled || tone ? 0 : 1, borderColor: c.border, opacity: pressed ? 0.7 : 1 })}>
      <Icon name={icon} color={filled || tone ? c.onBrand : c.text} size={20} />
    </Pressable>
  );
}

function Bubble({ m, tasks, typing, speaking, onSpeak }: { m: ChatMessage; tasks: Record<string, ChatTaskRef>; typing: boolean; speaking: boolean; onSpeak: () => void }) {
  const c = useTheme();
  if (m.role === 'user') {
    return (
      <View style={{ alignSelf: 'flex-end', maxWidth: '85%', backgroundColor: c.surface, borderColor: c.border, borderWidth: 1, borderRadius: 18, paddingVertical: 10, paddingHorizontal: 14 }}>
        <T>
          {m.via === 'voice' ? '🎙 ' : ''}
          {m.content}
        </T>
      </View>
    );
  }
  const update = m.meta.kind === 'task_update' && m.meta.task_id ? tasks[m.meta.task_id] : undefined;
  return (
    <View style={update ? { borderLeftWidth: 3, borderLeftColor: c.accent, paddingLeft: 12 } : undefined}>
      {update && <TaskChip t={update} label="Task update" />}
      {m.content ? <ChatText text={m.content} /> : typing ? <T muted>…</T> : null}
      {(m.meta.tasks ?? []).map((t) => (
        <TaskChip key={t.id} t={tasks[t.id] ?? t} label="Started a task" />
      ))}
      {(m.meta.memories ?? []).map((x) => (
        <T key={x} small muted style={{ marginTop: 6 }}>
          💾 Remembered: {x}
        </T>
      ))}
      {!typing && !!m.content && (
        <View style={{ flexDirection: 'row', gap: 6, marginTop: 6 }}>
          <Button title="Copy" small variant="ghost" onPress={() => Clipboard.setStringAsync(m.content)} />
          <Button title={speaking ? 'Stop' : 'Listen'} small variant="ghost" onPress={onSpeak} />
        </View>
      )}
    </View>
  );
}

function TaskChip({ t, label }: { t: ChatTaskRef; label: string }) {
  const c = useTheme();
  const waiting = t.status === 'blocked' ? (t.waiting_for_connection ?? []) : [];
  const tone = t.status === 'completed' ? c.ok : t.status === 'failed' ? c.bad : ['blocked', 'waiting_for_approval'].includes(t.status) ? c.warn : c.info;
  return (
    <View style={{ borderWidth: 1, borderColor: c.border, backgroundColor: c.surface, borderRadius: 12, padding: 10, marginVertical: 6, gap: 8 }}>
      <Pressable onPress={() => router.push(`/tasks/${t.id}`)} accessibilityRole="link">
        <T small muted>
          {label}
        </T>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <T bold>{t.title}</T>
          <Badge label={STATUS_TEXT[t.status] ?? t.status} tone={tone} />
        </View>
      </Pressable>
      {t.status === 'waiting_for_approval' && <Button title="Review & approve" small onPress={() => router.push('/approvals')} />}
      {waiting.length > 0 && (
        <Button
          title={`Connect ${joinNames(waiting.map(serviceName))}`}
          small
          onPress={() => router.push({ pathname: '/connections', params: { need: waiting.join(',') } })}
        />
      )}
    </View>
  );
}

function Orb({ state, onPress }: { state: VoiceState; onPress: () => void }) {
  const c = useTheme();
  const [scale] = useState(() => new Animated.Value(1));
  useEffect(() => {
    scale.stopAnimation();
    if (state === 'listening' || state === 'speaking' || state === 'thinking') {
      const [to, ms] = state === 'speaking' ? [1.08, 260] : state === 'listening' ? [1.1, 800] : [0.92, 600];
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(scale, { toValue: to, duration: ms, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
          Animated.timing(scale, { toValue: 1, duration: ms, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    }
    Animated.timing(scale, { toValue: state === 'paused' ? 0.85 : 1, duration: 200, useNativeDriver: true }).start();
  }, [state, scale]);
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel="Tap to talk or interrupt">
      <Animated.View style={{ width: 170, height: 170, borderRadius: 85, backgroundColor: c.accent, borderWidth: 18, borderColor: c.brand, opacity: state === 'paused' ? 0.6 : 1, transform: [{ scale }] }} />
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
}) {
  const c = useTheme();
  const insets = useSafeAreaInsets();
  const [langOpen, setLangOpen] = useState(false);
  return (
    <Modal visible={props.open} animationType="slide" transparent onRequestClose={props.onClose}>
      <View style={{ flex: 1, flexDirection: 'row' }}>
        <View style={{ width: '82%', maxWidth: 340, backgroundColor: c.surface, paddingTop: insets.top + 12, paddingBottom: insets.bottom + 12, paddingHorizontal: 12, gap: 8 }}>
          <Button title="New chat" onPress={() => props.onOpen(null)} />
          <ScrollView style={{ flex: 1 }}>
            {props.conversations.length === 0 && (
              <T small muted style={{ padding: 8 }}>
                Your chats appear here.
              </T>
            )}
            {props.conversations.map((conv) => (
              <Pressable
                key={conv.id}
                onPress={() => props.onOpen(conv.id)}
                onLongPress={() => props.onDelete(conv)}
                accessibilityRole="button"
                accessibilityHint="Long-press to delete"
                style={{ padding: 12, borderRadius: 10, backgroundColor: conv.id === props.activeId ? c.bg : 'transparent' }}>
                <T numberOfLines={1}>{conv.title}</T>
              </Pressable>
            ))}
          </ScrollView>
          <T small muted>
            Long-press a chat to delete it.
          </T>
          <View style={{ borderTopWidth: 1, borderTopColor: c.border, paddingTop: 10, gap: 10 }}>
            <Pressable onPress={() => setLangOpen((v) => !v)} accessibilityRole="button" style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <T small>Voice language</T>
              <T small bold>
                {VOICE_LANGUAGES.find((l) => l.code === props.lang)?.label ?? props.lang}
              </T>
            </Pressable>
            {langOpen &&
              VOICE_LANGUAGES.map((l) => (
                <Pressable
                  key={l.code}
                  onPress={() => {
                    props.onLang(l.code);
                    setLangOpen(false);
                  }}
                  style={{ paddingVertical: 6, paddingLeft: 10 }}>
                  <T small bold={l.code === props.lang}>
                    {l.label}
                  </T>
                </Pressable>
              ))}
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <T small>Read replies aloud</T>
              <Switch value={props.readAloud} onValueChange={props.onReadAloud} accessibilityLabel="Read replies aloud" />
            </View>
          </View>
        </View>
        <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' }} onPress={props.onClose} accessibilityLabel="Close chats" />
      </View>
    </Modal>
  );
}
