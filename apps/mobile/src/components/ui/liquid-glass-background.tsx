import {
  GlassView,
  isGlassEffectAPIAvailable,
  isLiquidGlassAvailable,
  type GlassStyle,
} from 'expo-glass-effect';
import { useEffect, useState, type ReactNode } from 'react';
import {
  AccessibilityInfo,
  Platform,
  StyleSheet,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';

import { getLiquidGlassPointerEvents, shouldUseLiquidGlass } from './liquid-glass';
import { useLiquidGlassMode } from './liquid-glass-mode';
import { useColorScheme } from '@/hooks/use-color-scheme';

type LiquidGlassBackgroundProps = {
  borderRadius: number;
  children?: ReactNode;
  contentStyle?: StyleProp<ViewStyle>;
  fallbackColor: string;
  glassEffectStyle?: GlassStyle;
  invertColorScheme?: boolean;
  isInteractive?: boolean;
  tintColor?: string;
};

const glassEffectAPIAvailable =
  Platform.OS === 'ios' && isGlassEffectAPIAvailable();
const liquidGlassAvailable =
  glassEffectAPIAvailable && isLiquidGlassAvailable();

export function LiquidGlassBackground({
  borderRadius,
  children,
  contentStyle,
  fallbackColor,
  glassEffectStyle = 'regular',
  invertColorScheme = false,
  isInteractive = true,
  tintColor,
}: LiquidGlassBackgroundProps) {
  const colorScheme = useColorScheme();
  const mode = useLiquidGlassMode();
  const reducedMotion = Boolean(useReducedMotion());
  const [reduceTransparency, setReduceTransparency] = useState(true);

  useEffect(() => {
    if (!liquidGlassAvailable) return;

    let active = true;
    void AccessibilityInfo.isReduceTransparencyEnabled().then((enabled) => {
      if (active) setReduceTransparency(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener(
      'reduceTransparencyChanged',
      setReduceTransparency,
    );

    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  const useGlass = shouldUseLiquidGlass({
    apiAvailable: glassEffectAPIAvailable,
    forceFallback: mode === 'regular',
    liquidGlassAvailable,
    platform: Platform.OS,
    reduceTransparency,
  });
  const surfaceStyle = [StyleSheet.absoluteFill, { borderRadius }];
  const glassColorScheme = invertColorScheme
    ? colorScheme === 'dark' ? 'light' : 'dark'
    : colorScheme === 'dark' ? 'dark' : 'light';
  const nativeIsInteractive = isInteractive && !reducedMotion;
  const hasChildren = children !== undefined && children !== null;
  const pointerEvents = getLiquidGlassPointerEvents(hasChildren);
  const hostStyle = [
    surfaceStyle,
    { backgroundColor: useGlass ? 'transparent' : fallbackColor },
    contentStyle,
  ];

  return (
    <GlassView
      colorScheme={glassColorScheme}
      glassEffectStyle={useGlass ? glassEffectStyle : 'none'}
      isInteractive={useGlass && nativeIsInteractive}
      pointerEvents={pointerEvents}
      style={hostStyle}
      tintColor={useGlass ? tintColor : undefined}
    >
      {children}
    </GlassView>
  );
}
