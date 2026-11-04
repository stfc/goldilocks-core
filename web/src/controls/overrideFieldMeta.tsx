import type { ReactNode } from "react";

import type { Setting, Source } from "../api/coreClient";
import { SourceLabel } from "../api/SourceLabel";

export interface OverrideFieldMeta {
  readonly key: string;
  readonly type: string;
  readonly enum?: readonly string[] | undefined;
  readonly unit?: string | null;
  readonly default?: unknown;
  readonly description: string;
}

export function fieldLabel(
  meta: Pick<OverrideFieldMeta, "key" | "unit">,
): string {
  const humanized = meta.key.replace(/_/g, " ");
  return meta.unit ? `${humanized} · ${meta.unit}` : humanized;
}

/** The labels of the override controls that do not show their
 * `fieldLabel`. */
export const CONTROL_LABELS = {
  functional: "Functional",
  pseudo_table_id: "Pseudopotential table",
  k_grid: "K-point grid",
} as const;

const CONTROL_LABEL_BY_KEY: ReadonlyMap<string, string> = new Map(
  Object.entries(CONTROL_LABELS),
);

/** The label of the control that edits override `key`, a setting or a fact
 * (which has no unit): `CONTROL_LABELS` or its `fieldLabel`. */
export function overrideLabel(
  key: string,
  settings: readonly Setting[],
): string {
  const unit = settings.find((setting) => setting.key === key)?.unit ?? null;
  return CONTROL_LABEL_BY_KEY.get(key) ?? fieldLabel({ key, unit });
}

/** `unknown`-safe stringification -- most override values are
 * primitives, but array/object-shaped ones (`k_grid`, `u_by_element`)
 * would otherwise stringify to the useless `"[object Object]"`. */
export function stringifyValue(value: unknown): string {
  return typeof value === "object" && value !== null
    ? JSON.stringify(value)
    : String(value);
}

export function automaticPlaceholder(meta: OverrideFieldMeta): string {
  return meta.default === undefined
    ? "Automatic"
    : `Automatic (${stringifyValue(meta.default)})`;
}

/** An override control's own description names the tier that produced
 * the value it shows -- "Your override" once pinned, else `source`, which
 * the caller derives from the value shown (`resolvedSource`: a setting
 * without a recorded value has none, #187), else the field's own
 * description alone. */
export function describeSource(
  description: string,
  pinned: boolean,
  source: Source | null | undefined,
): ReactNode {
  if (pinned)
    return (
      <>
        {description} · <SourceLabel source="human" />
      </>
    );
  if (source)
    return (
      <>
        {description} · <SourceLabel source={source} />
      </>
    );
  return description;
}
