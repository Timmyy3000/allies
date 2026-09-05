import { isCloudError } from "@allies/cloud-client";

export type ConversationAccessFailure =
  | "session-expired"
  | "forbidden"
  | "inaccessible"
  | "recoverable";

export function classifyConversationAccessError(error: unknown): ConversationAccessFailure {
  if (!isCloudError(error)) return "recoverable";
  if (error.kind === "unauthorized" || error.status === 401) return "session-expired";
  if (error.kind === "forbidden" || error.kind === "security" || error.status === 403) return "forbidden";
  if (error.kind === "not-found" || error.status === 404) return "inaccessible";
  return "recoverable";
}

export function conversationAccessCopy(failure: Exclude<ConversationAccessFailure, "recoverable">) {
  if (failure === "session-expired") {
    return { title: "Your session ended", detail: "Sign in again to keep talking with your Allies." };
  }
  if (failure === "forbidden") {
    return { title: "This conversation isn't available", detail: "You don't have permission to open it here." };
  }
  return { title: "This conversation isn't available", detail: "Choose another Ally to keep talking." };
}
