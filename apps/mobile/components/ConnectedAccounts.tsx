import * as Linking from 'expo-linking';
import { useFocusEffect } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, ErrorText, T, styles } from '@/components/ui';
import { api, post, type ProviderConnections } from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';
import { useTheme } from '@/lib/theme';

const RESULT: Record<string, string> = {
  connected: '✅ Gmail connected. Approved emails will now be sent from it.',
  cancelled: "Gmail wasn't connected (you cancelled).",
  missing_permission: 'Please tick "Send email on your behalf" on Google\'s screen and try again.',
  error: "Gmail couldn't be connected. Please try again.",
};

/** Connect the owner's Gmail through Google's own sign-in page (in-app browser). */
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

  const connect = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const returnUrl = Linking.createURL('settings');
      const { auth_url } = await post<{ auth_url: string }>('/connections/gmail/start', {
        redirect_to: returnUrl,
      });
      const result = await WebBrowser.openAuthSessionAsync(auth_url, returnUrl);
      if (result.type === 'success') {
        const { queryParams } = Linking.parse(result.url);
        const outcome = queryParams?.connected ? 'connected' : String(queryParams?.status ?? 'error');
        setNotice(RESULT[outcome] ?? RESULT.error);
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
      `Disconnect ${name ?? 'Gmail'}?`,
      "Agents won't be able to send email until you reconnect.",
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

  const gmail = providers?.find((p) => p.provider === 'gmail');
  const active = gmail?.accounts.some((a) => a.status === 'active');

  return (
    <Card>
      <T bold>✉️ Gmail</T>
      <T small muted style={{ marginTop: 4 }}>
        Lets agents send emails you approve. Permission: send only. It can&apos;t read or delete
        your mail.
      </T>
      {notice && <T small style={{ marginTop: 8 }}>{notice}</T>}
      {gmail?.accounts.map((a) => (
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
      {gmail && !gmail.configured ? (
        <T small muted>Gmail isn&apos;t set up on the server yet (see the deployment guide).</T>
      ) : (
        <Button
          title={active ? 'Reconnect Gmail' : 'Connect Gmail'}
          variant={active ? 'ghost' : 'primary'}
          onPress={connect}
          loading={busy}
          disabled={!gmail}
        />
      )}
      <ErrorText>{error}</ErrorText>
    </Card>
  );
}
