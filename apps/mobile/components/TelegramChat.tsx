import * as Linking from 'expo-linking';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { Button, T } from '@/components/ui';
import { api, post } from '@/lib/api';
import { useTheme } from '@/lib/theme';

interface Link {
  bot: string | null;
  linked: boolean;
  link_url: string | null;
  available: boolean;
  reason: string | null;
}

/** Chat with your assistant from Telegram (free): link your Telegram chat once. */
export function TelegramChat() {
  const c = useTheme();
  const [link, setLink] = useState<Link | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Link>('/telegram/link')
      .then(setLink)
      .catch(() => {});
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const l = await post<Link>('/telegram/link');
      setLink(l);
      if (l.link_url) await Linking.openURL(l.link_url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!link) return null;
  return (
    <View style={{ marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: c.border, gap: 6 }}>
      <T bold>Chat with your assistant on Telegram</T>
      {link.linked ? (
        <>
          <T small>
            <T small color={c.ok}>● Linked. </T>
            Message your bot any time; updates, reminders and important-email alerts arrive there too.
          </T>
          <Button title="Unlink" small variant="ghost" onPress={async () => setLink(await post<Link>('/telegram/unlink'))} />
        </>
      ) : !link.available ? (
        <T small muted>
          {link.reason ?? 'Not set up on the server yet.'}
        </T>
      ) : (
        <>
          <T small muted>
            Free. Opens Telegram; tap Start to link your chat (the link works once, for 30 minutes).
          </T>
          <Button title="Link Telegram chat" onPress={start} loading={busy} />
        </>
      )}
      {!!error && (
        <T small color={c.bad}>
          {error}
        </T>
      )}
    </View>
  );
}
