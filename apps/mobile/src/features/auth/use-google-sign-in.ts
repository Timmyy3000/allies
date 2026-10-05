import { useNativeSession } from '../../lib/session/session-context';

export function useGoogleSignIn() {
  const session = useNativeSession();
  const { cancelGoogleSignIn, startGoogleSignIn, submitGoogleSignInCode } = session;

  return {
    cancel: cancelGoogleSignIn,
    isAvailable: Boolean(session.client && session.nativeAuthRedirectUri)
      && session.status !== 'checking'
      && session.status !== 'refreshing',
    isBusy: session.googleSignInStatus !== 'idle',
    isManual: session.nativeAuthCompletionMode === 'manual_code',
    manualCodeError: session.googleSignInManualCodeError,
    outcome: session.googleSignInOutcome,
    start: startGoogleSignIn,
    status: session.googleSignInStatus,
    submitManualCode: submitGoogleSignInCode,
  };
}
