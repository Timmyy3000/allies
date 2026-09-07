import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import type { GlassStyle } from 'expo-glass-effect';
import type { ReactNode } from 'react';

import { LiquidGlassBackground } from './liquid-glass-background';
import { useTheme } from '@/hooks/use-theme';

export type GlassSurfaceProps = {
  children?: ReactNode;
  fallbackColor?: string;
  glassEffectStyle?: GlassStyle;
  isInteractive?: boolean;
  style?: StyleProp<ViewStyle>;
  tintColor?: string;
};

export function GlassSurface({
  children,
  fallbackColor,
  glassEffectStyle = 'regular',
  isInteractive,
  style,
  tintColor,
}: GlassSurfaceProps) {
  const theme = useTheme();
  const resolvedFallback = fallbackColor ?? theme.controlSurface;

  return (
    <View style={[styles.base, style]}>
      <LiquidGlassBackground
        borderRadius={0}
        fallbackColor={resolvedFallback}
        glassEffectStyle={glassEffectStyle}
        isInteractive={isInteractive}
        tintColor={tintColor}
      />
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    overflow: 'hidden',
  },
});
