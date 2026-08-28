import { activityItems } from '@/features/app-preview/screen-map';
import { PreviewCard, PreviewListRow, PreviewPage, PreviewSectionTitle } from '@/features/app-preview/preview-ui';
import { StyleSheet, Text } from 'react-native';

export default function ActivityScreen() {
  return (
    <PreviewPage
      activeRoot="activity"
      subtitle="What needs you, what finished, and what changed."
      title="Activity">
      <PreviewCard tone="orange">
        <Text style={styles.introTitle}>Your attention, not a technical log.</Text>
        <Text style={styles.introText}>
          Results, questions, approvals, and problems arrive here in plain language.
        </Text>
      </PreviewCard>
      <PreviewSectionTitle>Today</PreviewSectionTitle>
      {activityItems.map((item) => (
        <PreviewListRow
          detail={`${item.status} · ${item.summary}`}
          href={`/activity/${item.id}`}
          key={item.id}
          label={item.title}
          tone={item.tone}
        />
      ))}
    </PreviewPage>
  );
}

const styles = StyleSheet.create({
  introText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 21,
    marginBottom: 12,
    marginTop: 6,
  },
  introTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 19,
    lineHeight: 24,
    marginTop: 12,
  },
});
