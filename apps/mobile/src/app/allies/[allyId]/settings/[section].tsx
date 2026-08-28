import { useLocalSearchParams } from 'expo-router';

import { getPreviewScreen } from '@/features/app-preview/screen-map';
import { PreviewDetailPage } from '@/features/app-preview/preview-ui';

export default function AllySettingsDetailScreen() {
  const params = useLocalSearchParams<{ allyId?: string | string[]; section?: string | string[] }>();
  const rawAllyId = Array.isArray(params.allyId) ? params.allyId[0] : params.allyId;
  const section = Array.isArray(params.section) ? params.section[0] : params.section;
  const allyId = encodeURIComponent(rawAllyId?.trim() || 'sample');

  return (
    <PreviewDetailPage
      backHref={`/allies/${allyId}/settings`}
      screen={getPreviewScreen('ally', section ?? '')}
    />
  );
}
