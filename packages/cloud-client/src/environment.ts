import { z } from "zod";

const cloudUrlSchema = z
  .url()
  .transform((value) => new URL(value))
  .refine((url) => !url.username && !url.password, "Cloud URL cannot contain credentials")
  .refine(
    (url) => url.protocol === "https:" || (url.protocol === "http:" && ["localhost", "127.0.0.1", "::1"].includes(url.hostname)),
    "Cloud URL must use HTTPS outside local development",
  )
  .refine((url) => url.pathname === "/" && !url.search && !url.hash, "Cloud URL must be an origin")
  .transform((url) => url.origin);

export function parsePublicCloudUrl(value: unknown): string {
  return cloudUrlSchema.parse(value);
}
