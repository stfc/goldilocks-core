/** A Cartesian vector in ångström. */
export type Vector3 = readonly [number, number, number];

/** Lattice vectors a, b and c of a unit cell, in the viewer's Cartesian frame. */
export type CellVectors = readonly [Vector3, Vector3, Vector3];

export interface CellFraming {
  /** Look-at point: the cell centroid (a + b + c) / 2. */
  readonly center: Vector3;
  /** Distance from the camera to the centroid, in ångström. */
  readonly distance: number;
}

// Room beyond the farthest corner for the atom spheres drawn on corner sites.
const MARGIN = 1.2;

// The corners sit at (±a ± b ± c) / 2 from the centroid; these four sign
// patterns reach all eight of them up to an overall sign.
const DIAGONALS: readonly Vector3[] = [
  [1, 1, 1],
  [1, 1, -1],
  [1, -1, 1],
  [-1, 1, 1],
];

/**
 * Frames a unit cell for a perspective camera whose field of view is vertical
 * (3Dmol's camera). Returns the cell centroid and the camera distance at which
 * the sphere through the cell's farthest corner, enlarged by 20%, fits the
 * canvas's narrower angular extent. The sphere does not depend on the view
 * direction, so every corner stays inside the canvas however the cell is
 * rotated. Assumes a canvas with positive width and height.
 */
export function frameUnitCell(
  [a, b, c]: CellVectors,
  canvas: { readonly width: number; readonly height: number },
  fovDegrees: number,
): CellFraming {
  const center: Vector3 = [
    (a[0] + b[0] + c[0]) / 2,
    (a[1] + b[1] + c[1]) / 2,
    (a[2] + b[2] + c[2]) / 2,
  ];
  const radius = Math.max(
    ...DIAGONALS.map(
      ([i, j, k]) =>
        Math.hypot(
          i * a[0] + j * b[0] + k * c[0],
          i * a[1] + j * b[1] + k * c[1],
          i * a[2] + j * b[2] + k * c[2],
        ) / 2,
    ),
  );
  const halfHeightAngle = (fovDegrees * Math.PI) / 360;
  const halfWidthAngle = Math.atan(
    (Math.tan(halfHeightAngle) * canvas.width) / canvas.height,
  );
  const halfAngle = Math.min(halfHeightAngle, halfWidthAngle);
  return { center, distance: (MARGIN * radius) / Math.sin(halfAngle) };
}
