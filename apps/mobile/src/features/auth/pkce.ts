export type NativeAuthReturn =
  | { status: 'success'; code: string }
  | { status: 'canceled' }
  | { status: 'error'; reason: 'state-mismatch' | 'invalid-return' | 'flow-failed' };

const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function toBase64Url(value: string): string {
  return value.replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '');
}

export function bytesToBase64Url(bytes: Uint8Array): string {
  let encoded = '';

  for (let index = 0; index < bytes.length; index += 3) {
    const first = bytes[index] ?? 0;
    const second = bytes[index + 1];
    const third = bytes[index + 2];
    const hasSecond = second !== undefined;
    const hasThird = third !== undefined;

    encoded += BASE64_ALPHABET[first >> 2];
    encoded += BASE64_ALPHABET[((first & 0x03) << 4) | ((second ?? 0) >> 4)];
    encoded += hasSecond
      ? BASE64_ALPHABET[((second! & 0x0f) << 2) | ((third ?? 0) >> 6)]
      : '=';
    encoded += hasThird ? BASE64_ALPHABET[third! & 0x3f] : '=';
  }

  return toBase64Url(encoded);
}

function matchesRedirect(url: URL, redirectUri?: string): boolean {
  if (!redirectUri) return true;

  try {
    const expected = new URL(redirectUri);
    return (
      url.origin === expected.origin &&
      url.pathname === expected.pathname &&
      !url.username &&
      !url.password &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function parseNativeAuthReturn(
  rawUrl: string,
  expectedState: string,
  redirectUri?: string,
): NativeAuthReturn {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return { status: 'error', reason: 'invalid-return' };
  }

  if (!matchesRedirect(url, redirectUri)) return { status: 'error', reason: 'invalid-return' };

  const state = url.searchParams.get('state');
  if (!state || state !== expectedState) return { status: 'error', reason: 'state-mismatch' };

  const error = url.searchParams.get('error');
  if (error === 'access_denied') return { status: 'canceled' };
  if (error) return { status: 'error', reason: 'flow-failed' };

  const code = url.searchParams.get('code');
  if (!code) return { status: 'error', reason: 'invalid-return' };
  return { status: 'success', code };
}
