import {
  type KeyboardEvent,
  type PointerEvent,
  useRef,
  useState,
} from "react";

import type { ComputationResult } from "../api/coreClient";
import { artifactDigest } from "./artifacts";

const DEFAULT_INPUT_HEIGHT = 352;
const MIN_INPUT_HEIGHT = 160;
const KEYBOARD_RESIZE_STEP = 32;

export function GeneratedInputReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [inputHeight, setInputHeight] = useState<number | null>(null);
  const [fullHeight, setFullHeight] = useState(DEFAULT_INPUT_HEIGHT);
  const input = useRef<HTMLPreElement | null>(null);
  const activePointer = useRef<{
    readonly id: number;
    readonly startHeight: number;
    readonly startY: number;
  } | null>(null);
  const files = result.records.generated_files ?? [];
  const file =
    files.find((candidate) => candidate.path === selectedPath) ?? files[0];
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
    const currentHeight = inputHeight ?? Math.min(DEFAULT_INPUT_HEIGHT, fullHeight);
    let nextHeight: number | null = null;
    switch (event.key) {
      case "ArrowUp":
        nextHeight = currentHeight - KEYBOARD_RESIZE_STEP;
        break;
      case "ArrowDown":
        nextHeight = currentHeight + KEYBOARD_RESIZE_STEP;
        break;
      case "Home":
        nextHeight = MIN_INPUT_HEIGHT;
        break;
      case "End":
        nextHeight = fullHeight;
        break;
    }
    if (nextHeight === null) return;
    event.preventDefault();
    resizeInput(nextHeight);
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
    <section className="review-section generated-review">
      <header>
        <span className="review-section__index">A</span>
        <div>
          <h3>Generated inputs</h3>
          <p>{files.length} files</p>
        </div>
      </header>
      {file === undefined ? (
        <p className="no-files">No generated input files.</p>
      ) : (
        <>
          <div
            className="file-tabs"
            role="group"
            aria-label="Generated input files"
          >
            {files.map((candidate) => (
              <button
                key={candidate.path}
                type="button"
                aria-pressed={candidate.path === file.path}
                onClick={() => {
                  setSelectedPath(candidate.path);
                }}
              >
                {candidate.path.split("/").at(-1)}
              </button>
            ))}
          </div>
          <div className="code-frame">
            <div>
              <span>{file.path}</span>
              {result.records.dft_input_data === undefined ? null : (
                <code>
                  {artifactDigest(
                    result.records.dft_input_data.artifacts,
                    file.path,
                  )?.slice(0, 10) ?? "unlisted"}
                </code>
              )}
            </div>
            <pre
              key={`${file.path}\0${file.content}`}
              id="generated-input-content"
              ref={measureInput}
              className={inputHeight === null ? undefined : "generated-input--sized"}
              style={inputHeight === null ? undefined : { height: inputHeight }}
              aria-label={`Generated input ${file.path}`}
              tabIndex={0}
            >
              {file.content}
            </pre>
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
        </>
      )}
    </section>
  );
}
