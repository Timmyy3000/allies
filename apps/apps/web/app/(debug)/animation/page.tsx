import { notFound } from "next/navigation";
import AnimationPlayground from "./animation-playground";

function isDebugEnvironment() {
  if (process.env.NODE_ENV !== "production") return true;

  const deploymentEnvironment = (
    process.env.VERCEL_ENV ??
    process.env.NEXT_PUBLIC_ENVIRONMENT ??
    process.env.NEXT_PUBLIC_APP_ENV ??
    process.env.APP_ENV ??
    ""
  ).toLowerCase();

  return deploymentEnvironment === "preview" || deploymentEnvironment === "staging";
}

export default function AnimationDebugPage() {
  if (!isDebugEnvironment()) notFound();

  return <AnimationPlayground />;
}
