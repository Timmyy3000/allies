import { z } from "zod";

export type CloudErrorKind =
  | "bad-request"
  | "unauthorized"
  | "security"
  | "forbidden"
  | "not-found"
  | "conflict"
  | "too-large"
  | "unsupported-media"
  | "validation"
  | "throttled"
  | "server"
  | "network"
  | "timeout"
  | "aborted"
  | "contract"
  | "client";

export interface FieldIssue {
  field?: string;
  message?: string;
}

export interface CloudError {
  kind: CloudErrorKind;
  status?: number;
  code?: string;
  fieldIssues?: FieldIssue[];
}

const errorEnvelopeSchema = z
  .object({
    status: z.literal("error"),
    data: z
      .object({
        code: z.string().optional(),
        details: z
          .object({
            errors: z
              .array(
                z.object({
                  field: z.string().optional(),
                  message: z.string().optional(),
                }),
              )
              .optional(),
          })
          .optional()
          .nullable(),
      })
      .optional()
      .nullable(),
  })
  .loose();

function kindForStatus(status: number, code?: string): CloudErrorKind {
  if (status === 400) return "bad-request";
  if (status === 401) return "unauthorized";
  if (status === 403 && code && /csrf|origin/i.test(code)) return "security";
  if (status === 403) return "forbidden";
  if (status === 404) return "not-found";
  if (status === 409) return "conflict";
  if (status === 413) return "too-large";
  if (status === 415) return "unsupported-media";
  if (status === 422) return "validation";
  if (status === 429) return "throttled";
  if (status >= 500) return "server";
  return "client";
}

export function normalizeCloudError(status: number, body: unknown): CloudError {
  const parsed = errorEnvelopeSchema.safeParse(body);
  const code = parsed.success ? parsed.data.data?.code : undefined;
  const fieldIssues = parsed.success ? parsed.data.data?.details?.errors : undefined;

  return {
    kind: kindForStatus(status, code),
    status,
    ...(code ? { code } : {}),
    ...(fieldIssues?.length ? { fieldIssues } : {}),
  };
}

export function isCloudError(value: unknown): value is CloudError {
  return typeof value === "object" && value !== null && "kind" in value;
}
