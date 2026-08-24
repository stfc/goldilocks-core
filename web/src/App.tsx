import { Component } from "react";

import type { StructureInspection } from "./api/coreClient";
import { GuidedControls } from "./controls/GuidedControls";
import { ReviewPanel } from "./review/ReviewPanel";
import { FailureBanner } from "./status/FailureBanner";
import { OperationStatus } from "./status/OperationStatus";
import { StructureFallback } from "./viewer/StructureFallback";
import { StructureViewport } from "./viewer/StructureViewport";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";
import "./App.css";

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
        <OperationStatus
          operation={snapshot.operation}
          hasFailure={snapshot.failure !== null}
        />
      </header>

      {snapshot.failure === null ? null : (
        <FailureBanner
          failure={snapshot.failure}
          retryAvailable={
            snapshot.failure.retryable ||
            snapshot.failureOperation === "capabilities"
          }
          dismissAvailable={snapshot.capabilities !== null}
          onRetry={() => {
            void workspace.dispatch({ type: "failure.retry" });
          }}
          onDismiss={() => {
            void workspace.dispatch({ type: "failure.dismiss" });
          }}
        />
      )}

      {snapshot.capabilities === null ? (
        <main className="workbench-grid" aria-labelledby="workbench-title">
          <h1 id="workbench-title" className="visually-hidden">
            Goldilocks guided SCF preparation
          </h1>
          <section className="structure-stage" aria-label="Structure workspace">
            <div className="empty-stage empty-stage--loading" role="status">
              <p className="eyebrow">Goldilocks Core</p>
              <h1>Loading Core capabilities</h1>
              <p>Loading supported calculations, defaults, and catalogs.</p>
            </div>
          </section>
        </main>
      ) : (
        <main className="workbench-grid" aria-labelledby="workbench-title">
          <h1 id="workbench-title" className="visually-hidden">
            Goldilocks guided SCF preparation
          </h1>
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
          <StructureFallback structure={structure} onRetry={this.retry} />
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
      <h2>{loading ? "Reading the crystal" : "Start with a structure"}</h2>
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
