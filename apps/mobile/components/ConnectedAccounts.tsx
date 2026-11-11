import * as Linking from 'expo-linking';
import { useFocusEffect } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, ErrorText, T, styles } from '@/components/ui';
import { api, post, type ProviderConnections } from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';
import { useTheme } from '@/lib/theme';

const ICON: Record<string, string> = { gmail: '✉️', google_calendar: '📅' };

function resultText(name: string, outcome: string): string {
  return (
    {
      connected: `✅ ${name} connected.`,
      cancelled: `${name} wasn't connected (you cancelled).`,
      missing_permission: `Please allow every permission ${name} asks for on Google's screen, then try again.`,
    }[outcome] ?? `${name} couldn't be connected. Please try again.`
  );
}

/** Connect Google services through Google's own sign-in page (in-app browser). */
export function ConnectedAccounts() {
  const c = useTheme();
  const [providers, setProviders] = useState<ProviderConnections[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setProviders(await api<ProviderConnections[]>('/connections'));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const connect = async (provider: string, name: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const returnUrl = Linking.createURL('settings');
      const { auth_url } = await post<{ auth_url: string }>(`/connections/${provider}/start`, {
        redirect_to: returnUrl,
      });
      const result = await WebBrowser.openAuthSessionAsync(auth_url, returnUrl);
      if (result.type === 'success') {
        const { queryParams } = Linking.parse(result.url);
        const outcome = queryParams?.connected ? 'connected' : String(queryParams?.status ?? 'error');
        setNotice(resultText(name, outcome));
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (id: string, name: string | null) => {
    const ok = await confirmAsync(
      `Disconnect ${name ?? 'this account'}?`,
      "Agents won't be able to use it until you reconnect.",
      'Disconnect',
      true,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await post(`/connections/${id}/disconnect`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!providers) {
    return (
      <Card>
        <T muted>{error ?? 'Loading…'}</T>
      </Card>
    );
  }

  return (
    <>
      {notice && (
        <Card>
          <T small>{notice}</T>
        </Card>
      )}
      {providers.map((p) => {
        const active = p.accounts.some((a) => a.status === 'active');
        return (
          <Card key={p.provider}>
            <T bold>
              {ICON[p.provider] ?? '🔗'} {p.name}
            </T>
            <T small muted style={{ marginTop: 4 }}>
              {p.description}
            </T>
            {p.accounts.map((a) => (
              <View key={a.id} style={[styles.between, { marginTop: 10 }]}>
                <View style={{ flex: 1 }}>
                  <T small bold>
                    {a.status === 'active' ? '🟢' : '🟠'} {a.display_name}
                  </T>
                  {a.status !== 'active' && <T small color={c.warn}>Access expired. Please reconnect.</T>}
                  {a.last_used_at && <T small muted>Last used {new Date(a.last_used_at).toLocaleString()}</T>}
                </View>
                <Button title="Disconnect" small variant="ghost" onPress={() => disconnect(a.id, a.display_name)} disabled={busy} />
              </View>
            ))}
            <View style={{ height: 12 }} />
            {!p.configured ? (
              <T small muted>Not set up on the server yet (see the deployment guide).</T>
            ) : (
              <Button
                title={active ? `Reconnect ${p.name}` : `Connect ${p.name}`}
                variant={active ? 'ghost' : 'primary'}
                onPress={() => connect(p.provider, p.name)}
                loading={busy}
              />
            )}
          </Card>
        );
      })}
      <ErrorText>{error}</ErrorText>
    </>
  );
}
