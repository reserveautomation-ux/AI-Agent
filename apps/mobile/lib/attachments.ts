import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

import { API_URL, post } from './api';
import { supabase } from './supabase';

export interface ChatFile {
  id: string;
  name: string;
  media_type: string;
  size_bytes?: number;
  /** Local preview while composing. */
  preview?: string;
}

const MAX_IMAGE = 5 * 1024 * 1024;
const MAX_PDF = 10 * 1024 * 1024;
const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

async function upload(name: string, mediaType: string, base64: string, preview?: string): Promise<ChatFile> {
  const bytes = Math.floor((base64.length * 3) / 4);
  const isPdf = mediaType === 'application/pdf';
  if (bytes > (isPdf ? MAX_PDF : MAX_IMAGE)) throw new Error(`${name} is too big (max ${isPdf ? 10 : 5} MB)`);
  const out = await post<ChatFile>('/chat/files', { name, media_type: mediaType, data: base64 });
  return { ...out, preview };
}

function imageAssets(result: ImagePicker.ImagePickerResult): Promise<ChatFile>[] {
  if (result.canceled) return [];
  return result.assets.map((a, i) => {
    const type = a.mimeType && IMAGE_TYPES.includes(a.mimeType) ? a.mimeType : 'image/jpeg';
    const name = a.fileName || `photo-${Date.now()}-${i + 1}.${type === 'image/png' ? 'png' : 'jpg'}`;
    if (!a.base64) return Promise.reject(new Error('Could not read the photo'));
    return upload(name, type, a.base64, a.uri);
  });
}

/** Take a photo with the camera (a bill, a form, a whiteboard). */
export async function takePhoto(): Promise<Promise<ChatFile>[]> {
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) throw new Error('Camera permission was denied. Allow it in Settings.');
  // quality < 1 also makes the phone send a JPEG of a sensible size.
  return imageAssets(await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7, base64: true }));
}

/** Pick up to `limit` photos from the gallery. */
export async function pickPhotos(limit: number): Promise<Promise<ChatFile>[]> {
  return imageAssets(
    await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsMultipleSelection: limit > 1,
      selectionLimit: limit,
      quality: 0.7,
      base64: true,
    }),
  );
}

/** Pick PDF documents. */
export async function pickPdfs(limit: number): Promise<Promise<ChatFile>[]> {
  const result = await DocumentPicker.getDocumentAsync({
    type: 'application/pdf',
    multiple: limit > 1,
    copyToCacheDirectory: true,
  });
  if (result.canceled) return [];
  return result.assets.slice(0, limit).map(async (a) => {
    if ((a.size ?? 0) > MAX_PDF) throw new Error(`${a.name} is too big (max 10 MB)`);
    let base64: string;
    if (Platform.OS === 'web' && a.file) {
      base64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(',', 2)[1] ?? '');
        r.onerror = () => reject(new Error('Could not read the PDF'));
        r.readAsDataURL(a.file!);
      });
    } else {
      base64 = await new File(a.uri).base64();
    }
    return upload(a.name || 'document.pdf', 'application/pdf', base64);
  });
}

/** Image source for an attached photo (needs the sign-in token). */
export async function photoSource(id: string): Promise<{ uri: string; headers?: Record<string, string> }> {
  const { data } = await supabase.auth.getSession();
  const headers = { Authorization: `Bearer ${data.session?.access_token ?? ''}` };
  const uri = `${API_URL}/chat/files/${id}`;
  if (Platform.OS !== 'web') return { uri, headers };
  const res = await fetch(uri, { headers });
  return { uri: URL.createObjectURL(await res.blob()) };
}
