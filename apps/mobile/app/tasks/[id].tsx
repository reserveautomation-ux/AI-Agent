import { Stack, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, RefreshControl, ScrollView, View } from 'react-native';

import { Badge, Button, Card, ErrorText, H, Input, T, styles } from '@/components/ui';
import { api, post, shareArtifact, type TaskDetail } from '@/lib/api';
import { useTheme } from '@/lib/theme';

const TERMINAL = new Set(['completed', 'cancelled', 'expired']);
const WORKING = new Set(['draft', 'planned', 'queued', 'running', 'verifying']);

const ACTION_LABEL: Record<string, string> = {
  send_email: 'Send email',
  send_whatsapp: 'Send WhatsApp',
  calendar_create_event: 'Create calendar event',
  post_social: 'Publish post',
  deploy_web: 'Deploy website',
  book_flight: 'Book flight',
  place_stock_order: 'Place stock order',
  play_store_release: 'Release on Play Store',
  app_store_submit: 'Submit to App Store',
  browser_submit_form: 'Submit web form',
};

const FIELD_LABEL: Record<string, string> = {
  subject: 'Subject',
  body: 'Message',
  message: 'Message',
  text: 'Text',
  network: 'Network',
  title: 'Title',
  start: 'Starts',
  end: 'Ends',
  symbol: 'Stock',
  side: 'Buy/Sell',
  quantity: 'Quantity',
  order_type: 'Order type',
  amount: 'Amount',
  currency: 'Currency',
};

function CsvTable({ text }: { text: string }) {
  const c = useTheme();
  const rows = text
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(0, 6)
    .map((l) => l.split(','));
  if (rows.length < 2) return null;
  return (
    <ScrollView horizontal style={{ marginTop: 8 }}>
      <View>
        {rows.map((r, i) => (
          <View key={i} style={{ flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.border }}>
            {r.map((cell, j) => (
              <T key={j} small bold={i === 0} style={{ width: 130, padding: 6 }} numberOfLines={2}>
                {cell}
              </T>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

export default function TaskScreen() {
  const c = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [openStep, setOpenStep] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setTask(await api<TaskDetail>(`/tasks/${id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      load();
      const t = setInterval(load, 4000);
      return () => clearInterval(t);
    }, [load]),
  );

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setAnswer('');
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const confirmCancel = () =>
    Alert.alert('Cancel this task?', 'Agents will stop working on it.', [
      { text: 'Keep working', style: 'cancel' },
      { text: 'Cancel task', style: 'destructive', onPress: () => act(() => post(`/tasks/${id}/cancel`, {})) },
    ]);

  if (!task) {
    return (
      <View style={[styles.screen, { flex: 1, backgroundColor: c.bg }]}>
        {error ? <ErrorText>{error}</ErrorText> : <ActivityIndicator />}
      </View>
    );
  }

  const pending = task.approvals.filter((a) => a.status === 'pending');
  const asking = task.status === 'blocked' && task.steps.length === 0;

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
      <Stack.Screen options={{ title: task.title }} />
      <Card>
        <View style={styles.between}>
          <T bold size={18} style={{ flex: 1 }}>{task.title}</T>
          <Badge status={task.status} />
        </View>
        {task.objective.trim() !== task.title.trim() && (
          <T muted small style={{ marginTop: 6 }}>{task.objective}</T>
        )}

        {WORKING.has(task.status) && (
          <View style={[styles.row, { marginTop: 12 }]}>
            <ActivityIndicator color={c.info} size="small" />
            <T small color={c.info} style={{ flex: 1 }}>
              Your workforce is on it. You can close the app; you&apos;ll get a notification.
            </T>
          </View>
        )}

        {task.result_summary && (
          <View
            style={{
              marginTop: 12,
              padding: 12,
              borderRadius: 10,
              backgroundColor: c.bg,
              borderLeftWidth: 3,
              borderLeftColor: task.status === 'completed' ? c.ok : c.warn,
            }}>
            <T>{task.result_summary}</T>
          </View>
        )}

        {(task.status === 'blocked' || task.status === 'failed') && (
          <View style={{ marginTop: 14, gap: 10 }}>
            <T bold>{asking ? "Answer the Chief's question" : 'Add guidance (optional) and retry'}</T>
            <Input
              value={answer}
              onChangeText={setAnswer}
              multiline
              placeholder={asking ? 'Type your answer' : 'Anything to change?'}
              style={{ minHeight: 70, textAlignVertical: 'top' }}
            />
            <Button
              title={asking ? 'Answer and continue' : 'Retry'}
              onPress={() => act(() => post(`/tasks/${id}/retry`, answer.trim() ? { answer } : {}))}
              loading={busy}
              disabled={asking && !answer.trim()}
            />
          </View>
        )}

        <View style={[styles.between, { marginTop: 14 }]}>
          <T small muted>
            Cost ${Number(task.cost_usd).toFixed(3)}
            {task.budget_limit_usd ? ` of $${task.budget_limit_usd}` : ''}
          </T>
          {!TERMINAL.has(task.status) && (
            <Button title="Cancel" variant="ghost" small onPress={confirmCancel} disabled={busy} />
          )}
        </View>
        <ErrorText>{error}</ErrorText>
      </Card>

      {pending.length > 0 && (
        <>
          <H>Waiting for your approval</H>
          <T small muted>
            Nothing here has been sent, booked or paid. One-tap approvals arrive in the next update.
          </T>
          {pending.map((a) => (
            <Card key={a.id} style={{ borderColor: c.warn, marginTop: 10 }}>
              <T bold>{ACTION_LABEL[a.action] ?? a.action}</T>
              {a.recipient && <T small>To: {a.recipient}</T>}
              {a.amount && <T small>Amount: {a.amount} {a.currency}</T>}
              <View style={{ marginTop: 8, gap: 4 }}>
                {Object.entries(a.action_payload)
                  .filter(([k]) => k !== 'to')
                  .map(([k, v]) => (
                    <T key={k} small>
                      <T small bold>{FIELD_LABEL[k] ?? k}: </T>
                      {typeof v === 'string' ? v : JSON.stringify(v)}
                    </T>
                  ))}
              </View>
              <T small muted style={{ marginTop: 6 }}>
                Expires {new Date(a.expires_at).toLocaleString()}
              </T>
            </Card>
          ))}
        </>
      )}

      {task.artifacts.length > 0 && (
        <>
          <H>Files</H>
          {task.artifacts.map((a) => (
            <Card key={a.id}>
              <View style={styles.between}>
                <View style={{ flex: 1 }}>
                  <T bold numberOfLines={1}>📄 {a.name}</T>
                  <T small muted>{(a.size_bytes / 1024).toFixed(1)} KB</T>
                </View>
                <Button
                  title="Share"
                  small
                  variant="ghost"
                  icon={{ ios: 'square.and.arrow.up', android: 'share', web: 'share' }}
                  onPress={() => shareArtifact(a).catch((e) => setError(e.message))}
                />
              </View>
              {a.file_type === 'text/csv' && a.preview ? (
                <CsvTable text={a.preview} />
              ) : (
                a.preview && (
                  <T small muted style={{ marginTop: 8 }} numberOfLines={8}>
                    {a.preview}
                  </T>
                )
              )}
            </Card>
          ))}
        </>
      )}

      {task.plan?.understanding && (
        <>
          <H>Plan</H>
          <Card>
            <T>{task.plan.understanding}</T>
            {!!task.plan.assumptions?.length && (
              <T small muted style={{ marginTop: 6 }}>Assumptions: {task.plan.assumptions.join('; ')}</T>
            )}
            {task.steps.map((s) => (
              <Pressable
                key={s.sequence}
                onPress={() => setOpenStep(openStep === s.sequence ? null : s.sequence)}
                accessibilityRole="button"
                accessibilityState={{ expanded: openStep === s.sequence }}
                style={{ marginTop: 14, borderTopWidth: 1, borderTopColor: c.border, paddingTop: 12 }}>
                <View style={styles.between}>
                  <T bold style={{ flex: 1 }}>
                    {s.sequence}. {s.title}
                  </T>
                  <Badge status={s.status === 'succeeded' ? 'completed' : s.status} />
                </View>
                <T small muted>{s.agent_name ?? 'Unassigned'}</T>
                {s.summary && <T style={{ marginTop: 4 }}>{s.summary}</T>}
                {openStep === s.sequence && s.result && s.result !== s.summary && (
                  <T small muted style={{ marginTop: 6 }}>{s.result}</T>
                )}
                {s.limitations.length > 0 && (
                  <T small color={c.warn} style={{ marginTop: 4 }}>
                    Couldn&apos;t do: {s.limitations.join('; ')}
                  </T>
                )}
              </Pressable>
            ))}
          </Card>
        </>
      )}

      {!!task.verification?.criteria?.length && (
        <>
          <H>Quality check</H>
          <Card>
            {task.verification.criteria.map((cr, i) => (
              <T key={i} small style={{ marginBottom: 6 }}>
                {cr.met ? '✅' : '❌'} {cr.criterion}
                {cr.note ? ` — ${cr.note}` : ''}
              </T>
            ))}
          </Card>
        </>
      )}

      <H>Timeline</H>
      {task.events.map((ev) => (
        <View key={ev.id} style={[styles.row, { marginBottom: 8, flexWrap: 'wrap' }]}>
          <Badge status={ev.to_status} />
          <T small muted>
            {new Date(ev.created_at).toLocaleTimeString()} · {ev.actor_type}
            {ev.reason ? ` · ${ev.reason}` : ''}
          </T>
        </View>
      ))}
    </ScrollView>
  );
}
