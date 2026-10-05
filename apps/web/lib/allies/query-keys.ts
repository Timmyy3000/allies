export function alliesQueryKey(workspaceId: string) {
  return ["workspaces", workspaceId, "allies"] as const;
}
