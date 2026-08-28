import { useLocalSearchParams } from 'expo-router';

import { getPreviewScreen } from '@/features/app-preview/screen-map';
import { PreviewDetailPage } from '@/features/app-preview/preview-ui';

export default function ConnectionDetailScreen() {
  const params = useLocalSearchParams<{ service?: string | string[] }>();
  const service = Array.isArray(params.service) ? params.service[0] : params.service;

  return <PreviewDetailPage backHref="/settings/connections" screen={getPreviewScreen('connection', service ?? '')} />;
}
