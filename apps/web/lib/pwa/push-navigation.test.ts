import { expect, it } from "vitest";
import { pushReturnPath } from "./push-navigation";
const ally = "00000000-0000-4000-8000-000000000001";
const workspace = "00000000-0000-4000-8000-000000000002";
const conversation = "00000000-0000-4000-8000-000000000003";
it("preserves a signed-out notification journey through the landing returnTo query", () => {
  const target = `/home/${ally}?push_workspace=${workspace}&push_conversation=${conversation}`;
  const landing = `/?returnTo=${encodeURIComponent(pushReturnPath(target)!)}`;
  expect(pushReturnPath(new URL(landing, "https://allies.example").searchParams.get("returnTo"))).toBe(target);
  for (const unsafe of ["https://evil.example/home/" + ally, "//evil.example/", "/home/" + ally + "?push_workspace=bad", target + "&url=https://evil.example", target + "#private", "/home/%2e%2e/account"]) expect(pushReturnPath(unsafe)).toBeNull();
});
