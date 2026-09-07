import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const glassSurfaceSource = readFileSync(
  fileURLToPath(new URL('./glass-surface.tsx', import.meta.url)),
  'utf8',
);

describe('GlassSurface component contract', () => {
  it('uses the guarded Liquid Glass background', () => {
    expect(glassSurfaceSource).toContain("import { LiquidGlassBackground }");
    expect(glassSurfaceSource).toContain('<LiquidGlassBackground');
  });

  it('does not render GlassView without the shared availability guard', () => {
    expect(glassSurfaceSource).not.toContain('<GlassView');
  });

  it('defaults fallback color to theme.controlSurface', () => {
    expect(glassSurfaceSource).toContain("fallbackColor ?? theme.controlSurface");
    expect(glassSurfaceSource).toContain('fallbackColor={resolvedFallback}');
  });

  it('leaves interaction defaulting to LiquidGlassBackground', () => {
    expect(glassSurfaceSource).toContain('isInteractive,');
    expect(glassSurfaceSource).not.toContain('isInteractive = false');
  });

  it('enforces overflow hidden to respect border radius clipping', () => {
    expect(glassSurfaceSource).toContain("overflow: 'hidden'");
  });
});
