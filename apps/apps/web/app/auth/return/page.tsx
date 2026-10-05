import {
  AuthReturnClient,
} from "./auth-return-client";
import {
  selectAuthError,
  selectAuthReturnTo,
} from "../../../lib/session/auth-route-query";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function AuthReturnPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const returnTo = typeof params.returnTo === "string" ? params.returnTo : undefined;
  const authError = typeof params.auth_error === "string" ? params.auth_error : undefined;

  return (
    <AuthReturnClient
      returnTo={selectAuthReturnTo(returnTo)}
      errorCode={selectAuthError(authError)}
    />
  );
}
