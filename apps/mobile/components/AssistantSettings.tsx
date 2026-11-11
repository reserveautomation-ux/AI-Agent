import * as Speech from 'expo-speech';
import { useEffect, useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { post } from '@/lib/api';
import { FONTS, usePaper } from '@/lib/theme';
import { VOICE_LANGUAGES } from '@/lib/useVoice';

export interface VoicePrefs {
  /** A voice identifier from Speech.getAvailableVoicesAsync(); empty: the phone's default for the language. */
  voice: string;
  rate: number;
  pitch: number;
}
export const DEFAULT_VOICE: VoicePrefs = { voice: '', rate: 1, pitch: 1 };

const NAME_IDEAS = ['Maya', 'Aria', 'Jarvis', 'Kabir', 'Ira', 'Nova'];

function Mono({ children, color }: { children: ReactNode; color?: string }) {
  const p = usePaper();
  return (
    <Text style={{ fontFamily: FONTS.mono, fontSize: 11.5, letterSpacing: 2.6, textTransform: 'uppercase', color: color ?? p.muted }}>
      {children}
    </Text>
  );
}

/** Name your assistant and choose how it sounds (voices come from this phone). */
export function AssistantSettings({
  open,
  name,
  lang,
  prefs,
  onClose,
  onSaved,
}: {
  open: boolean;
  name: string;
  lang: string;
  prefs: VoicePrefs;
  onClose: () => void;
  onSaved: (name: string, lang: string, prefs: VoicePrefs) => void;
}) {
  const p = usePaper();
  const insets = useSafeAreaInsets();
  const [draftName, setDraftName] = useState(name === 'AI Assistant' ? '' : name);
  const [draftLang, setDraftLang] = useState(lang);
  const [draft, setDraft] = useState<VoicePrefs>(prefs);
  const [voices, setVoices] = useState<Speech.Voice[]>([]);
  const [picker, setPicker] = useState<'lang' | 'voice' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!open) return;
    Speech.getAvailableVoicesAsync()
      .then(setVoices)
      .catch(() => setVoices([]));
  }, [open]);

  const base = draftLang.split('-')[0];
  const matching = voices
    .filter((v) => v.language.replace('_', '-').startsWith(base))
    .sort(
      (a, b) =>
        Number(b.language.replace('_', '-') === draftLang) - Number(a.language.replace('_', '-') === draftLang) ||
        Number(b.quality === Speech.VoiceQuality.Enhanced) - Number(a.quality === Speech.VoiceQuality.Enhanced) ||
        a.name.localeCompare(b.name),
    );
  const chosen = voices.find((v) => v.identifier === draft.voice);
  const shownName = draftName.trim() || 'AI Assistant';
  const sample = draftLang.startsWith('hi')
    ? `नमस्ते, मैं ${shownName} हूँ। आज मैं आपकी क्या मदद करूँ?`
    : `Hi, I'm ${shownName}. What can I do for you today?`;

  const preview = () => {
    if (playing) {
      Speech.stop();
      setPlaying(false);
      return;
    }
    Speech.stop();
    setPlaying(true);
    Speech.speak(sample, {
      language: chosen?.language ?? draftLang,
      voice: draft.voice || undefined,
      rate: draft.rate,
      pitch: draft.pitch,
      onDone: () => setPlaying(false),
      onStopped: () => setPlaying(false),
      onError: () => setPlaying(false),
    });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (shownName !== name) await post('/me/assistant', { name: shownName });
      Speech.stop();
      onSaved(shownName, draftLang, draft);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const body = { fontFamily: FONTS.sans, fontSize: 16, color: p.ink };
  const box = { borderWidth: 1, borderColor: p.line, backgroundColor: p.card, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12 };
  const step = (key: 'rate' | 'pitch', delta: number, min: number, max: number) =>
    setDraft((d) => ({ ...d, [key]: Math.round(Math.min(max, Math.max(min, d[key] + delta)) * 100) / 100 }));

  const stepper = (label: string, k: 'rate' | 'pitch', min: number, max: number) => (
    <View style={{ flex: 1, gap: 6 }}>
      <Mono>{label}</Mono>
      <View style={[box, { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 6 }]}>
        <Pressable onPress={() => step(k, -0.1, min, max)} accessibilityRole="button" accessibilityLabel={`Lower ${label}`} hitSlop={8} style={{ padding: 8 }}>
          <Text style={[body, { fontSize: 22 }]}>−</Text>
        </Pressable>
        <Text style={[body, { fontFamily: FONTS.sansMedium }]}>{draft[k].toFixed(1)}{k === 'rate' ? '×' : ''}</Text>
        <Pressable onPress={() => step(k, 0.1, min, max)} accessibilityRole="button" accessibilityLabel={`Raise ${label}`} hitSlop={8} style={{ padding: 8 }}>
          <Text style={[body, { fontSize: 22 }]}>+</Text>
        </Pressable>
      </View>
    </View>
  );

  return (
    <Modal visible={open} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' }}>
        <Pressable style={{ flex: 1 }} onPress={onClose} accessibilityLabel="Close" />
        <View style={{ backgroundColor: p.bg, borderTopLeftRadius: 28, borderTopRightRadius: 28, maxHeight: '90%', paddingBottom: insets.bottom + 12 }}>
          <ScrollView contentContainerStyle={{ padding: 22, gap: 14 }} keyboardShouldPersistTaps="handled">
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
              <View style={{ width: 40, height: 1.5, backgroundColor: p.terra }} />
              <Mono>Your assistant</Mono>
            </View>
            <Text style={{ fontFamily: FONTS.serif, fontSize: 36, color: p.ink }}>Name & voice</Text>

            <Mono>Name</Mono>
            <TextInput
              value={draftName}
              onChangeText={setDraftName}
              placeholder="AI Assistant"
              placeholderTextColor={p.muted}
              maxLength={40}
              style={[box, body, { fontSize: 18 }]}
              accessibilityLabel="Assistant name"
            />
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              {NAME_IDEAS.map((n) => (
                <Pressable key={n} onPress={() => setDraftName(n)} accessibilityRole="button" style={{ borderWidth: 1, borderColor: draftName === n ? p.teal : p.line, backgroundColor: p.card, borderRadius: 999, paddingVertical: 6, paddingHorizontal: 14 }}>
                  <Text style={body}>{n}</Text>
                </Pressable>
              ))}
            </View>

            <Mono>Language</Mono>
            <Pressable onPress={() => setPicker(picker === 'lang' ? null : 'lang')} accessibilityRole="button" style={box}>
              <Text style={body}>{VOICE_LANGUAGES.find((l) => l.code === draftLang)?.label ?? draftLang}</Text>
            </Pressable>
            {picker === 'lang' &&
              VOICE_LANGUAGES.map((l) => (
                <Pressable
                  key={l.code}
                  onPress={() => {
                    setDraftLang(l.code);
                    setDraft((d) => ({ ...d, voice: '' }));
                    setPicker(null);
                  }}
                  style={{ paddingVertical: 6, paddingLeft: 12 }}>
                  <Text style={[body, l.code === draftLang && { fontFamily: FONTS.sansBold }]}>{l.label}</Text>
                </Pressable>
              ))}

            <Mono>Voice</Mono>
            <Pressable onPress={() => setPicker(picker === 'voice' ? null : 'voice')} accessibilityRole="button" style={box}>
              <Text style={body}>{chosen ? `${chosen.name} · ${chosen.language}` : 'Automatic (phone default)'}</Text>
            </Pressable>
            {picker === 'voice' && (
              <View style={{ gap: 2 }}>
                {[{ identifier: '', name: 'Automatic (phone default)', language: '', quality: Speech.VoiceQuality.Default }, ...matching].map((v) => (
                  <Pressable
                    key={v.identifier || 'auto'}
                    onPress={() => {
                      setDraft((d) => ({ ...d, voice: v.identifier }));
                      setPicker(null);
                    }}
                    style={{ paddingVertical: 7, paddingLeft: 12 }}>
                    <Text style={[body, v.identifier === draft.voice && { fontFamily: FONTS.sansBold }]}>
                      {v.name}
                      {v.language ? ` · ${v.language}` : ''}
                      {v.quality === Speech.VoiceQuality.Enhanced ? ' · enhanced' : ''}
                    </Text>
                  </Pressable>
                ))}
                {matching.length === 0 && (
                  <Text style={[body, { color: p.muted, paddingLeft: 12 }]}>No voices for this language on this phone yet.</Text>
                )}
              </View>
            )}

            <View style={{ flexDirection: 'row', gap: 12 }}>
              {stepper('Speed', 'rate', 0.5, 1.8)}
              {stepper('Pitch', 'pitch', 0.5, 1.8)}
            </View>

            <Text style={[body, { color: p.muted, fontSize: 14, lineHeight: 20 }]}>
              Voices come from this phone. Add more natural ones in Settings ›{' '}
              {Platform.OS === 'ios' ? 'Accessibility › Spoken Content › Voices' : 'Text-to-speech'}.
            </Text>
            {!!error && <Text style={{ color: p.bad, fontFamily: FONTS.sans }}>{error}</Text>}

            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 4 }}>
              <Pressable onPress={preview} accessibilityRole="button" hitSlop={8}>
                <Text style={{ fontFamily: FONTS.sansBold, color: p.teal, fontSize: 16 }}>{playing ? '■ Stop' : '▶ Preview voice'}</Text>
              </Pressable>
              <View style={{ flex: 1 }} />
              <Pressable onPress={onClose} accessibilityRole="button" style={{ borderWidth: 1, borderColor: p.line, backgroundColor: p.card, borderRadius: 999, paddingVertical: 10, paddingHorizontal: 18 }}>
                <Mono color={p.ink}>Cancel</Mono>
              </Pressable>
              <Pressable onPress={save} disabled={busy} accessibilityRole="button" style={{ backgroundColor: p.teal, borderRadius: 999, paddingVertical: 11, paddingHorizontal: 22, opacity: busy ? 0.6 : 1 }}>
                <Text style={{ color: p.tealInk, fontFamily: FONTS.sansBold, fontSize: 16 }}>{busy ? 'Saving…' : 'Save'}</Text>
              </Pressable>
            </View>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
