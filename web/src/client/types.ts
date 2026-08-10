// Frontend domain types crossing the CoreClient seam.
//
// These are the Workbench's vocabulary for Core concepts: structures, the
// calculation request, and recommendations. They deliberately mirror the
// backend-owned transport schemas because Core is the source of scientific
// truth; they are NOT the raw generated client types. Only the HTTP adapter
// (`client/HttpCoreClient.ts`) knows the generated contract. React modules
// import from this module, never from `client/generated`.
//
// Types are declared as object type aliases (not `interface`) so they are
// structurally closed and remain assignable to the generated `extra="allow"`
// schemas (which carry an index signature); the type-level contract guard in
// `test/client/contract-drift.test-d.ts` enforces this. They are pure data
// shapes — no declaration merging or class implementation is required.

export type StructureFormat = 'cif' | 'poscar';

export type StructureSource = {
  content: string;
  format?: StructureFormat;
};

export type StructureLattice = {
  matrix: number[][];
  a: number;
  b: number;
  c: number;
  alpha: number;
  beta: number;
  gamma: number;
  volume: number;
  pbc: boolean[];
};

export type StructureSpecies = {
  element: string;
  occupancy: number;
};

export type StructureSite = {
  label: string;
  species: StructureSpecies[];
  abc: number[];
  xyz: number[];
};

export type StructureSourceInfo = {
  format?: string | null;
  source: string;
};

/** Core's canonical, transport-safe representation of a parsed structure. */
export type StructureDocument = {
  formula: string;
  reduced_formula: string;
  lattice: StructureLattice;
  sites: StructureSite[];
  charge?: number | null;
  source: StructureSourceInfo;
};

/** Calculation intent fields the Workbench may override. */
export type Intent = {
  code: string;
  task: string;
  functional: string;
  pseudo_mode: string;
};

/** Smearing schemes Core accepts for SCF broadening. */
export type SmearingType = 'fixed' | 'gaussian' | 'mp' | 'cold';

/** Dispersion-correction methods Core accepts. */
export type VdwMethod = 'd3' | 'd3bj' | 'ts' | 'mbd';

/** Operator hint fields the Workbench may override. */
export type Hints = {
  k_spacing?: number | null;
  k_grid?: number[] | null;
  smearing_type?: SmearingType | null;
  smearing_width_ry?: number | null;
  spin_polarized?: boolean | null;
  spin_orbit_coupling?: boolean | null;
  pseudo_mode?: string | null;
  pseudo_type?: string | null;
  relativistic_mode?: string | null;
  conv_thr?: number | null;
  mixing_beta?: number | null;
  electron_maxstep?: number | null;
  use_vdw?: boolean | null;
  vdw_method?: VdwMethod | null;
};

export type ComputationRequest = {
  structure: StructureSource;
  intent?: Intent;
  hints?: Hints;
};

/** Stable output record ids accepted by the compute operation. */
export type RecordName =
  'analysis' | 'advice' | 'k_points' | 'selection' | 'generated_files';

export type RecordQuery = {
  structure: StructureSource;
  outputs: RecordName[];
  intent?: Intent;
  hints?: Hints;
};

export type Provenance = {
  source: string;
  reason: string;
  data_source?: string | null;
  confidence?: number | null;
  details?: Record<string, unknown> | null;
  warnings?: string[];
};

export type Analysis = {
  formula: string;
  reduced_formula: string;
  site_count: number;
  elements: string[];
  contains_transition_metals: boolean;
  contains_lanthanides: boolean;
  contains_actinides: boolean;
  contains_heavy_elements: boolean;
  magnetic_elements: string[];
  heavy_elements: string[];
  disorder_warnings: string[];
  disordered_site_count: number;
  space_group_symbol?: string | number | Record<string, unknown> | null;
  space_group_number?: string | number | Record<string, unknown> | null;
  crystal_system?: string | number | Record<string, unknown> | null;
  dimensionality: string;
  has_vacuum: boolean;
  electronic_character: string;
  electronic_character_source: string;
  electronic_character_confidence?: number | null;
  analysis_warnings: string[];
};

export type SmearingAdvice = {
  smearing_type?: string | null;
  width_ry?: number | null;
  provenance: Provenance;
};

export type MagnetismAdvice = {
  spin_polarized: boolean;
  magnetic_elements: string[];
  provenance: Provenance;
};

export type SpinOrbitAdvice = {
  enabled: boolean;
  consider: boolean;
  heavy_elements: string[];
  provenance: Provenance;
};

export type PseudopotentialAdvice = {
  functional: string;
  pseudo_mode: string;
  pseudo_type?: string | null;
  relativistic_mode: string;
  provenance: Provenance;
};

export type ConvergenceAdvice = {
  conv_thr: number;
  mixing_beta: number;
  electron_maxstep: number;
  provenance: Provenance;
};

export type VdwAdvice = {
  use_vdw: boolean;
  method?: string | null;
  provenance: Provenance;
};

export type Advice = {
  smearing: SmearingAdvice;
  magnetism: MagnetismAdvice;
  spin_orbit: SpinOrbitAdvice;
  pseudopotentials: PseudopotentialAdvice;
  convergence: ConvergenceAdvice;
  vdw: VdwAdvice;
};

export type KPointSelection = {
  grid: number[];
  shift: number[];
  mesh_type: string;
  provenance: Provenance;
};

export type PseudopotentialSelection = {
  element: string;
  filename?: string | null;
  ecutwfc_ry?: number | null;
  ecutrho_ry?: number | null;
  provenance: Provenance;
  warnings: string[];
};

export type Selection = {
  pseudopotentials: PseudopotentialSelection[];
  warnings: string[];
};

export type GeneratedFile = {
  path: string;
  content: string;
  role: string;
};

export type Bundle = {
  path: string;
  manifest: Record<string, unknown>;
};

/** A completed recommend or generate preset result. */
export type Recommendation = {
  /** Core package version reported by the transport. */
  core_version: string;
  intent: Intent;
  analysis: Analysis;
  advice: Advice;
  k_points: KPointSelection;
  selection: Selection;
  warnings: string[];
  generated_files: GeneratedFile[];
  bundle?: Bundle | null;
};

/** The browser-safe generation deliverable returned by Core. */
export type GeneratedInputSet = Recommendation;

/** Result of the compute operation, keyed by stable record ids. */
export type RecordSet = {
  analysis?: Analysis | null;
  advice?: Advice | null;
  k_points?: KPointSelection | null;
  selection?: Selection | null;
  generated_files?: GeneratedFile[] | null;
};

export type StageDescription = {
  id: string;
  name: string;
  description: string;
  input_record_ids: string[];
  output_record_id: string;
};

export type PresetDescription = {
  id: string;
  name: string;
  output_record_ids: string[];
};

export type TaskGraphDescription = {
  id: string;
  revision: string;
  name: string;
  description: string;
  stages: StageDescription[];
  presets: PresetDescription[];
  selectable_record_ids: string[];
};

export type TaskCatalogue = {
  tasks: TaskGraphDescription[];
};
