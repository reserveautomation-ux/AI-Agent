import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { View } from 'react-native';

import { Button, Card, ErrorText, H, T, styles } from '@/components/ui';
import { api, post, REPEAT_LABEL, type Schedule } from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';

/** Reminders and repeating jobs set from chat, with a way to cancel them. */
export function Schedules() {
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Schedule[]>('/schedules')
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  }, []);
  useFocusEffect(load);

  const cancel = async (s: Schedule) => {
    if (!(await confirmAsync(`Cancel "${s.title}"?`, 'It will not run again.', 'Cancel it', true))) return;
    try {
      await post(`/schedules/${s.id}/cancel`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const active = (items ?? []).filter((s) => s.active);
  return (
    <>
      <H>Reminders & repeating jobs</H>
      <ErrorText>{error}</ErrorText>
      {items && active.length === 0 && (
        <Card>
          <T small muted>
            None yet. Ask in chat: “remind me at 6pm to call mom” or “every Monday at 9 send me a summary of my unread
            email”.
          </T>
        </Card>
      )}
      {active.map((s) => (
        <Card key={s.id}>
          <View style={styles.between}>
            <View style={{ flex: 1 }}>
              <T bold>
                {s.kind === 'reminder' ? '⏰ ' : '🔁 '}
                {s.title}
              </T>
              <T small muted>
                {s.kind === 'reminder' ? 'Reminder' : 'Job for your workforce'} · {REPEAT_LABEL[s.repeat]}
                {s.next_run_at
                  ? ` · next ${new Date(s.next_run_at).toLocaleString([], {
                      weekday: 'short',
                      day: 'numeric',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}`
                  : ''}
              </T>
            </View>
            <Button title="Cancel" small variant="ghost" onPress={() => cancel(s)} />
          </View>
        </Card>
      ))}
    </>
  );
}
