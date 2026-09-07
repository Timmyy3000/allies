import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const screenSource = readFileSync(
  fileURLToPath(new URL('./onboarding-allies-screen.tsx', import.meta.url)),
  'utf8',
);

describe('OnboardingAlliesScreen layout and tabs', () => {
  it('renders top tabs for My allies and Routines', () => {
    expect(screenSource).toContain('accessibilityLabel="My allies"');
    expect(screenSource).toContain('accessibilityLabel="Routines"');
  });

  it('does not render an add-list button', () => {
    expect(screenSource).not.toContain('Add new list');
    expect(screenSource).not.toContain('styles.addListButton');
  });

  it('renders the huge Make an ally button at the bottom', () => {
    expect(screenSource).toContain('<PrimaryButton');
    expect(screenSource).toContain('label="Make an ally"');
    expect(screenSource).toContain('styles.createButton');
  });

  it('keeps the decorative chef inert', () => {
    expect(screenSource).toContain('<View accessibilityLabel="Chef" accessible>');
    expect(screenSource).not.toContain('accessibilityLabel="Make an Ally"');
  });

  it('manages activeTab state between my-allies and routines', () => {
    expect(screenSource).toContain("const [activeTab, setActiveTab] = useState<'my-allies' | 'routines'>('my-allies');");
    expect(screenSource).toContain("activeTab === 'my-allies'");
    expect(screenSource).toContain("activeTab === 'routines'");
  });

  it('aligns the presence dot half inside and half outside the ally blob edge', () => {
    expect(screenSource).toContain('bottom: 2');
    expect(screenSource).toContain('right: 2');
    expect(screenSource).toContain('borderColor: theme.appBackground');
  });
});
