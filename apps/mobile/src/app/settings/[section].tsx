import { useLocalSearchParams } from 'expo-router';

import { getPreviewScreen } from '@/features/app-preview/screen-map';
import { PreviewDetailPage } from '@/features/app-preview/preview-ui';

export default function SettingsDetailScreen() {
  const params = useLocalSearchParams<{ section?: string | string[] }>();
  const section = Array.isArray(params.section) ? params.section[0] : params.section;

  return <PreviewDetailPage backHref="/settings" screen={getPreviewScreen('settings', section ?? '')} />;
}
