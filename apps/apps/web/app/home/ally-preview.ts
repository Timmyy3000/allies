import type { ConversationViewModel } from "@allies/cloud-client";

export type AllyReplyPreview = { content: string; createdAt: string };

export function latestAllyReply(conversation: ConversationViewModel): AllyReplyPreview | null {
  const replies = [
    ...conversation.messages.filter((message) => message.sender === "assistant"),
    ...(conversation.assistantReplies ?? []).filter((reply) => reply.hasFullPrefix),
  ];
  return replies.reduce<AllyReplyPreview | null>((latest, reply) => {
    if (!reply.content.trim()) return latest;
    return !latest || Date.parse(reply.createdAt) >= Date.parse(latest.createdAt) ? reply : latest;
  }, null);
}
