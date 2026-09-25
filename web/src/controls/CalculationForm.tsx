import type { ReactNode } from "react";
import {
  Accordion,
  Badge,
  CloseButton,
  Fieldset,
  Group,
  NativeSelect,
  NumberInput,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";

import type {
  AdvisorWarning,
  CalcTask,
  ExplainResult,
  HpcProfile,
  PseudopotentialTable,
  ResolvedField,
  Setting,
  Source,
  StructureInspection,
} from "../api/coreClient";
import { SourceLabel } from "../api/SourceLabel";
import { isAdvisorWarning } from "../review/warnings";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { OverrideControl } from "./OverrideControl";
import { describeSource } from "./overrideFieldMeta";

/** Groups whose overrides only make sense for a subset of tasks.
 * `capabilities.py`'s own `Setting.tasks` field is always `null` today
 * (not wired -- see its docstring), so this is a small, honestly-scoped
 * frontend-only allowlist rather than something derived from the API;
 * a setting outside this map is shown regardless of task. */
const GROUP_TASK_RELEVANCE: Readonly<Record<string, readonly CalcTask[]>> = {
  relax: ["relax", "vc-relax"],
};

const STATUS_COLORS: Readonly<Record<ResolvedField["status"], string>> = {
  resolved: "green",
  unavailable: "yellow",
  blocked: "red",
};

const STATUS_SEVERITY: Readonly<Record<ResolvedField["status"], number>> = {
  resolved: 0,
  unavailable: 1,
  blocked: 2,
};

/** Curated presentation order for the advisors accordion -- a
 * frontend-only display concern, independent of `capabilities()`'s own
 * settings order (that order is a reflected, cross-repo vocabulary
 * contract -- see capabilities.py's own docstring -- not something this
 * card should reorder). k_sampling leads because it's the one setting
 * with a real ML model behind it today (QRF95); pseudopotential table
 * and functional follow since almost everything else is computed
 * against whichever pseudopotentials that picks. Groups not listed here
 * keep capabilities()'s own relative order, appended after these. */
const GROUP_ORDER: readonly string[] = [
  "k_sampling",
  "pseudo_table_id",
  "functional",
  "vdw",
  "nbnd",
  "convergence",
];

/** A settings group can be folded into another group's accordion
 * section for display -- still two distinct `Setting.group`s/resolved
 * records underneath, purely a presentation grouping. n_irr_k's only
 * real lever (`nosym`) belongs next to the k-mesh it changes the count
 * for; cutoffs are computed against whichever pseudopotential table is
 * selected, so they read naturally right below it. */
const GROUP_MERGE_INTO: Readonly<Record<string, string>> = {
  n_irr_k: "k_sampling",
  cutoffs: "pseudo_table_id",
};

/** `resolve_hpc_profile` (server-side) isn't a smart "automatic" picker --
 * its own docstring: an explicit name always wins; with none given,
 * *exactly one* installed profile is an unambiguous default, and more
 * than one requires the caller to choose outright (a real error, not a
 * fallback). Labeling the unset state "Automatic" implied a selection
 * policy that doesn't exist and would silently stop applying the moment
 * a second profile is ever installed. With exactly one profile, this
 * shows that profile's real name pre-selected instead (still leaves
 * `value` unset/`null` in the request -- nothing to actually pin since
 * there is no alternative); with more than one and nothing chosen yet,
 * it shows a real "not selected" placeholder rather than a name that
 * doesn't resolve to anything in particular. */
function HpcProfileControl({
  hpcProfiles,
  value,
  disabled,
  onChange,
}: {
  readonly hpcProfiles: readonly HpcProfile[];
  readonly value: string | null;
  readonly disabled: boolean;
  readonly onChange: (hpc: string | null) => void;
}) {
  const soleProfile = hpcProfiles.length === 1 ? hpcProfiles[0] : undefined;
  const effective = value ?? soleProfile?.id ?? "";
  const needsPlaceholder = effective === "";
  return (
    <NativeSelect
      label="HPC profile"
      description={
        soleProfile === undefined ? undefined : "Only installed HPC profile."
      }
      disabled={disabled}
      value={effective}
      data={[
        ...(needsPlaceholder
          ? [{ value: "", label: "—", disabled: true }]
          : []),
        ...hpcProfiles.map((profile) => ({
          value: profile.id,
          label: profile.name,
        })),
      ]}
      onChange={(event) => {
        onChange(event.currentTarget.value || null);
      }}
    />
  );
}

/** Code/Task/HPC profile: which target this calculation is even for, as
 * opposed to `CalculationForm` below's per-step *settings* for that
 * target. Lives in `StructureCard` (v2 epic 12 follow-up) -- right
 * between loading a structure and viewing it, since it's the other
 * half of "what am I calculating" alongside the structure itself,
 * rather than a settings-tuning concern like the accordion is. */
export function CalculationContextControls() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { draft, capabilities, inspection } = snapshot;
  if (draft === null || capabilities === null) {
    return null;
  }

  const disabled = snapshot.operation === "inspect" || inspection === null;

  return (
    <Stack gap="sm">
      <NativeSelect
        label="Code"
        disabled={disabled}
        value={draft.code}
        data={capabilities.codes.map((code) => ({
          value: code.id,
          label: code.name,
        }))}
        onChange={(event) => {
          void workspace.dispatch({
            type: "draft.patch",
            code: event.currentTarget.value,
          });
        }}
      />
      <NativeSelect
        label="Task"
        disabled={disabled}
        value={draft.task}
        data={capabilities.tasks.map((task) => ({
          value: task.id,
          label: task.name,
        }))}
        onChange={(event) => {
          void workspace.dispatch({
            type: "draft.patch",
            task: event.currentTarget.value as CalcTask,
          });
        }}
      />

      <HpcProfileControl
        hpcProfiles={capabilities.hpc_profiles}
        value={draft.hpc}
        disabled={disabled}
        onChange={(hpc) => {
          void workspace.dispatch({ type: "draft.patch", hpc });
        }}
      />
    </Stack>
  );
}

export function CalculationForm() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { draft, capabilities, inspection, reviewed } = snapshot;
  if (draft === null || capabilities === null) {
    return null;
  }

  const inspecting = snapshot.operation === "inspect";
  const disabled = inspecting || inspection === null;

  const elements = inspection === null ? [] : uniqueElements(inspection);
  const overrides = draft.overrides;

  function patchOverrides(patch: Readonly<Record<string, unknown>>): void {
    void workspace.dispatch({ type: "draft.patch", overrides: patch });
  }

  return (
    <Stack>
      {inspecting ? (
        <Text c="red" size="sm" role="status">
          Calculation settings are disabled while the new structure loads.
        </Text>
      ) : null}
      {inspection === null ? (
        <Text c="dimmed" size="sm">
          Showing default settings — load a structure to configure a
          calculation.
        </Text>
      ) : null}

      <Accordion multiple transitionDuration={0}>
        <SettingsGroupItems
          settings={capabilities.settings}
          task={draft.task}
          overrides={overrides}
          reviewed={reviewed}
          elements={elements}
          pseudopotentialTables={capabilities.pseudopotential_tables}
          disabled={disabled}
          onChange={patchOverrides}
        />
      </Accordion>
    </Stack>
  );
}

function uniqueElements(inspection: StructureInspection): string[] {
  return [
    ...new Set(
      inspection.structure.sites.flatMap((site) =>
        site.species.map((species) => species.symbol),
      ),
    ),
  ];
}

function uniqueFunctionals(tables: readonly PseudopotentialTable[]): string[] {
  return [...new Set(tables.map((table) => table.functional))];
}

/** Both this and `FunctionalControl` below show the actual resolved
 * value pre-selected (with a source-naming description above the box)
 * rather than a separate read-only "here's what resolved" card next to
 * an always-"Automatic" select -- the same `resolvedValue`/`source`
 * pattern `OverrideControl` already uses for scalar/enum fields, just
 * hand-written here since a pseudopotential-table pick needs its own
 * elements/functional filtering `OverrideControl` doesn't know about. */
function PseudoTableControl({
  tables,
  elements,
  functionalOverride,
  pinned,
  resolvedTable,
  source,
  description,
  disabled,
  onChange,
}: {
  readonly tables: readonly PseudopotentialTable[];
  readonly elements: readonly string[];
  readonly functionalOverride: string | undefined;
  readonly pinned: unknown;
  readonly resolvedTable: unknown;
  readonly source: Source | null | undefined;
  readonly description: string;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const matching = tables.filter(
    (table) =>
      (functionalOverride === undefined ||
        table.functional === functionalOverride) &&
      elements.every((element) => table.elements.includes(element)),
  );
  const pinnedId = typeof pinned === "string" ? pinned : undefined;
  const resolvedId =
    typeof resolvedTable === "object" &&
    resolvedTable !== null &&
    typeof (resolvedTable as { id?: unknown }).id === "string"
      ? (resolvedTable as { id: string }).id
      : undefined;
  const effectiveId = pinnedId ?? resolvedId;
  const noMatch =
    matching.length === 0
      ? "No registered table supports this structure with this functional"
      : undefined;
  const needsPlaceholder =
    effectiveId === undefined ||
    !matching.some((table) => table.id === effectiveId);
  return (
    <NativeSelect
      label="Pseudopotential table"
      description={
        noMatch ?? describeSource(description, pinnedId !== undefined, source)
      }
      disabled={disabled}
      rightSection={
        pinnedId === undefined ? undefined : (
          <CloseButton
            aria-label="Reset Pseudopotential table to automatic"
            size="sm"
            disabled={disabled}
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            onClick={() => {
              onChange({ pseudo_table_id: undefined });
            }}
          />
        )
      }
      value={effectiveId ?? ""}
      data={[
        ...(needsPlaceholder
          ? [{ value: "", label: "—", disabled: true }]
          : []),
        ...matching.map((table) => ({
          value: table.id,
          label: `${table.provider} · ${table.functional} · ${table.accuracy} · ${table.relativistic}`,
        })),
      ]}
      onChange={(event) => {
        const raw = event.currentTarget.value;
        onChange({ pseudo_table_id: raw === "" ? undefined : raw });
      }}
    />
  );
}

function FunctionalControl({
  tables,
  value,
  resolvedValue,
  source,
  description,
  disabled,
  onChange,
}: {
  readonly tables: readonly PseudopotentialTable[];
  readonly value: string | undefined;
  readonly resolvedValue: string | undefined;
  readonly source: Source | null | undefined;
  readonly description: string;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const pinned = value !== undefined;
  const effective = pinned ? value : resolvedValue;
  const options = uniqueFunctionals(tables);
  const needsPlaceholder =
    effective === undefined || !options.includes(effective);
  return (
    <NativeSelect
      label="Functional"
      description={describeSource(description, pinned, source)}
      disabled={disabled}
      rightSection={
        pinned ? (
          <CloseButton
            aria-label="Reset Functional to automatic"
            size="sm"
            disabled={disabled}
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            onClick={() => {
              onChange({ functional: undefined, pseudo_table_id: undefined });
            }}
          />
        ) : undefined
      }
      value={effective ?? ""}
      data={[
        ...(needsPlaceholder
          ? [{ value: "", label: "—", disabled: true }]
          : []),
        ...options.map((functional) => ({
          value: functional,
          label: functional,
        })),
      ]}
      onChange={(event) => {
        const raw = event.currentTarget.value;
        // A pinned table pinned under the old functional may no
        // longer be a valid choice (and won't even appear in the
        // now-refiltered dropdown) -- clear it rather than silently
        // keep submitting a now-invisible override, matching how a
        // pseudopotential-table pin has always been invalidated by
        // changing the functional it was chosen under.
        onChange({
          functional: raw === "" ? undefined : raw,
          pseudo_table_id: undefined,
        });
      }}
    />
  );
}

/** `pseudo_table_id` is the settings group's internal name; the
 * accordion header shows the same human label as the control it
 * contains instead of a literal, ID-suffixed rendering of the group
 * name. */
const GROUP_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  pseudo_table_id: "Pseudopotential table",
};

function humanizeGroup(group: string): string {
  const override = GROUP_DISPLAY_NAMES[group];
  if (override !== undefined) return override;
  const spaced = group.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A settings group's own record key doesn't always equal the group
 * name verbatim (`pseudo_table_id` the group vs `pseudo_table` the
 * record, see recordGroups.ts) -- this is the one alias the advisors
 * accordion needs to look its own resolved value up. */
function recordKeyForGroup(group: string): string {
  return group === "pseudo_table_id" ? "pseudo_table" : group;
}

/** One `Setting` plus which real `Setting.group`/record it came from --
 * needed once a group can display another group's settings inline
 * (`GROUP_MERGE_INTO`): the display grouping and the record a setting's
 * resolved value/source come from are no longer always the same key. */
interface GroupedSetting {
  readonly originalGroup: string;
  readonly setting: Setting;
}

/** A compound decision's own field, looked up by the same name its
 * `Setting.key` uses -- works whenever an advisor's `*Decision` and
 * `*HumanInput` share field names (true for cutoffs/occupations/
 * convergence/job/parallelisation/...), silently falls back to
 * "nothing resolved yet" (the pre-existing "Automatic" placeholder
 * behaviour) for the handful that don't (e.g. k_sampling's `k_grid` ->
 * `mesh`, handled by hand where that's rendered). */
function fieldValue(record: ResolvedField | undefined, key: string): unknown {
  if (record?.status !== "resolved") return undefined;
  const value = record.value;
  if (typeof value !== "object" || value === null) return undefined;
  return (value as Readonly<Record<string, unknown>>)[key];
}

function fieldSource(
  record: ResolvedField | undefined,
  key: string,
): Source | null | undefined {
  if (record?.status !== "resolved") return undefined;
  return record.field_sources?.[key] ?? record.source;
}

/** Every compound decision that carries a `warnings` list used to
 * surface it via the group-level `ScientificRecord` card; that card is
 * gone now that each setting shows its own resolved value/source
 * inline, so this pulls just the `warnings` back out to show as a
 * small "Notes" list under the group instead of losing them outright. */
function recordNotes(record: ResolvedField | undefined): AdvisorWarning[] {
  if (record?.status !== "resolved") return [];
  const value = record.value;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return [];
  }
  const warnings = (value as Readonly<Record<string, unknown>>).warnings;
  return Array.isArray(warnings) ? warnings.filter(isAdvisorWarning) : [];
}

function GroupNotes({ notes }: { readonly notes: readonly AdvisorWarning[] }) {
  if (notes.length === 0) return null;
  return (
    <Stack gap={2}>
      <Text size="xs" fw={600} c="dimmed">
        Notes
      </Text>
      {notes.map((note) => (
        <Text key={note.code} size="xs" c="dimmed">
          {note.message}
        </Text>
      ))}
    </Stack>
  );
}

function SettingsGroupItems({
  settings,
  task,
  overrides,
  reviewed,
  elements,
  pseudopotentialTables,
  disabled,
  onChange,
}: {
  readonly settings: readonly Setting[];
  readonly task: CalcTask;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly reviewed: ExplainResult | null;
  readonly elements: readonly string[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const groups = new Map<string, GroupedSetting[]>();
  for (const setting of settings) {
    const relevantTasks = GROUP_TASK_RELEVANCE[setting.group];
    if (relevantTasks !== undefined && !relevantTasks.includes(task)) {
      continue;
    }
    const displayGroup = GROUP_MERGE_INTO[setting.group] ?? setting.group;
    const entry: GroupedSetting = { originalGroup: setting.group, setting };
    const bucket = groups.get(displayGroup);
    if (bucket === undefined) {
      groups.set(displayGroup, [entry]);
    } else {
      bucket.push(entry);
    }
  }

  const orderedGroups = [
    ...GROUP_ORDER.filter((group) => groups.has(group)),
    ...[...groups.keys()].filter((group) => !GROUP_ORDER.includes(group)),
  ];

  const functionalOverride =
    typeof overrides.functional === "string" ? overrides.functional : undefined;

  return (
    <>
      {orderedGroups.map((group) => {
        const groupedSettings = groups.get(group);
        if (groupedSettings === undefined) return null;
        const originalGroups = [
          ...new Set(groupedSettings.map((entry) => entry.originalGroup)),
        ];
        const records = new Map(
          originalGroups.map(
            (originalGroup) =>
              [
                originalGroup,
                reviewed?.records[recordKeyForGroup(originalGroup)],
              ] as const,
          ),
        );
        const worstStatus = [...records.values()].reduce<
          ResolvedField["status"] | undefined
        >((worst, record) => {
          if (record === undefined) return worst;
          if (worst === undefined) return record.status;
          return STATUS_SEVERITY[record.status] > STATUS_SEVERITY[worst]
            ? record.status
            : worst;
        }, undefined);
        const notes = originalGroups.flatMap((originalGroup) =>
          recordNotes(records.get(originalGroup)),
        );

        return (
          <Accordion.Item key={group} value={group}>
            <Accordion.Control>
              <Group gap="xs" wrap="nowrap">
                {worstStatus === undefined ? null : (
                  <Badge
                    size="xs"
                    circle
                    color={STATUS_COLORS[worstStatus]}
                    aria-hidden="true"
                  />
                )}
                <span>{humanizeGroup(group)}</span>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <GroupBody
                  group={group}
                  groupedSettings={groupedSettings}
                  records={records}
                  elements={elements}
                  pseudopotentialTables={pseudopotentialTables}
                  functionalOverride={functionalOverride}
                  overrides={overrides}
                  disabled={disabled}
                  onChange={onChange}
                />
                <GroupNotes notes={notes} />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </>
  );
}

/** One setting's own control -- `k_grid` keeps its dedicated
 * `KGridControl` (a single scalar select can't represent a 3-tuple),
 * everything else goes through the generic `OverrideControl`, now with
 * `resolvedValue`/`source` looked up from whichever record the
 * setting's *original* group resolved (see `GroupedSetting`). */
function renderSetting({
  entry,
  record,
  overrides,
  disabled,
  onChange,
}: {
  readonly entry: GroupedSetting;
  readonly record: ResolvedField | undefined;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}): ReactNode {
  const { setting } = entry;
  if (setting.key === "k_grid") {
    const mesh = fieldValue(record, "mesh");
    const resolvedMesh =
      Array.isArray(mesh) && mesh.length === 3
        ? (mesh as [number, number, number])
        : undefined;
    return (
      <KGridControl
        key={setting.key}
        value={overrides.k_grid}
        resolvedMesh={resolvedMesh}
        disabled={disabled}
        onChange={(value) => {
          onChange({ k_grid: value });
        }}
      />
    );
  }
  return (
    <OverrideControl
      key={setting.key}
      meta={setting}
      value={overrides[setting.key]}
      resolvedValue={fieldValue(record, setting.key)}
      source={fieldSource(record, setting.key)}
      disabled={disabled}
      onChange={(value) => {
        onChange({ [setting.key]: value });
      }}
    />
  );
}

/** The resolved `n_irr_k` count has no override of its own (only
 * `nosym`, a real `Setting` under the same merged section, does) -- so
 * it's shown as a plain read-only line rather than a control, the same
 * "Blocked --"/"Unavailable --" phrasing `AnalysisSection` uses for a
 * fact that failed to resolve. */
/** `k_distance` is deliberately `None` whenever `k_index` is what
 * actually resolved the mesh (a whole interval maps to one rung, not
 * one point -- see `KSamplingDecision.k_distance_interval`'s own
 * docstring) -- so the "k distance" control above this shows nothing.
 * Rather than leave that as a silent gap, this shows the honest range
 * the rung covers instead of fabricating a single point estimate (e.g.
 * the interval midpoint) to put in the box itself. Renders nothing once
 * `k_distance` itself has a real value -- the control already shows it. */
function KDistanceIntervalNote({
  record,
}: {
  readonly record: ResolvedField | undefined;
}) {
  if (record?.status !== "resolved") return null;
  const value = record.value;
  if (typeof value !== "object" || value === null) return null;
  const decision = value as Readonly<Record<string, unknown>>;
  if (decision.k_distance !== null && decision.k_distance !== undefined) {
    return null;
  }
  const interval = decision.k_distance_interval;
  if (!Array.isArray(interval) || interval.length !== 2) return null;
  const [low, high] = interval as [unknown, unknown];
  if (typeof low !== "number") return null;
  // The ladder's coarsest rung (Gamma-only) has no upper k_distance bound --
  // any distance at or above `low` still resolves to the same mesh -- and
  // the backend represents that open end as `null`, not a number
  // (kmesh.py's `(candidates[0], math.inf)`). Render "∞" instead of calling
  // .toFixed() on null.
  const highText = typeof high === "number" ? high.toFixed(3) : "∞";
  return (
    <Text size="xs" c="dimmed">
      This rung corresponds to Δk ∈ [{low.toFixed(3)}, {highText}] Å⁻¹
    </Text>
  );
}

function NIrrKSummary({
  record,
}: {
  readonly record: ResolvedField | undefined;
}) {
  if (record === undefined) return null;
  if (record.status === "resolved") {
    return (
      <Text size="sm" c="dimmed">
        Irreducible k-points: {String(record.value)}
        {record.source ? (
          <>
            {" "}
            · <SourceLabel source={record.source} />
          </>
        ) : null}
      </Text>
    );
  }
  return (
    <Text size="xs" c={record.status === "blocked" ? "red" : "dimmed"}>
      {record.status === "blocked"
        ? `Irreducible k-points blocked — ${record.blocked_by ?? "an upstream field failed"}`
        : `Irreducible k-points unavailable — ${record.reason ?? "no reason given"}`}
    </Text>
  );
}

function FunctionalGroupBody({
  groupedSettings,
  record,
  pseudopotentialTables,
  functionalOverride,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly record: ResolvedField | undefined;
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly functionalOverride: string | undefined;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  return (
    <FunctionalControl
      tables={pseudopotentialTables}
      value={functionalOverride}
      resolvedValue={
        record?.status === "resolved" && typeof record.value === "string"
          ? record.value
          : undefined
      }
      source={record?.status === "resolved" ? record.source : undefined}
      description={groupedSettings[0]?.setting.description ?? ""}
      disabled={disabled}
      onChange={onChange}
    />
  );
}

function PseudoTableGroupBody({
  groupedSettings,
  tableRecord,
  cutoffsRecord,
  elements,
  pseudopotentialTables,
  functionalOverride,
  overrides,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly tableRecord: ResolvedField | undefined;
  readonly cutoffsRecord: ResolvedField | undefined;
  readonly elements: readonly string[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly functionalOverride: string | undefined;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const pseudoSetting = groupedSettings.find(
    (entry) => entry.originalGroup === "pseudo_table_id",
  )?.setting;
  return (
    <>
      <PseudoTableControl
        tables={pseudopotentialTables}
        elements={elements}
        functionalOverride={functionalOverride}
        pinned={overrides.pseudo_table_id}
        resolvedTable={
          tableRecord?.status === "resolved" ? tableRecord.value : undefined
        }
        source={
          tableRecord?.status === "resolved" ? tableRecord.source : undefined
        }
        description={pseudoSetting?.description ?? ""}
        disabled={disabled}
        onChange={onChange}
      />
      {groupedSettings
        .filter((entry) => entry.originalGroup === "cutoffs")
        .map((entry) =>
          renderSetting({
            entry,
            record: cutoffsRecord,
            overrides,
            disabled,
            onChange,
          }),
        )}
    </>
  );
}

function KSamplingGroupBody({
  groupedSettings,
  kSamplingRecord,
  nIrrKRecord,
  overrides,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly kSamplingRecord: ResolvedField | undefined;
  readonly nIrrKRecord: ResolvedField | undefined;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  return (
    <>
      {groupedSettings
        .filter((entry) => entry.originalGroup === "k_sampling")
        .map((entry) =>
          renderSetting({
            entry,
            record: kSamplingRecord,
            overrides,
            disabled,
            onChange,
          }),
        )}
      <KDistanceIntervalNote record={kSamplingRecord} />
      <NIrrKSummary record={nIrrKRecord} />
      {groupedSettings
        .filter((entry) => entry.originalGroup === "n_irr_k")
        .map((entry) =>
          renderSetting({
            entry,
            record: nIrrKRecord,
            overrides,
            disabled,
            onChange,
          }),
        )}
    </>
  );
}

function GroupBody({
  group,
  groupedSettings,
  records,
  elements,
  pseudopotentialTables,
  functionalOverride,
  overrides,
  disabled,
  onChange,
}: {
  readonly group: string;
  readonly groupedSettings: readonly GroupedSetting[];
  readonly records: ReadonlyMap<string, ResolvedField | undefined>;
  readonly elements: readonly string[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly functionalOverride: string | undefined;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  if (group === "functional") {
    return (
      <FunctionalGroupBody
        groupedSettings={groupedSettings}
        record={records.get("functional")}
        pseudopotentialTables={pseudopotentialTables}
        functionalOverride={functionalOverride}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }
  if (group === "pseudo_table_id") {
    return (
      <PseudoTableGroupBody
        groupedSettings={groupedSettings}
        tableRecord={records.get("pseudo_table_id")}
        cutoffsRecord={records.get("cutoffs")}
        elements={elements}
        pseudopotentialTables={pseudopotentialTables}
        functionalOverride={functionalOverride}
        overrides={overrides}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }
  if (group === "k_sampling") {
    return (
      <KSamplingGroupBody
        groupedSettings={groupedSettings}
        kSamplingRecord={records.get("k_sampling")}
        nIrrKRecord={records.get("n_irr_k")}
        overrides={overrides}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }
  return (
    <>
      {groupedSettings.map((entry) =>
        renderSetting({
          entry,
          record: records.get(entry.originalGroup),
          overrides,
          disabled,
          onChange,
        }),
      )}
    </>
  );
}

/** Each axis shows its actual resolved mesh count as a real (dark,
 * editable) value, not a placeholder -- a placeholder is deliberately
 * faint (it's meant to read as a hint, not data) and the box was
 * `disabled` until a since-removed "set an explicit grid" checkbox was
 * ticked, which is exactly the "resolved value looks read-only" pattern
 * removed everywhere else in this accordion. Typing into any axis pins
 * the whole 3-tuple immediately (`k_grid` is all-or-nothing at the API
 * level -- there's no partial override); clearing any axis back to
 * empty un-pins it entirely, same "clear the box to go automatic"
 * convention every other numeric override control already uses. */
function KGridControl({
  value,
  resolvedMesh,
  disabled,
  onChange,
}: {
  readonly value: unknown;
  readonly resolvedMesh?: readonly [number, number, number] | undefined;
  readonly disabled: boolean;
  readonly onChange: (value: unknown) => void;
}) {
  const pinned =
    Array.isArray(value) && value.length === 3
      ? (value as [number, number, number])
      : undefined;
  const effective = pinned ?? resolvedMesh;
  return (
    <Fieldset legend="K-point grid">
      <SimpleGrid cols={3} spacing="xs">
        {(["x", "y", "z"] as const).map((axis, index) => (
          <NumberInput
            key={axis}
            aria-label={`K-point grid ${axis}`}
            min={1}
            max={99}
            disabled={disabled}
            value={effective?.[index] ?? ""}
            placeholder="Auto"
            onChange={(raw) => {
              if (raw === "") {
                onChange(undefined);
                return;
              }
              const parsed = Number(raw);
              if (!Number.isInteger(parsed) || parsed < 1 || parsed > 99)
                return;
              const base = effective ?? [1, 1, 1];
              const next: [number, number, number] = [...base];
              next[index] = parsed;
              onChange(next);
            }}
          />
        ))}
      </SimpleGrid>
    </Fieldset>
  );
}
