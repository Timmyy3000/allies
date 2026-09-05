// @vitest-environment jsdom
import { afterEach, expect, test } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { AllyAvatar } from './ally-avatar';

afterEach(cleanup);
test('waits for initial state and uses the mobile coloured-canvas ratio', () => {
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
  const { container, rerender } = render(<AllyAvatar shape="boxy" color="#FF5800" size={48} motion="full" stateReady={false} />);
  expect(container.querySelector('iframe')).toBeNull();
  rerender(<AllyAvatar shape="boxy" color="#FF5800" size={48} motion="full" state="sleeping" stateReady />);
  const frame = container.querySelector('iframe')!;
  expect(frame.srcdoc).toContain('"state":"sleeping"');
  const artwork = container.querySelector<HTMLElement>('[data-ally-artwork]')!;
  expect(artwork.style.width).toBe('100%');
  expect(artwork.style.height).toBe('100%');
  expect(artwork.style.transform).toBe('scale(0.86)');
  rerender(<AllyAvatar shape="boxy" color="#FF5800" size={48} motion="full" state="idle" stateReady />);
  expect(container.querySelector('iframe')).toBe(frame);
});

