const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function matchesPushTarget(search: string, workspace: string, conversation: string): boolean {
  const params = new URLSearchParams(search);
  const expectedWorkspace = params.get("push_workspace");
  const expectedConversation = params.get("push_conversation");
  if (expectedWorkspace === null && expectedConversation === null) return true;
  return !!expectedWorkspace && !!expectedConversation && UUID.test(expectedWorkspace) && UUID.test(expectedConversation) && expectedWorkspace === workspace && expectedConversation === conversation;
}

export function pushReturnPath(value: string | null): string | null {
  if (!value || !value.startsWith("/home/") || value.includes("\\") || /[\u0000-\u0020\u007f]/.test(value)) return null;
  const url = new URL(value, "https://allies.invalid");
  const ally = url.pathname.slice("/home/".length);
  if (url.origin !== "https://allies.invalid" || !UUID.test(ally) || url.hash) return null;
  const params = url.searchParams;
  if ([...params.keys()].some(key => key !== "push_workspace" && key !== "push_conversation")) return null;
  if (!params.size) return url.pathname;
  const workspace = params.get("push_workspace"); const conversation = params.get("push_conversation");
  if (params.size !== 2 || !workspace || !conversation || !UUID.test(workspace) || !UUID.test(conversation)) return null;
  return `${url.pathname}?push_workspace=${workspace}&push_conversation=${conversation}`;
}
