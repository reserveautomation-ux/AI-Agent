import { Tabs } from 'expo-router';
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';

import { Icon, type IconName } from '@/components/ui';
import { api } from '@/lib/api';
import { useTheme } from '@/lib/theme';

/** How many approvals are waiting (shown as a badge on the tab). */
function usePendingApprovals(): number {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<unknown[]>('/approvals?limit=99')
        .then((list) => alive && setCount(list.length))
        .catch(() => {});
    load();
    const timer = setInterval(load, 20000);
    const sub = AppState.addEventListener('change', (s) => s === 'active' && load());
    return () => {
      alive = false;
      clearInterval(timer);
      sub.remove();
    };
  }, []);
  return count;
}

const TABS: { name: string; title: string; icon: IconName }[] = [
  { name: 'index', title: 'Command', icon: { ios: 'bolt.fill', android: 'bolt', web: 'bolt' } },
  {
    name: 'approvals',
    title: 'Approvals',
    icon: { ios: 'checkmark.seal.fill', android: 'verified', web: 'verified' },
  },
  {
    name: 'workforce',
    title: 'Workforce',
    icon: { ios: 'person.3.fill', android: 'groups', web: 'groups' },
  },
  {
    name: 'memory',
    title: 'Memory',
    icon: { ios: 'brain.head.profile', android: 'psychology', web: 'psychology' },
  },
  {
    name: 'settings',
    title: 'Settings',
    icon: { ios: 'gearshape.fill', android: 'settings', web: 'settings' },
  },
];

export default function TabLayout() {
  const c = useTheme();
  const pending = usePendingApprovals();
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: c.tint,
        tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border },
        headerStyle: { backgroundColor: c.surface },
        headerTintColor: c.text,
        headerShown: true,
      }}>
      {TABS.map((t) => (
        <Tabs.Screen
          key={t.name}
          name={t.name}
          options={{
            title: t.title,
            tabBarIcon: ({ color }) => <Icon name={t.icon} color={String(color)} size={24} />,
            tabBarBadge: t.name === 'approvals' && pending > 0 ? pending : undefined,
          }}
        />
      ))}
    </Tabs>
  );
}
