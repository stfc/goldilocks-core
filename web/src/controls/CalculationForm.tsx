import { Fragment, type ReactNode, useId } from "react";
import {
  Accordion,
  Badge,
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
  HpcProfile,
  PseudopotentialTable,
  ResolvedField,
  Setting,
  Source,
  StructureInspection,
} from "../api/coreClient";
import { SourceLabel } from "../api/SourceLabel";
import { isAdvisorWarning } from "../review/warnings";
import { FindingNotes } from "../status/FindingNote";
import { currentFindings } from "../workspace/pipelineStatus";
import { readOnlyAdvisorRecords } from "../workspace/recordGroups";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { AdvisorRecordItems, AdvisorStepRecords } from "./AdvisorRecords";
import { OverrideControl } from "./OverrideControl";
import { CONTROL_LABELS, describeSource } from "./overrideFieldMeta";
import { OverrideSelect } from "./OverrideSelect";
import {
  resolvedSource,
  resolvedValue,
  settingRecord,
} from "./resolvedSetting";

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
 * records underneath, purely a presentation grouping. Cutoffs are computed
 * against whichever pseudopotential table is selected, so they read
 * naturally right below it. */
const GROUP_MERGE_INTO: Readonly<Record<string, string>> = {
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
  // The core refuses a setting no step of the task reads (#154), so a
  // setting is offered only for the tasks it declares.
  const settings = capabilities.settings.filter((setting) =>
    setting.tasks.includes(draft.task),
  );
  // Every advisor record of the response is shown: with the settings that
  // resolve into it, else read-only after them, by the response's layout.
  const readOnly =
    reviewed === null
      ? null
      : readOnlyAdvisorRecords(
          reviewed.layout,
          new Set(settings.map((setting) => setting.resolved_in.record)),
        );

  // A finding of the current draft turns the group of every setting it
  // concerns red (#165), and is shown under that setting's control (#151).
  const findingFields = new Set(
    currentFindings(snapshot).flatMap((finding) => finding.fields),
  );

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

      <Accordion
        multiple
        transitionDuration={0}
        classNames={{ label: "workbench-accordion-label" }}
      >
        <SettingsGroupItems
          settings={settings}
          overrides={overrides}
          records={reviewed?.records}
          findingFields={findingFields}
          elements={elements}
          pseudopotentialTables={capabilities.pseudopotential_tables}
          disabled={disabled}
          onChange={patchOverrides}
        />
        {readOnly === null || reviewed === null ? null : (
          <AdvisorRecordItems
            names={readOnly.ungrouped}
            records={reviewed.records}
          />
        )}
      </Accordion>
      {readOnly === null || reviewed === null
        ? null
        : readOnly.steps.map((step) => (
            <AdvisorStepRecords
              key={step.name}
              step={step.name}
              names={step.records}
              records={reviewed.records}
            />
          ))}
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
 * pattern `OverrideControl` already uses for scalar/enum fields, on the
 * same `OverrideSelect`, just hand-written here since a
 * pseudopotential-table pick needs its own elements/functional filtering
 * `OverrideControl` doesn't know about. */
function PseudoTableControl({
  tables,
  elements,
  functionalOverride,
  pinned,
  resolvedId,
  source,
  description,
  disabled,
  onChange,
}: {
  readonly tables: readonly PseudopotentialTable[];
  readonly elements: readonly string[];
  readonly functionalOverride: string | undefined;
  readonly pinned: unknown;
  readonly resolvedId: string | undefined;
  readonly source: Source | undefined;
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
  const effectiveId = pinnedId ?? resolvedId;
  const noMatch =
    matching.length === 0
      ? "No registered table supports this structure with this functional"
      : undefined;
  const needsPlaceholder =
    effectiveId === undefined ||
    !matching.some((table) => table.id === effectiveId);
  return (
    <OverrideSelect
      label={CONTROL_LABELS.pseudo_table_id}
      description={
        noMatch ?? describeSource(description, pinnedId !== undefined, source)
      }
      disabled={disabled}
      pinned={pinnedId !== undefined}
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
      onReset={() => {
        onChange({ pseudo_table_id: undefined });
      }}
      onChange={(raw) => {
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
  readonly source: Source | undefined;
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
    <OverrideSelect
      label={CONTROL_LABELS.functional}
      description={describeSource(description, pinned, source)}
      disabled={disabled}
      pinned={pinned}
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
      // A table pinned under the old functional may no longer be a valid
      // choice (and won't even appear in the now-refiltered dropdown) --
      // a reset or a change clears it rather than silently keep
      // submitting a now-invisible override, matching how a
      // pseudopotential-table pin has always been invalidated by changing
      // the functional it was chosen under.
      onReset={() => {
        onChange({ functional: undefined, pseudo_table_id: undefined });
      }}
      onChange={(raw) => {
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
  pseudo_table_id: CONTROL_LABELS.pseudo_table_id,
};

function humanizeGroup(group: string): string {
  const override = GROUP_DISPLAY_NAMES[group];
  if (override !== undefined) return override;
  const spaced = group.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** One `Setting` plus its real `Setting.group` -- a group can display
 * another group's settings inline (`GROUP_MERGE_INTO`) -- and the record
 * its `resolved_in` names, which holds its resolved value and tier (#187).
 * A setting's record is never looked up by its key or group name. */
interface GroupedSetting {
  readonly originalGroup: string;
  readonly setting: Setting;
  readonly record: ResolvedField | undefined;
}

/** The records `entries` resolve into, once each, by record name. */
function entryRecords(
  entries: readonly GroupedSetting[],
): Map<string, ResolvedField | undefined> {
  return new Map(
    entries.map((entry) => [entry.setting.resolved_in.record, entry.record]),
  );
}

/** The record of the first of `entries` from settings group `group`. */
function groupRecord(
  entries: readonly GroupedSetting[],
  group: string,
): ResolvedField | undefined {
  return entries.find((entry) => entry.originalGroup === group)?.record;
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

/** The status a group's badge shows: blocked when a finding concerns one of
 * its settings, else the worst status of the records they resolve into;
 * none while there is neither. */
function groupStatus(
  groupedSettings: readonly GroupedSetting[],
  findingFields: ReadonlySet<string>,
): ResolvedField["status"] | undefined {
  if (groupedSettings.some((entry) => findingFields.has(entry.setting.key))) {
    return "blocked";
  }
  return [...entryRecords(groupedSettings).values()].reduce<
    ResolvedField["status"] | undefined
  >((worst, record) => {
    if (record === undefined) return worst;
    if (worst === undefined) return record.status;
    return STATUS_SEVERITY[record.status] > STATUS_SEVERITY[worst]
      ? record.status
      : worst;
  }, undefined);
}

function SettingsGroupItems({
  settings,
  overrides,
  records,
  findingFields,
  elements,
  pseudopotentialTables,
  disabled,
  onChange,
}: {
  readonly settings: readonly Setting[];
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly records: Readonly<Record<string, ResolvedField>> | undefined;
  readonly findingFields: ReadonlySet<string>;
  readonly elements: readonly string[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const groups = new Map<string, GroupedSetting[]>();
  for (const setting of settings) {
    const displayGroup = GROUP_MERGE_INTO[setting.group] ?? setting.group;
    const entry: GroupedSetting = {
      originalGroup: setting.group,
      setting,
      record: settingRecord(setting, records),
    };
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
        const groupRecords = [...entryRecords(groupedSettings).values()];
        const worstStatus = groupStatus(groupedSettings, findingFields);
        const notes = groupRecords.flatMap(recordNotes);

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

/** One setting's own control, then the findings that concern it
 * (`FindingNotes`, #151). */
function renderSetting(props: {
  readonly entry: GroupedSetting;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}): ReactNode {
  const { key } = props.entry.setting;
  return (
    <Fragment key={key}>
      {settingControl(props)}
      <FindingNotes field={key} />
    </Fragment>
  );
}

/** `k_grid` keeps its dedicated `KGridControl` (a single scalar select
 * can't represent a 3-tuple), everything else goes through the generic
 * `OverrideControl` -- showing the value and tier `resolved_in` leads to in
 * the setting's record. */
function settingControl({
  entry,
  overrides,
  disabled,
  onChange,
}: {
  readonly entry: GroupedSetting;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}): ReactNode {
  const { setting, record } = entry;
  if (setting.key === "k_grid") {
    const mesh = resolvedValue(setting, record);
    const resolvedMesh =
      Array.isArray(mesh) && mesh.length === 3
        ? (mesh as [number, number, number])
        : undefined;
    return (
      <KGridControl
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
      meta={setting}
      value={overrides[setting.key]}
      resolvedValue={resolvedValue(setting, record)}
      source={resolvedSource(setting, record)}
      disabled={disabled}
      onChange={(value) => {
        onChange({ [setting.key]: value });
      }}
    />
  );
}

/** `k_distance` is deliberately `None` whenever `k_index` is what
 * actually resolved the mesh (a whole interval maps to one rung, not
 * one point -- see `KSamplingDecision.k_distance_interval`'s own
 * docstring) -- so the "k distance" control above this shows nothing.
 * Rather than leave that as a silent gap, this shows the honest range
 * the rung covers instead of fabricating a single point estimate (e.g.
 * the interval midpoint) to put in the box itself. Renders nothing once
 * `k_distance` itself has a real value -- the control already shows it.
 * Rung 1, the Gamma-only mesh, has no upper bound (`null`) and reads as
 * the open interval Δk ≥ low. */
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
  const [low, high] = interval as [number, number | null];
  const range =
    high === null
      ? `Δk ≥ ${low.toFixed(3)}`
      : `Δk ∈ [${low.toFixed(3)}, ${high.toFixed(3)}]`;
  return (
    <Text size="xs" c="dimmed">
      This rung corresponds to {range} Å⁻¹
    </Text>
  );
}

function FunctionalGroupBody({
  groupedSettings,
  pseudopotentialTables,
  functionalOverride,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly functionalOverride: string | undefined;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const entry = groupedSettings[0];
  if (entry === undefined) return null;
  const resolved = resolvedValue(entry.setting, entry.record);
  return (
    <>
      <FunctionalControl
        tables={pseudopotentialTables}
        value={functionalOverride}
        resolvedValue={typeof resolved === "string" ? resolved : undefined}
        source={resolvedSource(entry.setting, entry.record)}
        description={entry.setting.description}
        disabled={disabled}
        onChange={onChange}
      />
      <FindingNotes field={entry.setting.key} />
    </>
  );
}

function PseudoTableGroupBody({
  groupedSettings,
  elements,
  pseudopotentialTables,
  functionalOverride,
  overrides,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly elements: readonly string[];
  readonly pseudopotentialTables: readonly PseudopotentialTable[];
  readonly functionalOverride: string | undefined;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  const table = groupedSettings.find(
    (entry) => entry.originalGroup === "pseudo_table_id",
  );
  const resolvedId =
    table === undefined
      ? undefined
      : resolvedValue(table.setting, table.record);
  return (
    <>
      {table === undefined ? null : (
        <>
          <PseudoTableControl
            tables={pseudopotentialTables}
            elements={elements}
            functionalOverride={functionalOverride}
            pinned={overrides.pseudo_table_id}
            resolvedId={typeof resolvedId === "string" ? resolvedId : undefined}
            source={resolvedSource(table.setting, table.record)}
            description={table.setting.description}
            disabled={disabled}
            onChange={onChange}
          />
          <FindingNotes field={table.setting.key} />
        </>
      )}
      {groupedSettings
        .filter((entry) => entry.originalGroup === "cutoffs")
        .map((entry) =>
          renderSetting({ entry, overrides, disabled, onChange }),
        )}
    </>
  );
}

/** The k-mesh settings, then the note on the interval `k_index` covers,
 * read from the record they resolve into. */
function KSamplingGroupBody({
  groupedSettings,
  overrides,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  return (
    <>
      {groupedSettings.map((entry) =>
        renderSetting({ entry, overrides, disabled, onChange }),
      )}
      <KDistanceIntervalNote
        record={groupRecord(groupedSettings, "k_sampling")}
      />
    </>
  );
}

/** One entry of the resolved `hubbard` record's `u_values`
 * (`advisors.hubbard_u.HubbardU` on the wire): `citation` names a
 * built-in value's source and is `null` for a `u_by_element` value. */
interface HubbardU {
  readonly element: string;
  readonly manifold: string;
  readonly u_ev: number;
  readonly value_source: "table" | "human";
  readonly citation: string | null;
}

/** The resolved +U decision: every element that gets +U, with its
 * manifold, Dudarev U_eff and where the value came from. Elements left
 * out get plain DFT; one without a published U is named by the
 * decision's own warning, shown under the group's Notes. */
function AppliedHubbardU({
  record,
}: {
  readonly record: ResolvedField | undefined;
}) {
  const labelId = useId();
  const decision =
    record?.status === "resolved" &&
    typeof record.value === "object" &&
    record.value !== null
      ? (record.value as { readonly u_values?: unknown })
      : undefined;
  const uValues = decision?.u_values;
  if (!Array.isArray(uValues)) return null;
  if (uValues.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No element gets +U.
      </Text>
    );
  }
  return (
    <Stack gap={2}>
      <Text id={labelId} size="xs" fw={600} c="dimmed">
        Applied +U
      </Text>
      <Stack component="ul" gap={2} m={0} pl="md" aria-labelledby={labelId}>
        {(uValues as readonly HubbardU[]).map((entry) => (
          <Text component="li" key={entry.element} size="sm">
            {entry.element} {entry.manifold}: {entry.u_ev} eV ·{" "}
            {entry.value_source === "human" ? (
              <SourceLabel source="human" />
            ) : (
              entry.citation
            )}
          </Text>
        ))}
      </Stack>
    </Stack>
  );
}

/** The Hubbard settings, then the U values the decision they feed applied.
 * Of the settings, the `hubbard` record holds a value only of
 * `hubbard_projectors`, and only when an element gets +U. */
function HubbardGroupBody({
  groupedSettings,
  overrides,
  disabled,
  onChange,
}: {
  readonly groupedSettings: readonly GroupedSetting[];
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly disabled: boolean;
  readonly onChange: (patch: Readonly<Record<string, unknown>>) => void;
}) {
  return (
    <>
      {groupedSettings.map((entry) =>
        renderSetting({ entry, overrides, disabled, onChange }),
      )}
      <AppliedHubbardU record={groupRecord(groupedSettings, "hubbard")} />
    </>
  );
}

function GroupBody({
  group,
  groupedSettings,
  elements,
  pseudopotentialTables,
  functionalOverride,
  overrides,
  disabled,
  onChange,
}: {
  readonly group: string;
  readonly groupedSettings: readonly GroupedSetting[];
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
        elements={elements}
        pseudopotentialTables={pseudopotentialTables}
        functionalOverride={functionalOverride}
        overrides={overrides}
        disabled={disabled}
        onChange={onChange}
      />
    );
  }
  const bodyProps = { groupedSettings, overrides, disabled, onChange };
  if (group === "k_sampling") return <KSamplingGroupBody {...bodyProps} />;
  if (group === "hubbard") return <HubbardGroupBody {...bodyProps} />;
  return (
    <>
      {groupedSettings.map((entry) =>
        renderSetting({ entry, overrides, disabled, onChange }),
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
    <Fieldset legend={CONTROL_LABELS.k_grid}>
      <SimpleGrid cols={3} spacing="xs">
        {(["x", "y", "z"] as const).map((axis, index) => (
          <NumberInput
            key={axis}
            aria-label={`${CONTROL_LABELS.k_grid} ${axis}`}
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
