import { describe, expect, it } from 'vitest';

import { getAllyAppearance } from './ally-appearance';

describe('getAllyAppearance', () => {
  it('maps the accepted catalog key and falls back for future values', () => {
    expect(getAllyAppearance('rocky:fd304f')).toEqual({ shape: 'rocky', color: '#FD304F' });
    expect(getAllyAppearance('future:123456')).toEqual({ shape: 'ghosty', color: '#FF5800' });
  });
});
