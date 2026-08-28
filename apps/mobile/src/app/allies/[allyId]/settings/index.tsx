import { useLocalSearchParams } from 'expo-router';

import { PreviewCard, PreviewListRow, PreviewPage, PreviewSectionTitle } from '@/features/app-preview/preview-ui';
import { StyleSheet, Text } from 'react-native';

export default function AllySettingsScreen() {
  const params = useLocalSearchParams<{ allyId?: string | string[] }>();
  const rawAllyId = Array.isArray(params.allyId) ? params.allyId[0] : params.allyId;
  const allyId = encodeURIComponent(rawAllyId?.trim() || 'sample');
  const base = `/allies/${allyId}/settings`;

  return (
    <PreviewPage backHref="/settings" subtitle="Shape the Ally without turning it into a configuration panel." title="Sally">
      <PreviewCard tone="red">
        <Text style={styles.cardTitle}>Ally settings</Text>
        <Text style={styles.cardText}>
          Edit identity directly. Review learned responsibilities, routines, and connection access here.
        </Text>
      </PreviewCard>

      <PreviewSectionTitle>Identity</PreviewSectionTitle>
      <PreviewListRow detail="Name, job, personality, avatar, and colour" href={`${base}/identity`} label="Ally identity" tone="red" />

      <PreviewSectionTitle>Work</PreviewSectionTitle>
      <PreviewListRow detail="Ongoing work learned through conversation" href={`${base}/responsibilities`} label="Responsibilities" tone="red" />
      <PreviewListRow detail="Recurring work proposed in conversation" href={`${base}/routines`} label="Routines" tone="purple" />
      <PreviewListRow detail="Services and information Sally may use" href={`${base}/access`} label="Connection access" tone="blue" />

      <PreviewSectionTitle>Danger zone</PreviewSectionTitle>
      <PreviewListRow detail="Remove Sally and the work attached to this Ally" href={`${base}/delete`} label="Delete Ally" tone="red" />
    </PreviewPage>
  );
}

const styles = StyleSheet.create({
  cardText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 21,
    marginBottom: 12,
    marginTop: 6,
  },
  cardTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 19,
    lineHeight: 24,
    marginTop: 12,
  },
});
