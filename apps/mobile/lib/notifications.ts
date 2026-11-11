import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { post } from './api';

// Show task alerts even while the app is open (phones only; push isn't available on web).
if (Platform.OS !== 'web') {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

export type PushResult = { ok: true; token: string } | { ok: false; reason: string };

/** Ask permission, get this phone's Expo push token and register it with the API. */
export async function registerForPush(): Promise<PushResult> {
  if (Platform.OS === 'web') return { ok: false, reason: 'Push notifications need the phone app.' };
  if (!Device.isDevice) return { ok: false, reason: 'Push needs a real phone, not a simulator.' };

  // The channel must exist before asking for a token (Android 13+ shows the prompt then).
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('tasks', {
      name: 'Task updates',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 200, 120, 200],
    });
  }

  const current = await Notifications.getPermissionsAsync();
  let granted = current.granted;
  if (!granted) granted = (await Notifications.requestPermissionsAsync()).granted;
  if (!granted) return { ok: false, reason: 'Notifications are turned off for this app.' };

  const projectId =
    Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId;
  if (!projectId) {
    return { ok: false, reason: 'Run "npx eas-cli init" once so the app has an Expo project ID.' };
  }
  const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  await post('/devices', {
    token,
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    device_name: Device.deviceName ?? Device.modelName ?? null,
  });
  return { ok: true, token };
}

/** Open the right task when the owner taps a notification. */
export function useNotificationTaps() {
  const last = Notifications.useLastNotificationResponse();

  useEffect(() => {
    const url = last?.notification.request.content.data?.url;
    if (typeof url === 'string' && url.startsWith('/tasks/')) router.push(url as `/tasks/${string}`);
  }, [last]);
}
