export type PreviewFamily = 'activity' | 'settings' | 'connection' | 'ally';
export type PreviewTone = 'orange' | 'red' | 'blue' | 'green' | 'purple';

export type PreviewAction = {
  label: string;
  href?: string;
  disabled?: boolean;
};

export type PreviewScreen = {
  family: PreviewFamily;
  id: string;
  title: string;
  summary: string;
  status: string;
  tone: PreviewTone;
  details: { label: string; value: string; note?: string }[];
  actions?: PreviewAction[];
  progress?: { value: number; label: string; note: string };
};

const screens: Record<PreviewFamily, Record<string, PreviewScreen>> = {
  activity: {
    result: {
      family: 'activity',
      id: 'result',
      title: 'Friday cash review',
      summary: 'Sally finished the weekly review and found one change worth your attention.',
      status: 'Result ready',
      tone: 'green',
      details: [
        { label: 'Completed by', value: 'Sally' },
        { label: 'Result', value: 'Cash is up 8% from last Friday.', note: 'Two overdue invoices account for most of the difference.' },
        { label: 'Next step', value: 'Review the overdue invoices with Sally.' },
      ],
      actions: [{ label: 'Open Allies', href: '/allies' }],
    },
    waiting: {
      family: 'activity',
      id: 'waiting',
      title: 'Waiting for your answer',
      summary: 'Rolly needs one detail before the supplier comparison can continue.',
      status: 'Waiting',
      tone: 'blue',
      details: [
        { label: 'Question', value: 'Should delivery speed or price matter more for this order?' },
        { label: 'Work preserved', value: 'The comparison stays ready while Rolly waits.' },
      ],
      actions: [{ label: 'Open Allies', href: '/allies' }],
    },
    approval: {
      family: 'activity',
      id: 'approval',
      title: 'Approve a calendar change?',
      summary: 'Sally wants permission before moving three customer calls.',
      status: 'Needs your decision',
      tone: 'orange',
      details: [
        { label: 'Action', value: 'Move three calls to Thursday afternoon.' },
        { label: 'Target', value: 'Your connected work calendar.' },
        { label: 'Reason', value: 'Wednesday now overlaps with the supplier review.' },
        { label: 'Consequence', value: 'Guests will receive updated calendar invitations.' },
      ],
      actions: [
        { label: 'Approve · Preview', disabled: true },
        { label: 'Reject · Preview', disabled: true },
      ],
    },
    failure: {
      family: 'activity',
      id: 'failure',
      title: 'Sally could not finish this',
      summary: 'The work stopped safely after the connected service became unavailable.',
      status: 'Needs attention',
      tone: 'red',
      details: [
        { label: 'What happened', value: 'The calendar connection stopped responding.' },
        { label: 'What is safe', value: 'No event was changed and the original request is preserved.' },
        { label: 'Recovery', value: 'Reconnect the service, then ask Sally to try again.' },
      ],
      actions: [
        { label: 'Review connections', href: '/settings/connections' },
        { label: 'Try again · Preview', disabled: true },
      ],
    },
    routine: {
      family: 'activity',
      id: 'routine',
      title: 'Weekly review delivered',
      summary: 'Sally completed the Friday routine and left the result in your shared timeline.',
      status: 'Routine complete',
      tone: 'purple',
      details: [
        { label: 'Routine', value: 'Weekly cash-position summary' },
        { label: 'Schedule', value: 'Every Friday at 4:00 PM' },
        { label: 'Delivered', value: 'Today at 4:07 PM' },
      ],
      actions: [{ label: 'Review Ally routines', href: '/allies/sample/settings/routines' }],
    },
  },
  settings: {
    preferences: {
      family: 'settings', id: 'preferences', title: 'Preferences',
      summary: 'Choose how Allies looks and when the app should get your attention.',
      status: 'Visual preview', tone: 'orange',
      details: [
        { label: 'Appearance', value: 'Light', note: 'Dark mode will follow the same calm visual language.' },
        { label: 'Notifications', value: 'On', note: 'One simple account-wide control.' },
        { label: 'Motion', value: 'Follow device setting' },
      ],
      actions: [{ label: 'Save preferences · Preview', disabled: true }],
    },
    connections: {
      family: 'settings', id: 'connections', title: 'Connections',
      summary: 'Connect services once, then decide which Allies may use them.',
      status: 'Visual preview', tone: 'blue',
      details: [
        { label: 'Google Workspace', value: 'Not connected', note: 'Calendar, Gmail, and Drive.' },
        { label: 'Slack', value: 'Not connected' },
        { label: 'Notion', value: 'Not connected' },
      ],
      actions: [
        { label: 'Google Workspace', href: '/settings/connection/google-workspace' },
        { label: 'Slack', href: '/settings/connection/slack' },
        { label: 'Notion', href: '/settings/connection/notion' },
      ],
    },
    usage: {
      family: 'settings', id: 'usage', title: 'Usage and billing',
      summary: 'See the account-wide seven-day window without turning useful work into a token dashboard.',
      status: 'Visual preview', tone: 'purple',
      details: [
        { label: 'Current window', value: 'Monday to Sunday' },
        { label: 'Plan', value: 'Internal preview' },
        { label: 'Billing', value: 'No payment method required yet' },
      ],
      progress: { value: 0.42, label: '42% of this week used', note: 'Work already running is allowed to finish.' },
      actions: [{ label: 'Preview limit reached', href: '/settings/usage-limit' }],
    },
    'usage-limit': {
      family: 'settings', id: 'usage-limit', title: 'This week is fully used',
      summary: 'Your active work can finish. New work starts when the next seven-day window begins.',
      status: 'Limit reached', tone: 'orange',
      details: [
        { label: 'Next window', value: 'Monday at 12:00 AM' },
        { label: 'Active work', value: 'Allowed to finish' },
        { label: 'New work', value: 'Available next window' },
      ],
      progress: { value: 1, label: '100% of this week used', note: 'Usage is measured after useful work completes.' },
    },
    privacy: {
      family: 'settings', id: 'privacy', title: 'Privacy and sessions',
      summary: 'Understand your data and the devices that can access your account.',
      status: 'Visual preview', tone: 'green',
      details: [
        { label: 'Data export', value: 'Prepare a copy of your Allies information' },
        { label: 'Privacy', value: 'Review how account data is used' },
        { label: 'Sessions', value: '2 signed-in devices' },
      ],
      actions: [{ label: 'Review sessions', href: '/settings/sessions' }],
    },
    sessions: {
      family: 'settings', id: 'sessions', title: 'Signed-in devices',
      summary: 'Review where your Allies account is currently available.',
      status: 'Visual preview', tone: 'green',
      details: [
        { label: 'This Android phone', value: 'Active now', note: 'Lagos, Nigeria' },
        { label: 'Chrome on Windows', value: 'Last active 2 hours ago' },
      ],
      actions: [{ label: 'End other sessions · Preview', disabled: true }],
    },
    'screen-map': {
      family: 'settings', id: 'screen-map', title: 'App screen map',
      summary: 'Walk through every planned mobile destination from one place.',
      status: 'Product preview', tone: 'orange',
      details: [
        { label: 'M2', value: 'Workspace, Create Ally, conversation, and identity' },
        { label: 'M3', value: 'Activity, Settings, Profile, connections, responsibilities, and routines' },
        { label: 'M4', value: 'Approvals, usage limits, failures, recovery, receipts, and deletion' },
      ],
      actions: [
        { label: 'Activity result', href: '/activity/result' },
        { label: 'Approval request', href: '/activity/approval' },
        { label: 'Critical failure', href: '/activity/failure' },
        { label: 'Preferences', href: '/settings/preferences' },
        { label: 'Connections', href: '/settings/connections' },
        { label: 'Usage and billing', href: '/settings/usage' },
        { label: 'Privacy and sessions', href: '/settings/privacy' },
        { label: 'Ally settings', href: '/allies/sample/settings' },
        { label: 'Delete Ally', href: '/allies/sample/settings/delete' },
      ],
    },
  },
  connection: {
    'google-workspace': {
      family: 'connection', id: 'google-workspace', title: 'Google Workspace',
      summary: 'Connect Calendar, Gmail, and Drive, then choose which Allies may use them.',
      status: 'Not connected', tone: 'blue',
      details: [
        { label: 'Calendar', value: 'Read and update events with approval when needed' },
        { label: 'Gmail', value: 'Read and draft messages within granted access' },
        { label: 'Drive', value: 'Find and create files within granted access' },
        { label: 'Ally access', value: 'No Allies have access yet' },
      ],
      actions: [{ label: 'Connect Google · Preview', disabled: true }],
    },
    slack: {
      family: 'connection', id: 'slack', title: 'Slack',
      summary: 'Let selected Allies read or post in approved workspaces and channels.',
      status: 'Not connected', tone: 'purple',
      details: [
        { label: 'Workspace', value: 'No workspace selected' },
        { label: 'Channel access', value: 'Granted per Ally' },
        { label: 'Ally access', value: 'No Allies have access yet' },
      ],
      actions: [{ label: 'Connect Slack · Preview', disabled: true }],
    },
    notion: {
      family: 'connection', id: 'notion', title: 'Notion',
      summary: 'Choose the pages selected Allies may read and update.',
      status: 'Not connected', tone: 'orange',
      details: [
        { label: 'Pages', value: 'No pages shared' },
        { label: 'Write access', value: 'Requires explicit access' },
        { label: 'Ally access', value: 'No Allies have access yet' },
      ],
      actions: [{ label: 'Connect Notion · Preview', disabled: true }],
    },
  },
  ally: {
    identity: {
      family: 'ally', id: 'identity', title: 'Ally identity',
      summary: 'Keep the parts that make this Ally recognizable and useful.',
      status: 'Visual preview', tone: 'red',
      details: [
        { label: 'Name', value: 'Sally' },
        { label: 'Job', value: 'Help me run my small business and stay on top of the work that matters.' },
        { label: 'Personality', value: 'Concise, warm, and willing to challenge unclear decisions.' },
        { label: 'Avatar', value: 'Rolly · red' },
      ],
      actions: [{ label: 'Save identity · Preview', disabled: true }],
    },
    responsibilities: {
      family: 'ally', id: 'responsibilities', title: 'Responsibilities',
      summary: 'Review the ongoing work Sally has learned to own through conversation.',
      status: 'Conversation-led', tone: 'red',
      details: [
        { label: 'Cash position', value: 'Keep the weekly cash position current and point out unusual changes.' },
        { label: 'Customer follow-up', value: 'Keep important customer commitments from being forgotten.' },
      ],
      actions: [{ label: 'Discuss in conversation', href: '/allies' }],
    },
    routines: {
      family: 'ally', id: 'routines', title: 'Routines',
      summary: 'Review recurring work Sally proposed and you accepted in conversation.',
      status: 'Visual preview', tone: 'purple',
      details: [
        { label: 'Weekly cash review', value: 'Every Friday at 4:00 PM', note: 'Last run completed today.' },
        { label: 'Monday priorities', value: 'Every Monday at 8:30 AM', note: 'Next run in 3 days.' },
      ],
      actions: [{ label: 'Discuss in conversation', href: '/allies' }],
    },
    access: {
      family: 'ally', id: 'access', title: 'Sally’s access',
      summary: 'See which account connections this Ally may use for its job.',
      status: 'Visual preview', tone: 'blue',
      details: [
        { label: 'Google Calendar', value: 'Allowed with approval for consequential changes' },
        { label: 'Gmail', value: 'Not allowed' },
        { label: 'Drive', value: 'Allowed for the Business folder' },
      ],
      actions: [{ label: 'Change access · Preview', disabled: true }],
    },
    delete: {
      family: 'ally', id: 'delete', title: 'Delete Sally',
      summary: 'Deleting an Ally removes its conversation, memory, files, routines, and connection access.',
      status: 'Destructive preview', tone: 'red',
      details: [
        { label: 'Confirmation', value: 'Type “delete Sally”' },
        { label: 'Safety timer', value: '3 seconds after the exact phrase' },
        { label: 'Recovery', value: 'No recovery or trash in the current product direction' },
      ],
      actions: [{ label: 'Delete Sally · Not connected', disabled: true }],
    },
  },
};

export const activityItems = ['result', 'waiting', 'approval', 'failure', 'routine']
  .map((id) => screens.activity[id]);

export function getPreviewScreen(family: PreviewFamily, id: string): PreviewScreen | null {
  return screens[family][id] ?? null;
}

export function getAllPreviewScreens(): PreviewScreen[] {
  return Object.values(screens).flatMap((family) => Object.values(family));
}
