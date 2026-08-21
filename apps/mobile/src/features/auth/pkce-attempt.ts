import * as Crypto from 'expo-crypto';

import { bytesToBase64Url, toBase64Url } from './pkce';

export interface PkceAttempt {
  codeVerifier: string;
  codeChallenge: string;
  state: string;
}

export async function createPkceAttempt(): Promise<PkceAttempt> {
  const verifier = bytesToBase64Url(await Crypto.getRandomBytesAsync(32));
  const state = bytesToBase64Url(await Crypto.getRandomBytesAsync(32));
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 },
  );

  return {
    codeVerifier: verifier,
    codeChallenge: toBase64Url(digest),
    state,
  };
}
