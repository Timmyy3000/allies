import { notFound } from "next/navigation";

import { canAccessChatFrames } from "../../chat-frame-access";

export function GET() {
  if (!canAccessChatFrames()) notFound();
  notFound();
}
