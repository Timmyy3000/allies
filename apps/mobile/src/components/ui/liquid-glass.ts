type LiquidGlassAvailability = {
  apiAvailable: boolean;
  forceFallback?: boolean;
  liquidGlassAvailable: boolean;
  platform: string;
  reduceTransparency: boolean;
};

export function getLiquidGlassPointerEvents(hasChildren: boolean): 'auto' | 'none' {
  return hasChildren ? 'auto' : 'none';
}

export function shouldUseLiquidGlass({
  apiAvailable,
  forceFallback = false,
  liquidGlassAvailable,
  platform,
  reduceTransparency,
}: LiquidGlassAvailability) {
  return (
    !forceFallback &&
    platform === 'ios' &&
    apiAvailable &&
    liquidGlassAvailable &&
    !reduceTransparency
  );
}
