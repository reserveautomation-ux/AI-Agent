import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { STATUS_TONE, statusLabel, useTheme } from '@/lib/theme';

export type IconName = SymbolViewProps['name'];

export function Icon({ name, color, size = 22 }: { name: IconName; color: string; size?: number }) {
  return <SymbolView name={name} tintColor={color} size={size} />;
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  const c = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }, style]}>
      {children}
    </View>
  );
}

export function T({
  children,
  muted,
  small,
  bold,
  size,
  color,
  style,
  numberOfLines,
}: {
  children: ReactNode;
  muted?: boolean;
  small?: boolean;
  bold?: boolean;
  size?: number;
  color?: string;
  style?: TextStyle;
  numberOfLines?: number;
}) {
  const c = useTheme();
  return (
    <Text
      numberOfLines={numberOfLines}
      style={[
        {
          color: color ?? (muted ? c.muted : c.text),
          fontSize: size ?? (small ? 13 : 15),
          fontWeight: bold ? '600' : '400',
          lineHeight: (size ?? (small ? 13 : 15)) * 1.4,
        },
        style,
      ]}>
      {children}
    </Text>
  );
}

export function H({ children, style }: { children: ReactNode; style?: TextStyle }) {
  return (
    <T bold size={18} style={{ marginTop: 20, marginBottom: 8, ...style }}>
      {children}
    </T>
  );
}

export function Button({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  small,
  icon,
}: {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'ghost' | 'danger';
  disabled?: boolean;
  loading?: boolean;
  small?: boolean;
  icon?: IconName;
}) {
  const c = useTheme();
  const bg = variant === 'primary' ? c.brand : variant === 'danger' ? c.bad : 'transparent';
  const fg = variant === 'primary' ? c.onBrand : variant === 'danger' ? '#fff' : c.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        {
          backgroundColor: bg,
          borderColor: variant === 'ghost' ? c.border : bg,
          opacity: disabled ? 0.45 : pressed ? 0.75 : 1,
        },
      ]}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <View style={styles.row}>
          {icon && <Icon name={icon} color={fg} size={small ? 15 : 18} />}
          <Text style={{ color: fg, fontWeight: '600', fontSize: small ? 13 : 15 }}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

export function Badge({ status, label, tone }: { status?: string; label?: string; tone?: string }) {
  const c = useTheme();
  const color = tone ?? c[STATUS_TONE[status ?? ''] ?? 'muted'];
  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Text style={{ color, fontSize: 12, fontWeight: '600' }}>{label ?? statusLabel(status ?? '')}</Text>
    </View>
  );
}

export function Input(props: TextInputProps) {
  const c = useTheme();
  return (
    <TextInput
      placeholderTextColor={c.muted}
      {...props}
      style={[
        styles.input,
        { backgroundColor: c.bg, borderColor: c.border, color: c.text },
        props.style,
      ]}
    />
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  const c = useTheme();
  return children ? <T color={c.bad} small style={{ marginTop: 8 }}>{children}</T> : null;
}

export const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  button: {
    minHeight: 46,
    paddingHorizontal: 18,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonSmall: { minHeight: 34, paddingHorizontal: 12, borderRadius: 10 },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, alignSelf: 'flex-start' },
  input: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16 },
  screen: { padding: 16, paddingBottom: 48 },
});
