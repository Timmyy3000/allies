import { describe, expect, it } from 'vitest';

import { DEFAULT_MOCK_ALLIES, getMockGreeting, getMockReply } from './mock-app';

describe('mock app copy', () => {
  it('uses the first Ally greeting copy', () => {
    const greeting = getMockGreeting();

    expect(greeting).toContain(
      'Welcome! I am your ally, and I am thrilled to help you make your day easier, more productive, and fun.',
    );
    expect(greeting).toContain('🌟 What We Can Do Together');
    expect(greeting).toContain(
      '• Chat Freely: Ask me questions about history, science, pop culture, or everyday facts.',
    );
    expect(greeting).toContain(
      '• Brainstorm Ideas: Outline your next big business project, travel itinerary, or workout plan.',
    );
  });

  it('seeds the screenshot roster in display order', () => {
    expect(DEFAULT_MOCK_ALLIES.map(({ id }) => id)).toEqual(['timi', 'mock-ally']);
    expect(DEFAULT_MOCK_ALLIES[0]).toMatchObject({
      color: '#3446E9',
      name: 'timi',
      preview: 'Think of me as your always-available part…',
      shape: 'ghosty',
      time: '12:20 PM',
    });
    expect(DEFAULT_MOCK_ALLIES[1]).toMatchObject({
      color: '#FD304F',
      name: 'Sally',
      preview: 'Welcome! I am your ally, and I am thrilled t…',
      shape: 'rolly',
      time: '9:40 AM',
    });
  });

  it('returns a short deterministic reply for the mock composer', () => {
    expect(getMockReply('  Plan tomorrow. ')).toContain('three most important outcomes');
    expect(getMockReply('')).toContain('help you with that');
  });
});
