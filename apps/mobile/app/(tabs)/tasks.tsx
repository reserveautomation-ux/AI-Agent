import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  View,
} from 'react-native';

import { Badge, Button, Card, ErrorText, H, Icon, Input, T, styles } from '@/components/ui';
import { api, post, type Capability, type Task } from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { useVoice, VOICE_LANGUAGES } from '@/lib/useVoice';

const HANDLING: Record<Capability['handling'], string> = {
  automatic: 'Does it for you',
  asks_approval: 'Asks before sending',
  owner_approval: 'Needs your approval',
  you_confirm_in_app: 'You confirm in app',
};
const HANDLING_TONE: Record<Capability['handling'], 'ok' | 'info' | 'warn' | 'muted'> = {
  automatic: 'ok',
  asks_approval: 'info',
  owner_approval: 'warn',
  you_confirm_in_app: 'muted',
};

export default function CommandScreen() {
  const c = useTheme();
  const [objective, setObjective] = useState('');
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [caps, setCaps] = useState<Capability[]>([]);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState('en-IN');
  const [autoSend, setAutoSend] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const base = useRef('');
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);

  useEffect(() => {
    AsyncStorage.multiGet(['voice.lang', 'voice.autoSend'])
      .then(([[, l], [, a]]) => {
        if (l) setLang(l);
        if (a) setAutoSend(a === 'true');
      })
      .catch(() => {});
    api<Capability[]>('/capabilities').then(setCaps).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      setTasks(await api<Task[]>('/tasks?limit=50'));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // Refresh while this screen is visible: tasks run in the background.
  useFocusEffect(
    useCallback(() => {
      load();
      const t = setInterval(load, 5000);
      return () => clearInterval(t);
    }, [load]),
  );

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await post<Task>('/tasks', { objective: text });
      setObjective('');
      setTasks((prev) => [task, ...(prev ?? [])]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const voice = useVoice({
    lang,
    onText: (spoken) => setObjective(base.current + spoken),
    onDone: (spoken) => {
      if (autoSend) send(base.current + spoken);
    },
  });

  const toggleMic = () => {
    if (voice.listening) return voice.stop();
    base.current = objective.trim() ? objective.trim() + ' ' : '';
    voice.start();
  };

  const langLabel = VOICE_LANGUAGES.find((l) => l.code === lang)?.label ?? lang;
  const areas = [...new Set(caps.map((cap) => cap.area))];

  return (
    <ScrollView
      ref={scroll}
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={styles.screen}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={async () => {
            setRefreshing(true);
            await load();
            setRefreshing(false);
          }}
        />
      }>
      <Card>
        <T bold size={17}>What should your workforce do?</T>
        <View style={{ marginTop: 10 }}>
          <Input
            value={objective}
            onChangeText={setObjective}
            multiline
            placeholder={voice.listening ? 'Listening… speak now' : 'Type here, or tap the mic and speak'}
            accessibilityLabel="Instruction"
            style={[
              local.input,
              voice.listening && { borderColor: c.bad, borderWidth: 2 },
            ]}
          />
          <Pressable
            onPress={toggleMic}
            disabled={!voice.available}
            accessibilityRole="button"
            accessibilityLabel={voice.listening ? 'Stop listening' : 'Speak your instruction'}
            accessibilityState={{ selected: voice.listening, disabled: !voice.available }}
            style={({ pressed }) => [
              local.mic,
              {
                backgroundColor: !voice.available ? c.border : voice.listening ? c.bad : c.accent,
                opacity: pressed ? 0.8 : 1,
              },
            ]}>
            <Icon
              name={
                voice.listening
                  ? { ios: 'stop.fill', android: 'stop', web: 'stop' }
                  : { ios: 'mic.fill', android: 'mic', web: 'mic' }
              }
              color={voice.listening ? '#fff' : '#14213d'}
              size={26}
            />
          </Pressable>
        </View>

        <View style={[styles.between, { marginTop: 12 }]}>
          <Pressable
            onPress={() => setLangOpen(true)}
            accessibilityRole="button"
            accessibilityLabel={`Voice language: ${langLabel}`}
            style={[local.chip, { borderColor: c.border }]}>
            <T small>🌐 {langLabel}</T>
          </Pressable>
          <View style={styles.row}>
            <T small muted>Send when I stop</T>
            <Switch
              value={autoSend}
              onValueChange={(v) => {
                setAutoSend(v);
                AsyncStorage.setItem('voice.autoSend', String(v)).catch(() => {});
              }}
              accessibilityLabel="Send when I stop talking"
            />
          </View>
        </View>

        {voice.listening && <T small muted style={{ marginTop: 8 }}>🎙 Listening… tap the mic to stop.</T>}
        {!voice.available && (
          <T small muted style={{ marginTop: 8 }}>Voice isn&apos;t available on this device; typing works.</T>
        )}
        <ErrorText>{voice.error}</ErrorText>
        <View style={{ height: 12 }} />
        <Button
          title={busy ? 'Sending…' : 'Give instruction'}
          icon={{ ios: 'paperplane.fill', android: 'send', web: 'send' }}
          onPress={() => {
            if (voice.listening) voice.stop();
            send(objective);
          }}
          disabled={!objective.trim()}
          loading={busy}
        />
        <ErrorText>{error}</ErrorText>
      </Card>

      <H>Tasks</H>
      {tasks === null ? (
        <T muted>Loading…</T>
      ) : tasks.length === 0 ? (
        <T muted>No tasks yet. Type or speak your first instruction above.</T>
      ) : (
        tasks.map((t) => (
          <Pressable
            key={t.id}
            onPress={() => router.push(`/tasks/${t.id}`)}
            accessibilityRole="button"
            accessibilityLabel={`${t.title}, ${t.status.replaceAll('_', ' ')}`}
            style={({ pressed }) => [
              styles.card,
              styles.between,
              { backgroundColor: c.surface, borderColor: c.border, opacity: pressed ? 0.8 : 1 },
            ]}>
            <View style={{ flex: 1 }}>
              <T bold numberOfLines={2}>{t.title}</T>
              <T small muted>{new Date(t.created_at).toLocaleString()}</T>
            </View>
            <Badge status={t.status} />
          </Pressable>
        ))
      )}

      {areas.length > 0 && (
        <>
          <H>What your workforce can do</H>
          <T small muted>Tap an example to use it, or ask for anything.</T>
          {areas.map((area) => (
            <View key={area} style={{ marginTop: 14 }}>
              <T small bold muted style={{ textTransform: 'uppercase', letterSpacing: 0.6 }}>{area}</T>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
                {caps
                  .filter((cap) => cap.area === area)
                  .map((cap) => (
                    <Pressable
                      key={cap.key}
                      onPress={() => {
                        setObjective(cap.example);
                        scroll.current?.scrollTo({ y: 0, animated: true });
                      }}
                      accessibilityRole="button"
                      accessibilityLabel={`${cap.title}. Example: ${cap.example}`}
                      style={({ pressed }) => [
                        local.cap,
                        { backgroundColor: c.surface, borderColor: c.border, opacity: pressed ? 0.8 : 1 },
                      ]}>
                      <T bold>{cap.title}</T>
                      <T small muted numberOfLines={3}>“{cap.example}”</T>
                      <Badge label={HANDLING[cap.handling]} tone={c[HANDLING_TONE[cap.handling]]} />
                    </Pressable>
                  ))}
              </ScrollView>
            </View>
          ))}
        </>
      )}

      <Modal visible={langOpen} transparent animationType="slide" onRequestClose={() => setLangOpen(false)}>
        <Pressable style={local.backdrop} onPress={() => setLangOpen(false)} accessibilityLabel="Close" />
        <View style={[local.sheet, { backgroundColor: c.surface }]}>
          <T bold size={17} style={{ marginBottom: 8 }}>Voice language</T>
          <ScrollView>
            {VOICE_LANGUAGES.map((l) => (
              <Pressable
                key={l.code}
                onPress={() => {
                  setLang(l.code);
                  AsyncStorage.setItem('voice.lang', l.code).catch(() => {});
                  setLangOpen(false);
                }}
                accessibilityRole="button"
                accessibilityState={{ selected: l.code === lang }}
                style={[local.langRow, { borderBottomColor: c.border }]}>
                <T bold={l.code === lang}>{l.label}</T>
                {l.code === lang && <T color={c.ok}>✓</T>}
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
    </ScrollView>
  );
}

const local = StyleSheet.create({
  input: { minHeight: 110, paddingRight: 70, textAlignVertical: 'top' },
  mic: {
    position: 'absolute',
    right: 10,
    bottom: 10,
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  cap: { width: 250, borderWidth: 1, borderRadius: 14, padding: 14, marginRight: 10, gap: 6 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { maxHeight: '60%', borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 20 },
  langRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
});
