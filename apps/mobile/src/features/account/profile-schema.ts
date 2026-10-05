import { z } from 'zod';

export const MAX_DISPLAY_NAME_LENGTH = 80;

export const profileFormSchema = z.object({
  displayName: z
    .string()
    .trim()
    .min(1, 'Enter a name')
    .max(MAX_DISPLAY_NAME_LENGTH, 'Name is too long'),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;
