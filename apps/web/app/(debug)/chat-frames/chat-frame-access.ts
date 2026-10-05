export interface ChatFrameServerEnvironment {
  nodeEnv?: string;
  deploymentEnvironment?: string;
}

export function canAccessChatFrames(
  environment: ChatFrameServerEnvironment = {
    nodeEnv: process.env.NODE_ENV,
    deploymentEnvironment: process.env.VERCEL_ENV
      ?? process.env.APP_ENV
      ?? process.env.NEXT_PUBLIC_ENVIRONMENT,
  },
): boolean {
  if (environment.nodeEnv !== "development") return false;
  const deployment = environment.deploymentEnvironment?.trim().toLowerCase();
  return !deployment || deployment === "local" || deployment === "development";
}
