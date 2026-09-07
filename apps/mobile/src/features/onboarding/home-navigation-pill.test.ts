import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const pillSource = readFileSync(
  fileURLToPath(new URL('./home-navigation-pill.tsx', import.meta.url)),
  'utf8',
);

describe('HomeNavigationPill contract', () => {
  it('wraps the navigation pill in GlassSurface', () => {
    expect(pillSource).toContain('<GlassSurface');
    expect(pillSource).toContain("import { GlassSurface } from '@/components/ui/glass-surface';");
  });

  it('renders all three items: Allies, Routines, and Make an ally', () => {
    expect(pillSource).toContain("'allies', 'Allies'");
    expect(pillSource).toContain("'routines', 'Routines'");
    expect(pillSource).toContain('Make an ally');
  });

  it('supports center-action layout as the default', () => {
    expect(pillSource).toContain("layout = 'center-action'");
    expect(pillSource).toContain("layout === 'center-action'");
  });

  it('connects onCreateAlly callback to the Make an ally button', () => {
    expect(pillSource).toContain('onPress={onCreateAlly}');
  });
});
