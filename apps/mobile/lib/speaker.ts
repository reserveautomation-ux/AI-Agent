import * as Speech from 'expo-speech';

import { speakable } from '@/components/ChatText';

export interface SpeakPrefs {
  /** Voice identifier; empty: the most natural voice this phone has for the language. */
  voice: string;
  rate: number;
  pitch: number;
}

let cachedVoices: Speech.Voice[] | null = null;

export async function phoneVoices(): Promise<Speech.Voice[]> {
  if (cachedVoices?.length) return cachedVoices;
  try {
    cachedVoices = await Speech.getAvailableVoicesAsync();
  } catch {
    cachedVoices = [];
  }
  return cachedVoices;
}

/** Higher is more natural: iOS Enhanced/Premium voices, Android network (neural) voices. */
export function voiceScore(v: Speech.Voice, lang: string): number {
  let s = 0;
  if (v.quality === Speech.VoiceQuality.Enhanced) s += 4;
  if (/premium|enhanced|natural|neural/i.test(v.name + v.identifier)) s += 3;
  if (/network/i.test(v.identifier)) s += 2;
  if (/compact|espeak/i.test(v.name + v.identifier)) s -= 3;
  if (v.language.replace('_', '-') === lang) s += 5;
  return s;
}

export function isNatural(v: Speech.Voice): boolean {
  return v.quality === Speech.VoiceQuality.Enhanced || /premium|natural|neural|network/i.test(v.name + v.identifier);
}

export function voicesFor(voices: Speech.Voice[], lang: string): Speech.Voice[] {
  const base = lang.split('-')[0];
  return voices
    .filter((v) => v.language.replace('_', '-').startsWith(base))
    .sort((a, b) => voiceScore(b, lang) - voiceScore(a, lang) || a.name.localeCompare(b.name));
}

/** Whole sentences ready to speak, plus the unfinished tail of a streaming reply. */
export function takeSentences(buffer: string, final = false): [string[], string] {
  const out: string[] = [];
  let rest = buffer;
  const boundary = /^([\s\S]*?(?:[.!?।…]["')\]]*(?=\s)|\n))\s*/;
  for (let m = boundary.exec(rest); m && m[0]; m = boundary.exec(rest)) {
    if (m[1].trim()) out.push(m[1].trim());
    rest = rest.slice(m[0].length);
  }
  if (!final && rest.length > 240) {
    const cut = Math.max(rest.lastIndexOf(', ', 200), rest.lastIndexOf(' ', 200));
    if (cut > 40) {
      out.push(rest.slice(0, cut + 1).trim());
      rest = rest.slice(cut + 1);
    }
  }
  if (final && rest.trim()) {
    out.push(rest.trim());
    rest = '';
  }
  return [out, rest];
}

/**
 * The assistant's voice on the phone (free, on-device). Speaks one sentence after another,
 * so a reply can be spoken while it is still being written: begin → push… → end.
 */
export class Speaker {
  /** onChange: which message is being spoken (null when quiet). */
  constructor(private onChange: (id: string | null) => void = () => {}) {}

  private run = 0;
  private pending: string[] = [];
  private busy = false;
  private ended = true;
  private buffer = '';
  private inCode = false;
  private lang = 'en-IN';
  private prefs: SpeakPrefs = { voice: '', rate: 1, pitch: 1 };
  private voice: string | undefined;
  private onAll: (() => void) | undefined;

  begin(id: string, lang: string, prefs: SpeakPrefs, onAll?: () => void) {
    this.stop();
    this.run += 1;
    Object.assign(this, { lang, prefs, onAll, ended: false, buffer: '', inCode: false, pending: [] });
    this.voice = prefs.voice || voicesFor(cachedVoices ?? [], lang)[0]?.identifier;
    this.onChange(id);
  }

  push(text: string) {
    if (this.ended) return;
    const [sentences, rest] = takeSentences(this.buffer + text);
    this.buffer = rest;
    this.enqueue(sentences);
  }

  end() {
    if (this.ended) return;
    const [sentences] = takeSentences(this.buffer, true);
    this.buffer = '';
    this.enqueue(sentences);
    this.ended = true;
    this.maybeFinish();
  }

  speak(text: string, id: string, lang: string, prefs: SpeakPrefs, onAll?: () => void) {
    if (!speakable(text)) return onAll?.();
    this.begin(id, lang, prefs, onAll);
    this.push(text);
    this.end();
  }

  stop() {
    this.run += 1;
    this.pending = [];
    this.busy = false;
    this.ended = true;
    this.onAll = undefined;
    void Speech.stop();
    this.onChange(null);
  }

  private enqueue(sentences: string[]) {
    for (const raw of sentences) {
      const fences = (raw.match(/```/g) ?? []).length;
      const skip = this.inCode || fences > 0;
      if (fences % 2) this.inCode = !this.inCode;
      const text = skip ? '' : speakable(raw);
      if (text) this.pending.push(text);
    }
    if (!this.busy) this.next();
  }

  private next() {
    const run = this.run;
    const text = this.pending.shift();
    if (!text) {
      this.busy = false;
      this.maybeFinish();
      return;
    }
    this.busy = true;
    const after = () => {
      if (run === this.run) this.next();
    };
    Speech.speak(text, {
      language: this.lang,
      voice: this.voice,
      rate: this.prefs.rate,
      pitch: this.prefs.pitch,
      onDone: after,
      onError: after,
    });
  }

  private maybeFinish() {
    if (!this.ended || this.busy || this.pending.length) return;
    this.onChange(null);
    const cb = this.onAll;
    this.onAll = undefined;
    cb?.();
  }
}
