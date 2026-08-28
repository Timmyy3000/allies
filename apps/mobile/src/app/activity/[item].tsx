import { useLocalSearchParams } from 'expo-router';

import { getPreviewScreen } from '@/features/app-preview/screen-map';
import { PreviewDetailPage } from '@/features/app-preview/preview-ui';

export default function ActivityDetailScreen() {
  const params = useLocalSearchParams<{ item?: string | string[] }>();
  const item = Array.isArray(params.item) ? params.item[0] : params.item;

  return <PreviewDetailPage backHref="/activity" screen={getPreviewScreen('activity', item ?? '')} />;
}
