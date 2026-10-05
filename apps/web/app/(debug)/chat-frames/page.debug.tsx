import { notFound } from "next/navigation";

import { canAccessChatFrames } from "./chat-frame-access";
import { CHAT_FRAME_IDS, getChatFrameFixture, isChatFrameId } from "./chat-frame-fixtures";
import { ChatFramePreview } from "./chat-frame-preview";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ChatFramesPage({ searchParams }: { searchParams: SearchParams }) {
  if (!canAccessChatFrames()) notFound();

  const params = await searchParams;
  const requestedFrame = typeof params.frame === "string" ? params.frame : CHAT_FRAME_IDS[0];
  if (!isChatFrameId(requestedFrame)) notFound();

  return <ChatFramePreview fixture={getChatFrameFixture(requestedFrame)} />;
}
