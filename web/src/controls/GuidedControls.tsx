import { type ChangeEvent, type DragEvent, useRef, useState } from "react";
import { ArrowRight, LoaderCircle, Upload } from "lucide-react";

import type {
  StructureInspection,
  StructureSource,
} from "../api/workbenchClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
const K_GRID_AXES = ["x", "y", "z"] as const;

export function GuidedControls() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);

  async function openFile(file: File): Promise<void> {
    setReadError(null);
    if (file.size > 5 * 1024 * 1024) {
      setReadError("Structure files must be 5 MB or smaller.");
      return;
    }
    if (file.size === 0) {
      setReadError("The selected structure file is empty.");
      return;
    }
    try {
      const content = await file.text();
      const source: StructureSource = {
        name: file.name,
        format: structureFormat(file.name),
        content,
      };
      await workspace.dispatch({ type: "source.open", source });
    } catch {
      setReadError("The selected file could not be read.");
    }
  }

  function fileSelected(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (file !== undefined) void openFile(file);
  }

  function fileDropped(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file !== undefined) void openFile(file);
  }

  return (
    <aside className="control-rail" aria-label="Calculation setup">
      <section className="rail-section rail-section--source">
        <SectionHeading number="01" title="Structure" />
        <div
          className={`file-drop${dragging ? " file-drop--active" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
          }}
          onDragLeave={() => {
            setDragging(false);
          }}
          onDrop={fileDropped}
          aria-busy={snapshot.operation === "inspect"}
        >
          <input ref={input} hidden type="file" onChange={fileSelected} />
          <span className="file-drop__mark" aria-hidden="true">
            {snapshot.operation === "inspect" ? (
              <LoaderCircle className="spinning-icon" size={15} />
            ) : (
              <Upload size={15} />
            )}
          </span>
          {snapshot.source === null ? (
            <>
              <strong>Drop a structure</strong>
              <span>CIF or POSCAR · 5 MB max</span>
            </>
          ) : (
            <>
              <strong>{snapshot.source.name}</strong>
              <span>
                {snapshot.inspection === null
                  ? "Inspecting structure"
                  : `${String(snapshot.inspection.structure.site_count)} sites · parsed`}
              </span>
            </>
          )}
          <button
            className="text-button"
            type="button"
            aria-label={
              snapshot.source === null
                ? "Choose a CIF or POSCAR structure"
                : "Replace structure file"
            }
            onClick={() => {
              input.current?.click();
            }}
            disabled={snapshot.operation === "inspect"}
          >
            {snapshot.source === null ? "Browse files" : "Replace file"}
          </button>
        </div>
        {readError === null ? null : (
          <p className="field-error" role="alert">
            {readError}
          </p>
        )}
        {snapshot.inspection === null ? null : (
          <StructureSummary inspection={snapshot.inspection} />
        )}
      </section>

      <section className="rail-section rail-section--calculation">
        <SectionHeading number="02" title="Calculation" />
        {snapshot.draft === null || snapshot.inspection === null ? (
          <div className="rail-placeholder">
            <span>Waiting for a structure</span>
            <p>Defaults and compatible assets appear after inspection.</p>
          </div>
        ) : (
          <CalculationForm inspection={snapshot.inspection} />
        )}
      </section>
    </aside>
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

function StructureSummary({
  inspection,
}: {
  readonly inspection: StructureInspection;
}) {
  const structure = inspection.structure;
  const elements = [
    ...new Set(
      structure.sites.flatMap((site) =>
        site.species.map((species) => species.symbol),
      ),
    ),
  ];
  return (
    <dl className="structure-summary">
      <div>
        <dt>Formula</dt>
        <dd>{structure.formula}</dd>
      </div>
      <div>
        <dt>Elements</dt>
        <dd>{elements.join(" · ")}</dd>
      </div>
      <div>
        <dt>Cell</dt>
        <dd>{structure.lattice.volume_angstrom3.toFixed(1)} Å³</dd>
      </div>
      <div>
        <dt>Periodic</dt>
        <dd>{structure.periodicity.every(Boolean) ? "3D" : "Partial"}</dd>
      </div>
    </dl>
  );
}

function CalculationForm({
  inspection,
}: {
  readonly inspection: StructureInspection;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const draft = snapshot.draft;
  if (draft === null) return null;

  const tables = compatibleTables(inspection, draft.intent);
  const functionals = [
    ...new Set(inspection.pseudo_tables.map((table) => table.functional)),
  ];
  const kGrid = draft.hints.k_grid;
  const explicitKGrid = kGrid !== null && kGrid !== undefined;
  const spinSetting = formatOptionalSwitch(draft.hints.spin_polarized);
  const vdwSetting = formatOptionalSwitch(draft.hints.use_vdw);
  const inspecting = snapshot.operation === "inspect";
  const busy = snapshot.operation !== null;

  function updateKGrid(index: 0 | 1 | 2, raw: string): void {
    if (kGrid === null || kGrid === undefined) return;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 1 || value > 99) return;
    const next: [number, number, number] = [...kGrid];
    next[index] = value;
    void workspace.dispatch({ type: "draft.patch", hints: { k_grid: next } });
  }

  return (
    <form
      className="calculation-form"
      onSubmit={(event) => {
        event.preventDefault();
        void workspace.dispatch({ type: "review.recompute" });
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
        <select value={draft.intent.task} disabled>
          <option value="scf_single_point">SCF · single point</option>
        </select>
      </label>
      <div className="field-row">
        <label className="field">
          <span>Functional</span>
          <select
            value={draft.intent.functional}
            disabled={inspecting}
            onChange={(event) =>
              void workspace.dispatch({
                type: "draft.patch",
                intent: { functional: event.currentTarget.value },
                pseudoTableId: null,
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
            value={draft.intent.pseudo_accuracy}
            disabled={inspecting}
            onChange={(event) =>
              void workspace.dispatch({
                type: "draft.patch",
                intent: {
                  pseudo_accuracy: event.currentTarget.value as
                    "efficiency" | "precision",
                },
                pseudoTableId: null,
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
          value={draft.pseudo_table_id ?? ""}
          onChange={(event) =>
            void workspace.dispatch({
              type: "draft.patch",
              pseudoTableId: event.currentTarget.value || null,
            })
          }
        >
          <option value="">Selected by Core</option>
          {tables.map((table) => (
            <option key={table.id} value={table.id}>
              {table.provider} · {table.upstream_table}
            </option>
          ))}
        </select>
      </label>

      <details className="advanced-controls">
        <summary>Scientific overrides</summary>
        <p className="advanced-controls__summary">
          {explicitKGrid ? `${kGrid.join("×")} k grid` : "automatic k grid"} ·{" "}
          {draft.hints.smearing_width_ry === null ||
          draft.hints.smearing_width_ry === undefined
            ? "automatic smearing"
            : `${String(draft.hints.smearing_width_ry)} Ry smearing`}{" "}
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
              value={draft.hints.smearing_width_ry ?? ""}
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
              value={optionalSwitchValue(draft.hints.spin_polarized)}
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
              value={optionalSwitchValue(draft.hints.use_vdw)}
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

      {snapshot.reviewStale ? (
        <p className="stale-note">Overrides changed · review is now stale</p>
      ) : null}
      <button className="primary-action" type="submit" disabled={busy}>
        <span>
          {snapshot.operation === "review"
            ? "Computing"
            : snapshot.review === null
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

function compatibleTables(
  inspection: StructureInspection,
  intent: StructureInspection["defaults"]["intent"],
) {
  const elements = new Set(
    inspection.structure.sites.flatMap((site) =>
      site.species.map((species) => species.symbol),
    ),
  );
  return inspection.pseudo_tables.filter(
    (table) =>
      table.functional === intent.functional &&
      table.accuracy === intent.pseudo_accuracy &&
      table.relativistic === "scalar" &&
      [...elements].every((element) => table.elements.includes(element)),
  );
}

function structureFormat(name: string): "cif" | "poscar" {
  return name.toLowerCase().endsWith(".cif") ? "cif" : "poscar";
}
