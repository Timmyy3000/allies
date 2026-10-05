import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

type FileEntry = {
  absolutePath: string;
  relativePath: string;
};

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const buildRoot = path.join(appRoot, ".next");

const manifestPath = path.join(appRoot, "tests", "chat-frames", "chat-frame-visual-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as {
  frames: Array<{ nodeId: string }>;
};

const forbiddenTokens = [
  "chat-frame-fixtures",
  "chat-frame-preview",
  "debug-conversation-frame",
  "chat-frame-debug",
  "(debug)/chat-frames",
  "data-frame-id",
  "/chat-frames?frame=",
  ...manifest.frames.map((frame) => frame.nodeId),
];

async function collectTextFiles(root: string): Promise<FileEntry[]> {
  const entries: FileEntry[] = [];

  async function visit(directory: string) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolutePath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(absolutePath);
        continue;
      }

      if (!/\.(?:css|html|js|json|map|txt)$/.test(entry.name)) continue;
      entries.push({
        absolutePath,
        relativePath: path.relative(buildRoot, absolutePath).replaceAll(path.sep, "/"),
      });
    }
  }

  await visit(root);
  return entries;
}

async function requireDirectory(directory: string) {
  try {
    if (!(await stat(directory)).isDirectory()) throw new Error("not a directory");
  } catch {
    throw new Error(`Production build output is missing: ${directory}`);
  }
}

await requireDirectory(buildRoot);
await requireDirectory(path.join(buildRoot, "server"));
await requireDirectory(path.join(buildRoot, "static"));

const emittedFiles = [
  ...(await collectTextFiles(path.join(buildRoot, "server"))),
  ...(await collectTextFiles(path.join(buildRoot, "static"))),
];
const violations: string[] = [];

for (const file of emittedFiles) {
  const text = await readFile(file.absolutePath, "utf8");
  for (const token of forbiddenTokens) {
    if (text.includes(token)) {
      violations.push(`${file.relativePath} contains ${JSON.stringify(token)}`);
    }
  }
}

const serverManifestFiles = emittedFiles.filter(
  (file) => file.relativePath.startsWith("server/") && file.relativePath.endsWith("manifest.json"),
);
for (const file of serverManifestFiles) {
  const text = await readFile(file.absolutePath, "utf8");
  if (text.includes("chat-frames")) {
    violations.push(`${file.relativePath} exposes the debug chat-frame route`);
  }
}

if (violations.length > 0) {
  throw new Error(
    [
      "Production bundle boundary failed; synthetic chat-frame code or route metadata was emitted:",
      ...violations,
    ].join("\n"),
  );
}

console.log(`Production bundle boundary passed (${emittedFiles.length} emitted text files inspected).`);
