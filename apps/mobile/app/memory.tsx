import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, ScrollView, Switch, View } from 'react-native';

import { Button, Card, ErrorText, H, Input, T, styles } from '@/components/ui';
import { api, del, post, type Memory } from '@/lib/api';
import { useTheme } from '@/lib/theme';

const TYPES: { value: Memory['memory_type']; label: string; hint: string }[] = [
  { value: 'preference', label: 'Preference', hint: 'I prefer aisle seats' },
  { value: 'fact', label: 'Fact', hint: 'My office is in Andheri East' },
  { value: 'contact', label: 'Contact', hint: 'Rahul (designer) — rahul@example.com' },
  { value: 'instruction', label: 'Rule', hint: 'Never book flights before 8am' },
];

function MemoryRow({ m, onChange }: { m: Memory; onChange: (fn: () => Promise<unknown>) => void }) {
  const c = useTheme();
  return (
    <Card>
      <T>{m.content}</T>
      <T small muted style={{ marginTop: 4 }}>
        {m.memory_type === 'instruction' ? 'Standing rule' : m.memory_type}
        {m.agent_name ? ` · ${m.agent_name}` : ''}
        {m.use_count > 0 ? ` · used ${m.use_count}×` : ''}
        {!m.trusted ? ' · unverified' : ''}
      </T>
      <View style={[styles.row, { marginTop: 10, flexWrap: 'wrap' }]}>
        {!m.trusted && (
          <Button title="Confirm" small variant="ghost" onPress={() => onChange(() => post(`/memories/${m.id}/confirm`))} />
        )}
        <Button
          title={m.pinned ? '★ Pinned' : '☆ Pin'}
          small
          variant="ghost"
          onPress={() => onChange(() => post(`/memories/${m.id}/pin`, { pinned: !m.pinned }))}
        />
        <Button
          title="Forget"
          small
          variant="ghost"
          onPress={() =>
            Alert.alert('Forget this?', m.content, [
              { text: 'Keep', style: 'cancel' },
              { text: 'Forget', style: 'destructive', onPress: () => onChange(() => del(`/memories/${m.id}`)) },
            ])
          }
        />
      </View>
      {m.pinned && <T small color={c.muted}>Agents always see pinned memories.</T>}
    </Card>
  );
}

export default function MemoryScreen() {
  const c = useTheme();
  const [items, setItems] = useState<Memory[] | null>(null);
  const [q, setQ] = useState('');
  const [content, setContent] = useState('');
  const [type, setType] = useState<Memory['memory_type']>('preference');
  const [pinned, setPinned] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (query: string) => {
    try {
      const path = query.trim() ? `/memories?q=${encodeURIComponent(query)}` : '/memories';
      setItems(await api<Memory[]>(path));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(q);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [load]),
  );

  useEffect(() => {
    const t = setTimeout(() => load(q), 300);
    return () => clearTimeout(t);
  }, [q, load]);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load(q);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const add = async () => {
    setBusy(true);
    await run(async () => {
      await post('/memories', { content, memory_type: type, pinned });
      setContent('');
      setPinned(false);
    });
    setBusy(false);
  };

  const yours = items?.filter((m) => m.owner_scope === 'workspace' && m.trusted) ?? [];
  const noted = items?.filter((m) => m.owner_scope === 'workspace' && !m.trusted) ?? [];
  const learned = items?.filter((m) => m.owner_scope === 'agent') ?? [];

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.screen} keyboardShouldPersistTaps="handled">
      <Card>
        <T bold size={17}>Teach your workforce</T>
        <T small muted style={{ marginBottom: 10 }}>
          Never stored: passwords, OTPs, card, Aadhaar or PAN numbers.
        </T>
        <View style={[styles.row, { flexWrap: 'wrap', marginBottom: 10 }]}>
          {TYPES.map((t) => (
            <Pressable
              key={t.value}
              onPress={() => setType(t.value)}
              accessibilityRole="button"
              accessibilityState={{ selected: type === t.value }}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 999,
                borderWidth: 1,
                borderColor: type === t.value ? c.tint : c.border,
                backgroundColor: type === t.value ? c.bg : 'transparent',
              }}>
              <T small bold={type === t.value}>{t.label}</T>
            </Pressable>
          ))}
        </View>
        <Input
          value={content}
          onChangeText={setContent}
          multiline
          placeholder={TYPES.find((t) => t.value === type)?.hint}
          style={{ minHeight: 70, textAlignVertical: 'top' }}
        />
        <View style={[styles.between, { marginVertical: 10 }]}>
          <T small muted>Always use (pin)</T>
          <Switch value={pinned} onValueChange={setPinned} accessibilityLabel="Pin memory" />
        </View>
        <Button title="Remember" onPress={add} loading={busy} disabled={!content.trim()} />
        <ErrorText>{error}</ErrorText>
      </Card>

      <Input value={q} onChangeText={setQ} placeholder="Search memories…" accessibilityLabel="Search memories" />

      {items === null ? (
        <T muted style={{ marginTop: 12 }}>Loading…</T>
      ) : items.length === 0 ? (
        <T muted style={{ marginTop: 12 }}>{q ? 'Nothing matches.' : 'Nothing remembered yet.'}</T>
      ) : (
        <>
          {yours.length > 0 && <H>About you</H>}
          {yours.map((m) => (
            <MemoryRow key={m.id} m={m} onChange={run} />
          ))}
          {noted.length > 0 && (
            <>
              <H>Noted by agents</H>
              <T small muted style={{ marginBottom: 8 }}>
                Confirm the ones that are right. Unconfirmed notes are never treated as instructions.
              </T>
            </>
          )}
          {noted.map((m) => (
            <MemoryRow key={m.id} m={m} onChange={run} />
          ))}
          {learned.length > 0 && <H>Agents&apos; own learnings</H>}
          {learned.map((m) => (
            <MemoryRow key={m.id} m={m} onChange={run} />
          ))}
        </>
      )}
    </ScrollView>
  );
}
