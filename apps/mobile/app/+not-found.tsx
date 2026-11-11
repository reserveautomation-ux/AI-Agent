import { Link, Stack } from 'expo-router';
import { View } from 'react-native';

import { T, styles } from '@/components/ui';
import { useTheme } from '@/lib/theme';

export default function NotFoundScreen() {
  const c = useTheme();
  return (
    <>
      <Stack.Screen options={{ title: 'Not found' }} />
      <View style={[styles.screen, { flex: 1, backgroundColor: c.bg, gap: 12 }]}>
        <T bold size={18}>This screen doesn&apos;t exist.</T>
        <Link href="/">
          <T color={c.info}>Go to the command screen</T>
        </Link>
      </View>
    </>
  );
}
