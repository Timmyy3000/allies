import type { AllyShape } from "../../../components/ally-avatar";
import type { ProductCardItem } from "../../home/conversation-frame-primitives";

export interface DebugConversationMessage {
  id: string;
  sender: "user" | "assistant";
  text: string;
  status?: string;
  retryable?: boolean;
}

export interface DebugActivityEntry {
  id: string;
  text: string;
  activityKind?: string;
  tone?: "accent" | "muted" | "default";
}

export interface DebugActivityItem {
  kind: "activity";
  id: string;
  label: string;
  entries: DebugActivityEntry[];
  open?: boolean;
}

export interface DebugThinkingItem {
  kind: "thinking";
  id: string;
  label: string;
}

export interface DebugStatusItem {
  kind: "status";
  id: string;
  text: string;
  tone: "default" | "success" | "warning";
}

export interface DebugRichTextItem {
  kind: "rich-text";
  id: string;
  text: string;
}

export interface DebugRoutineItem {
  kind: "routine-card";
  id: string;
  name: string;
  schedule: string;
}

export interface DebugProductsItem {
  kind: "products";
  id: string;
  intro: string;
  products: ProductCardItem[];
}

export interface DebugCartItem {
  kind: "cart-summary";
  id: string;
  restaurant: string;
  itemCount: number;
  expanded?: boolean;
}

export interface DebugCartEditorItem {
  kind: "cart-editor";
  id: string;
  itemCount: number;
  quantity: number;
}

export interface DebugFailureItem {
  kind: "failure";
  id: string;
  text: string;
  actionLabel: string;
}

export interface DebugImageItem {
  kind: "image";
  id: string;
  alt: string;
}

export type DebugRichItem =
  | DebugRoutineItem
  | DebugProductsItem
  | DebugCartItem
  | DebugCartEditorItem
  | DebugFailureItem
  | DebugImageItem
  | DebugRichTextItem;

export type DebugTimelineItem =
  | ({ kind: "message" } & DebugConversationMessage)
  | DebugActivityItem
  | DebugThinkingItem
  | DebugStatusItem
  | DebugRichItem;

export type DebugConversationOverlay =
  | { kind: "approval"; question: string }
  | { kind: "image"; alt: string }
  | { kind: "cart"; itemCount: number; products: ProductCardItem[] }
  | { kind: "routine" }
  | { kind: "delete-routine" };

export type DebugConversationAction =
  | "approve"
  | "reject"
  | "report"
  | "push"
  | "open-image"
  | "open-cart"
  | "open-routine"
  | "delete-routine"
  | "cancel-delete"
  | "confirm-delete"
  | "close-overlay"
  | "done-cart";

export interface DebugConversationFrameModel {
  frameId: string;
  title: string;
  ally: {
    name: string;
    job: string;
    shape: AllyShape;
    accent: string;
  };
  dateLabel: string;
  timeline: DebugTimelineItem[];
  queue: { id: string; content: string }[];
  queueAction?: "push";
  composer: {
    draft: string;
    placeholder: string;
  };
  overlay: DebugConversationOverlay | null;
  acknowledgement: string | null;
  deleted: boolean;
}

export interface DebugConversationFrameActions {
  onAction: (action: DebugConversationAction) => void;
  onComposerChange: (value: string) => void;
  onComposerSubmit: () => void;
  onRemoveQueue: (id: string) => void;
  onQuantityChange: (id: string, next: number) => void;
}
