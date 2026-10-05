import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { CHAT_FRAME_IDS } from "../../app/(debug)/chat-frames/chat-frame-fixtures";

type JsonObject = Record<string, unknown>;
type Bounds = { x: number; y: number; width: number; height: number };
type ManifestFrame = {
  nodeId: string;
  name: string;
  normalizedText: string[];
  bounds: { frame: Bounds; header: Bounds; contentRail: Bounds; composer: Bounds; [key: string]: Bounds };
  typography: JsonObject;
  colors: JsonObject;
  radii: JsonObject;
  clipping: JsonObject;
  expectedSnapshot: string;
  assets: JsonObject[];
  unresolvedReasons: JsonObject[];
  evidenceSha256: string;
};

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const manifestPath = resolve(testsDirectory, "chat-frame-visual-manifest.json");
const manifestHashPath = resolve(testsDirectory, "chat-frame-visual-manifest.sha256");
const signoffPath = resolve(testsDirectory, "chat-frame-baseline-signoff.json");
const mode = process.argv.find((argument) => argument.startsWith("--mode="))?.slice("--mode=".length) ?? "signoff";
const expectedImportId = "df3eb62c0b54964800ee8dbc6ae2927bdb6b22c86c0f0b5a2364d5d9779f491b";
const expectedExcludedId = "315:1827";

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => [key, canonicalize(entry)]),
  );
}

function withoutEvidence(frame: ManifestFrame): JsonObject {
  const payload = { ...frame };
  delete (payload as { evidenceSha256?: string }).evidenceSha256;
  return payload;
}

function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(canonicalize(value)), "utf8").digest("hex");
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

function fail(message: string): never {
  throw new Error(`[chat-frame-manifest] ${message}`);
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) fail(message);
}

function safeRelativePath(path: string): boolean {
  return path.length > 0
    && !path.includes("..")
    && !/^(?:[a-z]:[\\/]|[\\/]|file:|https?:)/i.test(path)
    && !/\.fig\b|\.aphrodite[\\/]|[\\/]Users[\\/]|Downloads/i.test(path);
}

function assertBounds(bounds: unknown, expected: Partial<Bounds>, label: string): asserts bounds is Bounds {
  assert(bounds && typeof bounds === "object", `${label} bounds are missing`);
  for (const [key, value] of Object.entries(expected)) {
    assert((bounds as Record<string, unknown>)[key] === value, `${label}.${key} must be ${value}`);
  }
}

function assertAsset(asset: JsonObject, label: string, signoff: boolean) {
  assert(typeof asset.canonicalNodeId === "string" && asset.canonicalNodeId.length > 0, `${label} is missing canonicalNodeId`);
  assert(typeof asset.kind === "string" && asset.kind.length > 0, `${label} is missing kind`);
  assert(typeof asset.rawReference === "string" && asset.rawReference.length > 0, `${label} is missing rawReference`);
  assert(typeof asset.diagnosticStatus === "string", `${label} is missing diagnosticStatus`);
  const dispositions = ["tracked-copy", "verified-reuse", "masked-os-chrome", "css-native-substitution"]
    .filter((key) => key in asset);
  assert(dispositions.length === 1, `${label} must have exactly one disposition`);
  assert(safeRelativePath(String(asset.rawReference)), `${label} contains a private/source path`);
  if (!signoff) return;
  if (dispositions[0] === "tracked-copy" || dispositions[0] === "verified-reuse") {
    assert(typeof asset.path === "string" && safeRelativePath(asset.path), `${label} needs a safe repository path`);
    assert(typeof asset.sha256 === "string" && /^[a-f0-9]{64}$/.test(asset.sha256), `${label} needs a byte SHA-256`);
  }
  if (dispositions[0] === "masked-os-chrome") {
    assert(asset.mask && typeof asset.mask === "object", `${label} needs an exact mask rectangle`);
    assert(typeof asset.rationale === "string" && asset.rationale.length > 0, `${label} needs a mask rationale`);
  }
  if (dispositions[0] === "css-native-substitution") {
    assert(typeof asset.implementation === "string" && asset.implementation.length > 0, `${label} needs an implementation reference`);
    assert(typeof asset.approver === "string" && asset.approver.length > 0, `${label} needs an approver`);
    assert(typeof asset.approvedAt === "string" && !Number.isNaN(Date.parse(asset.approvedAt)), `${label} needs an approval timestamp`);
    assert(typeof asset.approvalReference === "string" && asset.approvalReference.length > 0, `${label} needs an approval reference`);
  }
}

function main() {
  assert(mode === "prebaseline" || mode === "signoff", `unknown mode ${mode}`);
  const manifest = readJson<JsonObject>(manifestPath);
  const frames = manifest.frames;
  assert(manifest.schemaVersion === 1, "schemaVersion must be 1");
  assert(manifest.source && typeof manifest.source === "object", "source identity is missing");
  const source = manifest.source as JsonObject;
  assert(source.provider === "aphrodite", "provider must be aphrodite");
  assert(source.alias === "handoff", "alias must be handoff");
  assert(source.importId === expectedImportId, "immutable Aphrodite import ID changed");
  assert(source.figmaFormat === 106, "Figma format must be 106");
  assert(source.page === "product", "source page must be product");
  assert(JSON.stringify(manifest.referenceViewport) === JSON.stringify({ width: 375, height: 812 }), "reference viewport must be 375x812");
  assert(JSON.stringify(manifest.excludedFrameIds) === JSON.stringify([expectedExcludedId]), "keyboard frame exclusion changed");
  assert(Array.isArray(frames), "frames must be an array");
  assert(frames.length === CHAT_FRAME_IDS.length, "manifest must contain exactly 25 frames");

  const frameRecords = frames as ManifestFrame[];
  const manifestIds = frameRecords.map((frame) => frame.nodeId);
  assert(new Set(manifestIds).size === manifestIds.length, "manifest contains duplicate frame IDs");
  assert(!manifestIds.includes(expectedExcludedId), "excluded keyboard frame must not be in the manifest");
  assert(JSON.stringify([...manifestIds].sort()) === JSON.stringify([...CHAT_FRAME_IDS].sort()), "manifest and fixture frame IDs differ");

  const manifestText = readFileSync(manifestPath, "utf8");
  assert(!/\.fig\b|\.aphrodite[\\/]|[\\/]Users[\\/]|Downloads|file:\/\//i.test(manifestText), "manifest contains a private/source path");
  for (const frame of frameRecords) {
    const label = `frame ${frame.nodeId}`;
    assert(typeof frame.name === "string" && frame.name.length > 0, `${label} is missing a name`);
    assert(Array.isArray(frame.normalizedText) && frame.normalizedText.every((line) => typeof line === "string" && line.trim()), `${label} needs normalized content lines`);
    assertBounds(frame.bounds?.frame, { x: 0, y: 0, width: 375, height: 812 }, `${label}.frame`);
    assertBounds(frame.bounds?.header, { x: 0, y: 0, width: 375 }, `${label}.header`);
    assertBounds(frame.bounds?.contentRail, { x: 20, width: 335 }, `${label}.contentRail`);
    assertBounds(frame.bounds?.composer, { x: 20, y: 706, width: 335, height: 48 }, `${label}.composer`);
    assert(frame.typography && typeof frame.typography.fontFamily === "string", `${label} typography is missing`);
    assert(frame.colors && typeof frame.colors.background === "string" && typeof frame.colors.ink === "string", `${label} colors are missing`);
    assert(frame.radii && typeof frame.radii === "object", `${label} radii are missing`);
    assert(frame.clipping && typeof frame.clipping === "object", `${label} clipping facts are missing`);
    assert(typeof frame.expectedSnapshot === "string" && safeRelativePath(frame.expectedSnapshot), `${label} has an invalid snapshot path`);
    assert(frame.expectedSnapshot.endsWith(`chat-frame-${frame.nodeId.replace(":", "-")}.png`), `${label} snapshot does not identify its node`);
    assert(Array.isArray(frame.assets), `${label} assets must be an array`);
    assert(Array.isArray(frame.unresolvedReasons), `${label} unresolvedReasons must be an array`);
    for (const [index, asset] of frame.assets.entries()) assertAsset(asset, `${label} asset ${index}`, mode === "signoff");
    assert(frame.evidenceSha256 !== "PENDING" && /^[a-f0-9]{64}$/.test(frame.evidenceSha256), `${label} evidenceSha256 is missing or invalid`);
    assert(frame.evidenceSha256 === digest({ importId: expectedImportId, frame: withoutEvidence(frame) }), `${label} evidenceSha256 does not match canonical evidence`);
  }

  const manifestForHash = { ...manifest, frames: frameRecords.map(withoutEvidence) };
  const manifestSha256 = digest(manifestForHash);
  assert(existsSync(manifestHashPath), "manifest checksum file is missing");
  assert(readFileSync(manifestHashPath, "utf8").trim() === manifestSha256, "manifest checksum does not match canonical JSON");

  const signoff = readJson<JsonObject>(signoffPath);
  const captures = signoff.captures;
  assert(Array.isArray(captures) && captures.length === frameRecords.length, "sign-off must contain 25 capture slots");
  assert(JSON.stringify((captures as JsonObject[]).map((capture) => capture.frameId).sort()) === JSON.stringify([...CHAT_FRAME_IDS].sort()), "sign-off capture IDs differ from fixtures");
  for (const capture of captures as JsonObject[]) {
    assert(typeof capture.path === "string" && safeRelativePath(capture.path), `capture ${String(capture.frameId)} has an invalid path`);
    assert(typeof capture.sha256 === "string" || capture.sha256 === null, `capture ${String(capture.frameId)} has an invalid hash slot`);
  }

  if (mode === "prebaseline") {
    const exception = signoff.provisionalException as JsonObject | undefined;
    assert(exception?.status === "accepted", "provisional sign-off exception must be accepted");
    assert(typeof exception.owner === "string" && exception.owner.length > 0, "provisional exception needs an owner");
    assert(typeof exception.reason === "string" && exception.reason.length > 0, "provisional exception needs a reason");
    assert(typeof exception.revisit === "string" && exception.revisit.length > 0, "provisional exception needs a revisit condition");
    assert(typeof exception.reference === "string" && safeRelativePath(exception.reference), "provisional exception needs a safe repository reference");
  }

  if (mode === "signoff") {
    assert(manifest.evidenceStatus === "complete", "sign-off requires complete Aphrodite evidence");
    assert(Array.isArray(manifest.unresolvedReasons) && manifest.unresolvedReasons.length === 0, "sign-off has unresolved manifest evidence");
    assert(frameRecords.every((frame) => frame.unresolvedReasons.length === 0), "sign-off has unresolved frame evidence");
    assert(frameRecords.every((frame) => frame.assets.length > 0), "sign-off requires material asset dispositions for every frame");
    assert(signoff.manifestSha256 === manifestSha256, "sign-off manifest checksum is stale");
    assert(signoff.sourceImportId === expectedImportId, "sign-off source identity changed");
    assert(typeof signoff.implementationCommit === "string" && !signoff.implementationCommit.startsWith("TBD_"), "sign-off implementation commit is missing");
    assert(typeof signoff.baselineApprover === "string" && !signoff.baselineApprover.startsWith("TBD_"), "sign-off approver is still the sentinel");
    assert(typeof signoff.approvedAt === "string" && !Number.isNaN(Date.parse(signoff.approvedAt)), "sign-off timestamp is missing");
    assert(typeof signoff.approvalReference === "string" && /^https?:\/\//.test(signoff.approvalReference), "sign-off approval reference is missing");
    assert(signoff.runtime && JSON.stringify(signoff.runtime) === JSON.stringify({ playwright: "1.62.1", chromium: { browserVersion: "151.0.7922.34", revision: "1234" } }), "sign-off runtime fingerprint changed");
    for (const capture of captures as JsonObject[]) {
      assert(typeof capture.sha256 === "string" && /^[a-f0-9]{64}$/.test(capture.sha256), `capture ${String(capture.frameId)} has no approved hash`);
      const capturePath = resolve(testsDirectory, capture.path as string);
      assert(existsSync(capturePath), `approved capture is missing: ${capture.path}`);
      assert(createHash("sha256").update(readFileSync(capturePath)).digest("hex") === capture.sha256, `approved capture hash does not match: ${capture.path}`);
    }
  }

  console.log(`[chat-frame-manifest] ${mode} verification passed for ${frameRecords.length} frames (${manifestSha256})`);
  if (mode === "prebaseline") {
    console.log(`[chat-frame-manifest] provisional evidence: ${JSON.stringify(manifest.unresolvedReasons)}`);
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
