import type { ConfigContext, ExpoConfig } from 'expo/config';

export interface NativeLinkConfig {
  android: {
    intentFilters: Array<{
      action: 'VIEW';
      autoVerify: true;
      category: ['BROWSABLE', 'DEFAULT'];
      data: {
        scheme: 'https';
        host: string;
        port?: string;
        pathPrefix: string;
      };
    }>;
  };
  ios: {
    associatedDomains: string[];
  };
}

export function getNativeLinkConfig(value: unknown): Partial<NativeLinkConfig> {
  if (value === undefined || value === null || value === '') return {};
  if (typeof value !== 'string') throw new Error('Native auth redirect URI must be a string');

  const url = new URL(value);
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    value.includes('*')
  ) {
    throw new Error('Native auth redirect URI must be an exact HTTPS URL without query or fragment');
  }

  const data = {
    scheme: 'https' as const,
    host: url.hostname,
    ...(url.port ? { port: url.port } : {}),
    pathPrefix: url.pathname,
  };

  return {
    android: {
      intentFilters: [
        {
          action: 'VIEW',
          autoVerify: true,
          category: ['BROWSABLE', 'DEFAULT'],
          data,
        },
      ],
    },
    ios: {
      associatedDomains: [`applinks:${url.hostname}${url.port ? `:${url.port}` : ''}`],
    },
  };
}

export default ({ config }: ConfigContext): ExpoConfig => {
  const nativeLinks = getNativeLinkConfig(process.env.EXPO_PUBLIC_NATIVE_AUTH_REDIRECT_URI);

  return {
    ...config,
    name: config.name ?? 'allies',
    slug: config.slug ?? 'mobile',
    ...(nativeLinks.android ? { android: { ...config.android, ...nativeLinks.android } } : {}),
    ...(nativeLinks.ios ? { ios: { ...config.ios, ...nativeLinks.ios } } : {}),
  };
};
