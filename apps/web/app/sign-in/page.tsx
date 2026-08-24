import { SignInClient } from "./sign-in-client";
import { selectAuthReturnTo } from "../../lib/session/auth-route-query";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function SignInPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const returnTo = typeof params.returnTo === "string" ? params.returnTo : undefined;

  return <SignInClient returnTo={selectAuthReturnTo(returnTo)} />;
}
