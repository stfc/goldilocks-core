import { Component } from "react";
import { RotateCw, X } from "lucide-react";

import type { StructureInspection } from "./api/coreClient";
import { GuidedControls } from "./controls/GuidedControls";
import { ReviewPanel } from "./review/ReviewPanel";
import { StructureViewport } from "./viewer/StructureViewport";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";

export function App() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/" aria-label="Goldilocks Workbench home">
          <span className="brand__mark" aria-hidden="true">
            G
          </span>
          <span>
            <strong>Goldilocks</strong>
            <small>Workbench</small>
          </span>
        </a>
        <div className="header-context">
          <span className="header-context__line" aria-hidden="true" />
          <span>Guided SCF preparation</span>
        </div>
        <div className="header-status">
          <span className="status-light" aria-hidden="true" />
          <span>
            {snapshot.operation === null
              ? "Ready"
              : operationLabel(snapshot.operation)}
          </span>
          <span className="version-badge">β</span>
        </div>
      </header>

      {snapshot.failure === null ? null : (
        <div className="failure-banner" role="alert">
          <div>
            <strong>{failureTitle(snapshot.failure.kind)}</strong>
            <span>{snapshot.failure.message}</span>
          </div>
          <div className="failure-banner__actions">
            {(snapshot.failure.retryable ||
              snapshot.failureOperation === "capabilities") ? (
              <button
                type="button"
                onClick={() =>
                  void workspace.dispatch({ type: "failure.retry" })
                }
              >
                <RotateCw aria-hidden="true" size={11} />
                Retry
              </button>
            ) : null}
            {snapshot.capabilities === null ? null : (
              <button
                type="button"
                aria-label="Dismiss error"
                onClick={() =>
                  void workspace.dispatch({ type: "failure.dismiss" })
                }
              >
                <X aria-hidden="true" size={13} />
              </button>
            )}
          </div>
        </div>
      )}

      {snapshot.capabilities === null ? (
        <main className="workbench-grid">
          <section className="structure-stage" aria-label="Structure workspace">
            <div className="empty-stage empty-stage--loading" role="status">
              <p className="eyebrow">Goldilocks Core</p>
              <h1>Loading Core capabilities</h1>
              <p>Loading supported calculations, defaults, and catalogs.</p>
            </div>
          </section>
        </main>
      ) : (
        <main className="workbench-grid">
          <GuidedControls />
          <section className="structure-stage" aria-label="Structure workspace">
            {snapshot.inspection === null ? (
              <EmptyStage loading={snapshot.operation === "inspect"} />
            ) : (
              <SafeStructureViewport inspection={snapshot.inspection} />
            )}
            <footer className="stage-footer">
              <span>Scientific decisions by Core</span>
              <span>
                Records remain immutable · overrides trigger recomputation
              </span>
            </footer>
          </section>
          <ReviewPanel />
        </main>
      )}
    </div>
  );
}

interface SafeStructureViewportState {
  readonly failed: boolean;
  readonly attempt: number;
}

class SafeStructureViewport extends Component<
  { readonly inspection: StructureInspection },
  SafeStructureViewportState
> {
  state: SafeStructureViewportState = { failed: false, attempt: 0 };

  static getDerivedStateFromError(): Partial<SafeStructureViewportState> {
    return { failed: true };
  }

  componentDidUpdate(previous: Readonly<{ inspection: StructureInspection }>) {
    if (
      previous.inspection.canonical_cif !==
        this.props.inspection.canonical_cif &&
      this.state.failed
    ) {
      this.setState((state) => ({
        failed: false,
        attempt: state.attempt + 1,
      }));
    }
  }

  private readonly retry = () => {
    this.setState((state) => ({
      failed: false,
      attempt: state.attempt + 1,
    }));
  };

  render() {
    if (this.state.failed) {
      const structure = this.props.inspection.structure;
      return (
        <section className="viewport" aria-label="Crystal structure viewer">
          <div className="viewport__fallback" role="alert">
            <span>3D preview unavailable</span>
            <small>
              {structure.reduced_formula} · {structure.site_count} atomic sites.
              The parsed structure and recommendation remain available.
            </small>
            <button type="button" onClick={this.retry}>
              Retry 3D preview
            </button>
          </div>
        </section>
      );
    }
    return (
      <StructureViewport
        key={this.state.attempt}
        inspection={this.props.inspection}
      />
    );
  }
}

function EmptyStage({ loading }: { readonly loading: boolean }) {
  return (
    <div className={`empty-stage${loading ? " empty-stage--loading" : ""}`}>
      <div className="empty-stage__orbital" aria-hidden="true">
        <span />
        <span />
        <span />
        <i />
      </div>
      <p className="eyebrow">Structure workspace</p>
      <h1>{loading ? "Reading the crystal" : "Start with a structure"}</h1>
      <p>
        {loading
          ? "Canonicalizing sites, lattice, and scientific defaults."
          : "Load a CIF or POSCAR to inspect the crystal, review Core's recommendations, and export a reproducible Quantum ESPRESSO calculation."}
      </p>
      <div className="empty-stage__steps" aria-hidden="true">
        <span>Inspect</span>
        <i />
        <span>Recommend</span>
        <i />
        <span>Archive</span>
      </div>
    </div>
  );
}

function operationLabel(
  operation: "capabilities" | "inspect" | "compute" | "download",
): string {
  switch (operation) {
    case "capabilities":
      return "Loading";
    case "inspect":
      return "Inspecting";
    case "compute":
      return "Computing";
    case "download":
      return "Archiving";
  }
}

function failureTitle(kind: string): string {
  switch (kind) {
    case "invalid_request":
      return "Check the request";
    case "assets_unavailable":
    case "asset_not_installed":
    case "asset_corrupt":
      return "Runtime assets unavailable";
    case "server_busy":
      return "Workbench is busy";
    case "invalid_structure":
      return "Check the structure";
    case "pseudo_table_mismatch":
      return "Pseudopotential set mismatch";
    case "network_error":
      return "Cannot reach Core";
    case "invalid_response":
      return "Unexpected server response";
    default:
      return "Calculation failed";
  }
}
