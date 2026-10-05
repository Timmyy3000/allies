import { describe, expect, it } from 'vitest';

import {
  addConversationAttachments,
  CONVERSATION_ALLY_SIZE,
  CONVERSATION_FOLLOW_LATEST_THRESHOLD,
  CONVERSATION_INITIAL_CONTENT_OFFSET,
  getAttachmentDisplayName,
  isAttachmentPickerCancellation,
  isConversationNearBottom,
} from './mock-conversation-layout';
import { getMockPreviewText } from './mock-app';

describe('mock conversation layout', () => {
  it('keeps the conversation inset and Ally size aligned with onboarding', () => {
    expect(CONVERSATION_INITIAL_CONTENT_OFFSET).toBe(78);
    expect(CONVERSATION_ALLY_SIZE).toBe(40.32);
  });

  it('follows the latest content through the exact threshold only', () => {
    expect(
      isConversationNearBottom(
        1000,
        1000 - 400 - CONVERSATION_FOLLOW_LATEST_THRESHOLD,
        400,
      ),
    ).toBe(true);
    expect(
      isConversationNearBottom(
        1000,
        1000 - 400 - CONVERSATION_FOLLOW_LATEST_THRESHOLD - 1,
        400,
      ),
    ).toBe(false);
  });

  it('keeps attachment state bounded and preserves picker cancellation', () => {
    const attachments = Array.from({ length: 6 }, (_, index) => ({
      kind: 'file' as const,
      name: `file-${index}`,
      uri: `file://${index}`,
    }));

    expect(addConversationAttachments([], attachments)).toHaveLength(5);
    expect(getAttachmentDisplayName('msf:12345', 'content://provider/item', 'file')).toBe('File');
    expect(getAttachmentDisplayName('notes.pdf', 'content://provider/item', 'file')).toBe('notes.pdf');
    expect(isAttachmentPickerCancellation(new Error('The user cancelled the picker'))).toBe(true);
    expect(isAttachmentPickerCancellation(new Error('Permission denied'))).toBe(false);
  });

  it('uses attachment metadata for an attachment-only mock preview', () => {
    expect(getMockPreviewText('  ', [{ kind: 'file', name: 'notes.pdf', uri: 'file://notes' }])).toBe('notes.pdf');
    expect(getMockPreviewText('', [
      { kind: 'file', name: 'one', uri: 'file://one' },
      { kind: 'folder', name: 'two', uri: 'file://two' },
    ])).toBe('2 attachments');
  });
});
