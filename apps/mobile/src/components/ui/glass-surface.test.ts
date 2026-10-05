import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const glassSurfaceSource = readFileSync(
  fileURLToPath(new URL('./glass-surface.tsx', import.meta.url)),
  'utf8',
);

describe('GlassSurface component contract', () => {

  it('does not render GlassView without the shared availability guard', () => {
    expect(glassSurfaceSource).not.toContain('<GlassView');
  });
});
