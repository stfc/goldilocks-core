import { useEffect, useRef, useState } from "react";

import type { StructureInspection } from "../api/coreClient";
import { StructureFallback } from "./StructureFallback";
import "./StructureViewport.css";
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
  const [viewerRevision, setViewerRevision] = useState(0);

  useEffect(() => {
    if (host.current === null) return;
    try {
      viewer.current = createViewer(host.current);
      if (fallback.current !== null) fallback.current.hidden = true;
    } catch {
      viewer.current = null;
      if (fallback.current !== null) fallback.current.hidden = false;
    }
    return () => {
      viewer.current?.dispose();
      viewer.current = null;
    };
  }, [createViewer, viewerRevision]);

  useEffect(() => {
    if (viewer.current === null) return;
    try {
      viewer.current.show(inspection.canonical_cif);
      if (fallback.current !== null) fallback.current.hidden = true;
    } catch {
      if (fallback.current !== null) fallback.current.hidden = false;
    }
  }, [inspection.canonical_cif, viewerRevision]);

  const lattice = inspection.structure.lattice;
  return (
    <section className="viewport" aria-label="Crystal structure viewer">
      <div className="viewport__canvas" ref={host} />
      <StructureFallback
        structure={inspection.structure}
        containerRef={fallback}
        hidden
        onRetry={() => {
          setViewerRevision((revision) => revision + 1);
        }}
      />
      <div className="viewport__eyebrow">
        <span className="status-light" aria-hidden="true" />
        Canonical structure
      </div>
      <h2 className="viewport__title">
        <strong>{inspection.structure.reduced_formula}</strong>
        <span>{inspection.structure.site_count} atomic sites</span>
      </h2>
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
