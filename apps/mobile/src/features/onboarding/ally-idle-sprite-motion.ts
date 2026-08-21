export const ALLY_IDLE_PERIOD_MS = 4000;

export type AllyIdleIdentity = 'boxy' | 'ghosty' | 'rocky' | 'rolly';

export const ALLY_IDLE_SPRITES = {
  boxy: { columns: 16, frameCount: 130 },
  ghosty: { columns: 16, frameCount: 132 },
  rocky: { columns: 16, frameCount: 132 },
  rolly: { columns: 16, frameCount: 132 },
} as const;

export function getAllyIdleSpriteFrame(progress: number, frameCount: number) {
  'worklet';

  const boundedProgress = Math.min(1, Math.max(0, progress));
  return Math.min(frameCount - 1, Math.floor(boundedProgress * frameCount));
}
