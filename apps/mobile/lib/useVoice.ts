import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import { useCallback, useEffect, useRef, useState } from 'react';

export const VOICE_LANGUAGES: { code: string; label: string }[] = [
  { code: 'en-IN', label: 'English (India)' },
  { code: 'hi-IN', label: 'हिन्दी' },
  { code: 'mr-IN', label: 'मराठी' },
  { code: 'gu-IN', label: 'ગુજરાતી' },
  { code: 'bn-IN', label: 'বাংলা' },
  { code: 'ta-IN', label: 'தமிழ்' },
  { code: 'te-IN', label: 'తెలుగు' },
  { code: 'kn-IN', label: 'ಕನ್ನಡ' },
  { code: 'ml-IN', label: 'മലയാളം' },
  { code: 'pa-IN', label: 'ਪੰਜਾਬੀ' },
  { code: 'en-US', label: 'English (US)' },
  { code: 'en-GB', label: 'English (UK)' },
];

const ERRORS: Record<string, string> = {
  'not-allowed': 'Microphone or speech permission was denied. Allow it in Settings.',
  'no-speech': "Didn't catch that. Tap the mic and try again.",
  'speech-timeout': "Didn't catch that. Tap the mic and try again.",
  'audio-capture': 'No microphone found.',
  network: 'Voice recognition needs an internet connection.',
  'language-not-supported': 'This language is not available on your phone yet.',
  'service-not-allowed': 'Speech recognition is not available on this device.',
};

/** Native speech-to-text (Android SpeechRecognizer / iOS Speech) in the chosen language. */
export function useVoice(opts: {
  lang: string;
  onText: (text: string) => void;
  /** Called when listening ends with something heard. */
  onDone?: (text: string) => void;
  /** Called whenever listening ends, even if nothing was heard (voice conversation). */
  onEnd?: (text: string) => void;
}) {
  const [listening, setListening] = useState(false);
  const [available, setAvailable] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const text = useRef('');
  const cb = useRef(opts);
  cb.current = opts;

  useEffect(() => {
    try {
      setAvailable(ExpoSpeechRecognitionModule.isRecognitionAvailable());
    } catch {
      setAvailable(false);
    }
  }, []);

  useSpeechRecognitionEvent('result', (event) => {
    const transcript = event.results[0]?.transcript ?? '';
    text.current = transcript.trim();
    cb.current.onText(text.current);
  });
  useSpeechRecognitionEvent('error', (event) => {
    if (event.error !== 'aborted') setError(ERRORS[event.error] ?? event.message ?? 'Voice error');
  });
  useSpeechRecognitionEvent('end', () => {
    // "end" is always the last event, including after errors.
    setListening(false);
    if (text.current) cb.current.onDone?.(text.current);
    cb.current.onEnd?.(text.current);
  });

  const start = useCallback(async () => {
    setError(null);
    const perm = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
    if (!perm.granted) {
      setError(ERRORS['not-allowed']);
      return;
    }
    text.current = '';
    ExpoSpeechRecognitionModule.start({
      lang: cb.current.lang,
      interimResults: true, // show words as they are spoken
      continuous: false, // one instruction per tap; ends when you stop talking
      addsPunctuation: true,
    });
    setListening(true);
  }, []);

  const stop = useCallback(() => ExpoSpeechRecognitionModule.stop(), []);

  return { listening, available, error, start, stop };
}
