import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Platform, ScrollView, View } from 'react-native';

import { Badge, Button, Card, ErrorText, H, T, styles } from '@/components/ui';
import { API_URL, api, post, type Me } from '@/lib/api';
import { registerForPush } from '@/lib/notifications';
import { supabase } from '@/lib/supabase';
import { useTheme } from '@/lib/theme';

export default function SettingsScreen() {
  const c = useTheme();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [push, setPush] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setMe(await api<Me>('/me'));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const toggleKill = () => {
    if (!me) return;
    const enabling = !me.workspace.kill_switch;
    const doIt = async () => {
      setBusy(true);
      try {
        const ws = await post<Me['workspace']>('/workspace/kill-switch', { enabled: enabling });
        setMe({ ...me, workspace: ws });
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    };
    if (!enabling) return doIt();
    Alert.alert('Stop everything?', 'All agents stop and new tasks are blocked until you resume.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Stop all', style: 'destructive', onPress: doIt },
    ]);
  };

  const enablePush = async () => {
    setBusy(true);
    try {
      const r = await registerForPush();
      setPush(r.ok ? 'Notifications are on for this phone.' : r.reason);
    } catch (e) {
      setPush((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.screen}>
      <Card>
        <T muted small>Signed in as</T>
        <T bold>{me?.email ?? '…'}</T>
        {me && (
          <View style={[styles.row, { marginTop: 6 }]}>
            <T small muted>{me.workspace.name}</T>
            <Badge label={me.workspace.role} tone={c.info} />
          </View>
        )}
      </Card>

      <H>Emergency stop</H>
      <Card style={me?.workspace.kill_switch ? { borderColor: c.bad } : undefined}>
        <T>
          {me?.workspace.kill_switch
            ? 'Everything is stopped. Agents are paused and new tasks are blocked.'
            : 'Instantly stop all agents and block new tasks.'}
        </T>
        <View style={{ height: 10 }} />
        {me?.workspace.role === 'owner' ? (
          <Button
            title={me.workspace.kill_switch ? 'Resume work' : 'Stop all agents'}
            variant={me.workspace.kill_switch ? 'primary' : 'danger'}
            onPress={toggleKill}
            loading={busy}
          />
        ) : (
          <T small muted>Only the owner can use the emergency stop.</T>
        )}
      </Card>

      {Platform.OS !== 'web' && (
        <>
          <H>Notifications</H>
          <Card>
            <T>Get a notification when a task is done, needs your answer or needs approval.</T>
            <View style={{ height: 10 }} />
            <Button title="Turn on notifications" variant="ghost" onPress={enablePush} loading={busy} />
            {push && <T small muted style={{ marginTop: 8 }}>{push}</T>}
          </Card>
        </>
      )}

      <H>About</H>
      <Card>
        <T small muted>Server: {API_URL}</T>
        <T small muted>Voice, memory and files work the same as on the web app.</T>
      </Card>

      <Button title="Sign out" variant="ghost" onPress={() => supabase.auth.signOut()} />
      <ErrorText>{error}</ErrorText>
    </ScrollView>
  );
}
