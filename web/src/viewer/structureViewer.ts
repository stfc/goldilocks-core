import type { GLModel, GLViewer } from "3dmol";

import { type CellVectors, frameUnitCell } from "./cellFraming";

export interface StructureViewer {
  show(canonicalCif: string): void;
  refreshTheme(): void;
  dispose(): void;
}

export type StructureViewerFactory = (
  element: HTMLElement,
  signal: AbortSignal,
) => StructureViewer | Promise<StructureViewer>;

// 3dmol 2.5.5 has no viewer destructor: clear() only clears the scene, and
// setContainer() installs additional canvas listeners. Keep one viewer and its
// original container for the document lifetime; each viewport leases it.
let retained: { viewer: GLViewer; surface: HTMLDivElement } | undefined;
let owner: symbol | undefined;

// The camera's vertical field of view in degrees, set on the viewer so the
// camera and frameUnitCell use the same angle.
const FIELD_OF_VIEW_DEGREES = 20;

// The nine elements of a 3Dmol Matrix3, column by column.
type ColumnMajor3 = readonly [
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
];

/**
 * Returns the lattice vectors 3Dmol placed the model's atoms and cell box with:
 * the columns of the matrix it derives from the CIF cell parameters (a along
 * x, b in the xy plane), not the orientation of the uploaded lattice. Throws
 * when the model has no unit cell.
 */
function cellVectors(model: GLModel): CellVectors {
  const cryst = model.getCrystData() as {
    readonly matrix: { readonly elements: ColumnMajor3 };
  } | null;
  if (cryst === null) throw new Error("The structure has no unit cell.");
  const [ax, ay, az, bx, by, bz, cx, cy, cz] = cryst.matrix.elements;
  return [
    [ax, ay, az],
    [bx, by, bz],
    [cx, cy, cz],
  ];
}

export const attachStructureViewer: StructureViewerFactory = async (
  element,
  signal,
) => {
  signal.throwIfAborted();
  const { createViewer } = await import("3dmol");
  signal.throwIfAborted();
  if (retained === undefined) {
    const surface = document.createElement("div");
    surface.style.cssText = "position:relative;width:100%;height:100%";
    element.append(surface);
    try {
      const viewer = createViewer(surface, { antialias: true });
      viewer.setCameraParameters({ fov: FIELD_OF_VIEW_DEGREES });
      retained = { viewer, surface };
    } catch (error) {
      surface.remove();
      throw error;
    }
  }
  const { viewer, surface } = retained;
  const lease = Symbol();
  owner = lease;
  element.append(surface);
  // The library's ResizeObserver and IntersectionObserver stay attached to
  // this same surface, including while it is detached between inspections.
  viewer.resize();

  let cell: CellVectors | undefined;
  // Looks at the cell centroid from the distance that fits the cell to the
  // surface's current size, keeping the user's rotation.
  const frameCell = (): void => {
    const { offsetWidth: width, offsetHeight: height } = surface;
    if (cell === undefined || width === 0 || height === 0) return;
    const { center, distance } = frameUnitCell(
      cell,
      { width, height },
      FIELD_OF_VIEW_DEGREES,
    );
    viewer.setPerceivedDistance(distance);
    // getView(): model translation, rotation-group z (the distance), quaternion.
    const [, , , ...distanceAndRotation] = viewer.getView() as number[];
    // setView draws the scene.
    viewer.setView([
      -center[0],
      -center[1],
      -center[2],
      ...distanceAndRotation,
    ]);
  };
  // The library's own observer resizes the renderer but keeps the old framing;
  // re-fit the cell whenever the surface changes size (e.g. a grid column
  // appearing beside the card).
  const resizeObserver = new ResizeObserver(() => {
    if (owner === lease) frameCell();
  });
  resizeObserver.observe(surface);

  return {
    show(canonicalCif): void {
      if (owner !== lease) return;
      viewer.clear();
      const model = viewer.addModel(canonicalCif, "cif");
      viewer.setStyle(
        {},
        {
          sphere: { scale: 0.3, colorscheme: "Jmol" },
          stick: { radius: 0.12, colorscheme: "Jmol" },
        },
      );
      const rootStyle = getComputedStyle(document.documentElement);
      viewer.addUnitCell(model, {
        box: {
          color: rootStyle.getPropertyValue("--mantine-color-gray-6").trim(),
          linewidth: 1.5,
        },
      });
      cell = cellVectors(model);
      // zoomTo centres on the atoms, which leaves the box off-centre when atoms
      // sit on its corners; it still sets the clipping slab and fog for the
      // atoms and the box together, and frameCell then re-centres on the cell.
      viewer.zoomTo();
      frameCell();
      viewer.render();
    },
    refreshTheme(): void {
      if (owner !== lease) return;
      const backgroundColor = getComputedStyle(document.documentElement)
        .getPropertyValue("--mantine-color-body")
        .trim();
      viewer.setBackgroundColor(backgroundColor, 1);
    },
    dispose(): void {
      resizeObserver.disconnect();
      if (owner !== lease) return;
      owner = undefined;
      viewer.clear();
      surface.remove();
    },
  };
};
