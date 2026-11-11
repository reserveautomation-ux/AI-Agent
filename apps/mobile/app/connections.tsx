import * as Linking from 'expo-linking';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, View } from 'react-native';

import { TelegramChat } from '@/components/TelegramChat';
import { Badge, Button, Card, ErrorText, H, Input, T, styles } from '@/components/ui';
import { api, post, type Connector, type Me } from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';
import { connectorState, joinNames, STATE_BADGE } from '@/lib/labels';
import { useTheme } from '@/lib/theme';

function resultText(name: string, outcome: string): string {
  return (
    {
      connected: `✅ ${name} connected. Anything that was waiting for it carries on by itself.`,
      cancelled: `${name} wasn't connected (you cancelled).`,
      missing_permission: `Please allow every permission ${name} asks for, then try again.`,
    }[outcome] ?? `${name} couldn't be connected. Please try again.`
  );
}

/** Every service in one place: connect what you need, when you need it. */
export default function ConnectionsScreen() {
  const c = useTheme();
  const { need } = useLocalSearchParams<{ need?: string }>();
  const needed = useMemo(() => (need ? String(need).split(',').filter(Boolean) : []), [need]);
  const [items, setItems] = useState<Connector[] | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('All');
  const [keyFor, setKeyFor] = useState<Connector | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, who] = await Promise.all([api<Connector[]>('/connectors'), api<Me>('/me')]);
      setItems(list);
      setMe(who);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const canManage = !me || ['owner', 'admin'].includes(me.workspace.role);
  const categories = useMemo(() => ['All', ...new Set((items ?? []).map((x) => x.category))], [items]);
  const q = query.trim().toLowerCase();
  const visible = (items ?? []).filter(
    (x) =>
      (category === 'All' || x.category === category) &&
      (!q || `${x.name} ${x.description} ${x.category} ${x.keywords}`.toLowerCase().includes(q)),
  );
  const mine = visible.filter((x) => ['connected', 'expired'].includes(connectorState(x)));
  const rest = visible
    .filter((x) => !mine.includes(x))
    .sort((a, b) => Number(needed.includes(b.key)) - Number(needed.includes(a.key)));
  const stillNeeded = (items ?? []).filter((x) => needed.includes(x.key) && connectorState(x) !== 'connected');

  const signIn = async (x: Connector) => {
    setBusy(x.key);
    setError(null);
    setNotice(null);
    try {
      const returnUrl = Linking.createURL('connections');
      const { auth_url } = await post<{ auth_url: string }>(`/connections/${x.key}/start`, {
        redirect_to: returnUrl,
      });
      const result = await WebBrowser.openAuthSessionAsync(auth_url, returnUrl);
      if (result.type === 'success') {
        const { queryParams } = Linking.parse(result.url);
        setNotice(resultText(x.name, queryParams?.connected ? 'connected' : String(queryParams?.status ?? 'error')));
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async (x: Connector, id: string, name: string | null) => {
    const ok = await confirmAsync(
      `Disconnect ${name ?? x.name}?`,
      "Agents won't be able to use it until you reconnect.",
      'Disconnect',
      true,
    );
    if (!ok) return;
    setBusy(x.key);
    try {
      await post(`/connections/${id}/disconnect`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const card = (x: Connector) => {
    const state = connectorState(x);
    const [label, tone] = STATE_BADGE[state];
    const connectable = x.live && x.available && (x.auth === 'oauth2' || x.auth === 'api_key');
    return (
      <Card key={x.key} style={needed.includes(x.key) && state !== 'connected' ? { borderColor: c.warn, borderWidth: 2 } : undefined}>
        <View style={styles.between}>
          <T bold style={{ flex: 1 }}>
            {x.icon} {x.name}
          </T>
          <View style={styles.row}>
            {x.plan !== 'free' && <Badge label={x.plan === 'pro' ? 'Pro' : x.plan} tone={c.info} />}
            <Badge label={label} tone={c[tone]} />
          </View>
        </View>
        <T small muted style={{ marginTop: 4 }}>
          {x.description}
        </T>
        {!!x.note && (
          <T small style={{ marginTop: 4 }}>
            {x.note}
          </T>
        )}
        {x.accounts.map((a) => (
          <View key={a.id} style={[styles.between, { marginTop: 10 }]}>
            <View style={{ flex: 1 }}>
              <T small bold>
                {a.status === 'active' ? '🟢' : '🟠'} {a.display_name}
              </T>
              {a.status !== 'active' && <T small color={c.warn}>Access expired. Please reconnect.</T>}
            </View>
            {canManage && (
              <Button title="Disconnect" small variant="ghost" onPress={() => disconnect(x, a.id, a.display_name)} disabled={!!busy} />
            )}
          </View>
        ))}
        {state === 'unavailable' && (
          <T small muted style={{ marginTop: 8 }}>
            The server admin needs to switch this on first.
          </T>
        )}
        {x.key === 'telegram' && state === 'connected' && <TelegramChat />}
        {x.auth === 'deep_link' && !!x.open_url && (
          <View style={{ marginTop: 10 }}>
            <Button title={`Open ${x.name}`} small variant="ghost" onPress={() => Linking.openURL(x.open_url)} />
          </View>
        )}
        {connectable && canManage && (
          <View style={{ marginTop: 12 }}>
            <Button
              title={state === 'connected' ? 'Add another account' : state === 'expired' ? 'Reconnect' : `Connect ${x.name}`}
              variant={state === 'connected' ? 'ghost' : 'primary'}
              loading={busy === x.key}
              disabled={!!busy}
              onPress={() => (x.auth === 'oauth2' ? signIn(x) : setKeyFor(x))}
            />
          </View>
        )}
        {connectable && !canManage && state !== 'connected' && (
          <T small muted style={{ marginTop: 8 }}>
            Ask the workspace owner to connect this.
          </T>
        )}
      </Card>
    );
  };

  return (
    <>
      <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.screen} keyboardShouldPersistTaps="handled">
        <T muted small>
          Connect a service only when you need it. If a task needs one, it waits and carries on by itself once you
          connect. Sign-ins and keys are stored encrypted and never shown again.
        </T>
        {notice && (
          <Card style={{ marginTop: 12 }}>
            <T small>{notice}</T>
          </Card>
        )}
        {stillNeeded.length > 0 && (
          <Card style={{ borderColor: c.warn, marginTop: 12 }}>
            <T bold>A task is waiting for {joinNames(stillNeeded.map((x) => x.name))}</T>
            <T small muted>Connect it below and the task continues by itself.</T>
          </Card>
        )}
        <View style={{ height: 12 }} />
        <Input
          value={query}
          onChangeText={setQuery}
          placeholder="Search: WhatsApp, GitHub, cab, food…"
          autoCapitalize="none"
          accessibilityLabel="Search services"
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 10 }} contentContainerStyle={{ gap: 6 }}>
          {categories.map((cat) => (
            <Pressable
              key={cat}
              onPress={() => setCategory(cat)}
              accessibilityRole="button"
              accessibilityState={{ selected: category === cat }}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 999,
                borderWidth: 1,
                borderColor: category === cat ? c.text : c.border,
                backgroundColor: category === cat ? c.text : 'transparent',
              }}>
              <T small color={category === cat ? c.bg : c.muted}>
                {cat}
              </T>
            </Pressable>
          ))}
        </ScrollView>
        <ErrorText>{error}</ErrorText>

        {!items ? (
          <T muted style={{ marginTop: 12 }}>
            Loading…
          </T>
        ) : (
          <>
            {mine.length > 0 && (
              <>
                <H>Your connections</H>
                {mine.map(card)}
              </>
            )}
            <H>{mine.length ? 'More services' : 'Services'}</H>
            {rest.length === 0 ? <T muted>Nothing matches “{query}”.</T> : rest.map(card)}
          </>
        )}
      </ScrollView>
      <KeyForm
        connector={keyFor}
        onClose={() => setKeyFor(null)}
        onSaved={async (name) => {
          setKeyFor(null);
          setNotice(resultText(name, 'connected'));
          await load();
        }}
      />
    </>
  );
}

/** Paste a key or token; the server checks it with the provider before saving it encrypted. */
function KeyForm({
  connector,
  onClose,
  onSaved,
}: {
  connector: Connector | null;
  onClose: () => void;
  onSaved: (name: string) => void;
}) {
  const c = useTheme();
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setValues({});
    setError(null);
    onClose();
  };

  const save = async () => {
    if (!connector) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/connections/${connector.key}/key`, { fields: values });
      setValues({});
      onSaved(connector.name);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const complete = connector?.fields.every((f) => (values[f.key] ?? '').trim()) ?? false;

  return (
    <Modal visible={!!connector} transparent animationType="slide" onRequestClose={close}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' }} onPress={close} accessibilityLabel="Close" />
        <View style={{ backgroundColor: c.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 20, maxHeight: '85%' }}>
          <ScrollView keyboardShouldPersistTaps="handled">
            <T bold size={17}>
              {connector?.icon} Connect {connector?.name}
            </T>
            {!!connector?.how_to_get && (
              <T small muted style={{ marginTop: 6 }}>
                {connector.how_to_get}
              </T>
            )}
            {connector?.fields.map((f) => (
              <View key={f.key} style={{ marginTop: 12 }}>
                <T small bold>
                  {f.label}
                </T>
                <Input
                  value={values[f.key] ?? ''}
                  onChangeText={(t) => setValues((v) => ({ ...v, [f.key]: t }))}
                  placeholder={f.placeholder}
                  secureTextEntry={f.secret}
                  autoCapitalize="none"
                  autoCorrect={false}
                  accessibilityLabel={f.label}
                />
                {!!f.help && (
                  <T small muted>
                    {f.help}
                  </T>
                )}
              </View>
            ))}
            <T small muted style={{ marginTop: 12 }}>
              We check it with {connector?.name}, then store it encrypted. It is never shown again.
            </T>
            <ErrorText>{error}</ErrorText>
            <View style={{ height: 12 }} />
            <Button title="Save and connect" onPress={save} loading={busy} disabled={!complete} />
            <View style={{ height: 8 }} />
            <Button title="Cancel" variant="ghost" onPress={close} disabled={busy} />
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
