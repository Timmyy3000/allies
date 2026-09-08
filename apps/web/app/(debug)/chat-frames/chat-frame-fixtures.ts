import type {
  DebugActivityItem,
  DebugConversationFrameModel,
  DebugConversationMessage,
  DebugRichItem,
  DebugTimelineItem,
} from "./debug-conversation-frame-model";

export const CHAT_FRAME_IDS = [
  "315:1612",
  "315:2050",
  "346:5812",
  "315:2837",
  "315:2927",
  "315:3009",
  "370:6544",
  "370:6622",
  "346:5714",
  "346:5880",
  "315:3256",
  "347:5953",
  "362:6356",
  "365:6452",
  "355:6222",
  "355:6112",
  "331:4419",
  "332:4537",
  "332:5289",
  "332:5604",
  "332:4983",
  "372:6829",
  "376:7026",
  "332:4740",
  "315:3141",
] as const;

export type ChatFrameId = (typeof CHAT_FRAME_IDS)[number];

export interface ChatFrameFixture {
  frameId: ChatFrameId;
  name: string;
  model: DebugConversationFrameModel;
  expectedAnchors: {
    viewport: { width: 375; height: 812 };
    contentGutter: 20;
    railWidth: 335;
    composerHeight: 48;
  };
}

const SALLY = {
  name: "Sally",
  job: "Your personal assistant",
  shape: "ghosty" as const,
  accent: "#FD304F",
};

const WELCOME = "Welcome! I am your ally, and I am thrilled to help you make your day easier, more productive, and fun. Think of me as your always-available partner for brainstorming, writing, learning, and organising. No task is too big or too small, and I am constantly learning new ways to assist you better. Let us collaborate and build something great together.";
const SANDWICH = "i want a sandwich";
const SANDWICH_REPLY = "Okay. What kind of sandwich do you want and which store would you like to order from?";
const LONG_MESSAGE = "i don’t know but i like citysubs, check their menu, i only get their 6 inch subs, i think i want the chicken sub but let me what’s available";
const ROUTINE_REQUEST = "i don’t know but check their menu, i only get their 6 inch subs, i think i want the chicken sub, make this a daily routine";
const CART_INTRO = "This is everything on the menu for the Magodo branch. Let me your pick and I’ll build your cart.";

const PRODUCTS = [
  { id: "product-1", price: "$20", name: "Product name", color: "#F8C66D", alt: "Product name on a warm yellow background" },
  { id: "product-2", price: "$20", name: "Product name", color: "#E9B6B0", alt: "Product name on a blush background" },
  { id: "product-3", price: "$20", name: "Product name", color: "#BFDDBE", alt: "Product name on a green background" },
] as const;

const QUEUED_TEXT = "this is a message waiting to be sent which is interesting";

function message(
  id: string,
  sender: DebugConversationMessage["sender"],
  text: string,
  options: Pick<DebugConversationMessage, "status" | "retryable"> = {},
): DebugTimelineItem {
  return { kind: "message", id, sender, text, ...options };
}

function activity(
  id: string,
  label: string,
  entries: DebugActivityItem["entries"],
  open = false,
): DebugActivityItem {
  return { kind: "activity", id, label, entries, open };
}

function rich(item: DebugRichItem): DebugRichItem {
  return item;
}

function base(
  frameId: ChatFrameId,
  name: string,
  timeline: DebugTimelineItem[],
  options: Partial<Pick<DebugConversationFrameModel, "queue" | "queueAction" | "overlay" | "acknowledgement" | "deleted">> & {
    composerDraft?: string;
    composerPlaceholder?: string;
  } = {},
): ChatFrameFixture {
  return {
    frameId,
    name,
    model: {
      frameId,
      title: name,
      ally: SALLY,
      dateLabel: "TODAY 9:40 AM",
      timeline,
      queue: options.queue ?? [],
      queueAction: options.queueAction,
      overlay: options.overlay ?? null,
      acknowledgement: options.acknowledgement ?? null,
      deleted: options.deleted ?? false,
      composer: {
        draft: options.composerDraft ?? "",
        placeholder: options.composerPlaceholder ?? "Reply Sally",
      },
    },
    expectedAnchors: {
      viewport: { width: 375, height: 812 },
      contentGutter: 20,
      railWidth: 335,
      composerHeight: 48,
    },
  };
}

export const CHAT_FRAME_FIXTURES: Record<ChatFrameId, ChatFrameFixture> = {
  "315:1612": base("315:1612", "chat", [message("welcome", "assistant", WELCOME)]),
  "315:2050": base("315:2050", "chat ~ thinking state", [
    message("sandwich", "user", SANDWICH),
    { kind: "thinking", id: "thinking-1", label: "Thinking" },
  ], { composerPlaceholder: "Ask Sally" }),
  "346:5812": base("346:5812", "thinking", [
    message("sandwich-alt", "user", SANDWICH),
    { kind: "thinking", id: "thinking-2", label: "Thinking" },
  ], { composerPlaceholder: "Ask Sally" }),
  "315:2837": base("315:2837", "chat ~ ally reply", [
    message("sandwich-reply-user", "user", SANDWICH),
    message("sandwich-reply", "assistant", SANDWICH_REPLY),
  ]),
  "315:2927": base("315:2927", "chat ~ long message", [
    message("long-draft-context", "assistant", WELCOME),
  ], { composerDraft: LONG_MESSAGE }),
  "315:3009": base("315:3009", "chat ~ long message", [
    message("long-sent", "user", LONG_MESSAGE),
    activity("citysubs-search", "Searching for citysubs", [
      { id: "citysubs-search-start", text: "Searching for citysubs", tone: "accent" },
    ]),
    message("citysubs-reply", "assistant", "Got it! I’ll look for citysubs and let you know what’s on their menu."),
  ]),
  "370:6544": base("370:6544", "routine", [
    message("routine-request", "user", ROUTINE_REQUEST),
    activity("routine-making", "Making a routine", [
      { id: "routine-making-entry", text: "Making a routine", tone: "accent" },
    ]),
  ], { composerPlaceholder: "Ask Sally" }),
  "370:6622": base("370:6622", "routine created", [
    message("routine-created-copy", "assistant", "Your routine has been created to check the menu every Monday. "),
    rich({ kind: "routine-card", id: "routine-card", name: "Routine name", schedule: "4pm every Monday" }),
  ]),
  "346:5714": base("346:5714", "sleeping", [
    { kind: "status", id: "sleeping-status", text: "Sally is asleep", tone: "default" },
  ]),
  "346:5880": base("346:5880", "waking", [
    { kind: "status", id: "waking-status", text: "Sally is waking", tone: "warning" },
    { kind: "thinking", id: "waking-thinking", label: "Waking" },
  ], { composerPlaceholder: "Ask Sally" }),
  "315:3256": base("315:3256", "chat ~ error message", [
    message("error-user", "user", "order from the magodo branch", { status: "Failed", retryable: true }),
    activity("branch-selecting", "Selecting a branch", [
      { id: "branch-selecting-entry", text: "Selecting a branch", tone: "accent" },
    ]),
    { kind: "status", id: "retry-message", text: "Try sending this again", tone: "warning" },
  ]),
  "347:5953": base("347:5953", "queueing", [
    message("queueing-context", "assistant", "I’m still working on your last request."),
    activity("queueing-activity", "Working", [
      { id: "queueing-activity-entry", text: "Working", tone: "accent" },
    ]),
  ], {
    queue: [{ id: "queue-one", content: QUEUED_TEXT }],
    queueAction: "push",
    composerPlaceholder: "Ask Sally",
  }),
  "362:6356": base("362:6356", "failed", [
    rich({ kind: "failure", id: "failure-item", text: "Error message sits here", actionLabel: "Report" }),
    { kind: "thinking", id: "retrying-activity", label: "Retrying" },
  ]),
  "365:6452": base("365:6452", "failed b", [
    { kind: "status", id: "report-acknowledged", text: "Thanks for sharing this report", tone: "success" },
  ]),
  "355:6222": base("355:6222", "approval request", [
    activity("approval-waiting", "Waiting", [
      { id: "approval-waiting-entry", text: "Waiting", tone: "accent" },
    ]),
  ], {
    overlay: {
      kind: "approval",
      question: "Allow Sally perform this specific action that requires manual approval?",
    },
  }),
  "355:6112": base("355:6112", "multiple message queueing", [
    activity("multiple-queue-working", "Working", [
      { id: "multiple-queue-working-entry", text: "Working", tone: "accent" },
    ]),
  ], {
    queue: [
      { id: "queue-two", content: "first message waiting to be sent" },
      { id: "queue-three", content: "second message waiting to be sent" },
    ],
    queueAction: "push",
    composerPlaceholder: "Ask Sally",
  }),
  "331:4419": base("331:4419", "chat ~ interrupted mid work", [
    activity("interrupted-working", "Working", [
      { id: "interrupted-working-entry", text: "Working", tone: "accent" },
    ]),
    message("interrupted-user", "user", "order from the magodo branch"),
    message("interrupted-reply", "assistant", "Got it! I’ll look for citysubs and let you know what’s on their menu."),
  ]),
  "332:4537": base("332:4537", "chat ~ cart", [
    rich({ kind: "products", id: "menu-products", intro: CART_INTRO, products: [...PRODUCTS] }),
  ]),
  "332:5289": base("332:5289", "chat ~ image display", [
    message("image-context", "assistant", "Here is the image you asked me to find."),
    rich({ kind: "image", id: "sandwich-image", alt: "A sandwich from the citysubs menu" }),
  ], {
    overlay: { kind: "image", alt: "A sandwich from the citysubs menu" },
  }),
  "332:5604": base("332:5604", "chat ~ cart", [
    message("cart-context", "assistant", CART_INTRO),
    rich({ kind: "cart-summary", id: "cart-summary", restaurant: "Sooyah Bistro", itemCount: 4 }),
  ]),
  "332:4983": base("332:4983", "chat ~ cart expanded", [
    message("expanded-cart-context", "assistant", CART_INTRO),
    rich({ kind: "cart-summary", id: "expanded-cart-summary", restaurant: "Sooyah Bistro", itemCount: 4, expanded: true }),
  ], {
    overlay: { kind: "cart", itemCount: 4, products: [...PRODUCTS] },
  }),
  "372:6829": base("372:6829", "chat ~ routine", [
    rich({ kind: "routine-card", id: "routine-detail-card", name: "Routine name goes in this text box", schedule: "4pm every Monday" }),
  ], { overlay: { kind: "routine" } }),
  "376:7026": base("376:7026", "chat ~ routine delete", [
    rich({ kind: "routine-card", id: "routine-delete-card", name: "Routine name goes in this text box", schedule: "4pm every Monday" }),
  ], { overlay: { kind: "delete-routine" } }),
  "332:4740": base("332:4740", "chat ~ cart expanded", [
    rich({ kind: "cart-editor", id: "cart-editor", itemCount: 4, quantity: 1 }),
  ]),
  "315:3141": base("315:3141", "chat ~ activity dropdown", [
    activity("activity-dropdown", "Searching for citysubs", [
      { id: "activity-search", text: "Searched the web for citysubs sandwich", tone: "accent", activityKind: "web_search" },
      { id: "activity-visited", text: "Visited https://citysubs.daash.restaurant/", tone: "muted", activityKind: "browser_navigate" },
    ], true),
  ]),
};

export function isChatFrameId(value: string): value is ChatFrameId {
  return (CHAT_FRAME_IDS as readonly string[]).includes(value);
}

export function getChatFrameFixture(frameId: ChatFrameId): ChatFrameFixture {
  return CHAT_FRAME_FIXTURES[frameId];
}
