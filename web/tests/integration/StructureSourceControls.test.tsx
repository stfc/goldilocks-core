import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StructureInspection } from "../../src/api/coreClient";
import { StructureSourceControls } from "../../src/controls/StructureSourceControls";
import { inspection } from "../support/workbenchFixtures";

/** A graphene monolayer as /inspect returns it: pymatgen marks every CIF
 * fully periodic, so `periodicity` is all true even though the cell is a
 * 2D sheet in vacuum. */
const graphene: StructureInspection = {
  ...inspection,
  source: { ...inspection.source, name: "graphene.cif" },
  structure: {
    ...inspection.structure,
    formula: "C2",
    reduced_formula: "C",
    site_count: 2,
    periodicity: [true, true, true],
    lattice: {
      vectors_angstrom: [
        [2.467, 0, 0],
        [-1.2335, 2.1365, 0],
        [0, 0, 19.97],
      ],
      lengths_angstrom: [2.467, 2.467, 19.97],
      angles_degrees: [90, 90, 120],
      volume_angstrom3: 105.26,
    },
    sites: [
      {
        fractional_coordinates: [1 / 3, 2 / 3, 0.5],
        cartesian_coordinates_angstrom: [0, 1.4243, 9.985],
        label: "C1",
        species: [
          { symbol: "C", label: "C1", occupancy: 1, oxidation_state: null },
        ],
      },
      {
        fractional_coordinates: [2 / 3, 1 / 3, 0.5],
        cartesian_coordinates_angstrom: [1.2335, 0.7122, 9.985],
        label: "C2",
        species: [
          { symbol: "C", label: "C2", occupancy: 1, oxidation_state: null },
        ],
      },
    ],
  },
};

describe("StructureSourceControls", () => {
  it("summarizes a monolayer without a dimensionality claim", () => {
    render(
      <MantineProvider env="test">
        <StructureSourceControls
          source={{
            structure_content: "data_graphene",
            structure_name: "graphene.cif",
            structure_format: "cif",
          }}
          inspection={graphene}
          inspecting={false}
          onOpen={vi.fn()}
        />
      </MantineProvider>,
    );

    const summary = screen.getByLabelText("Inspected structure summary");
    expect(summary.textContent).toBe("C2 · C · 105.3 Å³");
    expect(summary.textContent).not.toMatch(/\b[23]D\b|Partial/);
  });
});
