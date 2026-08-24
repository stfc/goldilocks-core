import type {
  CalculationDraft,
  Capabilities,
  ComputationResult,
  StructureInspection,
  StructureSource,
} from "../api/coreClient";

export const source: StructureSource = {
  kind: "inline",
  name: "Si.cif",
  format: "cif",
  content: "data_Si",
};

const pseudoSet: Capabilities["pseudopotential_sets"][number] = {
  id: "pseudodojo-pbesol-efficiency-sr",
  version: "0.4",
  provider: "pseudodojo",
  upstream_name: "PseudoDojo fixture",
  functional: "PBEsol",
  accuracy: "efficiency",
  relativistic_treatment: "scalar",
  licence: "CC-BY-4.0",
  citation: "van Setten et al.",
  supported_elements: ["Si"],
  default: true,
};

export const capabilities: Capabilities = {
  core_version: "1.2.3",
  default_intent: {
    code: "quantum_espresso",
    task: "scf_single_point",
    functional: "PBEsol",
    pseudo_accuracy: "efficiency",
  },
  default_hints: {},
  target_codes: ["quantum_espresso"],
  models: [],
  pseudopotential_sets: [
    pseudoSet,
    {
      ...pseudoSet,
      id: "sssp-pbesol-efficiency-sr",
      version: "1.3.0",
      provider: "sssp",
      upstream_name: "SSSP efficiency",
      default: false,
    },
  ],
  tasks: [
    {
      id: "scf_single_point",
      revision: "1",
      name: "Single-point SCF",
      description: "Prepare a single-point SCF calculation.",
      stages: [],
      selectable_record_ids: [
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
        "dft_input_data",
      ],
      presets: [
        {
          id: "generate",
          name: "generate",
          output_record_ids: [
            "analysis",
            "advice",
            "k_points",
            "selection",
            "generated_files",
            "dft_input_data",
          ],
        },
      ],
    },
  ],
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
        species: [
          { symbol: "Si", label: "Si", occupancy: 1, oxidation_state: null },
        ],
      },
    ],
  },
};

export const draft: CalculationDraft = {
  structure: source,
  intent: capabilities.default_intent,
  hints: capabilities.default_hints,
};

const provenance = {
  source: "lookup" as const,
  reason: "Fixture lookup.",
  confidence: null,
  data_source: null,
  details: null,
  warnings: [],
};

export const computationResult: ComputationResult = {
  schema_version: 1,
  task: "scf_single_point",
  task_revision: "1",
  selection: { preset: "generate" },
  publication: null,
  warnings: [],
  draft: {
    structure: inspection,
    intent: capabilities.default_intent,
    hints: {
      conv_thr: null,
      electron_maxstep: null,
      k_grid: [3, 3, 3],
      k_spacing: null,
      mixing_beta: null,
      pseudo_accuracy: null,
      pseudo_type: null,
      relativistic_mode: null,
      smearing_type: null,
      smearing_width_ry: null,
      spin_orbit_coupling: null,
      spin_polarized: null,
      use_vdw: null,
      vdw_method: null,
    },
    pseudo_metadata: null,
    pseudo_root: null,
    pseudo_table: pseudoSet.id,
    kmesh_model: null,
  },
  records: {
    analysis: {
      formula: "Si1",
      reduced_formula: "Si",
      site_count: 1,
      elements: ["Si"],
      dimensionality: "3d",
      low_dimensional: false,
      crystal_system: "cubic",
      space_group_symbol: "Fd-3m",
      space_group_number: 227,
      contains_transition_metals: false,
      contains_lanthanides: false,
      contains_actinides: false,
      contains_heavy_elements: false,
      heavy_elements: [],
      magnetic_elements: [],
      disordered_site_count: 0,
      disorder_warnings: [],
      analysis_warnings: [],
      electronic_character: "insulator",
      electronic_character_confidence: 0.9,
      electronic_character_source: "fixture",
    },
    k_points: {
      grid: [3, 3, 3],
      shift: [0, 0, 0],
      mesh_type: "monkhorst-pack",
      provenance,
    },
    selection: {
      pseudopotentials: [
        {
          element: "Si",
          filename: "Si.upf",
          functional: "PBEsol",
          relativistic: "scalar",
          ecutwfc_ry: 30,
          ecutrho_ry: 120,
          provenance,
          warnings: [],
        },
      ],
      warnings: [],
    },
    generated_files: [
      { path: "inputs/qe.in", role: "input", content: "&CONTROL\n/\n" },
    ],
    dft_input_data: {
      schema_version: 1,
      pseudopotential_set: {
        id: pseudoSet.id,
        version: pseudoSet.version,
        provider: pseudoSet.provider,
        functional: pseudoSet.functional,
        accuracy: pseudoSet.accuracy,
        relativistic: pseudoSet.relativistic_treatment,
        licence: pseudoSet.licence,
        citation: pseudoSet.citation,
        policy: {},
      },
      artifacts: [
        {
          path: "inputs/qe.in",
          role: "input",
          media_type: "text/plain",
          sha256: "c".repeat(64),
          size_bytes: 11,
          provenance: null,
          source: { kind: "generated", identity: "qe-input" },
        },
        {
          path: "pseudo/Si.upf",
          role: "pseudopotential",
          media_type: "application/octet-stream",
          sha256: "d".repeat(64),
          size_bytes: 128,
          provenance,
          source: {
            kind: "installed",
            asset_id: pseudoSet.id,
            asset_version: pseudoSet.version,
            preparation_fingerprint: "fixture",
            path: "Si.upf",
          },
        },
      ],
      citations: [pseudoSet.citation],
      manifest: {},
      runtime: {
        core_version: "1.2.3",
        models: [],
        assets: [],
      },
    },
  },
};
