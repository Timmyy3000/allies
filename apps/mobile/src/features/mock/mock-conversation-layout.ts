import { ONBOARDING_TOP_PADDING } from '../onboarding/onboarding-layout';
import type { MockAttachment } from './mock-app';
import {
  ONBOARDING_PREVIEW_GREETING_TOP_GAP,
  ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
  ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE,
} from '../onboarding/onboarding-preview';

export const CONVERSATION_INITIAL_CONTENT_OFFSET = ONBOARDING_TOP_PADDING
  + ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE
  + ONBOARDING_PREVIEW_GREETING_TOP_GAP;
export const CONVERSATION_ALLY_SIZE = ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE;
export const CONVERSATION_FOLLOW_LATEST_THRESHOLD = 96;
export const CONVERSATION_MAX_ATTACHMENTS = 5;

export function isConversationNearBottom(
  contentHeight: number,
  offsetY: number,
  viewportHeight: number,
  threshold = CONVERSATION_FOLLOW_LATEST_THRESHOLD,
): boolean {
  return contentHeight - (offsetY + viewportHeight) <= threshold;
}

export function addConversationAttachments(
  current: MockAttachment[],
  picked: MockAttachment[],
): MockAttachment[] {
  return [...current, ...picked].slice(0, CONVERSATION_MAX_ATTACHMENTS);
}

export function getAttachmentDisplayName(
  name: string,
  uri: string,
  kind: MockAttachment['kind'],
): string {
  const fallback = kind === 'folder' ? 'Folder' : 'File';
  const trimmedName = name.trim();
  const opaqueContentName = uri.startsWith('content://') && /^[a-z]+:\d+$/iu.test(trimmedName);
  return trimmedName && !opaqueContentName ? trimmedName : fallback;
}

export function isAttachmentPickerCancellation(error: unknown): boolean {
  return error instanceof Error && /abort|cancel/i.test(`${error.name} ${error.message}`);
}
