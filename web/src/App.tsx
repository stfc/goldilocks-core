import {
  Component,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { ArrowRight } from "lucide-react";

import type { StructureInspection } from "./api/coreClient";
import { GuidedControls } from "./controls/GuidedControls";
import { ReviewPanel } from "./review/ReviewPanel";
import { FailureBanner } from "./status/FailureBanner";
import { OperationStatus } from "./status/OperationStatus";
import { type Theme, useTheme } from "./theme";
import { StructureFallback } from "./viewer/StructureFallback";
import { StructureViewport } from "./viewer/StructureViewport";
import { useWorkspace, useWorkspaceSnapshot } from "./workspace/useWorkspace";
import "./App.css";

const DEFAULT_CONTROLS_WIDTH = 34;
const MIN_CONTROLS_WIDTH = 24;
const MAX_CONTROLS_WIDTH = 42;
const KEYBOARD_RESIZE_STEP = 2;

type WorkspaceView = "structure" | "recommendation";

export function App() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { theme, toggleTheme } = useTheme();
  const grid = useRef<HTMLElement>(null);
  const [controlsWidth, setControlsWidth] = useState(DEFAULT_CONTROLS_WIDTH);
  const [workspaceView, setWorkspaceView] =
    useState<WorkspaceView>("structure");

  useLayoutEffect(() => {
    if (workspaceView !== "recommendation") return;
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [workspaceView]);

  function resizeControls(requestedWidth: number): void {
    setControlsWidth(
      Math.min(
        MAX_CONTROLS_WIDTH,
        Math.max(MIN_CONTROLS_WIDTH, requestedWidth),
      ),
    );
  }

  const gridStyle = {
    "--controls-width": `${String(controlsWidth)}%`,
  } as CSSProperties;

  return (
    <div className="app-shell">
      <OperationStatus
        operation={snapshot.operation}
        hasFailure={snapshot.failure !== null}
      />

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
        <main
          className="workbench-grid workbench-grid--loading"
          aria-labelledby="workbench-title"
        >
          <h1 id="workbench-title" className="visually-hidden">
            Goldilocks SCF setup
          </h1>
          <section className="structure-stage" aria-label="Structure workspace">
            <div className="empty-stage empty-stage--loading" role="status">
              <div className="empty-stage__orbital" aria-hidden="true">
                <span />
                <span />
                <span />
                <i />
              </div>
              <h1>Loading Workbench</h1>
            </div>
          </section>
        </main>
      ) : (
        <main
          ref={grid}
          className="workbench-grid"
          style={gridStyle}
          aria-labelledby="workbench-title"
        >
          <h1 id="workbench-title" className="visually-hidden">
            Goldilocks SCF setup
          </h1>
          <GuidedControls
            theme={theme}
            onToggleTheme={toggleTheme}
            onShowStructure={() => {
              setWorkspaceView("structure");
            }}
            onShowRecommendation={() => {
              setWorkspaceView("recommendation");
            }}
          />
          <PanelResizeHandle
            grid={grid}
            value={controlsWidth}
            onResize={resizeControls}
          />
          {workspaceView === "recommendation" ? (
            <ReviewPanel
              onShowStructure={() => {
                setWorkspaceView("structure");
              }}
            />
          ) : (
            <section
              id="structure-panel"
              className="structure-stage"
              aria-label="Structure workspace"
            >
              {snapshot.inspection === null ? (
                <EmptyStage loading={snapshot.operation === "inspect"} />
              ) : (
                <SafeStructureViewport
                  inspection={snapshot.inspection}
                  theme={theme}
                />
              )}
              {snapshot.reviewed === null ? null : (
                <button
                  className="stage-navigation"
                  type="button"
                  onClick={() => {
                    setWorkspaceView("recommendation");
                  }}
                >
                  Recommendation
                  <ArrowRight aria-hidden="true" size={15} />
                </button>
              )}
            </section>
          )}
        </main>
      )}
    </div>
  );
}

function PanelResizeHandle({
  grid,
  value,
  onResize,
}: {
  readonly grid: RefObject<HTMLElement | null>;
  readonly value: number;
  readonly onResize: (value: number) => void;
}) {
  const activePointer = useRef<number | null>(null);

  function resizeFromPointer(event: ReactPointerEvent<HTMLDivElement>): void {
    if (activePointer.current !== event.pointerId || grid.current === null) {
      return;
    }
    const bounds = grid.current.getBoundingClientRect();
    if (bounds.width === 0) return;
    onResize(((event.clientX - bounds.left) / bounds.width) * 100);
    event.preventDefault();
  }

  function resizeFromKeyboard(event: ReactKeyboardEvent<HTMLDivElement>): void {
    let next: number | null = null;
    switch (event.key) {
      case "ArrowLeft":
        next = value - KEYBOARD_RESIZE_STEP;
        break;
      case "ArrowRight":
        next = value + KEYBOARD_RESIZE_STEP;
        break;
      case "Home":
        next = MIN_CONTROLS_WIDTH;
        break;
      case "End":
        next = MAX_CONTROLS_WIDTH;
        break;
    }
    if (next === null) return;
    event.preventDefault();
    onResize(next);
  }

  return (
    <div
      className="pane-resizer"
      role="separator"
      aria-label="Resize calculation setup"
      aria-controls="calculation-panel"
      aria-orientation="vertical"
      aria-valuemin={MIN_CONTROLS_WIDTH}
      aria-valuemax={MAX_CONTROLS_WIDTH}
      aria-valuenow={Math.round(value)}
      aria-valuetext={`${String(Math.round(value))}% of workspace width`}
      tabIndex={0}
      title="Drag or use arrow keys to resize"
      onKeyDown={resizeFromKeyboard}
      onDoubleClick={() => {
        onResize(DEFAULT_CONTROLS_WIDTH);
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        activePointer.current = event.pointerId;
        event.currentTarget.setPointerCapture(event.pointerId);
        event.preventDefault();
      }}
      onPointerMove={resizeFromPointer}
      onPointerUp={(event) => {
        if (activePointer.current === event.pointerId) {
          activePointer.current = null;
        }
      }}
      onPointerCancel={() => {
        activePointer.current = null;
      }}
      onLostPointerCapture={() => {
        activePointer.current = null;
      }}
    />
  );
}

interface SafeStructureViewportState {
  readonly failed: boolean;
  readonly attempt: number;
}

class SafeStructureViewport extends Component<
  { readonly inspection: StructureInspection; readonly theme: Theme },
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
        key={`${String(this.state.attempt)}-${this.props.theme}`}
        inspection={this.props.inspection}
      />
    );
  }
}

function EmptyStage({ loading }: { readonly loading: boolean }) {
  return (
    <div
      className={`empty-stage${loading ? " empty-stage--loading" : ""}`}
      role={loading ? "status" : undefined}
    >
      <div className="empty-stage__orbital" aria-hidden="true">
        <span />
        <span />
        <span />
        <i />
      </div>
      <h2>{loading ? "Reading structure" : "No structure selected"}</h2>
    </div>
  );
}
