import type { AllyViewModel } from "@allies/cloud-client";

import { ALLY_SHAPES, type AllyShape } from "../../components/ally-avatar";
import { WAITLIST_APPEARANCE_CATALOG_VERSION, WAITLIST_COLORS } from "../waitlist/catalog";

export type ResolvedAllyAppearance = { shape: AllyShape; color: string };

export function resolveAllyAppearance(ally: AllyViewModel): ResolvedAllyAppearance | null {
  if (ally.appearance.catalogVersion !== WAITLIST_APPEARANCE_CATALOG_VERSION) return null;
  const [rawShape, rawColor, ...extra] = ally.appearance.key.split(":");
  if (extra.length > 0 || !ALLY_SHAPES.includes(rawShape as AllyShape)) return null;
  const color = WAITLIST_COLORS.find(
    (candidate) => candidate.slice(1) === rawColor?.toLowerCase(),
  );
  return color ? { shape: rawShape as AllyShape, color } : null;
}

export function allyAppearanceKey(appearance: ResolvedAllyAppearance): string {
  return `${appearance.shape}:${appearance.color.slice(1)}`;
}
