import {
  Accordion,
  Button,
  Checkbox,
  NativeSelect,
  NumberInput,
} from "@mantine/core";
import { ArrowRight } from "lucide-react";

import type { CalculationDraft } from "../api/coreClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import "./CalculationForm.css";

const K_GRID_AXES = ["x", "y", "z"] as const;
const SELECT_CLASSES = {
  root: "field",
  wrapper: "field__wrapper",
  label: "field__label",
  input: "field__input field__select",
  section: "field__section",
};
const NUMBER_CLASSES = {
  root: "field",
  wrapper: "field__wrapper",
  label: "field__label",
  input: "field__input field__number",
  controls: "field__number-controls",
  control: "field__number-control",
};
type SmearingType = NonNullable<
  NonNullable<CalculationDraft["hints"]>["smearing_type"]
>;
type PseudoAccuracy = NonNullable<
  CalculationDraft["intent"]
>["pseudo_accuracy"];
const SMEARING_OPTIONS = [
  { value: "", label: "Automatic" },
  { value: "fixed", label: "Fixed occupations" },
  { value: "cold", label: "Cold" },
  { value: "gaussian", label: "Gaussian" },
  { value: "mp", label: "Methfessel-Paxton" },
] satisfies { value: SmearingType | ""; label: string }[];
const BOOLEAN_HINT_FIELDS = [
  {
    hint: "spin_polarized",
    label: "Spin treatment",
    enabled: "Spin polarized",
    disabled: "Non-spin-polarized",
  },
  {
    hint: "use_vdw",
    label: "Dispersion correction",
    enabled: "Enabled",
    disabled: "Disabled",
  },
] as const;

export function CalculationForm({
  onShowRecommendation,
}: {
  readonly onShowRecommendation: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { draft, capabilities, inspection } = snapshot;
  if (!draft?.intent || !draft.hints || !capabilities || !inspection) {
    return null;
  }
  const { intent, hints } = draft;
  const accuracy = hints.pseudo_accuracy ?? intent.pseudo_accuracy;

  const functionals = [
    ...new Set(
      capabilities.pseudopotential_sets.map((item) => item.functional),
    ),
  ];
  const matchingTables = capabilities.pseudopotential_sets.filter(
    (table) =>
      table.functional === intent.functional && table.accuracy === accuracy,
  );
  const inspecting = snapshot.operation === "inspect";
  const busy = snapshot.operation !== null;
  let submitLabel =
    snapshot.reviewed === null
      ? "Generate recommendation"
      : "Update recommendation";
  if (snapshot.operation === "compute") submitLabel = "Computing";

  return (
    <form
      className="calculation-form"
      onSubmit={(event) => {
        event.preventDefault();
        onShowRecommendation();
        void workspace.dispatch({ type: "review.compute" });
      }}
    >
      {inspecting ? (
        <p className="stale-note" role="status">
          Calculation settings are disabled while the new structure loads.
        </p>
      ) : null}
      <NativeSelect
        label="Task"
        classNames={SELECT_CLASSES}
        value={intent.task}
        disabled
        data={capabilities.tasks.map((task) => ({
          value: task.id,
          label: task.name,
        }))}
      />
      <div className="field-row">
        <NativeSelect
          label="Functional"
          classNames={SELECT_CLASSES}
          value={intent.functional}
          disabled={inspecting}
          data={functionals}
          onChange={(event) =>
            void workspace.dispatch({
              type: "draft.patch",
              intent: { functional: event.currentTarget.value },
              pseudoTable: null,
            })
          }
        />
        <NativeSelect
          label="Accuracy"
          classNames={SELECT_CLASSES}
          value={accuracy}
          disabled={inspecting}
          onChange={(event) =>
            void workspace.dispatch({
              type: "draft.patch",
              intent: {
                pseudo_accuracy: parsePseudoAccuracy(event.currentTarget.value),
              },
              hints: { pseudo_accuracy: null },
              pseudoTable: null,
            })
          }
          data={[
            { value: "efficiency", label: "Efficiency" },
            { value: "precision", label: "Precision" },
          ]}
        />
      </div>
      <NativeSelect
        label="Pseudopotential table"
        classNames={SELECT_CLASSES}
        disabled={inspecting}
        aria-describedby="pseudo-table-help"
        value={draft.pseudo_table ?? ""}
        onChange={(event) =>
          void workspace.dispatch({
            type: "draft.patch",
            pseudoTable: event.currentTarget.value || null,
          })
        }
        data={[
          { value: "", label: "Automatic" },
          ...matchingTables.map((table) => ({
            value: table.id,
            label: `${table.upstream_name} · ${table.functional} · ${table.accuracy} · ${table.relativistic_treatment}`,
          })),
        ]}
      />
      <p
        id="pseudo-table-help"
        className={
          matchingTables.length === 0 ? "stale-note" : "visually-hidden"
        }
        role="status"
      >
        {matchingTables.length === 0
          ? "No registered table matches these settings. Choose another functional or accuracy."
          : `Showing ${intent.functional} / ${accuracy} tables. Automatic lets Core choose; changing either setting resets the table.`}
      </p>

      <ScientificOverrides hints={hints} inspecting={inspecting} />

      <Button
        classNames={{
          root: "primary-action",
          inner: "primary-action__inner",
        }}
        type="submit"
        fullWidth
        rightSection={<ArrowRight aria-hidden="true" size={14} />}
        disabled={busy || matchingTables.length === 0}
      >
        {submitLabel}
      </Button>
    </form>
  );
}

function ScientificOverrides({
  hints,
  inspecting,
}: {
  readonly hints: NonNullable<CalculationDraft["hints"]>;
  readonly inspecting: boolean;
}) {
  const workspace = useWorkspace();
  const kGrid = hints.k_grid ?? null;
  const explicitKGrid = kGrid !== null;
  const spinSetting = formatOptionalSwitch(hints.spin_polarized);
  const vdwSetting = formatOptionalSwitch(hints.use_vdw);
  const smearingType = hints.smearing_type ?? null;
  const smearingWidth = hints.smearing_width_ry;

  function updateKGrid(index: 0 | 1 | 2, raw: string | number): void {
    if (kGrid === null) return;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 1 || value > 99) return;
    const next = [...kGrid];
    next[index] = value;
    void workspace.dispatch({ type: "draft.patch", hints: { k_grid: next } });
  }

  return (
    <Accordion
      order={3}
      transitionDuration={0}
      chevron={
        <span className="advanced-controls__indicator" aria-hidden="true" />
      }
      classNames={{
        root: "advanced-controls",
        item: "advanced-controls__item",
        control: "advanced-controls__control",
        label: "advanced-controls__label",
        chevron: "advanced-controls__chevron",
        content: "advanced-controls__content",
      }}
    >
      <Accordion.Item value="scientific-overrides">
        <Accordion.Control>Scientific overrides</Accordion.Control>
        <Accordion.Panel>
          <p className="advanced-controls__summary">
            {explicitKGrid ? `${kGrid.join("×")} k grid` : "automatic k grid"} ·{" "}
            {smearingSummary(smearingType, smearingWidth)} · spin {spinSetting}{" "}
            · vdW {vdwSetting}
          </p>
          <div className="advanced-controls__body">
            <fieldset className="k-grid-field">
              <legend>K-point grid</legend>
              <Checkbox
                label="Set an explicit grid"
                size="md"
                classNames={{
                  root: "check-field",
                  body: "check-field__body",
                  input: "check-field__input",
                  label: "check-field__label",
                  icon: "check-field__icon",
                }}
                checked={explicitKGrid}
                disabled={inspecting}
                onChange={(event) =>
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: {
                      k_grid: event.currentTarget.checked ? [1, 1, 1] : null,
                    },
                  })
                }
              />
              <div className="k-grid-inputs">
                {([0, 1, 2] as const).map((index) => (
                  <NumberInput
                    key={index}
                    aria-label={`K-point grid ${K_GRID_AXES[index]}`}
                    classNames={{
                      ...NUMBER_CLASSES,
                      input: "field__input k-grid-inputs__input",
                    }}
                    role="spinbutton"
                    aria-valuemin={1}
                    aria-valuemax={99}
                    aria-valuenow={kGrid?.[index]}
                    min={1}
                    max={99}
                    clampBehavior="none"
                    disabled={!explicitKGrid || inspecting}
                    value={kGrid?.[index] ?? ""}
                    placeholder="Auto"
                    onChange={(value) => {
                      updateKGrid(index, value);
                    }}
                  />
                ))}
              </div>
            </fieldset>
            <div className="field-row">
              <NativeSelect
                label="Smearing treatment"
                classNames={SELECT_CLASSES}
                disabled={inspecting}
                value={smearingType ?? ""}
                onChange={(event) => {
                  const selected = parseSmearingType(event.currentTarget.value);
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: {
                      smearing_type: selected,
                      smearing_width_ry: usesSmearingWidth(selected)
                        ? (smearingWidth ?? 0.01)
                        : null,
                    },
                  });
                }}
                data={SMEARING_OPTIONS}
              />
              <NumberInput
                label="Smearing width · Ry"
                classNames={NUMBER_CLASSES}
                role="spinbutton"
                aria-valuemin={0.001}
                aria-valuenow={smearingWidth ?? undefined}
                step={0.001}
                disabled={inspecting || !usesSmearingWidth(smearingType)}
                min={0.001}
                clampBehavior="none"
                value={smearingWidth ?? ""}
                placeholder="Select smearing"
                onChange={(value) => {
                  const width = Number(value);
                  if (!Number.isFinite(width) || width <= 0) return;
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: { smearing_width_ry: width },
                  });
                }}
              />
            </div>
            {BOOLEAN_HINT_FIELDS.map((field) => (
              <NativeSelect
                key={field.hint}
                label={field.label}
                classNames={SELECT_CLASSES}
                disabled={inspecting}
                value={String(hints[field.hint] ?? "")}
                onChange={(event) =>
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: {
                      [field.hint]: parseOptionalSwitch(
                        event.currentTarget.value,
                      ),
                    },
                  })
                }
                data={[
                  { value: "", label: "Automatic" },
                  { value: "true", label: field.enabled },
                  { value: "false", label: field.disabled },
                ]}
              />
            ))}
          </div>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}

function usesSmearingWidth(type: SmearingType | null): boolean {
  return type !== null && type !== "fixed";
}

function parsePseudoAccuracy(value: string): PseudoAccuracy {
  if (value === "efficiency" || value === "precision") return value;
  throw new Error(`Unsupported pseudopotential accuracy: ${value}`);
}

function parseSmearingType(value: string): SmearingType | null {
  const option = SMEARING_OPTIONS.find((item) => item.value === value);
  if (option === undefined) {
    throw new Error(`Unsupported smearing treatment: ${value}`);
  }
  return option.value || null;
}

function smearingSummary(
  type: SmearingType | null,
  width: number | null | undefined,
): string {
  if (type === null) return "automatic smearing";
  if (!usesSmearingWidth(type)) return "fixed occupations";
  return `${type} · ${String(width)} Ry`;
}

function parseOptionalSwitch(value: string): boolean | null {
  if (value === "") return null;
  return value === "true";
}

function formatOptionalSwitch(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "automatic";
  return value ? "on" : "off";
}
