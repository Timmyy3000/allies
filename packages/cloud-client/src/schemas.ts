import { z } from "zod";

export const externalHttpsUrlSchema = z.url().refine((value) => {
  const url = new URL(value);
  return url.protocol === "https:" && !url.username && !url.password;
});

export type CloudCsrfToken = string;

export const csrfTokenSchema: z.ZodType<CloudCsrfToken> = z
  .string()
  .regex(/^(?:[A-Za-z0-9]{32}|[A-Za-z0-9]{64})$/);
