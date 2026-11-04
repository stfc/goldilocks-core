import type { ResolvedField, Setting, Source } from "../api/coreClient";

/** The record `setting.resolved_in` names in `records`: the record of the
 * decision the setting feeds (#187). */
export function settingRecord(
  setting: Pick<Setting, "resolved_in">,
  records: Readonly<Record<string, ResolvedField>> | undefined,
): ResolvedField | undefined {
  return records?.[setting.resolved_in.record];
}

/** `setting`'s resolved value: what `setting.resolved_in.path` leads to in
 * its resolved `record`. `undefined` while the record is not resolved,
 * for a setting without a path (the record holds no value of it), and
 * where the path leads to nothing. */
export function resolvedValue(
  setting: Pick<Setting, "resolved_in">,
  record: ResolvedField | undefined,
): unknown {
  const { path } = setting.resolved_in;
  if (record?.status !== "resolved" || path === null) return undefined;
  let value: unknown = record.value;
  for (const key of path) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return undefined;
    }
    value = (value as Readonly<Record<string, unknown>>)[key];
  }
  return value;
}

/** The tier to caption `setting`'s resolved value with, naming only the
 * tier that produced that value: none while there is no value; for a value
 * that is the whole record, the record's source; else the setting's own
 * entry in the record's `field_sources`; else the record's source, unless
 * that is `human` -- a setting the request set reads `human` in
 * `field_sources` or is pinned in the draft, so a record-level `human`
 * came from another of the record's settings. */
export function resolvedSource(
  setting: Pick<Setting, "key" | "resolved_in">,
  record: ResolvedField | undefined,
): Source | undefined {
  const value = resolvedValue(setting, record);
  if (record === undefined || value === undefined || value === null) {
    return undefined;
  }
  const source = record.source ?? undefined;
  if (setting.resolved_in.path?.length === 0) return source;
  const own = record.field_sources?.[setting.key];
  if (own !== undefined) return own;
  return source === "human" ? undefined : source;
}
