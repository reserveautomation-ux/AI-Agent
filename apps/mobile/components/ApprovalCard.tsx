import * as LocalAuthentication from 'expo-local-authentication';
import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, View } from 'react-native';

import { Badge, Button, Card, ErrorText, Input, T, styles } from '@/components/ui';
import { post, type ApprovalItem } from '@/lib/api';
import { confirmAsync } from '@/lib/confirm';
import {
  ACTION_LABEL,
  EDITABLE_FIELDS,
  decidedBadge,
  detailEntries,
  expiresIn,
  fieldLabel,
  fieldValue,
  formatMoney,
} from '@/lib/labels';
import { useTheme } from '@/lib/theme';


/** Money and other high-impact actions need a fingerprint / Face ID (or a confirm). */
async function confirmHighImpact(item: ApprovalItem): Promise<boolean> {
  const what = `${ACTION_LABEL[item.action] ?? item.action}${
    item.amount ? ` for ${formatMoney(item.amount, item.currency)}` : ''
  }`;
  if (Platform.OS !== 'web') {
    const [hasHardware, enrolled] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
    ]);
    if (hasHardware && enrolled) {
      const res = await LocalAuthentication.authenticateAsync({
        promptMessage: `Approve: ${what}`,
        cancelLabel: 'Cancel',
      });
      return res.success;
    }
  }
  return confirmAsync('Approve this?', what, 'Approve');
}

export function ApprovalCard({
  item,
  onDecided,
  showTask = true,
}: {
  item: ApprovalItem;
  onDecided: (updated: ApprovalItem) => void;
  showTask?: boolean;
}) {
  const c = useTheme();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = item.status === 'pending';
  const textFields = Object.entries(item.action_payload).filter(
    ([k, v]) => EDITABLE_FIELDS.has(k) && typeof v === 'string',
  );
  const [doneLabel, doneTone] = decidedBadge(item.status, item.execution_status);

  const startEdit = () => {
    setDraft(Object.fromEntries(textFields.map(([k, v]) => [k, v as string])));
    setEditing(true);
  };

  const approve = async () => {
    setError(null);
    if (item.owner_only && !(await confirmHighImpact(item))) return;
    const changes = editing
      ? Object.fromEntries(
          Object.entries(draft).filter(([k, v]) => v !== item.action_payload[k]),
        )
      : {};
    setBusy('approve');
    try {
      const updated = await post<ApprovalItem>(`/approvals/${item.id}/approve`, {
        action_hash: item.action_hash,
        ...(Object.keys(changes).length ? { changes } : {}),
      });
      setEditing(false);
      onDecided(updated);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    if (!(await confirmAsync('Decline this?', 'It will not be done.', 'Decline', true))) return;
    setBusy('reject');
    setError(null);
    try {
      onDecided(await post<ApprovalItem>(`/approvals/${item.id}/reject`, { action_hash: item.action_hash }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card style={pending ? { borderColor: item.owner_only ? c.bad : c.warn, borderWidth: 1.5 } : undefined}>
      <View style={styles.between}>
        <T bold size={16} style={{ flex: 1 }}>
          {ACTION_LABEL[item.action] ?? item.action}
        </T>
        {pending ? (
          <Badge
            label={item.owner_only ? '🔒 Owner only' : 'Needs approval'}
            tone={item.owner_only ? c.bad : c.warn}
          />
        ) : (
          <Badge label={doneLabel} tone={c[doneTone === 'bad' ? 'bad' : doneTone]} />
        )}
      </View>

      {showTask && (
        <Pressable onPress={() => router.push(`/tasks/${item.task_id}`)} accessibilityRole="link">
          <T small color={c.info} numberOfLines={1}>
            For: {item.task_title}
          </T>
        </Pressable>
      )}

      {item.amount && (
        <T bold size={20} style={{ marginTop: 8 }}>
          {formatMoney(item.amount, item.currency)}
        </T>
      )}

      <View style={{ marginTop: 10, gap: 8 }}>
        {editing
          ? textFields.map(([k]) => (
              <View key={k}>
                <T small muted>{fieldLabel(k)}</T>
                <Input
                  value={draft[k] ?? ''}
                  onChangeText={(v) => setDraft((d) => ({ ...d, [k]: v }))}
                  multiline={(draft[k] ?? '').length > 40}
                  accessibilityLabel={fieldLabel(k)}
                  style={{ marginTop: 4, textAlignVertical: 'top' }}
                />
              </View>
            ))
          : detailEntries(item.action_payload, !!item.amount).map(([k, v]) => (
              <View key={k}>
                <T small muted>{fieldLabel(k)}</T>
                <T>{fieldValue(v, k)}</T>
              </View>
            ))}
      </View>

      {item.action === 'calendar_create_event' && typeof item.action_payload.attendees === 'string' && (
        <T small style={{ marginTop: 8 }}>📨 Google will email invitations to these people when you approve.</T>
      )}
      {pending ? (
        <>
          <T small muted style={{ marginTop: 10 }}>
            ⏳ {expiresIn(item.expires_at)} · nothing happens until you approve
          </T>
          <View style={[styles.row, { marginTop: 12, flexWrap: 'wrap' }]}>
            <View style={{ flex: 1, minWidth: 140 }}>
              <Button
                title={editing ? 'Save & approve' : 'Approve'}
                icon={{ ios: 'checkmark', android: 'check', web: 'check' }}
                onPress={approve}
                loading={busy === 'approve'}
                disabled={busy !== null}
              />
            </View>
            {textFields.length > 0 && !editing && (
              <Button title="Edit" variant="ghost" onPress={startEdit} disabled={busy !== null} />
            )}
            {editing && <Button title="Undo edits" variant="ghost" onPress={() => setEditing(false)} />}
            <Button title="Decline" variant="ghost" onPress={reject} loading={busy === 'reject'} disabled={busy !== null} />
          </View>
        </>
      ) : (
        item.execution_result && (
          <T small style={{ marginTop: 10 }} color={item.execution_status === 'succeeded' ? c.ok : c.muted}>
            {item.execution_status === 'succeeded' ? '✅ ' : ''}
            {item.execution_result}
          </T>
        )
      )}
      <ErrorText>{error}</ErrorText>
    </Card>
  );
}
