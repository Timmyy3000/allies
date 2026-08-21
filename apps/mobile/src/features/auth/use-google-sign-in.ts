import { useCallback, useMemo, useState } from 'react';

import { useNativeSession } from '@/lib/session/session-context';

import {
  createGoogleSignInFlow,
  type GoogleSignInFlowStatus,
  type GoogleSignInOutcome,
} from './google-sign-in';

export function useGoogleSignIn() {
  const session = useNativeSession();
  const [status, setStatus] = useState<GoogleSignInFlowStatus>('idle');
  const [outcome, setOutcome] = useState<GoogleSignInOutcome | null>(null);
  const flow = useMemo(() => {
    if (!session.client || !session.nativeAuthRedirectUri) return null;

    return createGoogleSignInFlow({
      client: session.client,
      completeSignIn: session.completeSignIn,
      onStatusChange: setStatus,
      redirectUri: session.nativeAuthRedirectUri,
    });
  }, [session.client, session.completeSignIn, session.nativeAuthRedirectUri]);

  const start = useCallback(async () => {
    setOutcome(null);
    if (!flow) {
      const unavailable: GoogleSignInOutcome = { status: 'failed', reason: 'unavailable' };
      setOutcome(unavailable);
      return unavailable;
    }

    const nextOutcome = await flow.start();
    setOutcome(nextOutcome);
    return nextOutcome;
  }, [flow]);

  return {
    isAvailable: Boolean(flow) && session.status !== 'checking' && session.status !== 'refreshing',
    isBusy: status !== 'idle',
    outcome,
    start,
    status,
  };
}
