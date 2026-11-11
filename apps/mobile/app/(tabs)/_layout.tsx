import { Tabs } from 'expo-router';

import { Icon, type IconName } from '@/components/ui';
import { useTheme } from '@/lib/theme';

const TABS: { name: string; title: string; icon: IconName }[] = [
  { name: 'index', title: 'Command', icon: { ios: 'bolt.fill', android: 'bolt', web: 'bolt' } },
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
          }}
        />
      ))}
    </Tabs>
  );
}
