import { describe, expect, it } from 'vitest';

import { getNativeLinkConfig } from '../../app.config';

describe('getNativeLinkConfig', () => {
  it('does not add claimed-link configuration before a redirect is registered', () => {
    expect(getNativeLinkConfig(undefined)).toEqual({});
  });

  it('derives matching Android and iOS link configuration from the exact return URL', () => {
    expect(getNativeLinkConfig('https://auth.example.com:8443/mobile/auth/return')).toEqual({
      android: {
        intentFilters: [
          {
            action: 'VIEW',
            autoVerify: true,
            category: ['BROWSABLE', 'DEFAULT'],
            data: {
              scheme: 'https',
              host: 'auth.example.com',
              port: '8443',
              pathPrefix: '/mobile/auth/return',
            },
          },
        ],
      },
      ios: {
        associatedDomains: ['applinks:auth.example.com:8443'],
      },
    });
  });

  it.each([
    'http://auth.example.com/auth/return',
    'https://auth.example.com/auth/return?state=bad',
    'https://auth.example.com/auth/return#fragment',
    'https://user:password@auth.example.com/auth/return',
    'https://*.example.com/auth/return',
  ])('rejects an unsafe return URL: %s', (value) => {
    expect(() => getNativeLinkConfig(value)).toThrow();
  });
});
