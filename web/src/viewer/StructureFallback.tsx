import type { Ref } from "react";

import type { StructureInspection } from "../api/coreClient";

export function StructureFallback({
  structure,
  onRetry,
  containerRef,
  hidden = false,
}: {
  readonly structure: StructureInspection["structure"];
  readonly onRetry: () => void;
  readonly containerRef?: Ref<HTMLDivElement>;
  readonly hidden?: boolean;
}) {
  const siteLabel =
    structure.site_count === 1
      ? "1 atomic site"
      : `${String(structure.site_count)} atomic sites`;
  return (
    <div
      ref={containerRef}
      className="viewport__fallback"
      hidden={hidden}
      role="status"
      aria-label="3D structure preview unavailable"
      aria-live="polite"
    >
      <strong>3D preview unavailable</strong>
      <p>
        {structure.reduced_formula} · {siteLabel}
      </p>
      <small>
        The parsed structure and recommendation remain available without the
        interactive preview.
      </small>
      <button type="button" onClick={onRetry}>
        Retry 3D preview
      </button>
    </div>
  );
}
