import { describe, expect, it } from 'vitest';

import { getMockGreeting, getMockReply } from './mock-app';

describe('mock app copy', () => {
  it('personalises a new Ally greeting', () => {
    expect(getMockGreeting('Sally', 'Keep my business moving')).toContain('Sally');
    expect(getMockGreeting('Sally', 'Keep my business moving')).toContain('Keep my business moving');
  });

  it('returns a useful first reply', () => {
    expect(getMockReply('Help me plan tomorrow')).toContain('tomorrow');
  });
});
