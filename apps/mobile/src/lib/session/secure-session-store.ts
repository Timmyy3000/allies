import * as SecureStore from 'expo-secure-store';

export const NATIVE_REFRESH_TOKEN_KEY = 'allies.native.refresh-token';

export interface NativeSessionStore {
  readRefresh(): Promise<string | null>;
  writeRefresh(token: string): Promise<void>;
  clear(): Promise<void>;
}

export function createSecureSessionStore(): NativeSessionStore {
  return {
    readRefresh: () => SecureStore.getItemAsync(NATIVE_REFRESH_TOKEN_KEY),
    writeRefresh: (token) => SecureStore.setItemAsync(NATIVE_REFRESH_TOKEN_KEY, token),
    clear: () => SecureStore.deleteItemAsync(NATIVE_REFRESH_TOKEN_KEY),
  };
}
