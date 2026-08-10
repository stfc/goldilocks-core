// Known-good fixtures for the frontend test suites. The structure and
// recommendation mirror what the real backend produces for the bundled
// silicon CIF, so tracer tests exercise realistic shapes through the seams.

import type { Recommendation, StructureDocument } from '../../client/types';

export const siCif = `# generated using pymatgen
data_Si
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5.43100000
_cell_length_b   5.43100000
_cell_length_c   5.43100000
_cell_angle_alpha   90.00000000
_cell_angle_beta   90.00000000
_cell_angle_gamma   90.00000000
_symmetry_Int_Tables_number   1
_chemical_formula_structural   Si
_chemical_formula_sum   Si8
_cell_volume   160.19147799
_cell_formula_units_Z   8
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  Si  Si0  1  0.50000000  0.00000000  0.50000000  1
  Si  Si1  1  0.25000000  0.25000000  0.25000000  1
  Si  Si2  1  0.00000000  0.00000000  0.00000000  1
  Si  Si3  1  0.25000000  0.75000000  0.75000000  1
  Si  Si4  1  0.75000000  0.25000000  0.75000000  1
  Si  Si5  1  0.00000000  0.50000000  0.50000000  1
  Si  Si6  1  0.50000000  0.50000000  0.00000000  1
  Si  Si7  1  0.75000000  0.75000000  0.25000000  1
`;

export const siStructureDocument: StructureDocument = {
  formula: 'Si8',
  reduced_formula: 'Si',
  lattice: {
    matrix: [
      [5.431, 0, 0],
      [0, 5.431, 0],
      [0, 0, 5.431],
    ],
    a: 5.431,
    b: 5.431,
    c: 5.431,
    alpha: 90,
    beta: 90,
    gamma: 90,
    volume: 160.191477991,
    pbc: [true, true, true],
  },
  sites: [
    {
      label: 'Si0',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.5, 0, 0.5],
      xyz: [2.7155, 0, 2.7155],
    },
    {
      label: 'Si1',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.25, 0.25, 0.25],
      xyz: [1.35775, 1.35775, 1.35775],
    },
    {
      label: 'Si2',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0, 0, 0],
      xyz: [0, 0, 0],
    },
    {
      label: 'Si3',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.25, 0.75, 0.75],
      xyz: [1.35775, 4.07325, 4.07325],
    },
    {
      label: 'Si4',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.75, 0.25, 0.75],
      xyz: [4.07325, 1.35775, 4.07325],
    },
    {
      label: 'Si5',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0, 0.5, 0.5],
      xyz: [0, 2.7155, 2.7155],
    },
    {
      label: 'Si6',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.5, 0.5, 0],
      xyz: [2.7155, 2.7155, 0],
    },
    {
      label: 'Si7',
      species: [{ element: 'Si', occupancy: 1 }],
      abc: [0.75, 0.75, 0.25],
      xyz: [4.07325, 4.07325, 1.35775],
    },
  ],
  charge: 0,
  source: { format: 'cif', source: 'inline' },
};

export const siRecommendation: Recommendation = {
  intent: {
    code: 'quantum_espresso',
    task: 'scf_single_point',
    functional: 'PBEsol',
    pseudo_mode: 'efficiency',
  },
  analysis: {
    formula: 'Si8',
    reduced_formula: 'Si',
    site_count: 8,
    elements: ['Si'],
    contains_transition_metals: false,
    contains_lanthanides: false,
    contains_actinides: false,
    contains_heavy_elements: false,
    magnetic_elements: [],
    heavy_elements: [],
    disorder_warnings: [],
    disordered_site_count: 0,
    space_group_symbol: 'Fd-3m',
    space_group_number: 227,
    crystal_system: 'cubic',
    dimensionality: '3d',
    has_vacuum: false,
    electronic_character: 'semiconductor',
    electronic_character_source: 'heuristic',
    electronic_character_confidence: 0.9,
    analysis_warnings: [],
  },
  advice: {
    smearing: {
      smearing_type: 'mv',
      width_ry: 0.01,
      provenance: {
        source: 'goldilocks:smearing',
        reason: 'Non-magnetic semiconductor; default Methfessel–Paxton broadening.',
      },
    },
    magnetism: {
      spin_polarized: false,
      magnetic_elements: [],
      provenance: {
        source: 'goldilocks:magnetism',
        reason: 'No magnetic elements detected.',
      },
    },
    spin_orbit: {
      enabled: false,
      consider: false,
      heavy_elements: [],
      provenance: {
        source: 'goldilocks:soc',
        reason: 'No heavy elements requiring spin–orbit coupling.',
      },
    },
    pseudopotentials: {
      functional: 'PBEsol',
      pseudo_mode: 'efficiency',
      pseudo_type: 'NC',
      relativistic_mode: 'scalar',
      provenance: {
        source: 'goldilocks:pseudo',
        reason: 'Efficiency mode selects the configured SSSP library.',
      },
    },
    convergence: {
      conv_thr: 1e-8,
      mixing_beta: 0.4,
      electron_maxstep: 80,
      provenance: {
        source: 'goldilocks:convergence',
        reason: 'Default tight SCF convergence.',
      },
    },
    vdw: {
      use_vdw: false,
      method: null,
      provenance: {
        source: 'goldilocks:vdw',
        reason: 'No dispersion correction recommended for this functional.',
      },
    },
  },
  k_points: {
    grid: [4, 4, 4],
    shift: [0, 0, 0],
    mesh_type: 'gamma',
    provenance: {
      source: 'goldilocks:kpoints',
      reason: 'Uniform k-mesh from the configured spacing.',
    },
  },
  selection: {
    pseudopotentials: [
      {
        element: 'Si',
        filename: 'Si.UPF',
        ecutwfc_ry: 30,
        ecutrho_ry: 120,
        provenance: {
          source: 'goldilocks:pseudo',
          reason: 'Efficiency SSSP selection for Si.',
        },
        warnings: [],
      },
    ],
    warnings: [],
  },
  warnings: [
    'Recommended k-point spacing limited by available pseudopotential cutoffs.',
  ],
  generated_files: [],
  bundle: null,
};
