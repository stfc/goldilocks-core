import { strToU8, zipSync } from "fflate";

import type {
  ArchiveDownload,
  Capabilities,
  ExplainResult,
  PseudopotentialTable,
  RecordLayout,
  ResolvedField,
  RunResult,
  StructureInput,
  StructureInspection,
} from "../../src/api/coreClient";
import type { CalculationDraft } from "../../src/workspace/workspace";

export const structureInput: StructureInput = {
  structure_content: "data_Si",
  structure_name: "Si.cif",
  structure_format: "cif",
};

const pseudoTable: PseudopotentialTable = {
  id: "pseudodojo-pbesol-efficiency-sr",
  provider: "pseudodojo",
  version: "0.4",
  functional: "PBEsol",
  relativistic: "scalar",
  accuracy: "efficiency",
  elements: ["Si"],
  licence: "CC-BY-4.0",
  citation: "van Setten et al.",
  default: true,
};

const pbeTable: PseudopotentialTable = {
  ...pseudoTable,
  id: "sssp-pbe-precision-sr",
  provider: "sssp",
  version: "1.3.0",
  functional: "PBE",
  accuracy: "precision",
  default: false,
};

export const capabilities: Capabilities = {
  core_version: "1.2.3",
  vocabulary_version: "5",
  codes: [
    {
      id: "quantum_espresso",
      name: "Quantum ESPRESSO",
      tasks: ["scf_single_point", "relax"],
    },
  ],
  tasks: [
    {
      id: "scf_single_point",
      name: "Single-point SCF",
      description: "One self-consistent-field calculation, no relaxation.",
      codes: ["quantum_espresso"],
      step_count: 1,
      executables: ["pw.x"],
    },
    {
      id: "relax",
      name: "Ionic relaxation",
      description: "scf plus BFGS/damped/FIRE ionic-position optimization.",
      codes: ["quantum_espresso"],
      step_count: 1,
      executables: ["pw.x"],
    },
  ],
  facts: [
    {
      key: "is_metal",
      type: "enum",
      values: ["metal", "non_metal"],
      ml_target: "is_metal",
      approaches: ["human", "heuristic"],
      overridable: true,
      description: "Whether the structure is metallic.",
    },
    {
      key: "needs_soc",
      type: "boolean",
      values: null,
      ml_target: null,
      approaches: ["heuristic"],
      overridable: false,
      description:
        "Whether spin-orbit coupling is likely relevant. Advice only: the spin_orbit_coupling setting enables it.",
    },
  ],
  settings: [
    {
      key: "functional",
      group: "functional",
      type: "string",
      unit: null,
      default: "PBEsol",
      enum_from: "pseudopotential_tables.functional",
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: false,
      resolved_in: { record: "functional", path: [] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Exchange-correlation functional label.",
    },
    {
      key: "pseudo_table_id",
      group: "pseudo_table_id",
      type: "string",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: true,
      resolved_in: { record: "pseudo_table", path: ["id"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Pin an explicit pseudopotential table id.",
    },
    {
      key: "spin_polarized",
      group: "magnetic",
      type: "boolean",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: true,
      resolved_in: { record: "magnetic", path: ["spin_polarized"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Force spin-polarized vs non-spin-polarized.",
    },
    {
      key: "spin_orbit_coupling",
      group: "magnetic",
      type: "boolean",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: true,
      resolved_in: {
        record: "magnetic",
        path: ["spin_orbit_enabled"],
      },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Enable noncollinear spin-orbit-coupling mode.",
    },
    {
      key: "smearing_type",
      group: "occupations",
      type: "string",
      enum: ["cold", "fd", "gaussian", "mp"],
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: ["scf", "relax"],
      programs: ["pw.x"],
      scope: "per_step",
      structure_specific: false,
      resolved_in: { record: "occupations", path: ["smearing_type"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Smearing function used when occupations=smearing.",
    },
    {
      key: "degauss",
      group: "occupations",
      type: "number",
      unit: "Ry",
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: ["scf", "relax"],
      programs: ["pw.x"],
      scope: "per_step",
      structure_specific: false,
      resolved_in: { record: "occupations", path: ["degauss"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Smearing width used when occupations=smearing.",
    },
    {
      key: "k_grid",
      group: "k_sampling",
      type: "array",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: ["scf", "relax"],
      programs: ["pw.x"],
      scope: "per_step",
      structure_specific: true,
      resolved_in: { record: "k_sampling", path: ["mesh"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Explicit Monkhorst-Pack mesh dimensions.",
    },
    {
      key: "k_distance",
      group: "k_sampling",
      type: "number",
      unit: "Å⁻¹",
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: ["scf", "relax"],
      programs: ["pw.x"],
      scope: "per_step",
      structure_specific: false,
      resolved_in: { record: "k_sampling", path: ["k_distance"] },
      ml_target: "k_distance",
      approaches: ["human", "ml", "heuristic"],
      description: "Target reciprocal-space spacing between k-points.",
    },
    {
      key: "hubbard_needs_correlation",
      group: "hubbard",
      type: "boolean",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: true,
      resolved_in: { record: "hubbard", path: null },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Force whether a Hubbard +U correction is applied.",
    },
    {
      key: "u_by_element",
      group: "hubbard",
      type: "object",
      unit: "eV",
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "system",
      structure_specific: true,
      resolved_in: { record: "hubbard", path: null },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Dudarev U_eff in eV (> 0) per element symbol.",
    },
    {
      key: "account",
      group: "job",
      type: "string",
      unit: null,
      codes: ["quantum_espresso"],
      tasks: ["scf_single_point", "relax"],
      steps: null,
      programs: null,
      scope: "task",
      structure_specific: false,
      resolved_in: { record: "job", path: ["account"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "HPC accounting/billing code.",
    },
    {
      key: "ion_dynamics",
      group: "relax",
      type: "string",
      enum: ["bfgs", "damp", "fire"],
      unit: null,
      default: "bfgs",
      codes: ["quantum_espresso"],
      tasks: ["relax"],
      steps: ["relax"],
      programs: ["pw.x"],
      scope: "per_step",
      structure_specific: false,
      resolved_in: { record: "relax", path: ["ion_dynamics"] },
      ml_target: null,
      approaches: ["human", "heuristic"],
      description: "Ionic relaxation algorithm for relax/vc-relax.",
    },
  ],
  pseudopotential_tables: [pseudoTable, pbeTable],
  hpc_profiles: [
    { id: "scarf", name: "SCARF", scheduler: "slurm", partitions: ["compute"] },
  ],
  models: [],
  warnings: [],
  sources: ["human", "ml", "llm", "heuristic"],
};

export const inspection: StructureInspection = {
  schema_version: 1,
  canonical_cif: "data_Si",
  source: {
    origin: "inline",
    name: "Si.cif",
    format: "cif",
    content: "data_Si",
    sha256: "a".repeat(64),
    size_bytes: 7,
  },
  structure: {
    schema_version: 1,
    formula: "Si1",
    reduced_formula: "Si",
    site_count: 1,
    periodicity: [true, true, true],
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
        label: "Si",
        species: [
          { symbol: "Si", label: "Si", occupancy: 1, oxidation_state: null },
        ],
      },
    ],
  },
};

type Coordinates = readonly [number, number, number];

const zirconiaSites: readonly (readonly [string, Coordinates, Coordinates])[] =
  [
    ["Zr1", [0.2771, 0.0432, 0.2095], [1.4006, 0.2251, 0.8722]],
    ["Zr2", [0.7229, 0.5432, 0.2905], [3.6532, 2.8293, 0.9204]],
    ["Zr3", [0.7229, 0.9568, 0.7905], [3.6532, 4.9832, 3.5674]],
    ["Zr4", [0.2771, 0.4568, 0.7095], [1.4006, 2.379, 3.5192]],
    ["O1", [0.0698, 0.3362, 0.3415], [0.353, 1.7509, 1.7485]],
    ["O2", [0.9302, 0.8362, 0.1585], [4.7008, 4.3551, 0.044]],
    ["O3", [0.9302, 0.6638, 0.6585], [4.7008, 3.4574, 2.6911]],
    ["O4", [0.0698, 0.1638, 0.8415], [0.353, 0.8533, 4.3955]],
    ["O5", [0.4486, 0.7577, 0.4795], [2.2673, 3.9463, 2.1553]],
    ["O6", [0.5514, 0.2577, 0.0205], [2.7865, 1.3421, -0.3628]],
    ["O7", [0.5514, 0.2423, 0.5205], [2.7865, 1.2621, 2.2843]],
    ["O8", [0.4486, 0.7423, 0.9795], [2.2673, 3.8663, 4.8024]],
  ];

/** Monoclinic ZrO2 (MC3D mc3d-78910) as /inspect returns it, with the
 * lattice at full precision and the sites rounded to 4 decimals: a
 * non-orthogonal cell (beta = 99.597 degrees). */
export const monoclinicInspection: StructureInspection = {
  schema_version: 1,
  canonical_cif: "data_ZrO2",
  source: {
    origin: "inline",
    name: "ZrO2.cif",
    format: "cif",
    content: "data_ZrO2",
    sha256: "b".repeat(64),
    size_bytes: 9,
  },
  structure: {
    schema_version: 1,
    formula: "Zr4 O8",
    reduced_formula: "ZrO2",
    site_count: zirconiaSites.length,
    periodicity: [true, true, true],
    lattice: {
      vectors_angstrom: [
        [5.053802818385099, 0, -0.8544960672976821],
        [0, 5.2083461389853, 0],
        [0, 0, 5.294079653689377],
      ],
      lengths_angstrom: [5.125532797294773, 5.2083461389853, 5.294079653689377],
      angles_degrees: [90, 99.59679594924226, 90],
      volume_angstrom3: 139.35052321494535,
    },
    sites: zirconiaSites.map(([label, fractional, cartesian]) => {
      const symbol = label.replace(/\d+$/u, "");
      return {
        fractional_coordinates: fractional,
        cartesian_coordinates_angstrom: cartesian,
        label,
        species: [
          { symbol, label: symbol, occupancy: 1, oxidation_state: null },
        ],
      };
    }),
  },
};

/** The workspace's own default draft, seeded from `capabilities` above
 * right after a successful `source.open` -- exported so tests can
 * assert against it without re-deriving `defaultDraft`'s logic. */
export const draft: CalculationDraft = {
  code: "quantum_espresso",
  task: "scf_single_point",
  hpc: null,
  overrides: {},
  fetchMissing: false,
};

// Field names confirmed against a real /explain response for Si.cif
// (2026-09-14): {mesh, shift, k_distance, warnings} -- not {grid,
// mesh_type} as an earlier draft of this fixture guessed.
const kSamplingRecord: ResolvedField<{
  mesh: readonly number[];
  shift: readonly number[];
  k_distance: number;
  warnings: unknown[];
}> = {
  status: "resolved",
  value: {
    mesh: [3, 3, 3],
    shift: [0, 0, 0],
    k_distance: 0.15,
    warnings: [],
  },
  source: "heuristic",
};

const cutoffsRecord: ResolvedField<{ ecutwfc_ry: number; ecutrho_ry: number }> =
  {
    status: "resolved",
    value: { ecutwfc_ry: 30, ecutrho_ry: 120 },
    source: "heuristic",
  };

export const scientificRecords: Readonly<Record<string, ResolvedField>> = {
  k_sampling: kSamplingRecord,
  n_irr_k: { status: "resolved", value: 10, source: "heuristic" },
  cutoffs: cutoffsRecord,
  magnetic: {
    status: "resolved",
    value: { spin_polarized: false },
    source: "heuristic",
  },
};

/** Where each of `scientificRecords` belongs, as `/explain` lays out an
 * scf task's records. */
export const scientificLayout: RecordLayout = {
  analysis: [],
  system: ["cutoffs", "magnetic"],
  steps: [{ name: "scf", records: ["k_sampling", "n_irr_k"] }],
};

export const explainResult: ExplainResult = {
  records: scientificRecords,
  warnings: [],
  blocking: [],
  layout: scientificLayout,
};

export const runResult: RunResult = {
  files: [
    "scf.in",
    "pseudo/Si.upf",
    "licences/pseudodojo-pbesol-efficiency-sr.txt",
    "goldilocks.json",
  ],
  records: scientificRecords,
  warnings: [],
  layout: scientificLayout,
};

const MANIFEST_TEXT = JSON.stringify({
  schema_version: 2,
  request: {
    code: "quantum_espresso",
    task: "scf_single_point",
    hpc: "scarf",
    core_version: "0.1.1",
    overrides: { pseudo_table_id: "pseudodojo-pbesol-efficiency-sr" },
    structure: {
      name: "Si.cif",
      format: "cif",
      sha256: "f".repeat(64),
      size_bytes: 812,
    },
  },
  records: scientificRecords,
  warnings: [],
  citations: ["van Setten et al."],
  files: {
    "scf.in": { role: "input", sha256: "c".repeat(64), size_bytes: 11 },
    "pseudo/Si.upf": {
      role: "pseudopotential",
      sha256: "d".repeat(64),
      size_bytes: 128,
    },
    "licences/pseudodojo-pbesol-efficiency-sr.txt": {
      role: "licence",
      sha256: "e".repeat(64),
      size_bytes: 43,
    },
  },
});

/** jsdom's test realm has its own `Uint8Array` distinct from the one
 * `TextEncoder` (used by fflate's `strToU8`) produces -- `instanceof
 * Uint8Array` then fails inside fflate's own type check, so it treats
 * the bytes as a *nested folder object* instead (a real `Uint8Array`
 * exposes its elements as own enumerable "0","1",... keys) and recurses
 * into each byte as if it were a subdirectory. Re-homing through `new
 * Uint8Array(...)` in the caller's realm avoids that -- real browsers
 * never hit this, `TextEncoder` and `Uint8Array` always share one realm
 * there. */
function u8(text: string): Uint8Array {
  return new Uint8Array(strToU8(text));
}

/** A real zip, matching bundle.py's `bundle_files` shape closely enough
 * for GeneratedInputReview's client-side unzip to exercise for real. */
export function buildArchive(
  filename = "goldilocks-inputs.zip",
): ArchiveDownload {
  const zipped = zipSync({
    "scf.in": u8("&CONTROL\n/\n"),
    "pseudo/Si.upf": u8("UPF content"),
    "licences/pseudodojo-pbesol-efficiency-sr.txt": u8(
      "PseudoDojo pseudopotentials are CC BY 4.0.\n",
    ),
    "goldilocks.json": u8(MANIFEST_TEXT),
  });
  // Blob(...) copies exactly zipped.byteLength bytes; `zipped.buffer` is
  // the wrong thing to pass instead since a Uint8Array's underlying
  // ArrayBuffer can be larger than (or offset within) the view itself.
  // Re-wrapping through `new Uint8Array(zipped)` also gives a plain
  // `Uint8Array<ArrayBuffer>` (never `SharedArrayBuffer`), which is what
  // `BlobPart` requires.
  return {
    blob: new Blob([new Uint8Array(zipped)], { type: "application/zip" }),
    filename,
  };
}
