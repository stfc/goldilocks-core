import { describe, expect, it, vi } from "vitest";

import {
  HttpWorkbenchClient,
  type StructureInspection,
  type StructureSource,
  WorkbenchFailure,
} from "./workbenchClient";

const source: StructureSource = {
  name: "Si.cif",
  format: "cif",
  content: "data_Si",
};

const inspection: StructureInspection = {
  canonical_cif: "data_Si",
  defaults: {
    intent: {
      code: "quantum_espresso",
      task: "scf_single_point",
      functional: "PBEsol",
      pseudo_accuracy: "efficiency",
    },
    hints: {},
  },
  pseudo_tables: [
    {
      id: "pseudodojo-pbesol-efficiency-sr",
      version: "0.4",
      provider: "pseudodojo",
      upstream_table: "nc-sr-04_pbesol_standard",
      functional: "PBEsol",
      accuracy: "efficiency",
      relativistic: "SR",
      licence: "CC-BY-4.0",
      citation: "fixture citation",
      elements: ["Si"],
      default: true,
    },
  ],
  structure: {
    schema_version: 1,
    formula: "Si1",
    reduced_formula: "Si",
    site_count: 1,
    periodicity: [true, true, true],
    source: {
      name: "Si.cif",
      format: "cif",
      sha256: "a".repeat(64),
      size_bytes: 7,
    },
    lattice: {
      vectors_angstrom: [
        [4, 0, 0],
        [0, 4, 0],
        [0, 0, 4],
      ],
      lengths_angstrom: [4, 4, 4],
      angles_degrees: [90, 90, 90],
      volume_angstrom3: 64,
    },
    sites: [
      {
        fractional_coordinates: [0, 0, 0],
        cartesian_coordinates_angstrom: [0, 0, 0],
        species: [
          {
            symbol: "Si",
            label: "Si",
            occupancy: 1,
            oxidation_state: null,
          },
        ],
      },
    ],
  },
};

describe("HttpWorkbenchClient", () => {
  it("posts source content and validates the inspection response", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(inspection), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new HttpWorkbenchClient(fetcher);

    await expect(client.inspect(source)).resolves.toEqual(inspection);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/workbench/structure",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ source }),
      }),
    );
  });

  it("maps the server busy envelope to one retryable failure", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            kind: "server_busy",
            message: "The computation slot is busy; retry this request.",
            retryable: true,
            details: { retry_after_seconds: 0.5 },
          },
        }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = new HttpWorkbenchClient(fetcher);

    const failure = await client.inspect(source).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(WorkbenchFailure);
    expect(failure).toMatchObject({
      kind: "server_busy",
      retryable: true,
      details: { retry_after_seconds: 0.5 },
    });
  });

  it("rejects a successful response that violates the generated contract", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ canonical_cif: "missing structure" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new HttpWorkbenchClient(fetcher);

    await expect(client.inspect(source)).rejects.toMatchObject({
      kind: "invalid_response",
      retryable: false,
    });
  });
});
