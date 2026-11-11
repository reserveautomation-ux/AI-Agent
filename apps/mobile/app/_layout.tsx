import { DMMono_400Regular, DMMono_500Medium } from '@expo-google-fonts/dm-mono';
import { DMSans_400Regular, DMSans_500Medium, DMSans_700Bold } from '@expo-google-fonts/dm-sans';
import { InstrumentSerif_400Regular } from '@expo-google-fonts/instrument-serif';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, router, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Platform, View } from 'react-native';
import 'react-native-reanimated';

import { T, styles } from '@/components/ui';
import { useColorScheme } from '@/components/useColorScheme';
import { AuthProvider, useAuth } from '@/lib/auth';
import { registerForPush, useNotificationTaps } from '@/lib/notifications';
import { configError } from '@/lib/supabase';
import { useTheme } from '@/lib/theme';

export { ErrorBoundary } from 'expo-router';

export const unstable_settings = { anchor: '(tabs)' };

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useFonts({
    SpaceMono: require('../assets/fonts/SpaceMono-Regular.ttf'),
    InstrumentSerif_400Regular,
    DMSans_400Regular,
    DMSans_500Medium,
    DMSans_700Bold,
    DMMono_400Regular,
    DMMono_500Medium,
  });

  useEffect(() => {
    if (error) throw error;
  }, [error]);

  if (!loaded) return null;

  return (
    <AuthProvider>
      <RootNav />
    </AuthProvider>
  );
}

function RootNav() {
  const scheme = useColorScheme();
  const c = useTheme();
  const { session, ready } = useAuth();
  const segments = useSegments();

  useEffect(() => {
    if (ready) SplashScreen.hideAsync();
  }, [ready]);

  // Send signed-out users to the sign-in screen and signed-in users away from it.
  useEffect(() => {
    if (!ready || configError) return;
    const onLogin = segments[0] === 'login';
    if (!session && !onLogin) router.replace('/login');
    if (session && onLogin) router.replace('/');
  }, [ready, session, segments]);

  // Register this phone for task alerts once signed in (silently skipped if unavailable).
  useEffect(() => {
    if (session && Platform.OS !== 'web') registerForPush().catch(() => {});
  }, [session]);

  if (configError) {
    return (
      <View style={[styles.screen, { flex: 1, justifyContent: 'center', backgroundColor: c.bg }]}>
        <T bold size={18}>Configuration needed</T>
        <T muted style={{ marginTop: 8 }}>{configError}</T>
      </View>
    );
  }

  return (
    <ThemeProvider value={scheme === 'dark' ? DarkTheme : DefaultTheme}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      {session && Platform.OS !== 'web' && <NotificationTaps />}
      <Stack screenOptions={{ contentStyle: { backgroundColor: c.bg } }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ headerShown: false }} />
        <Stack.Screen name="tasks/[id]" options={{ title: 'Task', headerBackTitle: 'Back' }} />
        <Stack.Screen name="connections" options={{ title: 'Connections', headerBackTitle: 'Back' }} />
        <Stack.Screen name="memory" options={{ title: 'Memory', headerBackTitle: 'Back' }} />
      </Stack>
    </ThemeProvider>
  );
}

function NotificationTaps() {
  useNotificationTaps();
  return null;
}
