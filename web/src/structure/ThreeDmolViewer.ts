import type { AtomSpec, GLViewer } from '3dmol';
import type { StructureDocument } from '../client/types';
import {
  DEFAULT_VIEWER_OPTIONS,
  type CrystalViewerAdapter,
  type CrystalViewerAdapterFactory,
  type ViewerOptions,
} from './CrystalViewer';

type ThreeDmolModule = typeof import('3dmol');

/** Supplies the 3Dmol module; injectable for deterministic tests. */
type ThreeDmolModuleLoader = () => Promise<ThreeDmolModule>;

/** Warm stone, consistent with the Workbench's ink/stone neutrals. */
const CELL_COLOR = '#8a5a0d';

const BALL_STICK_STYLE = {
  stick: { radius: 0.16 },
  sphere: { scale: 0.3 },
};

const SPACEFILL_STYLE = {
  sphere: { scale: 0.55 },
};

/**
 * The single element used to render a site in 3D: the species with the highest
 * occupancy. Mixed/partial-occupancy sites are therefore approximated on
 * screen; the canonical Structure Document preserves every species and
 * occupancy exactly, and the Workbench discloses this limitation beside the
 * 3D view. The full canonical structure is still passed to the viewer so
 * nothing is lost at the model boundary.
 */
function representativeElement(site: StructureDocument['sites'][number]): string {
  return site.species.reduce((best, current) =>
    current.occupancy > best.occupancy ? current : best,
  ).element;
}

function atomsFromStructure(structure: StructureDocument): AtomSpec[] {
  return structure.sites.map((site, index) => ({
    x: site.xyz[0],
    y: site.xyz[1],
    z: site.xyz[2],
    elem: representativeElement(site),
    atom: site.label,
    serial: index + 1,
  }));
}

/**
 * 3Dmol.js-backed implementation of the library-neutral crystal viewer.
 *
 * All 3Dmol objects and types are confined to this module. The dynamic
 * `import('3dmol')` is deferred until the first `load`, so the library is code
 * split into a lazy chunk only fetched when a viewer mounts. One `GLViewer` is
 * created per container and updated across loads/option changes rather than
 * recreated; `dispose` best-effort releases what 3Dmol exposes. Real-browser
 * leak inspection (canvases, listeners, animation frames, WebGL resources)
 * remains final integration verification — jsdom cannot prove GPU cleanup.
 */
export class ThreeDmolViewer implements CrystalViewerAdapter {
  private mod: ThreeDmolModule | null = null;
  private viewer: GLViewer | null = null;
  private options: ViewerOptions = { ...DEFAULT_VIEWER_OPTIONS };
  private lastStructure: StructureDocument | null = null;
  private generation = 0;
  private disposed = false;

  constructor(
    private readonly container: HTMLElement,
    private readonly loadModule: ThreeDmolModuleLoader = () => import('3dmol'),
  ) {}

  async load(structure: StructureDocument): Promise<void> {
    const gen = ++this.generation;
    const mod = await this.getModule();
    if (this.disposed || gen !== this.generation) {
      return; // superseded by a newer load or disposed; never render stale data.
    }
    this.lastStructure = structure;
    this.render(mod);
  }

  setOptions(options: ViewerOptions): void {
    const changed =
      options.representation !== this.options.representation ||
      options.showCell !== this.options.showCell ||
      options.repetitions[0] !== this.options.repetitions[0] ||
      options.repetitions[1] !== this.options.repetitions[1] ||
      options.repetitions[2] !== this.options.repetitions[2];
    this.options = { ...options };
    if (changed && this.viewer !== null && this.lastStructure !== null) {
      void this.load(this.lastStructure);
    }
  }

  resetCamera(): void {
    this.viewer?.zoomTo();
  }

  exportPng(): Promise<Blob> | null {
    const dataUri = this.viewer?.pngURI();
    if (!dataUri) return null;
    return fetch(dataUri).then((response) => response.blob());
  }

  dispose(): void {
    this.disposed = true;
    this.generation += 1; // invalidate any in-flight load
    this.viewer?.clear();
    this.viewer = null;
    this.mod = null;
    this.lastStructure = null;
    // Remove the library-owned canvas and any other container children so the
    // unmounted container does not keep rendering.
    while (this.container.firstChild) {
      this.container.removeChild(this.container.firstChild);
    }
  }

  private async getModule(): Promise<ThreeDmolModule> {
    if (this.mod === null) {
      this.mod = await this.loadModule();
    }
    return this.mod;
  }

  private getViewer(mod: ThreeDmolModule): GLViewer {
    if (this.viewer === null) {
      this.viewer = mod.createViewer(this.container, {
        backgroundColor: '#faf8f5',
        antialias: true,
      });
    }
    return this.viewer;
  }

  private render(mod: ThreeDmolModule): void {
    const structure = this.lastStructure;
    const viewer = this.getViewer(mod);
    if (!structure) return;

    // Replace the model contents on the live viewer; the GLViewer itself is
    // kept across updates.
    viewer.removeAllModels();
    const model = viewer.addModel();
    model.addAtoms(atomsFromStructure(structure));
    const { a, b, c, alpha, beta, gamma } = structure.lattice;
    model.setCrystData(a, b, c, alpha, beta, gamma);

    const [ra, rb, rc] = this.options.repetitions;
    viewer.replicateUnitCell(ra, rb, rc, model);
    viewer.setStyle({}, this.styleFor(this.options.representation));
    if (this.options.showCell) {
      viewer.addUnitCell(model, { box: { color: CELL_COLOR, linewidth: 1.5 } });
    }
    viewer.zoomTo();
    viewer.render();
  }

  private styleFor(representation: ViewerOptions['representation']): object {
    return representation === 'spacefill' ? SPACEFILL_STYLE : BALL_STICK_STYLE;
  }
}

/**
 * Default factory: a fresh 3Dmol adapter bound to `container`. The dynamic
 * 3Dmol import happens on first `load`, so this factory itself is cheap.
 */
export const createThreeDmolAdapter: CrystalViewerAdapterFactory = (container) =>
  new ThreeDmolViewer(container);
