import { ArrowRight } from "lucide-react";

import type {
  CalculationDraft,
  Capabilities,
  StructureInspection,
} from "../api/coreClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { StructureSourceControls } from "./StructureSourceControls";
import "./GuidedControls.css";
const K_GRID_AXES = ["x", "y", "z"] as const;

export function GuidedControls() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  return (
    <section className="control-rail" aria-label="Calculation setup">
      <section className="rail-section rail-section--source">
        <SectionHeading number="01" title="Structure" />
        <StructureSourceControls
          source={snapshot.source}
          inspection={snapshot.inspection}
          inspecting={snapshot.operation === "inspect"}
          onOpen={(source) =>
            workspace.dispatch({ type: "source.open", source })
          }
        />
      </section>

      <section className="rail-section rail-section--calculation">
        <SectionHeading number="02" title="Calculation" />
        {snapshot.draft === null ||
        snapshot.inspection === null ||
        snapshot.capabilities === null ? (
          <div className="rail-placeholder">
            <span>Waiting for a structure</span>
            <p>Defaults and compatible assets appear after inspection.</p>
          </div>
        ) : (
          <CalculationForm
            capabilities={snapshot.capabilities}
            inspection={snapshot.inspection}
          />
        )}
      </section>
    </section>
  );
}

function SectionHeading({ number, title }: { number: string; title: string }) {
  return (
    <header className="section-heading">
      <span>{number}</span>
      <h2>{title}</h2>
    </header>
  );
}

function CalculationForm({
  capabilities,
  inspection,
}: {
  readonly capabilities: Capabilities;
  readonly inspection: StructureInspection;
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

  const tables = compatibleSets(capabilities, inspection, intent);
  const functionals = [
    ...new Set(
      capabilities.pseudopotential_sets.map((item) => item.functional),
    ),
  ];
  const kGrid = hints.k_grid;
  const explicitKGrid = kGrid !== null && kGrid !== undefined;
  const spinSetting = formatOptionalSwitch(hints.spin_polarized);
  const vdwSetting = formatOptionalSwitch(hints.use_vdw);
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
        void workspace.dispatch({ type: "review.compute" });
      }}
    >
      {inspecting ? (
        <p className="stale-note" role="status">
          Inspecting the replacement structure; calculation settings are
          temporarily disabled.
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
                  pseudo_accuracy: event.currentTarget.value,
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
          <option value="">Selected by Core</option>
          {tables.map((table) => (
            <option key={table.id} value={table.id}>
              {table.provider} · {table.upstream_name}
            </option>
          ))}
        </select>
      </label>

      <details className="advanced-controls">
        <summary>Scientific overrides</summary>
        <p className="advanced-controls__summary">
          {explicitKGrid ? `${kGrid.join("×")} k grid` : "automatic k grid"} ·{" "}
          {hints.smearing_width_ry === null ||
          hints.smearing_width_ry === undefined
            ? "automatic smearing"
            : `${String(hints.smearing_width_ry)} Ry smearing`}{" "}
          · spin {spinSetting} · vdW {vdwSetting}
          <span> Changes require recomputation.</span>
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
          <label className="field">
            <span>Smearing width · Ry</span>
            <input
              type="number"
              step="0.001"
              disabled={inspecting}
              min="0"
              value={hints.smearing_width_ry ?? ""}
              placeholder="Automatic"
              onChange={(event) =>
                void workspace.dispatch({
                  type: "draft.patch",
                  hints: {
                    smearing_width_ry:
                      event.currentTarget.value === ""
                        ? null
                        : Number(event.currentTarget.value),
                  },
                })
              }
            />
          </label>
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

      {snapshot.outOfDate ? (
        <p className="stale-note">Overrides changed · review is now stale</p>
      ) : null}
      <button className="primary-action" type="submit" disabled={busy}>
        <span>
          {snapshot.operation === "compute"
            ? "Computing"
            : snapshot.reviewed === null
              ? "Generate recommendation"
              : "Recompute recommendation"}
        </span>
        <ArrowRight aria-hidden="true" size={14} />
      </button>
    </form>
  );
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

function compatibleSets(
  capabilities: Capabilities,
  inspection: StructureInspection,
  intent: NonNullable<CalculationDraft["intent"]>,
) {
  const elements = new Set(
    inspection.structure.sites.flatMap((site) =>
      site.species.map((species) => species.symbol),
    ),
  );
  return capabilities.pseudopotential_sets.filter(
    (item) =>
      item.functional === intent.functional &&
      item.accuracy === intent.pseudo_accuracy &&
      [...elements].every((element) =>
        item.supported_elements.includes(element),
      ),
  );
}
