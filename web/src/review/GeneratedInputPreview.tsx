import { Group } from "@mantine/core";
import { type KeyboardEvent, type PointerEvent, useRef, useState } from "react";

const DEFAULT_INPUT_HEIGHT = 352;
const MIN_INPUT_HEIGHT = 160;
const KEYBOARD_RESIZE_STEP = 32;
const KEYBOARD_RESIZE_DELTAS: Readonly<Record<string, number>> = {
  ArrowUp: -KEYBOARD_RESIZE_STEP,
  ArrowDown: KEYBOARD_RESIZE_STEP,
  Home: -Infinity,
  End: Infinity,
};

export function GeneratedInputPreview({
  path,
  content,
  digest,
}: {
  readonly path: string;
  readonly content: string;
  readonly digest: string | null | undefined;
}) {
  const [inputHeight, setInputHeight] = useState<number | null>(null);
  const [fullHeight, setFullHeight] = useState(DEFAULT_INPUT_HEIGHT);
  const input = useRef<HTMLPreElement | null>(null);
  const activePointer = useRef<{
    readonly id: number;
    readonly startHeight: number;
    readonly startY: number;
  } | null>(null);

  function measureInput(element: HTMLPreElement | null): void {
    if (element === null || input.current === element) return;
    input.current = element;
    element.style.height = "auto";
    const measuredFullHeight = Math.max(MIN_INPUT_HEIGHT, element.scrollHeight);
    const initialHeight = Math.min(DEFAULT_INPUT_HEIGHT, measuredFullHeight);
    element.style.height = `${String(initialHeight)}px`;
    setFullHeight(measuredFullHeight);
    setInputHeight(initialHeight);
  }

  function resizeInput(requestedHeight: number): void {
    setInputHeight(
      Math.min(fullHeight, Math.max(MIN_INPUT_HEIGHT, requestedHeight)),
    );
  }

  function resizeFromKeyboard(event: KeyboardEvent<HTMLDivElement>): void {
    const currentHeight =
      inputHeight ?? Math.min(DEFAULT_INPUT_HEIGHT, fullHeight);
    const delta = KEYBOARD_RESIZE_DELTAS[event.key];
    if (typeof delta !== "number") return;
    event.preventDefault();
    // Endpoint keys saturate the same bounds as drag and arrow-key requests.
    resizeInput(currentHeight + delta);
  }

  function resizeFromPointer(event: PointerEvent<HTMLDivElement>): void {
    const active = activePointer.current;
    if (active?.id !== event.pointerId) return;
    resizeInput(active.startHeight + event.clientY - active.startY);
  }

  function stopPointerResize(event: PointerEvent<HTMLDivElement>): void {
    if (activePointer.current?.id !== event.pointerId) return;
    activePointer.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  const displayedHeight =
    inputHeight ?? Math.min(DEFAULT_INPUT_HEIGHT, fullHeight);
  return (
    <div className="code-frame">
      <Group
        className="code-frame__heading"
        justify="space-between"
        align="stretch"
        wrap="nowrap"
        gap={12}
        py={8}
        px={12}
      >
        <span>{path}</span>
        {digest === undefined ? null : (
          <code>{digest?.slice(0, 10) ?? "unlisted"}</code>
        )}
      </Group>
      <pre
        role="region"
        key={`${path}\0${content}`}
        id="generated-input-content"
        ref={measureInput}
        className={inputHeight === null ? undefined : "generated-input--sized"}
        style={inputHeight === null ? undefined : { height: inputHeight }}
        aria-label={`Generated input ${path}`}
        tabIndex={0}
      >
        {content}
      </pre>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Focusable ARIA window splitters are interactive separators, with range values and keyboard support. */}
      <div
        className="code-resizer"
        role="separator"
        aria-label="Resize generated input"
        aria-controls="generated-input-content"
        aria-orientation="horizontal"
        aria-valuemin={MIN_INPUT_HEIGHT}
        aria-valuemax={Math.round(fullHeight)}
        aria-valuenow={Math.round(displayedHeight)}
        aria-valuetext={
          displayedHeight >= fullHeight
            ? "Full input file visible"
            : `${String(Math.round(displayedHeight))} pixels high`
        }
        tabIndex={0}
        title="Drag or use arrow keys to resize the generated input"
        onKeyDown={resizeFromKeyboard}
        onDoubleClick={() => {
          resizeInput(fullHeight);
        }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          activePointer.current = {
            id: event.pointerId,
            startHeight: displayedHeight,
            startY: event.clientY,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          event.preventDefault();
        }}
        onPointerMove={resizeFromPointer}
        onPointerUp={stopPointerResize}
        onPointerCancel={stopPointerResize}
      />
    </div>
  );
}
