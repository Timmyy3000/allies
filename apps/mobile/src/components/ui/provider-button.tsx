import { Image } from 'expo-image';
import { Pressable, StyleSheet, Text, View, type ImageSourcePropType, type PressableProps } from 'react-native';

type ProviderButtonProps = Omit<PressableProps, 'children' | 'style'> & {
  icon: ImageSourcePropType;
  label: string;
};

export function ProviderButton({ disabled, icon, label, ...props }: ProviderButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      {...props}
      style={({ pressed }) => [
        styles.button,
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed,
      ]}>
      <View style={styles.iconContainer}>
        <Image accessibilityLabel="" contentFit="contain" source={icon} style={styles.icon} />
      </View>
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 999,
    flexDirection: 'row',
    height: 48,
    justifyContent: 'center',
    width: '100%',
  },
  disabled: {
    opacity: 0.56,
  },
  icon: {
    height: 24,
    width: 24,
  },
  iconContainer: {
    alignItems: 'center',
    height: 24,
    justifyContent: 'center',
    marginRight: 12,
    width: 24,
  },
  label: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: false,
    letterSpacing: -0.7,
    lineHeight: 18,
  },
  pressed: {
    opacity: 0.78,
  },
});
