export const WAITLIST_APPEARANCE_CATALOG_VERSION = "v1" as const;

export const WAITLIST_SHAPES = ["boxy", "ghosty", "rocky", "rolly"] as const;
export type WaitlistShape = (typeof WAITLIST_SHAPES)[number];

export const WAITLIST_COLORS = [
  "#ff5800",
  "#fd304f",
  "#0d92fd",
  "#be9bf5",
  "#3446e9",
  "#a3f06f",
  "#fbe65f",
] as const;

export const WAITLIST_PERSONALITIES = ["Concise", "Quirky", "Analytical", "Funny"] as const;
export const WAITLIST_PERSONALITY_NOTE_LIMIT = 200;
export const WAITLIST_CLOUD_TEXT_LIMIT = 1_200;

export interface WaitlistConfigurationInput {
  name: string;
  shape: string;
  color: string | null;
  job: string;
  personalities: readonly string[];
  personalityNote: string;
  personalityOverride?: string;
}

export interface WaitlistConfigurationPayload {
  name: string;
  appearance_catalog_version: typeof WAITLIST_APPEARANCE_CATALOG_VERSION;
  appearance_key: string;
  job: string;
  personality?: string;
}

export class WaitlistMappingError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WaitlistMappingError";
    this.code = code;
  }
}

function normalizeColor(value: string | null): string {
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) {
    throw new WaitlistMappingError("appearance_color_invalid", "Choose an Ally colour.");
  }
  const normalized = value.toLowerCase();
  if (!WAITLIST_COLORS.includes(normalized as (typeof WAITLIST_COLORS)[number])) {
    throw new WaitlistMappingError("appearance_color_unknown", "Choose a supported Ally colour.");
  }
  return normalized.slice(1);
}

function normalizeShape(value: string): WaitlistShape {
  if (!WAITLIST_SHAPES.includes(value as WaitlistShape)) {
    throw new WaitlistMappingError("appearance_shape_unknown", "Choose a supported Ally shape.");
  }
  return value as WaitlistShape;
}

export function serializeAppearance(shape: string, color: string | null): {
  appearance_catalog_version: typeof WAITLIST_APPEARANCE_CATALOG_VERSION;
  appearance_key: string;
} {
  const normalizedShape = normalizeShape(shape);
  const normalizedColor = normalizeColor(color);
  return {
    appearance_catalog_version: WAITLIST_APPEARANCE_CATALOG_VERSION,
    appearance_key: `${normalizedShape}:${normalizedColor}`,
  };
}

export function serializePersonality(
  personalities: readonly string[],
  note: string,
): string | undefined {
  const selected = new Set(personalities);
  const traits = WAITLIST_PERSONALITIES.filter((trait) => selected.has(trait));
  const trimmedNote = note.trim();
  const value = [
    traits.length > 0 ? traits.join(", ") : "",
    trimmedNote.length > 0 ? `Note: ${trimmedNote}` : "",
  ]
    .filter(Boolean)
    .join(". ");

  if (value.length === 0) return undefined;
  if (value.length > WAITLIST_CLOUD_TEXT_LIMIT) {
    throw new WaitlistMappingError("personality_too_long", "Keep the Ally personality shorter.");
  }
  return value;
}

export function parsePersonality(value: string | null): { personalities: string[]; personalityNote: string } {
  if (!value) return { personalities: [], personalityNote: "" };
  if (value.startsWith("Note: ")) {
    return { personalities: [], personalityNote: value.slice("Note: ".length).trim() };
  }

  const [traitPart, ...noteParts] = value.split(". Note: ");
  const personalities = traitPart
    .split(", ")
    .filter((trait) => WAITLIST_PERSONALITIES.includes(trait as (typeof WAITLIST_PERSONALITIES)[number]));
  const personalityNote = noteParts.length > 0
    ? noteParts.join(". Note: ")
    : personalities.length === 0
      ? value
      : "";
  return { personalities, personalityNote };
}

export function greetingFingerprintForSerialized(
  name: string | null,
  job: string | null,
  personality: string | null,
): string {
  return [name?.trim() ?? "", job?.trim() ?? "", personality ?? ""].join("\u0000");
}

export function serializeConfiguration(input: WaitlistConfigurationInput): WaitlistConfigurationPayload {
  const name = input.name.trim();
  const job = input.job.trim();
  if (!name) throw new WaitlistMappingError("name_required", "Give your Ally a name.");
  if (!job) throw new WaitlistMappingError("job_required", "Tell your Ally what to handle.");
  if (name.length > 80) throw new WaitlistMappingError("name_too_long", "Keep the Ally name shorter.");
  if (job.length > WAITLIST_CLOUD_TEXT_LIMIT) {
    throw new WaitlistMappingError("job_too_long", "Keep the Ally job shorter.");
  }

  const personality =
    input.personalityOverride !== undefined
      ? input.personalityOverride
      : serializePersonality(input.personalities, input.personalityNote);
  if (personality !== undefined && personality.length > WAITLIST_CLOUD_TEXT_LIMIT) {
    throw new WaitlistMappingError("personality_too_long", "Keep the Ally personality shorter.");
  }

  return {
    name,
    ...serializeAppearance(input.shape, input.color),
    job,
    ...(personality !== undefined ? { personality } : {}),
  };
}

export function greetingFingerprint(
  configuration: Pick<WaitlistConfigurationInput, "name" | "job" | "personalities" | "personalityNote">,
): string {
  return [
    configuration.name.trim(),
    configuration.job.trim(),
    serializePersonality(configuration.personalities, configuration.personalityNote) ?? "",
  ].join("\u0000");
}
