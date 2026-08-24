import { type ChangeEvent, type DragEvent, useRef, useState } from "react";
import { LoaderCircle, Upload } from "lucide-react";

import type {
  StructureInspection,
  StructureSource,
} from "../api/coreClient";

export function StructureSourceControls({
  source,
  inspection,
  inspecting,
  onOpen,
}: {
  readonly source: StructureSource | null;
  readonly inspection: StructureInspection | null;
  readonly inspecting: boolean;
  readonly onOpen: (source: StructureSource) => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const selectionEpoch = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);

  async function openFile(file: File): Promise<void> {
    const selection = ++selectionEpoch.current;
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
      if (selection !== selectionEpoch.current) return;
      await onOpen({
        kind: "inline",
        name: file.name,
        format: structureFormat(file.name),
        content,
      });
    } catch {
      if (selection === selectionEpoch.current) {
        setReadError("The selected file could not be read.");
      }
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
    <>
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
        aria-busy={inspecting}
      >
        <input ref={input} hidden type="file" onChange={fileSelected} />
        <span className="file-drop__mark" aria-hidden="true">
          {inspecting ? (
            <LoaderCircle className="spinning-icon" size={18} />
          ) : (
            <Upload size={18} />
          )}
        </span>
        {source === null ? (
          <>
            <strong>Drop a structure</strong>
            <span id="structure-source-help">
              CIF or POSCAR · 5 MB maximum file size
            </span>
          </>
        ) : (
          <>
            <strong>{source.name}</strong>
            <span id="structure-source-help">
              {inspection === null
                ? "Inspecting structure"
                : `${String(inspection.structure.site_count)} sites · parsed`}
            </span>
          </>
        )}
        <button
          className="text-button"
          type="button"
          aria-describedby="structure-source-help"
          aria-label={
            source === null
              ? "Choose a CIF or POSCAR structure"
              : "Replace structure file"
          }
          onClick={() => {
            input.current?.click();
          }}
          disabled={inspecting}
        >
          {source === null ? "Browse files" : "Replace file"}
        </button>
      </div>
      {readError === null ? null : (
        <p className="field-error" role="alert">
          {readError}
        </p>
      )}
      {inspection === null ? null : (
        <StructureSummary inspection={inspection} />
      )}
    </>
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
    <dl className="structure-summary" aria-label="Inspected structure summary">
      <div>
        <dt>Formula</dt>
        <dd>{structure.formula}</dd>
      </div>
      <div>
        <dt>Elements</dt>
        <dd>{elements.join(" · ")}</dd>
      </div>
      <div>
        <dt>Cell volume</dt>
        <dd>{structure.lattice.volume_angstrom3.toFixed(1)} Å³</dd>
      </div>
      <div>
        <dt>Periodicity</dt>
        <dd>{structure.periodicity.every(Boolean) ? "3D" : "Partial"}</dd>
      </div>
    </dl>
  );
}

function structureFormat(name: string): "cif" | "poscar" {
  return name.toLowerCase().endsWith(".cif") ? "cif" : "poscar";
}
