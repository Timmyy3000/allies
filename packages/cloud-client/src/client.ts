import createOpenApiClient from "openapi-fetch";
import { z } from "zod";

import type { paths } from "./generated/openapi";
import { isCloudError, normalizeCloudError, type CloudError } from "./errors";
import { parsePublicCloudUrl } from "./environment";
import { toAccountViewModel, type AccountViewModel } from "./mappers/account";
import { csrfTokenSchema, externalHttpsUrlSchema, type CloudCsrfToken } from "./schemas";
import { createControlledFetch } from "./transport";

const CloudRequest = globalThis.Request;

const successEnvelope = <T extends z.ZodType>(data: T) =>
  z.object({ status: z.literal("success"), message: z.string(), data }).loose();
const profileSchema = z
  .object({ display_name: z.string(), avatar_url: externalHttpsUrlSchema.nullable().optional() })
  .loose();
const avatarSchema = z
  .object({
    asset_id: z.string().min(1),
    url: externalHttpsUrlSchema.nullable().optional(),
    expires_at: z.iso.datetime({ offset: true }).nullable().optional(),
  })
  .loose();
const preparedAvatarSchema = z
  .object({
    asset_id: z.string().min(1),
    upload_url: externalHttpsUrlSchema,
    headers: z.record(z.string(), z.string()),
    expires_at: z.iso.datetime({ offset: true }),
  })
  .loose();
const workspaceSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    role: z.string().min(1),
    capabilities: z.array(z.string()),
  })
  .loose();
const maskedEmailSchema = z
  .string()
  .regex(/^[^@\s]+@[^@\s]+$/)
  .refine((value) => value.slice(0, value.indexOf("@")).includes("*"));
const waitlistEntrySchema = z.object({
  attempt_token: z.string().min(32),
  greeting: z.string().min(1),
});
const waitlistCompletionSchema = z.object({ email: maskedEmailSchema });

function normalizeRequestSignal(signal?: AbortSignal): AbortSignal | undefined {
  if (!signal) return undefined;
  try {
    new CloudRequest("https://cloud.example.com", { signal });
    return signal;
  } catch {
    return undefined;
  }
}

export interface ProfileViewModel {
  displayName: string;
  avatarUrl: string | null;
}

export interface AvatarViewModel {
  assetId: string;
  url: string | null;
  expiresAt: string | null;
}

export interface PreparedAvatarViewModel {
  assetId: string;
  uploadUrl: string;
  headers: Record<string, string>;
  expiresAt: string;
}

export interface WorkspaceViewModel {
  id: string;
  name: string;
  role: string;
  capabilities: string[];
}

export interface WaitlistEntryInput {
  attemptId: string;
  name: string;
  appearanceCatalogVersion: string;
  appearanceKey: string;
  job: string;
  personality: string;
}

export interface WaitlistEntryViewModel {
  attemptToken: string;
  greeting: string;
}

export interface WaitlistCompletionInput {
  attemptToken: string;
  reply: string;
  email: string;
  consentVersion: string;
}

export interface WaitlistCompletionViewModel {
  email: string;
}

export interface CloudClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  prepareRequest?: (request: Request) => Request | Promise<Request>;
  timeoutMs?: number;
  maxJsonBytes?: number;
}

interface ApiResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

async function unwrap<T>(operation: Promise<ApiResult>, map: (data: unknown) => T): Promise<T> {
  try {
    const result = await operation;
    if (!result.response.ok) throw normalizeCloudError(result.response.status, result.error);
    try {
      return map(result.data);
    } catch (error) {
      if (isCloudError(error)) throw error;
      throw { kind: "contract" } satisfies CloudError;
    }
  } catch (error) {
    if (isCloudError(error)) throw error;
    throw { kind: "contract" } satisfies CloudError;
  }
}

async function noContent(operation: Promise<ApiResult>): Promise<void> {
  await unwrap(operation, () => undefined);
}

function rejectPreAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw { kind: "aborted" } satisfies CloudError;
}

function hasControlCharacter(value: string): boolean {
  return /[\u0000-\u001f\u007f]/u.test(value);
}

function isSafeDecodedReturnPath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") && !hasControlCharacter(value);
}

export function parseSafeReturnPath(value: unknown): string | null {
  if (typeof value !== "string" || value.length < 1 || value.length > 500) return null;

  let decoded = value;
  for (let pass = 0; pass < 8; pass += 1) {
    if (!isSafeDecodedReturnPath(decoded)) return null;
    if (!decoded.includes("%")) return value;

    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) return value;
      decoded = next;
    } catch {
      return null;
    }
  }

  return null;
}

function parseReturnPath(value: string): string {
  const parsed = parseSafeReturnPath(value);
  if (parsed === null) throw { kind: "bad-request" } satisfies CloudError;
  return parsed;
}

export function createCloudClient(options: CloudClientOptions) {
  const baseUrl = parsePublicCloudUrl(options.baseUrl);
  const controlledFetch = createControlledFetch({
    fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    prepareRequest: options.prepareRequest,
    timeoutMs: options.timeoutMs,
    maxJsonBytes: options.maxJsonBytes,
  });
  const api = createOpenApiClient<paths>({ baseUrl, fetch: controlledFetch, Request: CloudRequest });

  return {
    async getCsrf(signal?: AbortSignal): Promise<CloudCsrfToken> {
      rejectPreAborted(signal);
      try {
        const result = await (api.GET("/api/v1/auths/csrf", {
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>);
        if (!result.response.ok) throw normalizeCloudError(result.response.status, result.error);
        if (result.response.status !== 204) throw { kind: "contract" } satisfies CloudError;
        const token = csrfTokenSchema.safeParse(result.response.headers.get("X-CSRFToken"));
        if (!token.success) throw { kind: "contract" } satisfies CloudError;
        return token.data;
      } catch (error) {
        if (isCloudError(error)) throw error;
        throw { kind: "contract" } satisfies CloudError;
      }
    },

    async beginSignIn(redirectTo: string, signal?: AbortSignal) {
      rejectPreAborted(signal);
      const safeRedirectTo = parseReturnPath(redirectTo);
      return unwrap(
        api.POST("/api/v1/auths/sign-in/{provider}", {
          params: { path: { provider: "google" } },
          body: { redirect_to: safeRedirectTo },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) =>
          successEnvelope(z.object({ redirect_url: externalHttpsUrlSchema }).loose()).parse(data).data.redirect_url,
      );
    },

    async refreshSession(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.POST("/api/v1/auths/refresh", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async logout(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.POST("/api/v1/auths/logout", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async getCurrentAccount(signal?: AbortSignal): Promise<AccountViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/auths/me", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>,
        (data) => toAccountViewModel(successEnvelope(z.unknown()).parse(data).data),
      );
    },

    async updateProfile(displayName: string, signal?: AbortSignal): Promise<ProfileViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.PATCH("/api/v1/auths/me/profile", {
          body: { display_name: displayName },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const profile = successEnvelope(profileSchema).parse(data).data;
          return { displayName: profile.display_name, avatarUrl: profile.avatar_url ?? null };
        },
      );
    },

    async prepareAvatarUpload(
      input: { contentType: string; size: number; sha256: string },
      signal?: AbortSignal,
    ): Promise<PreparedAvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/auths/me/avatar/uploads", {
          body: { content_type: input.contentType, size: input.size, sha256: input.sha256 },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const avatar = successEnvelope(preparedAvatarSchema).parse(data).data;
          return {
            assetId: avatar.asset_id,
            uploadUrl: avatar.upload_url,
            headers: avatar.headers,
            expiresAt: avatar.expires_at,
          };
        },
      );
    },

    async completeAvatar(assetId: string, signal?: AbortSignal): Promise<AvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/auths/me/avatar/{asset_id}/complete", {
          params: { path: { asset_id: assetId } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        mapAvatar,
      );
    },

    async getAvatarRead(signal?: AbortSignal): Promise<AvatarViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/auths/me/avatar/read", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>,
        mapAvatar,
      );
    },

    async deleteAvatar(signal?: AbortSignal) {
      rejectPreAborted(signal);
      await noContent(api.DELETE("/api/v1/auths/me/avatar", { signal: normalizeRequestSignal(signal) }) as Promise<ApiResult>);
    },

    async getWorkspace(workspaceId: string, signal?: AbortSignal): Promise<WorkspaceViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}", {
          params: { path: { workspace_id: workspaceId } },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => successEnvelope(workspaceSchema).parse(data).data,
      );
    },

    async createWaitlistEntry(
      input: WaitlistEntryInput,
      signal?: AbortSignal,
    ): Promise<WaitlistEntryViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/entries", {
          body: {
            attempt_id: input.attemptId,
            name: input.name,
            appearance_catalog_version: input.appearanceCatalogVersion,
            appearance_key: input.appearanceKey,
            job: input.job,
            personality: input.personality,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => {
          const entry = successEnvelope(waitlistEntrySchema).parse(data).data;
          return { attemptToken: entry.attempt_token, greeting: entry.greeting };
        },
      );
    },

    async completeWaitlistEntry(
      input: WaitlistCompletionInput,
      signal?: AbortSignal,
    ): Promise<WaitlistCompletionViewModel> {
      rejectPreAborted(signal);
      return unwrap(
        api.POST("/api/v1/waitlist/entries/complete", {
          body: {
            attempt_token: input.attemptToken,
            reply: input.reply,
            email: input.email,
            consent_version: input.consentVersion,
          },
          signal: normalizeRequestSignal(signal),
        }) as Promise<ApiResult>,
        (data) => successEnvelope(waitlistCompletionSchema).parse(data).data,
      );
    },
  };
}

function mapAvatar(data: unknown): AvatarViewModel {
  const avatar = successEnvelope(avatarSchema).parse(data).data;
  return {
    assetId: avatar.asset_id,
    url: avatar.url ?? null,
    expiresAt: avatar.expires_at ?? null,
  };
}

export type CloudClient = ReturnType<typeof createCloudClient>;
