import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { useNativeSession } from '@/lib/session/session-context';

import { accountKeys } from './account-queries';
import { MAX_AVATAR_BYTES, uploadAvatar } from './avatar-upload';

type AvatarUploadState = 'idle' | 'picking' | 'uploading' | 'success' | 'error';

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function useAvatarUpload() {
  const session = useNativeSession();
  const queryClient = useQueryClient();
  const [state, setState] = useState<AvatarUploadState>('idle');
  const [message, setMessage] = useState<string | null>(null);

  const pickAndUpload = useCallback(async () => {
    if (!session.accountClient || !session.adapter) {
      setState('error');
      setMessage('Avatar updates are unavailable in this build.');
      return false;
    }

    setState('picking');
    setMessage(null);
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        setState('error');
        setMessage('Photo access is needed to choose an avatar.');
        return false;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        allowsEditing: false,
        mediaTypes: ['images'],
        quality: 1,
      });
      if (result.canceled || !result.assets[0]) {
        setState('idle');
        return false;
      }

      const asset = result.assets[0];
      const file = new File(asset.uri);
      const fileSize = asset.fileSize ?? file.size;
      if (fileSize != null && fileSize > MAX_AVATAR_BYTES) {
        setState('error');
        setMessage('That image is too large. Choose one under 10 MiB.');
        return false;
      }
      setState('uploading');

      const avatar = await uploadAvatar({
        client: {
          completeAvatar: (assetId, signal) =>
            session.adapter!.withRefresh(() => session.accountClient!.completeAvatar(assetId, signal)),
          prepareAvatarUpload: (input, signal) =>
            session.adapter!.withRefresh(() => session.accountClient!.prepareAvatarUpload(input, signal)),
        },
        contentType: asset.mimeType ?? 'image/jpeg',
        size: fileSize,
        hash: async (bytes) => {
          const digestInput = new Uint8Array(bytes.byteLength);
          digestInput.set(bytes);
          const digest = await Crypto.digest(
            Crypto.CryptoDigestAlgorithm.SHA256,
            digestInput.buffer as ArrayBuffer,
          );
          return bytesToHex(new Uint8Array(digest));
        },
        readBytes: () => file.bytes(),
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: accountKeys.current }),
        queryClient.invalidateQueries({ queryKey: accountKeys.avatar }),
      ]);
      setState('success');
      setMessage('Avatar updated.');
      return Boolean(avatar);
    } catch {
      setState('error');
      setMessage('We could not choose or update your avatar. Try again.');
      return false;
    }
  }, [queryClient, session.accountClient, session.adapter]);

  return {
    isBusy: state === 'picking' || state === 'uploading',
    message,
    pickAndUpload,
    state,
  };
}
