import { z } from "zod";

import { isCloudError, normalizeCloudError, type CloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { externalHttpsUrlSchema } from "./schemas";
import { createControlledFetch } from "./transport";

const CloudRequest = globalThis.Request;

const successEnvelope = <T extends z.ZodType>(data: T) =>
  z.object({ status: z.literal("success"), message: z.string(), data }).loose();

const nativeStartSchema = successEnvelope(
  z.object({
    authorization_url: externalHttpsUrlSchema,
    expires_at: z.iso.datetime({ offset: true }),
  }).loose(),
);

const nativeTokensSchema = successEnvelope(
  z.object({
    token_type: z.literal("Bearer"),
    access_token: z.string().min(1),
    expires_in: z.number().int().positive(),
    refresh_token: z.string().min(1),
    refresh_expires_in: z.number().int().positive(),
    session_id: z.string().min(1),
  }).loose(),
);

type NativeStartData = z.infer<typeof nativeStartSchema>["data"];
type NativeTokenData = z.infer<typeof nativeTokensSchema>["data"];

const nativeRedirectSchema = z
  .string()
  .url()
  .refine((value) => {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash &&
      !value.includes("*")
    );
  });

const codeChallengeSchema = z.string().regex(/^[A-Za-z0-9_-]{43}$/);
const stateSchema = z.string().min(1).max(512);

export interface NativeAuthClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
  maxJsonBytes?: number;
}

export interface NativeGoogleSignInInput {
  redirectUri: string;
  codeChallenge: string;
  state: string;
}

export interface NativeGoogleCodeExchangeInput {
  code: string;
  codeVerifier: string;
  redirectUri: string;
}

export interface NativeAuthorizationStart {
  authorizationUrl: string;
  expiresAt: string;
}

export interface NativeSessionTokens {
  tokenType: "Bearer";
  accessToken: string;
  expiresIn: number;
  refreshToken: string;
  refreshExpiresIn: number;
  sessionId: string;
}

function rejectPreAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw { kind: "aborted" } satisfies CloudError;
}

function contractError(): CloudError {
  return { kind: "contract" };
}

function parseJson(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    throw contractError();
  }
}

function parseSuccess<T>(data: unknown, schema: z.ZodTypeAny): T {
  try {
    const parsed = schema.parse(data) as { data: T };
    return parsed.data;
  } catch {
    throw contractError();
  }
}

function parseRedirect(value: string): string {
  const parsed = nativeRedirectSchema.safeParse(value);
  if (!parsed.success) throw { kind: "bad-request" } satisfies CloudError;
  return parsed.data;
}

function parseChallenge(value: string): string {
  const parsed = codeChallengeSchema.safeParse(value);
  if (!parsed.success) throw { kind: "bad-request" } satisfies CloudError;
  return parsed.data;
}

function parseState(value: string): string {
  const parsed = stateSchema.safeParse(value);
  if (!parsed.success) throw { kind: "bad-request" } satisfies CloudError;
  return parsed.data;
}

async function readResponse(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return undefined;
  return parseJson(await response.text());
}

export function createNativeAuthClient(options: NativeAuthClientOptions): NativeAuthClient {
  const baseUrl = parsePublicCloudUrl(options.baseUrl);
  const controlledFetch = createControlledFetch({
    fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    timeoutMs: options.timeoutMs,
    maxJsonBytes: options.maxJsonBytes,
  });

  async function post<T>(
    path: string,
    body: unknown,
    schema: z.ZodTypeAny | null,
    accessToken?: string,
    signal?: AbortSignal,
  ): Promise<T> {
    rejectPreAborted(signal);
    const headers = new Headers({
      accept: "application/json",
      "content-type": "application/json",
    });
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
    const request = new CloudRequest(`${baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "omit",
      signal,
    });
    const response = await controlledFetch(request);
    let data: unknown;
    try {
      data = await readResponse(response);
    } catch (error) {
      if (isCloudError(error)) throw error;
      throw contractError();
    }
    if (!response.ok) throw normalizeCloudError(response.status, data);
    return schema ? parseSuccess(data, schema) : (undefined as T);
  }

  return {
    async beginGoogleSignIn(input, signal): Promise<NativeAuthorizationStart> {
      const redirectUri = parseRedirect(input.redirectUri);
      const codeChallenge = parseChallenge(input.codeChallenge);
      const state = parseState(input.state);
      const data = await post<NativeStartData>(
        "/api/v1/auths/native/sign-in/google",
        {
          redirect_uri: redirectUri,
          code_challenge: codeChallenge,
          code_challenge_method: "S256",
          state,
        },
        nativeStartSchema,
        undefined,
        signal,
      );
      return { authorizationUrl: data.authorization_url, expiresAt: data.expires_at };
    },

    async exchangeGoogleCode(input, signal): Promise<NativeSessionTokens> {
      const redirectUri = parseRedirect(input.redirectUri);
      if (!input.code || !input.codeVerifier) throw { kind: "bad-request" } satisfies CloudError;
      const data = await post<NativeTokenData>(
        "/api/v1/auths/native/token",
        {
          grant_type: "authorization_code",
          code: input.code,
          code_verifier: input.codeVerifier,
          redirect_uri: redirectUri,
        },
        nativeTokensSchema,
        undefined,
        signal,
      );
      return mapTokens(data);
    },

    async refreshSession(refreshToken, signal): Promise<NativeSessionTokens> {
      if (!refreshToken) throw { kind: "bad-request" } satisfies CloudError;
      const data = await post<NativeTokenData>(
        "/api/v1/auths/native/token/refresh",
        { grant_type: "refresh_token", refresh_token: refreshToken },
        nativeTokensSchema,
        undefined,
        signal,
      );
      return mapTokens(data);
    },

    async logout(refreshToken, accessToken, signal): Promise<void> {
      if (!refreshToken) return;
      await post(
        "/api/v1/auths/native/logout",
        { refresh_token: refreshToken },
        null,
        accessToken,
        signal,
      );
    },
  };
}

function mapTokens(data: NativeTokenData): NativeSessionTokens {
  return {
    tokenType: data.token_type,
    accessToken: data.access_token,
    expiresIn: data.expires_in,
    refreshToken: data.refresh_token,
    refreshExpiresIn: data.refresh_expires_in,
    sessionId: data.session_id,
  };
}

export interface NativeAuthClient {
  beginGoogleSignIn(
    input: NativeGoogleSignInInput,
    signal?: AbortSignal,
  ): Promise<NativeAuthorizationStart>;
  exchangeGoogleCode(
    input: NativeGoogleCodeExchangeInput,
    signal?: AbortSignal,
  ): Promise<NativeSessionTokens>;
  refreshSession(refreshToken: string, signal?: AbortSignal): Promise<NativeSessionTokens>;
  logout(refreshToken: string, accessToken?: string, signal?: AbortSignal): Promise<void>;
}
