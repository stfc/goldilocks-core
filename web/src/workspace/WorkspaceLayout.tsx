import { VisuallyHidden } from "@mantine/core";
import {
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  useRef,
  useState,
} from "react";

const DEFAULT_WIDTH = 34;
const MIN_WIDTH = 24;
const MAX_WIDTH = 42;
const KEYBOARD_STEP = 2;

export function WorkspaceLayout({
  controls,
  children,
}: {
  readonly controls: ReactNode;
  readonly children: ReactNode;
}) {
  const grid = useRef<HTMLElement>(null);
  const activePointer = useRef<number | null>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);

  function resize(value: number) {
    setWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value)));
  }

  function resizeFromPointer(event: PointerEvent<HTMLDivElement>) {
    if (activePointer.current !== event.pointerId || grid.current === null)
      return;
    const bounds = grid.current.getBoundingClientRect();
    if (bounds.width === 0) return;
    resize(((event.clientX - bounds.left) / bounds.width) * 100);
    event.preventDefault();
  }

  function resizeFromKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case "ArrowLeft":
        resize(width - KEYBOARD_STEP);
        break;
      case "ArrowRight":
        resize(width + KEYBOARD_STEP);
        break;
      case "Home":
        resize(MIN_WIDTH);
        break;
      case "End":
        resize(MAX_WIDTH);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  return (
    <main
      ref={grid}
      className={
        controls === null
          ? "workbench-grid workbench-grid--loading"
          : "workbench-grid"
      }
      style={{ "--controls-width": `${String(width)}%` } as CSSProperties}
      aria-labelledby="workbench-title"
    >
      <VisuallyHidden>
        <h1 id="workbench-title">Goldilocks SCF setup</h1>
      </VisuallyHidden>
      {controls}
      {controls !== null && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Focusable ARIA window splitters are interactive separators, with range values and keyboard support.
        <div
          className="pane-resizer"
          role="separator"
          aria-label="Resize calculation setup"
          aria-controls="calculation-panel"
          aria-orientation="vertical"
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          aria-valuenow={Math.round(width)}
          aria-valuetext={`${String(Math.round(width))}% of workspace width`}
          tabIndex={0}
          title="Drag or use arrow keys to resize"
          onKeyDown={resizeFromKeyboard}
          onDoubleClick={() => {
            resize(DEFAULT_WIDTH);
          }}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            activePointer.current = event.pointerId;
            event.currentTarget.setPointerCapture(event.pointerId);
            event.preventDefault();
          }}
          onPointerMove={resizeFromPointer}
          onPointerUp={(event) => {
            if (activePointer.current === event.pointerId)
              activePointer.current = null;
          }}
          onPointerCancel={() => {
            activePointer.current = null;
          }}
          onLostPointerCapture={() => {
            activePointer.current = null;
          }}
        />
      )}
      {children}
    </main>
  );
}
