import { lazy, Suspense } from "react";
import { RotateCw, X } from "lucide-react";

import { GuidedControls } from "./controls/GuidedControls";
import { ReviewPanel } from "./review/ReviewPanel";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";

const StructureViewport = lazy(() =>
  import("./viewer/StructureViewport").then((module) => ({
    default: module.StructureViewport,
  })),
);

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
          <span>{snapshot.operation === null ? "Ready" : operationLabel(snapshot.operation)}</span>
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
            {snapshot.failure.retryable ? (
              <button
                type="button"
                onClick={() => void workspace.dispatch({ type: "failure.retry" })}
              >
                <RotateCw aria-hidden="true" size={11} />
                Retry
              </button>
            ) : null}
            <button
              type="button"
              aria-label="Dismiss error"
              onClick={() => void workspace.dispatch({ type: "failure.dismiss" })}
            >
              <X aria-hidden="true" size={13} />
            </button>
          </div>
        </div>
      )}

      <main className="workbench-grid">
        <GuidedControls />
        <section className="structure-stage" aria-label="Structure workspace">
          {snapshot.inspection === null ? (
            <EmptyStage loading={snapshot.operation === "inspect"} />
          ) : (
            <Suspense
              fallback={
                <div className="viewer-loading" role="status">
                  Loading crystal viewer
                </div>
              }
            >
              <StructureViewport inspection={snapshot.inspection} />
            </Suspense>
          )}
          <footer className="stage-footer">
            <span>Scientific decisions by Core</span>
            <span>Records remain immutable · overrides trigger recomputation</span>
          </footer>
        </section>
        <ReviewPanel />
      </main>
    </div>
  );
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

function operationLabel(operation: "inspect" | "review" | "archive"): string {
  switch (operation) {
    case "inspect":
      return "Inspecting";
    case "review":
      return "Computing";
    case "archive":
      return "Archiving";
  }
}

function failureTitle(kind: string): string {
  switch (kind) {
    case "invalid_request":
      return "Check the request";
    case "assets_unavailable":
      return "Runtime assets unavailable";
    case "server_busy":
      return "Workbench is busy";
    case "stale_review":
      return "Review changed";
    case "network_error":
      return "Cannot reach Core";
    case "invalid_response":
      return "Unexpected server response";
    default:
      return "Calculation failed";
  }
}
