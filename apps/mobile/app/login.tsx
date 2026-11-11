import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Card, ErrorText, Input, T } from '@/components/ui';
import { supabase } from '@/lib/supabase';
import { useTheme } from '@/lib/theme';

/** Sign in with a 6-digit code sent by email (no passwords, no links to tap). */
export default function Login() {
  const c = useTheme();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendCode = async () => {
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: true },
    });
    setBusy(false);
    if (error) setError(error.message);
    else setSent(true);
  };

  const verify = async () => {
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.verifyOtp({
      email: email.trim(),
      token: code.trim(),
      type: 'email',
    });
    setBusy(false);
    if (error) setError(error.message);
    // On success the auth listener moves us to the home screen.
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1, justifyContent: 'center', padding: 20 }}>
        <View style={{ alignItems: 'center', marginBottom: 24 }}>
          <View
            style={{
              width: 64,
              height: 64,
              borderRadius: 16,
              backgroundColor: '#14213d',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
            <T size={30} color="#fca311">⚡</T>
          </View>
          <T bold size={24} style={{ marginTop: 12 }}>Workforce OS</T>
          <T muted>Your AI workforce, in your pocket.</T>
        </View>
        <Card>
          {!sent ? (
            <>
              <T bold>Sign up or sign in</T>
              <T muted small style={{ marginBottom: 12 }}>We&apos;ll email you a 6-digit code. New here? Your account is created automatically.</T>
              <Input
                value={email}
                onChangeText={setEmail}
                placeholder="you@example.com"
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                textContentType="emailAddress"
                accessibilityLabel="Email"
              />
              <View style={{ height: 12 }} />
              <Button title="Send code" onPress={sendCode} loading={busy} disabled={!email.includes('@')} />
            </>
          ) : (
            <>
              <T bold>Enter the code</T>
              <T muted small style={{ marginBottom: 12 }}>Sent to {email}</T>
              <Input
                value={code}
                onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 8))}
                placeholder="123456"
                keyboardType="number-pad"
                autoComplete="one-time-code"
                textContentType="oneTimeCode"
                accessibilityLabel="Sign-in code"
                style={{ fontSize: 22, letterSpacing: 6, textAlign: 'center' }}
              />
              <View style={{ height: 12 }} />
              <Button title="Continue" onPress={verify} loading={busy} disabled={code.length < 6} />
              <View style={{ height: 8 }} />
              <Button title="Use a different email" variant="ghost" onPress={() => setSent(false)} />
            </>
          )}
          <ErrorText>{error}</ErrorText>
        </Card>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
