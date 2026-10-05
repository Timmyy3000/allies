import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const localFile = process.env.ALLIES_CLOUD_OPENAPI_FILE;
const sourceRevision = process.env.ALLIES_CLOUD_OPENAPI_REVISION;
if (localFile && !/^[0-9a-f]{40}$/.test(sourceRevision ?? "")) {
  throw new Error("A local Cloud schema requires its source commit");
}
const source = localFile ? "https://github.com/alliesai/allies-cloud" : "https://cloud.staging.yourallies.io/api/v1/openapi.json";
const fetchUrl = process.env.ALLIES_CLOUD_OPENAPI_FETCH_URL ?? source;
const targetDirectory = path.resolve("packages/cloud-client/openapi");
const schemaPath = path.join(targetDirectory, "allies-cloud-0.1.0.json");
const metadataPath = path.join(targetDirectory, "metadata.json");

const bytes = localFile ? await readFile(localFile) : await (async () => {
  const response = await fetch(fetchUrl, { headers: { accept: "application/json" }, redirect: "error" });
  if (!response.ok) throw new Error(`Cloud schema request failed with HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
})();
const schema = JSON.parse(new TextDecoder().decode(bytes)) as {
  info?: { title?: unknown; version?: unknown };
  paths?: unknown;
};

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, canonicalize(child)]),
  );
}

if (
  schema.info?.title !== "Allies Cloud API" ||
  schema.info.version !== "0.1.0" ||
  typeof schema.paths !== "object" ||
  schema.paths === null
) {
  throw new Error("Cloud schema identity does not match Allies Cloud API 0.1.0");
}

const rootPackage = JSON.parse(await readFile(path.resolve("package.json"), "utf8")) as {
  devDependencies?: Record<string, string>;
};

await mkdir(targetDirectory, { recursive: true });
const pinnedBytes = new TextEncoder().encode(`${JSON.stringify(canonicalize(schema), null, 2)}\n`);
await writeFile(schemaPath, pinnedBytes);
await writeFile(
  metadataPath,
  `${JSON.stringify(
    {
      source,
      ...(localFile ? { sourceRevision, sourceDirty: process.env.ALLIES_CLOUD_OPENAPI_DIRTY === "true" } : {}),
      retrievedAt: new Date().toISOString().slice(0, 10),
      title: schema.info.title,
      version: schema.info.version,
      byteLength: pinnedBytes.byteLength,
      sha256: createHash("sha256").update(pinnedBytes).digest("hex"),
      generators: {
        "openapi-typescript": rootPackage.devDependencies?.["openapi-typescript"],
      },
    },
    null,
    2,
  )}\n`,
);

console.log(`Pinned ${schema.info.title} ${schema.info.version} (${pinnedBytes.byteLength} bytes)`);
