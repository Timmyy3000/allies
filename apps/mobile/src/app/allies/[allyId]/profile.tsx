import { useLocalSearchParams, useRouter } from 'expo-router';
import { Text, View } from 'react-native';

import { PrimaryButton } from '@/components/ui/primary-button';
import { AllyProfileLoading, AllyProfileScreen } from '@/features/allies/ally-profile-screen';
import { useAlly } from '@/features/allies/queries';
import { useTheme } from '@/hooks/use-theme';

export default function AllyProfileRoute() {
  const router = useRouter();
  const theme = useTheme();
  const { allyId: rawAllyId } = useLocalSearchParams<{ allyId?: string }>();
  const allyId = (Array.isArray(rawAllyId) ? rawAllyId[0] : rawAllyId)?.trim() || null;
  const allyQuery = useAlly(allyId);
  const back = () => (router.canGoBack() ? router.back() : router.replace(allyId ? `/allies/${allyId}` as never : '/allies' as never));

  if (allyQuery.data) return <AllyProfileScreen ally={allyQuery.data} onBack={back} />;
  if (allyQuery.isError || !allyId) {
    return (
      <View style={{ alignItems: 'center', backgroundColor: theme.appBackground, flex: 1, gap: 16, justifyContent: 'center', padding: 24 }}>
        <Text style={{ color: theme.primaryText, fontFamily: 'OpenRundeMedium', fontSize: 16 }}>
          {allyId ? 'We couldn’t load this Ally.' : 'That Ally link is not valid.'}
        </Text>
        {allyId ? <PrimaryButton label="Try again" onPress={() => void allyQuery.refetch()} /> : null}
        <PrimaryButton
          accentColor={theme.neutralButtonSurface}
          label="Back"
          labelColor={theme.neutralButtonText}
          onPress={back}
        />
      </View>
    );
  }
  return <AllyProfileLoading />;
}
