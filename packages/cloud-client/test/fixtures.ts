import type { paths } from "../src/generated/openapi";

type ContractOperation = { responses: Record<PropertyKey, unknown> };
type MethodFor<Path extends keyof paths> = {
  [Method in keyof paths[Path]]-?: NonNullable<paths[Path][Method]> extends ContractOperation
    ? Method
    : never;
}[keyof paths[Path]];
type ResponsesFor<Path extends keyof paths, Method extends MethodFor<Path>> =
  NonNullable<paths[Path][Method]> extends { responses: infer Responses } ? Responses : never;
type PayloadFor<Response> = Response extends {
  content: { "application/json": infer Body };
} ? Body : undefined;

export function defineApiFixture<
  Path extends keyof paths,
  Method extends MethodFor<Path>,
  Status extends keyof ResponsesFor<Path, Method>,
>(path: Path, method: Method, status: Status, body: PayloadFor<ResponsesFor<Path, Method>[Status]>) {
  return { path, method, status, body } as const;
}
