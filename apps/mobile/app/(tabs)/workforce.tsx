import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, RefreshControl, ScrollView, Switch, View } from 'react-native';

import { Badge, Button, Card, ErrorText, H, T, styles } from '@/components/ui';
import { api, post, type Agent, type LifecycleDecision, type Workforce } from '@/lib/api';
import { useTheme } from '@/lib/theme';

const pct = (v: number | null | undefined) => (v == null ? '–' : `${Math.round(v * 100)}%`);

function AgentCard({ agent, onAction }: { agent: Agent; onAction: (a: Agent, op: string) => void }) {
  const c = useTheme();
  const ev = agent.latest_evaluation;
  const removable = agent.role !== 'chief' && agent.status !== 'retired';
  return (
    <Card style={agent.status === 'sandbox' ? { borderStyle: 'dashed' } : undefined}>
      <View style={styles.between}>
        <T bold style={{ flex: 1 }}>{agent.name}</T>
        <Badge status={agent.status} />
      </View>
      {agent.description && <T small muted style={{ marginTop: 4 }}>{agent.description}</T>}
      <T small muted style={{ marginTop: 6 }}>
        {ev
          ? `Success ${pct(ev.success_rate)} · Quality ${pct(ev.quality_score)} · ${ev.sample_size} tasks`
          : 'Not evaluated yet'}
        {agent.generation > 1 ? ` · generation ${agent.generation}` : ''}
        {agent.status === 'sandbox' ? ' · on trial' : ''}
      </T>
      {agent.lessons.length > 0 && (
        <View style={{ marginTop: 6 }}>
          <T small bold>Lessons learned</T>
          {agent.lessons.slice(0, 4).map((l) => (
            <T key={l} small muted>
              • {l}
            </T>
          ))}
        </View>
      )}
      <View style={[styles.row, { marginTop: 10, flexWrap: 'wrap' }]}>
        {agent.status === 'active' && agent.role !== 'chief' && (
          <Button title="Clone" small variant="ghost" onPress={() => onAction(agent, 'clone')} />
        )}
        {agent.status === 'sandbox' && (
          <Button title="Promote" small variant="ghost" onPress={() => onAction(agent, 'promote')} />
        )}
        {removable && agent.status !== 'suspended' && (
          <Button title="Suspend" small variant="ghost" onPress={() => onAction(agent, 'suspend')} />
        )}
        {removable && (
          <Button title="Retire" small variant="ghost" onPress={() => onAction(agent, 'retire')} />
        )}
      </View>
      {agent.status === 'retired' && <T small color={c.muted}>Retired; history kept.</T>}
    </Card>
  );
}

export default function WorkforceScreen() {
  const c = useTheme();
  const [wf, setWf] = useState<Workforce | null>(null);
  const [review, setReview] = useState<LifecycleDecision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setWf(await api<Workforce>('/workforce'));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onAction = (agent: Agent, op: string) => {
    if (op === 'retire') {
      Alert.alert(`Retire ${agent.name}?`, 'It stops receiving work. Its history is kept.', [
        { text: 'Keep', style: 'cancel' },
        { text: 'Retire', style: 'destructive', onPress: () => run(() => post(`/agents/${agent.id}/retire`)) },
      ]);
      return;
    }
    run(() => post(`/agents/${agent.id}/${op}`));
  };

  const refreshControl = (
    <RefreshControl
      refreshing={refreshing}
      onRefresh={async () => {
        setRefreshing(true);
        await load();
        setRefreshing(false);
      }}
    />
  );

  if (wf && wf.agents.length === 0) {
    return (
      <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.screen} refreshControl={refreshControl}>
        <Card>
          <T bold size={20}>Hire your AI workforce</T>
          <T muted style={{ marginVertical: 10 }}>
            Creates the Chief AI Executive, a QA Verifier and eight departments of specialist agents.
            Each agent only gets the tools its job needs.
          </T>
          <Button title="Hire initial workforce" onPress={() => run(() => post('/workforce/bootstrap'))} loading={busy} />
          <ErrorText>{error}</ErrorText>
        </Card>
      </ScrollView>
    );
  }

  const top = (wf?.agents ?? [])
    .filter((a) => a.role === 'chief' || a.role === 'verifier')
    .sort((a) => (a.role === 'chief' ? -1 : 1));
  const others = (wf?.agents ?? []).filter((a) => a.status !== 'retired');
  const retired = (wf?.agents ?? []).filter((a) => a.status === 'retired');
  const changes = review?.filter((d) => d.action !== 'keep' && d.action !== 'insufficient_data') ?? [];

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.screen} refreshControl={refreshControl}>
      {wf && (
        <Card>
          <View style={styles.between}>
            <T bold style={{ flex: 1 }}>
              🧬 Improve itself every night
            </T>
            <Switch
              value={wf.auto_improve}
              disabled={busy}
              onValueChange={(v) =>
                run(async () => setWf(await post<Workforce>('/workforce/auto-improve', { enabled: v })))
              }
              accessibilityLabel="Let the workforce improve itself every night"
            />
          </View>
          <T small muted style={{ marginTop: 6 }}>
            Strong agents are cloned and learn from feedback, then prove themselves on supervised trial work. Weak
            ones are paused, then retired (history kept). Approvals still apply to everything.
          </T>
        </Card>
      )}
      <Button
        title="Review performance"
        variant="ghost"
        onPress={() => run(async () => setReview(await post<LifecycleDecision[]>('/workforce/lifecycle-review')))}
        loading={busy}
      />
      <ErrorText>{error}</ErrorText>

      {review && (
        <Card style={{ marginTop: 12 }}>
          <T bold>Performance review</T>
          <T small muted style={{ marginVertical: 6 }}>
            Strong agents get a trial clone that must pass its own evaluation. Weak agents are
            suspended, then retired if they stay weak. Nothing is deleted.
          </T>
          {changes.length === 0 ? (
            <T muted small>No changes yet. Agents need evaluated tasks first.</T>
          ) : (
            <>
              {changes.map((d) => (
                <T key={d.agent_id} small style={{ marginBottom: 4 }}>
                  • {d.agent_name}: {d.action} — {d.reason}
                  {d.applied ? ' ✓' : ''}
                </T>
              ))}
              <View style={{ height: 8 }} />
              <Button
                title="Apply recommendations"
                onPress={() =>
                  run(async () => setReview(await post<LifecycleDecision[]>('/workforce/lifecycle-review?apply=true')))
                }
                loading={busy}
              />
            </>
          )}
        </Card>
      )}

      <H>Leadership</H>
      {top.map((a) => (
        <AgentCard key={a.id} agent={a} onAction={onAction} />
      ))}
      {others.some((a) => !a.department_id && a.role === 'specialist') && (
        <>
          <H>Reports to the Chief</H>
          {others
            .filter((a) => !a.department_id && a.role === 'specialist')
            .map((a) => (
              <AgentCard key={a.id} agent={a} onAction={onAction} />
            ))}
        </>
      )}
      {wf?.departments.map((d) => (
        <View key={d.id}>
          <H>{d.name}</H>
          {others
            .filter((a) => a.department_id === d.id)
            .sort((a) => (a.role === 'department_head' ? -1 : 1))
            .map((a) => (
              <AgentCard key={a.id} agent={a} onAction={onAction} />
            ))}
        </View>
      ))}
      {retired.length > 0 && (
        <>
          <H>Retired ({retired.length})</H>
          {retired.map((a) => (
            <AgentCard key={a.id} agent={a} onAction={onAction} />
          ))}
        </>
      )}
    </ScrollView>
  );
}
