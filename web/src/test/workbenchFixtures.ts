import type {
  Recommendation,
  StructureInspection,
  StructureSource,
} from "../api/workbenchClient";

export const source: StructureSource = {
  name: "Si.cif",
  format: "cif",
  content: "data_Si",
};

const pseudoTable: StructureInspection["pseudo_tables"][number] = {
  id: "pseudodojo-pbesol-efficiency-sr",
  version: "0.4",
  provider: "pseudodojo",
  upstream_table: "PseudoDojo fixture",
  functional: "PBEsol",
  accuracy: "efficiency",
  relativistic: "SR",
  licence: "CC-BY-4.0",
  citation: "van Setten et al.",
  elements: ["Si"],
  default: true,
};

export const inspection: StructureInspection = {
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
  pseudo_tables: [pseudoTable],
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
          { symbol: "Si", label: "Si", occupancy: 1, oxidation_state: null },
        ],
      },
    ],
  },
};

export const recommendation: Recommendation = {
  schema_version: 1,
  review_digest: "b".repeat(64),
  structure: inspection.structure,
  canonical_cif: inspection.canonical_cif,
  intent: inspection.defaults.intent,
  hints: { k_grid: [3, 3, 3] },
  records: {
    analysis: { formula: "Si1" },
    advice: { smearing: { smearing_type: "fixed" } },
  },
  generated_files: [
    {
      path: "inputs/qe.in",
      role: "input",
      content: "&CONTROL\n/\n",
      sha256: "c".repeat(64),
    },
  ],
  selection: {
    table: pseudoTable,
    files: [
      {
        element: "Si",
        filename: "Si.upf",
        sha256: "d".repeat(64),
        functional: "PBEsol",
        ecutwfc_ry: 30,
        ecutrho_ry: 120,
        provenance: { source: "lookup" },
        warnings: [],
      },
    ],
    warnings: [],
  },
  warnings: [],
};
