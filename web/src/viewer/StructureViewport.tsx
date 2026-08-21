import { useEffect, useRef } from "react";

import type { StructureInspection } from "../api/workbenchClient";
import {
  attachStructureViewer,
  type StructureViewer,
  type StructureViewerFactory,
} from "./structureViewer";

export function StructureViewport({
  inspection,
  createViewer = attachStructureViewer,
}: {
  readonly inspection: StructureInspection;
  readonly createViewer?: StructureViewerFactory;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<StructureViewer | null>(null);
  const fallback = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (host.current === null) return;
    try {
      viewer.current = createViewer(host.current);
      if (fallback.current !== null) fallback.current.hidden = true;
    } catch {
      if (fallback.current !== null) fallback.current.hidden = false;
    }
    return () => {
      viewer.current?.dispose();
      viewer.current = null;
    };
  }, [createViewer]);

  useEffect(() => {
    if (viewer.current === null) return;
    try {
      viewer.current.show(inspection.canonical_cif);
      if (fallback.current !== null) fallback.current.hidden = true;
    } catch {
      if (fallback.current !== null) fallback.current.hidden = false;
    }
  }, [inspection.canonical_cif]);

  const lattice = inspection.structure.lattice;
  return (
    <section className="viewport" aria-label="Crystal structure viewer">
      <div className="viewport__canvas" ref={host} />
      <div ref={fallback} className="viewport__fallback" role="status" hidden>
        <span>3D preview unavailable</span>
        <small>The parsed structure and recommendation remain available.</small>
      </div>
      <div className="viewport__eyebrow">
        <span className="status-light" aria-hidden="true" />
        Canonical structure
      </div>
      <h1 className="viewport__title">
        <strong>{inspection.structure.reduced_formula}</strong>
        <span>{inspection.structure.site_count} atomic sites</span>
      </h1>
      <dl className="viewport__metrics">
        <div>
          <dt>a</dt>
          <dd>{formatLength(lattice.lengths_angstrom[0])}</dd>
        </div>
        <div>
          <dt>b</dt>
          <dd>{formatLength(lattice.lengths_angstrom[1])}</dd>
        </div>
        <div>
          <dt>c</dt>
          <dd>{formatLength(lattice.lengths_angstrom[2])}</dd>
        </div>
        <div>
          <dt>V</dt>
          <dd>{lattice.volume_angstrom3.toFixed(2)} Å³</dd>
        </div>
      </dl>
      <div className="viewport__hint">Drag to orbit · Scroll to zoom</div>
    </section>
  );
}

function formatLength(value: number): string {
  return `${value.toFixed(3)} Å`;
}
