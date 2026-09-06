import type { MessageViewModel } from "./mappers/allies";

const statusRank: Record<MessageViewModel["status"], number> = {
  queued: 0,
  in_progress: 1,
  awaiting_action: 1,
  completed: 2,
  failed: 2,
  stopped: 2,
};

export function mergeConversationMessageCopies(
  ...groups: readonly (readonly MessageViewModel[])[]
): MessageViewModel[] {
  const messages = new Map<string, MessageViewModel>();
  for (const group of groups) {
    for (const incoming of group) {
      const current = messages.get(incoming.id);
      if (current?.deletedAt) continue;
      if (current && !incoming.deletedAt) {
        if (statusRank[current.status] > statusRank[incoming.status]) continue;
        if (current.status === "queued" && incoming.status === "queued"
          && current.queueState === "claimed" && incoming.queueState !== "claimed") continue;
      }
      messages.set(incoming.id, incoming);
    }
  }
  return [...messages.values()].sort((a, b) => a.sequence - b.sequence || a.id.localeCompare(b.id));
}
