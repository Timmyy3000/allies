import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const directory = path.resolve("packages/cloud-client/openapi");
const canonicalSource = "https://cloud.staging.yourallies.io/api/v1/openapi.json";
const bytes = await readFile(path.join(directory, "allies-cloud-0.1.0.json"));
const metadata = JSON.parse(await readFile(path.join(directory, "metadata.json"), "utf8")) as {
  source: string;
  sourceRevision?: string;
  sourceDirty?: boolean;
  retrievedAt: string;
  title: string;
  version: string;
  byteLength: number;
  sha256: string;
  generators: { "openapi-typescript": string };
};
const rootPackage = JSON.parse(await readFile(path.resolve("package.json"), "utf8")) as {
  devDependencies?: Record<string, string>;
};
const schema = JSON.parse(bytes.toString("utf8")) as {
  info?: { title?: unknown; version?: unknown };
};
const hash = createHash("sha256").update(bytes).digest("hex");
const isIsoDate = /^\d{4}-\d{2}-\d{2}$/.test(metadata.retrievedAt) &&
  new Date(`${metadata.retrievedAt}T00:00:00.000Z`).toISOString().startsWith(metadata.retrievedAt);
const validSource = metadata.source === canonicalSource || (
  metadata.source === "https://github.com/Timmyy3000/allies"
  && /^[0-9a-f]{40}$/.test(metadata.sourceRevision ?? "")
  && metadata.sourceDirty === false
);

if (
  !validSource ||
  !isIsoDate ||
  metadata.title !== "Allies Cloud API" ||
  metadata.version !== "0.1.0" ||
  schema.info?.title !== metadata.title ||
  schema.info.version !== metadata.version ||
  metadata.byteLength !== bytes.byteLength ||
  metadata.sha256 !== hash ||
  metadata.generators["openapi-typescript"] !== rootPackage.devDependencies?.["openapi-typescript"]
) {
  throw new Error("Pinned Cloud schema does not match its metadata");
}

console.log(`Verified ${metadata.title} ${metadata.version} (${hash})`);
