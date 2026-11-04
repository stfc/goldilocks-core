import { describe, expect, it } from "vitest";

import {
  type CellVectors,
  frameUnitCell,
  type Vector3,
} from "../../src/viewer/cellFraming";

const FOV_DEGREES = 20;
// The issue's Structure-card canvases: five columns (Ni fcc) and four columns (Al, Pb fcc).
const FIVE_COLUMN_CANVAS = { width: 284, height: 457 };
const FOUR_COLUMN_CANVAS = { width: 417, height: 457 };
const LANDSCAPE_CANVAS = { width: 640, height: 360 };
const CANVASES = [FIVE_COLUMN_CANVAS, FOUR_COLUMN_CANVAS, LANDSCAPE_CANVAS];

// One-atom fcc Ni primitive cell (a0 = 3.524 Å): the atom sits on a cell corner.
const NI_FCC_A0 = 3.524;
const NI_FCC: CellVectors = [
  [0, NI_FCC_A0 / 2, NI_FCC_A0 / 2],
  [NI_FCC_A0 / 2, 0, NI_FCC_A0 / 2],
  [NI_FCC_A0 / 2, NI_FCC_A0 / 2, 0],
];

/** Lattice vectors from cell parameters, a along x and b in the xy plane (3Dmol's frame). */
function cellFromParameters(
  [a, b, c]: Vector3,
  [alphaDegrees, betaDegrees, gammaDegrees]: Vector3,
): CellVectors {
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  const [alpha, beta, gamma] = [
    radians(alphaDegrees),
    radians(betaDegrees),
    radians(gammaDegrees),
  ];
  const cx = Math.cos(beta);
  const cy =
    (Math.cos(alpha) - Math.cos(beta) * Math.cos(gamma)) / Math.sin(gamma);
  return [
    [a, 0, 0],
    [b * Math.cos(gamma), b * Math.sin(gamma), 0],
    [c * cx, c * cy, c * Math.sqrt(1 - cx * cx - cy * cy)],
  ];
}

const TRICLINIC = cellFromParameters([5.02, 6.21, 7.13], [78.4, 95.7, 104.2]);

/** The eight corners i a + j b + k c (i, j, k in {0, 1}) relative to `origin`. */
function cellCorners([a, b, c]: CellVectors, origin: Vector3): Vector3[] {
  const corners: Vector3[] = [];
  for (const i of [0, 1])
    for (const j of [0, 1])
      for (const k of [0, 1])
        corners.push([
          i * a[0] + j * b[0] + k * c[0] - origin[0],
          i * a[1] + j * b[1] + k * c[1] - origin[1],
          i * a[2] + j * b[2] + k * c[2] - origin[2],
        ]);
  return corners;
}

/** Rotations Rz(yaw) Ry(pitch) Rx(roll) on a 30-degree grid, standing in for user rotations. */
function sampledRotations(): ((point: Vector3) => Vector3)[] {
  const angles = Array.from({ length: 12 }, (_, step) => (step * Math.PI) / 6);
  const rotations: ((point: Vector3) => Vector3)[] = [];
  for (const yaw of angles)
    for (const pitch of angles)
      for (const roll of angles)
        rotations.push(([x, y, z]) => {
          const y1 = y * Math.cos(roll) - z * Math.sin(roll);
          const z1 = y * Math.sin(roll) + z * Math.cos(roll);
          const x2 = x * Math.cos(pitch) + z1 * Math.sin(pitch);
          const z2 = -x * Math.sin(pitch) + z1 * Math.cos(pitch);
          return [
            x2 * Math.cos(yaw) - y1 * Math.sin(yaw),
            x2 * Math.sin(yaw) + y1 * Math.cos(yaw),
            z2,
          ];
        });
  return rotations;
}

/**
 * Frames the cell, projects every corner in every sampled rotation about the
 * look-at point (camera on +z, 3Dmol's perspective with a vertical field of
 * view), and returns the largest corner offset from the canvas centre as a
 * fraction of the half width or half height: below 1 means inside the canvas.
 */
function largestCornerExtent(
  cell: CellVectors,
  canvas: { width: number; height: number },
): number {
  const { center, distance } = frameUnitCell(cell, canvas, FOV_DEGREES);
  const halfHeightSlope = Math.tan((FOV_DEGREES * Math.PI) / 360);
  const aspect = canvas.width / canvas.height;
  let extent = 0;
  for (const rotate of sampledRotations()) {
    for (const corner of cellCorners(cell, center)) {
      const [x, y, z] = rotate(corner);
      const depth = distance - z;
      extent = Math.max(
        extent,
        Math.abs(x) / (depth * halfHeightSlope * aspect),
        Math.abs(y) / (depth * halfHeightSlope),
      );
    }
  }
  return extent;
}

describe("frameUnitCell", () => {
  it("looks at the centroid (a + b + c) / 2 of a one-atom fcc cell, not at its atom", () => {
    const { center } = frameUnitCell(NI_FCC, FIVE_COLUMN_CANVAS, FOV_DEGREES);
    // a + b + c = (a0, a0, a0) for the fcc primitive vectors.
    expect(center[0]).toBeCloseTo(NI_FCC_A0 / 2, 12);
    expect(center[1]).toBeCloseTo(NI_FCC_A0 / 2, 12);
    expect(center[2]).toBeCloseTo(NI_FCC_A0 / 2, 12);
  });

  it("looks at the centroid of a triclinic cell", () => {
    const [a, b, c] = TRICLINIC;
    const { center } = frameUnitCell(TRICLINIC, LANDSCAPE_CANVAS, FOV_DEGREES);
    expect(center[0]).toBeCloseTo((a[0] + b[0] + c[0]) / 2, 12);
    expect(center[1]).toBeCloseTo((a[1] + b[1] + c[1]) / 2, 12);
    expect(center[2]).toBeCloseTo((a[2] + b[2] + c[2]) / 2, 12);
  });

  it.each(CANVASES)(
    "keeps all eight corners of the fcc and triclinic cells inside a $width x $height canvas in every rotation",
    (canvas) => {
      for (const cell of [NI_FCC, TRICLINIC]) {
        // Below 1 is inside; the rest is room for the atoms drawn on corners.
        expect(largestCornerExtent(cell, canvas)).toBeLessThan(0.85);
      }
    },
  );

  it.each(CANVASES)(
    "fits the cell to the narrower side of a $width x $height canvas instead of shrinking it",
    (canvas) => {
      for (const cell of [NI_FCC, TRICLINIC]) {
        expect(largestCornerExtent(cell, canvas)).toBeGreaterThan(0.75);
      }
    },
  );

  it("moves the camera back as a portrait canvas narrows, but not as a landscape one widens", () => {
    const distance = (width: number) =>
      frameUnitCell(NI_FCC, { width, height: 457 }, FOV_DEGREES).distance;
    expect(distance(284)).toBeGreaterThan(distance(417));
    expect(distance(417)).toBeGreaterThan(distance(457));
    expect(distance(914)).toBeCloseTo(distance(457), 12);
  });
});
