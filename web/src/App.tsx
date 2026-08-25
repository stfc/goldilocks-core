import {
  Component,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useRef,
  useState,
} from "react";
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

const DEFAULT_PANE_WIDTHS = { controls: 27, review: 32 } as const;
const MIN_PANE_WIDTHS = { controls: 20, review: 25 } as const;
const MAX_SIDEBAR_WIDTH = 70;
const KEYBOARD_RESIZE_STEP = 2;

type Pane = keyof typeof DEFAULT_PANE_WIDTHS;

export function App() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const { theme, toggleTheme } = useTheme();
  const grid = useRef<HTMLElement>(null);
  const [paneWidths, setPaneWidths] = useState(DEFAULT_PANE_WIDTHS);

  function resizePane(pane: Pane, requestedWidth: number): void {
    setPaneWidths((current) => {
      const otherPane = pane === "controls" ? "review" : "controls";
      const maximum = MAX_SIDEBAR_WIDTH - current[otherPane];
      return {
        ...current,
        [pane]: Math.min(
          maximum,
          Math.max(MIN_PANE_WIDTHS[pane], requestedWidth),
        ),
      };
    });
  }

  const gridStyle = {
    "--controls-width": `${String(paneWidths.controls)}%`,
    "--review-width": `${String(paneWidths.review)}%`,
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
          <GuidedControls theme={theme} onToggleTheme={toggleTheme} />
          <PaneResizeHandle
            pane="controls"
            label="Resize calculation setup"
            controls="calculation-panel"
            grid={grid}
            value={paneWidths.controls}
            maximum={MAX_SIDEBAR_WIDTH - paneWidths.review}
            onResize={(value) => {
              resizePane("controls", value);
            }}
          />
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
          </section>
          <PaneResizeHandle
            pane="review"
            label="Resize review panel"
            controls="review-panel"
            grid={grid}
            value={paneWidths.review}
            maximum={MAX_SIDEBAR_WIDTH - paneWidths.controls}
            onResize={(value) => {
              resizePane("review", value);
            }}
          />
          <ReviewPanel />
        </main>
      )}
    </div>
  );
}

function PaneResizeHandle({
  pane,
  label,
  controls,
  grid,
  value,
  maximum,
  onResize,
}: {
  readonly pane: Pane;
  readonly label: string;
  readonly controls: string;
  readonly grid: RefObject<HTMLElement | null>;
  readonly value: number;
  readonly maximum: number;
  readonly onResize: (value: number) => void;
}) {
  const activePointer = useRef<number | null>(null);

  function resizeFromPointer(event: ReactPointerEvent<HTMLDivElement>): void {
    if (activePointer.current !== event.pointerId || grid.current === null) {
      return;
    }
    const bounds = grid.current.getBoundingClientRect();
    if (bounds.width === 0) return;
    const width =
      pane === "controls"
        ? event.clientX - bounds.left
        : bounds.right - event.clientX;
    onResize((width / bounds.width) * 100);
    event.preventDefault();
  }

  function resizeFromKeyboard(event: ReactKeyboardEvent<HTMLDivElement>): void {
    let next: number | null = null;
    switch (event.key) {
      case "ArrowLeft":
        next =
          value +
          (pane === "review" ? KEYBOARD_RESIZE_STEP : -KEYBOARD_RESIZE_STEP);
        break;
      case "ArrowRight":
        next =
          value +
          (pane === "controls" ? KEYBOARD_RESIZE_STEP : -KEYBOARD_RESIZE_STEP);
        break;
      case "Home":
        next = MIN_PANE_WIDTHS[pane];
        break;
      case "End":
        next = maximum;
        break;
    }
    if (next === null) return;
    event.preventDefault();
    onResize(next);
  }

  return (
    <div
      className={`pane-resizer pane-resizer--${pane}`}
      role="separator"
      aria-label={label}
      aria-controls={controls}
      aria-orientation="vertical"
      aria-valuemin={MIN_PANE_WIDTHS[pane]}
      aria-valuemax={Math.round(maximum)}
      aria-valuenow={Math.round(value)}
      aria-valuetext={`${String(Math.round(value))}% of workspace width`}
      tabIndex={0}
      title="Drag or use arrow keys to resize"
      onKeyDown={resizeFromKeyboard}
      onDoubleClick={() => {
        onResize(DEFAULT_PANE_WIDTHS[pane]);
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
