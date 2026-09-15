import { ClaimInviteClient } from "./claim-invite-client";
import { selectAuthReturnTo } from "../../lib/session/auth-route-query";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ClaimInvitePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const returnTo = typeof params.returnTo === "string" ? params.returnTo : undefined;

  return <ClaimInviteClient returnTo={selectAuthReturnTo(returnTo)} />;
}
