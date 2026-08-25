import type { ReactNode } from "react";
import { ArrowRight, Moon, Sun } from "lucide-react";

import type { CalculationDraft, Capabilities } from "../api/coreClient";
import type { Theme } from "../theme";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { StructureSourceControls } from "./StructureSourceControls";
import "./GuidedControls.css";
const K_GRID_AXES = ["x", "y", "z"] as const;
type SmearingType = NonNullable<
  NonNullable<CalculationDraft["hints"]>["smearing_type"]
>;
type PseudoAccuracy = NonNullable<CalculationDraft["intent"]>["pseudo_accuracy"];

export function GuidedControls({
  theme,
  onToggleTheme,
  onShowStructure,
  onShowRecommendation,
}: {
  readonly theme: Theme;
  readonly onToggleTheme: () => void;
  readonly onShowStructure: () => void;
  readonly onShowRecommendation: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  return (
    <section
      id="calculation-panel"
      className="control-rail"
      aria-label="Calculation setup"
    >
      <section className="rail-section rail-section--source">
        <SectionHeading
          number="01"
          title="Structure"
          action={
            <button
              className="theme-toggle"
              type="button"
              aria-label={
                theme === "light"
                  ? "Switch to dark mode"
                  : "Switch to light mode"
              }
              title={theme === "light" ? "Dark mode" : "Light mode"}
              onClick={onToggleTheme}
            >
              {theme === "light" ? (
                <Sun aria-hidden="true" size={17} />
              ) : (
                <Moon aria-hidden="true" size={17} />
              )}
            </button>
          }
        />
        <StructureSourceControls
          source={snapshot.source}
          inspection={snapshot.inspection}
          inspecting={snapshot.operation === "inspect"}
          onOpen={(source) => {
            onShowStructure();
            return workspace.dispatch({ type: "source.open", source });
          }}
        />
      </section>

      <section className="rail-section rail-section--calculation">
        <SectionHeading number="02" title="Calculation" />
        {snapshot.draft === null ||
        snapshot.inspection === null ||
        snapshot.capabilities === null ? null : (
          <CalculationForm
            capabilities={snapshot.capabilities}
            onShowRecommendation={onShowRecommendation}
          />
        )}
      </section>
    </section>
  );
}

function SectionHeading({
  number,
  title,
  action,
}: {
  readonly number: string;
  readonly title: string;
  readonly action?: ReactNode;
}) {
  return (
    <header className="section-heading">
      <div>
        <span>{number}</span>
        <h2>{title}</h2>
      </div>
      {action}
    </header>
  );
}

function CalculationForm({
  capabilities,
  onShowRecommendation,
}: {
  readonly capabilities: Capabilities;
  readonly onShowRecommendation: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const draft = snapshot.draft;
  const intent = draft?.intent;
  const hints = draft?.hints;
  if (
    draft === null ||
    intent === null ||
    intent === undefined ||
    hints === null ||
    hints === undefined
  ) {
    return null;
  }

  const functionals = [
    ...new Set(
      capabilities.pseudopotential_sets.map((item) => item.functional),
    ),
  ];
  const kGrid = hints.k_grid;
  const explicitKGrid = kGrid !== null && kGrid !== undefined;
  const spinSetting = formatOptionalSwitch(hints.spin_polarized);
  const vdwSetting = formatOptionalSwitch(hints.use_vdw);
  const smearingType = hints.smearing_type;
  const smearingWidth = hints.smearing_width_ry;
  const inspecting = snapshot.operation === "inspect";
  const busy = snapshot.operation !== null;

  function updateKGrid(index: 0 | 1 | 2, raw: string): void {
    if (kGrid === null || kGrid === undefined) return;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 1 || value > 99) return;
    const next = [...kGrid];
    next[index] = value;
    void workspace.dispatch({ type: "draft.patch", hints: { k_grid: next } });
  }

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
      <label className="field">
        <span>Task</span>
        <select value={intent.task} disabled>
          {capabilities.tasks.map((task) => (
            <option key={task.id} value={task.id}>
              {task.name}
            </option>
          ))}
        </select>
      </label>
      <div className="field-row">
        <label className="field">
          <span>Functional</span>
          <select
            value={intent.functional}
            disabled={inspecting}
            onChange={(event) =>
              void workspace.dispatch({
                type: "draft.patch",
                intent: { functional: event.currentTarget.value },
                pseudoTable: null,
              })
            }
          >
            {functionals.map((functional) => (
              <option key={functional}>{functional}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Accuracy</span>
          <select
            value={intent.pseudo_accuracy}
            disabled={inspecting}
            onChange={(event) =>
              void workspace.dispatch({
                type: "draft.patch",
                intent: {
                  pseudo_accuracy: parsePseudoAccuracy(event.currentTarget.value),
                },
                pseudoTable: null,
              })
            }
          >
            <option value="efficiency">Efficiency</option>
            <option value="precision">Precision</option>
          </select>
        </label>
      </div>
      <label className="field">
        <span>Pseudopotential table</span>
        <select
          disabled={inspecting}
          value={draft.pseudo_table ?? ""}
          onChange={(event) =>
            void workspace.dispatch({
              type: "draft.patch",
              pseudoTable: event.currentTarget.value || null,
            })
          }
        >
          <option value="">Automatic</option>
          {capabilities.pseudopotential_sets.map((table) => (
            <option key={table.id} value={table.id}>
              {table.id} · {table.relativistic_treatment}
            </option>
          ))}
        </select>
      </label>

      <details className="advanced-controls">
        <summary>Scientific overrides</summary>
        <p className="advanced-controls__summary">
          {explicitKGrid ? `${kGrid.join("×")} k grid` : "automatic k grid"} ·{" "}
          {smearingSummary(smearingType, smearingWidth)} · spin {spinSetting} ·
          vdW {vdwSetting}
        </p>
        <div className="advanced-controls__body">
          <fieldset className="k-grid-field">
            <legend>K-point grid</legend>
            <label className="check-field">
              <input
                type="checkbox"
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
              <span>Set an explicit grid</span>
            </label>
            <div className="k-grid-inputs">
              {([0, 1, 2] as const).map((index) => (
                <input
                  key={index}
                  aria-label={`K-point grid ${K_GRID_AXES[index]}`}
                  type="number"
                  min="1"
                  max="99"
                  disabled={!explicitKGrid || inspecting}
                  value={kGrid?.[index] ?? ""}
                  placeholder="Auto"
                  onChange={(event) => {
                    updateKGrid(index, event.currentTarget.value);
                  }}
                />
              ))}
            </div>
          </fieldset>
          <div className="field-row">
            <label className="field">
              <span>Smearing treatment</span>
              <select
                disabled={inspecting}
                value={smearingType ?? ""}
                onChange={(event) => {
                  const selected = parseSmearingType(event.currentTarget.value);
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: {
                      smearing_type: selected,
                      smearing_width_ry:
                        selected === null || selected === "fixed"
                          ? null
                          : (smearingWidth ?? 0.01),
                    },
                  });
                }}
              >
                <option value="">Automatic</option>
                <option value="fixed">Fixed occupations</option>
                <option value="cold">Cold</option>
                <option value="gaussian">Gaussian</option>
                <option value="mp">Methfessel-Paxton</option>
              </select>
            </label>
            <label className="field">
              <span>Smearing width · Ry</span>
              <input
                type="number"
                step="0.001"
                disabled={
                  inspecting ||
                  smearingType === null ||
                  smearingType === undefined ||
                  smearingType === "fixed"
                }
                min="0.001"
                value={smearingWidth ?? ""}
                placeholder="Select smearing"
                onChange={(event) => {
                  const width = Number(event.currentTarget.value);
                  if (!Number.isFinite(width) || width <= 0) return;
                  void workspace.dispatch({
                    type: "draft.patch",
                    hints: { smearing_width_ry: width },
                  });
                }}
              />
            </label>
          </div>
          <label className="field">
            <span>Spin treatment</span>
            <select
              disabled={inspecting}
              value={optionalSwitchValue(hints.spin_polarized)}
              onChange={(event) =>
                void workspace.dispatch({
                  type: "draft.patch",
                  hints: {
                    spin_polarized: parseOptionalSwitch(
                      event.currentTarget.value,
                    ),
                  },
                })
              }
            >
              <option value="">Automatic</option>
              <option value="true">Spin polarized</option>
              <option value="false">Non-spin-polarized</option>
            </select>
          </label>
          <label className="field">
            <span>Dispersion correction</span>
            <select
              disabled={inspecting}
              value={optionalSwitchValue(hints.use_vdw)}
              onChange={(event) =>
                void workspace.dispatch({
                  type: "draft.patch",
                  hints: {
                    use_vdw: parseOptionalSwitch(event.currentTarget.value),
                  },
                })
              }
            >
              <option value="">Automatic</option>
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
          </label>
        </div>
      </details>

      <button className="primary-action" type="submit" disabled={busy}>
        <span>
          {snapshot.operation === "compute"
            ? "Computing"
            : snapshot.reviewed === null
              ? "Generate recommendation"
              : "Update recommendation"}
        </span>
        <ArrowRight aria-hidden="true" size={14} />
      </button>
    </form>
  );
}

function parsePseudoAccuracy(value: string): PseudoAccuracy {
  if (value === "efficiency" || value === "precision") return value;
  throw new Error(`Unsupported pseudopotential accuracy: ${value}`);
}

function parseSmearingType(value: string): SmearingType | null {
  switch (value) {
    case "":
      return null;
    case "fixed":
    case "cold":
    case "gaussian":
    case "mp":
      return value;
    default:
      throw new Error(`Unsupported smearing treatment: ${value}`);
  }
}

function smearingSummary(
  type: SmearingType | null | undefined,
  width: number | null | undefined,
): string {
  if (type === null || type === undefined) return "automatic smearing";
  if (type === "fixed") return "fixed occupations";
  return `${type} · ${String(width)} Ry`;
}

function optionalSwitchValue(value: boolean | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function parseOptionalSwitch(value: string): boolean | null {
  if (value === "") return null;
  return value === "true";
}

function formatOptionalSwitch(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "automatic";
  return value ? "on" : "off";
}
