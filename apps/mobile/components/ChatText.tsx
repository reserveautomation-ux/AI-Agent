import * as Linking from 'expo-linking';
import type { ReactNode } from 'react';
import { Platform, Text, View } from 'react-native';

import { useTheme } from '@/lib/theme';

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+)/g;

/** Chat replies with light formatting: paragraphs, bullet lists, **bold**, `code`, links. */
export function ChatText({ text, size = 16 }: { text: string; size?: number }) {
  const c = useTheme();
  const base = { color: c.text, fontSize: size, lineHeight: size * 1.45 };
  const mono = Platform.select({ ios: 'Menlo', default: 'monospace' });

  const inline = (line: string): ReactNode[] => {
    const out: ReactNode[] = [];
    let last = 0;
    for (const m of line.matchAll(TOKEN)) {
      const t = m[0];
      if (m.index! > last) out.push(line.slice(last, m.index));
      const k = out.length;
      if (t.startsWith('**')) {
        out.push(
          <Text key={k} style={{ fontWeight: '700' }}>
            {t.slice(2, -2)}
          </Text>,
        );
      } else if (t.startsWith('`')) {
        out.push(
          <Text key={k} style={{ fontFamily: mono, fontSize: size - 2 }}>
            {t.slice(1, -1)}
          </Text>,
        );
      } else {
        const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t) ?? [null, t, t];
        out.push(
          <Text key={k} style={{ color: c.info, textDecorationLine: 'underline' }} onPress={() => Linking.openURL(href!)}>
            {label}
          </Text>,
        );
      }
      last = m.index! + t.length;
    }
    if (last < line.length) out.push(line.slice(last));
    return out;
  };

  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]);
      blocks.push(
        <View key={blocks.length} style={{ backgroundColor: c.bg, borderColor: c.border, borderWidth: 1, borderRadius: 8, padding: 10 }}>
          <Text style={{ color: c.text, fontFamily: mono, fontSize: 13 }}>{code.join('\n')}</Text>
        </View>,
      );
      continue;
    }
    if (!line.trim()) continue;
    const bullet = /^\s*([-*•]|\d+[.)])\s+(.*)$/.exec(line);
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (bullet) {
      const mark = /\d/.test(bullet[1]) ? bullet[1] : '•';
      blocks.push(
        <View key={blocks.length} style={{ flexDirection: 'row', gap: 8, paddingLeft: 4 }}>
          <Text style={base}>{mark}</Text>
          <Text style={[base, { flex: 1 }]}>{inline(bullet[2])}</Text>
        </View>,
      );
    } else {
      blocks.push(
        <Text key={blocks.length} style={[base, heading ? { fontWeight: '700' } : null]} selectable>
          {inline(heading ? heading[1] : line)}
        </Text>,
      );
    }
  }
  return <View style={{ gap: 8 }}>{blocks}</View>;
}

/** Text to read aloud: no markdown symbols or long links. */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' (code) ')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '$1')
    .replace(/https?:\/\/\S+/g, 'the link')
    .replace(/[*_`#>|]+/g, '')
    .replace(/^\s*[-•]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}
