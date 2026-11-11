import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';

import { ApprovalCard } from '@/components/ApprovalCard';
import { Button, Card, ErrorText, H, T, styles } from '@/components/ui';
import { api, type ApprovalItem, type ProviderConnections } from '@/lib/api';
import { useTheme } from '@/lib/theme';

export default function ApprovalsScreen() {
  const c = useTheme();
  const [pending, setPending] = useState<ApprovalItem[] | null>(null);
  const [decided, setDecided] = useState<ApprovalItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [gmailReady, setGmailReady] = useState(true);

  const load = useCallback(async () => {
    try {
      const [p, d, conns] = await Promise.all([
        api<ApprovalItem[]>('/approvals'),
        api<ApprovalItem[]>('/approvals?state=decided&limit=20'),
        api<ProviderConnections[]>('/connections').catch(() => []),
      ]);
      setPending(p);
      setDecided(d);
      const gmail = conns.find((x) => x.provider === 'gmail');
      setGmailReady(!gmail || gmail.accounts.some((a) => a.status === 'active'));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
      const t = setInterval(load, 10000);
      return () => clearInterval(t);
    }, [load]),
  );

  const onDecided = (updated: ApprovalItem) => {
    setPending((list) => (list ?? []).filter((a) => a.id !== updated.id));
    setDecided((list) => [updated, ...list.filter((a) => a.id !== updated.id)]);
  };

  return (
    <ScrollView
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
      <T muted small>
        Your agents prepare emails, messages, bookings and orders. Nothing is sent, booked or paid
        until you approve the exact details below. Money actions need your fingerprint or Face ID.
      </T>
      <ErrorText>{error}</ErrorText>

      {!gmailReady && pending?.some((a) => a.action === 'send_email') && (
        <Card style={{ borderColor: c.warn, marginTop: 12 }}>
          <T bold>Connect Gmail to send these emails</T>
          <T small muted style={{ marginVertical: 6 }}>
            Without it, approved emails are recorded but not sent.
          </T>
          <Button title="Connect Gmail" variant="ghost" onPress={() => router.push('/settings')} />
        </Card>
      )}

      <H>Waiting for you{pending && pending.length ? ` (${pending.length})` : ''}</H>
      {pending === null ? (
        <T muted>Loading…</T>
      ) : pending.length === 0 ? (
        <Card>
          <View style={{ alignItems: 'center', paddingVertical: 12 }}>
            <T size={28}>✅</T>
            <T bold style={{ marginTop: 6 }}>All caught up</T>
            <T small muted>New approvals will notify your phone.</T>
          </View>
        </Card>
      ) : (
        pending.map((a) => <ApprovalCard key={a.id} item={a} onDecided={onDecided} />)
      )}

      {decided.length > 0 && (
        <>
          <H>Recently decided</H>
          {decided.map((a) => (
            <ApprovalCard key={a.id} item={a} onDecided={onDecided} />
          ))}
        </>
      )}
    </ScrollView>
  );
}
