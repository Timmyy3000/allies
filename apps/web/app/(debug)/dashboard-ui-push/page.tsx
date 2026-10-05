import { notFound } from "next/navigation";

import DashboardUiPushPreview from "./dashboard-ui-push-preview";
import { canAccessChatFrames } from "../chat-frames/chat-frame-access";

export default function DashboardUiPushDebugPage() {
  if (!canAccessChatFrames()) notFound();

  return <DashboardUiPushPreview />;
}
