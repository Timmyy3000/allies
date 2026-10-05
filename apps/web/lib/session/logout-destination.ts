export const NOTIFICATION_CLEANUP_NOTICE = "You are signed out. Notification cleanup could not be confirmed; Allies will retry it when you reopen.";
export function logoutDestination(result: { serverConfirmed: boolean; pushCleanupConfirmed?: boolean }, destination: string): string {
  if (!result.serverConfirmed) return `${destination}?signout=unconfirmed`;
  return result.pushCleanupConfirmed === false ? `${destination}?notification_cleanup=unconfirmed` : destination;
}
