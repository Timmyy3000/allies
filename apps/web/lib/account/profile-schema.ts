import { z } from "zod";

const unicodeCategoryC = /\p{C}/u;

const displayNameSchema = z
  .string()
  .refine((value) => !unicodeCategoryC.test(value), "Display name contains unsupported characters")
  .transform((value) => value.trim().replace(/\s+/gu, " "))
  .refine((value) => Array.from(value).length >= 1, "Display name is required")
  .refine((value) => Array.from(value).length <= 80, "Display name must be 80 characters or fewer");

export const profileFormSchema = z.object({ displayName: displayNameSchema });

export type ProfileFormValues = z.infer<typeof profileFormSchema>;
