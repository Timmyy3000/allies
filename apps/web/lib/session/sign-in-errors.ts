import { isCloudError } from "@allies/cloud-client";

export function googleSignInErrorMessage(error: unknown): string {
  if (isCloudError(error)) {
    if (error.code === "provider_unavailable" || error.kind === "not-found") {
      return "Google sign-in is temporarily unavailable. Try again.";
    }
    if (error.kind === "security") {
      return "We couldn't start sign-in securely. Try again.";
    }
    if (error.kind === "network" || error.kind === "server" || error.kind === "timeout") {
      return "Allies couldn't reach sign-in. Check your connection and try again.";
    }
  }

  return "We couldn't start sign-in. Try again.";
}
