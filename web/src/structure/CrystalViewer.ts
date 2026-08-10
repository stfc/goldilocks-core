import type { StructureDocument } from '../client/types';

/**
 * Library-neutral 3D crystal viewer.
 *
 * The Workbench component depends on this interface only; no 3D library
 * object, event, or type crosses this seam. The 3Dmol-backed implementation
 * lives in `ThreeDmolViewer.ts` and is imported lazily behind this interface.
 *
 * A single adapter instance is bound to one mounted container and must be
 * `dispose()`d when that container unmounts. Callers update a live adapter
 * with `setOptions`/`resetCamera` rather than recreating it; `load` supersedes
 * any earlier load and resolves only for the latest requested structure.
 */

/** Presentation choices the Workbench exposes for the crystal view. */
export type ViewerRepresentation = 'ball-stick' | 'spacefill';

export type ViewerOptions = {
  representation: ViewerRepresentation;
  /** Unit-cell replication along a/b/c, at least 1 in each axis. */
  repetitions: readonly [number, number, number];
  /** Draw the unit-cell box. */
  showCell: boolean;
};

export const DEFAULT_VIEWER_OPTIONS: ViewerOptions = {
  representation: 'ball-stick',
  repetitions: [1, 1, 1],
  showCell: true,
};

export interface CrystalViewerAdapter {
  /**
   * Render `structure`, superseding any prior render. Resolves once the view
   * is drawn. A later `load` (or `dispose`) invalidates this one; an
   * invalidated load resolves without touching the viewer.
   */
  load(structure: StructureDocument): Promise<void>;
  /** Apply presentation options to the live view. */
  setOptions(options: ViewerOptions): void;
  /** Reset the camera to the default framing. */
  resetCamera(): void;
  /** Export the current view as a PNG blob, or `null` when unavailable. */
  exportPng(): Promise<Blob> | null;
  /** Release the viewer, its resources, and container children. */
  dispose(): void;
}

/**
 * Creates an adapter bound to `container`. Used as the component's default
 * factory and injected as the internal test seam.
 */
export type CrystalViewerAdapterFactory = (
  container: HTMLElement,
) => CrystalViewerAdapter;
