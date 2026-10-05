import { describe, expect, it } from 'vitest';

import { MAX_DISPLAY_NAME_LENGTH, profileFormSchema } from './profile-schema';

describe('profileFormSchema', () => {
  it('normalizes a valid display name without changing its contract', () => {
    expect(profileFormSchema.parse({ displayName: '  Timi  ' })).toEqual({ displayName: 'Timi' });
  });

  it('rejects blank and overlong names at the mutation boundary', () => {
    expect(() => profileFormSchema.parse({ displayName: '   ' })).toThrow();
    expect(() => profileFormSchema.parse({ displayName: 'a'.repeat(MAX_DISPLAY_NAME_LENGTH + 1) })).toThrow();
  });
});
