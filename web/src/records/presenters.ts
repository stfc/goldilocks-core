// Record presentation.
//
// Turns Core recommendation records into a stable, renderable shape that Guided
// and Graph views both consume. Presenters are the single place that decides
// what a scientific value means and how it is worded; views only lay out the
// returned sections. Each record type has its own reusable presenter so Graph
// view can present a single record without duplicating value formatting, and
// every section carries the raw record so advanced "raw JSON" disclosure needs
// no second source of truth.

import type { Recommendation } from '../client/types';

export interface PresentedValue {
  label: string;
  value: string;
  unit?: string;
  provenance?: PresentedProvenance;
}

export interface PresentedProvenance {
  source: string;
  reason: string;
  confidence?: number | null;
}

export interface PresentedSection {
  id: string;
  title: string;
  values: PresentedValue[];
  provenance?: PresentedProvenance;
  warnings?: string[];
  /** The serializable record(s) backing this section, for raw disclosure. */
  raw: unknown;
}

export interface PresentedRecommendation {
  formula: string;
  reducedFormula: string;
  sections: PresentedSection[];
  warnings: string[];
}

function num(value: number, digits = 4): string {
  return Number(value).toPrecision(digits);
}

function grid(grid: number[]): string {
  return grid.join(' × ');
}

function list(items: string[]): string {
  return items.length > 0 ? items.join(', ') : '—';
}

function provenanceOf(
  p: { source: string; reason: string; confidence?: number | null } | undefined,
): PresentedProvenance | undefined {
  if (!p) return undefined;
  return { source: p.source, reason: p.reason, confidence: p.confidence };
}

function asSection(
  id: string,
  title: string,
  values: PresentedValue[],
  extra: {
    provenance?: PresentedProvenance;
    warnings?: string[];
    raw: unknown;
  },
): PresentedSection {
  return {
    id,
    title,
    values,
    provenance: extra.provenance,
    warnings: extra.warnings,
    raw: extra.raw,
  };
}

/** The Analysis record. */
export function presentAnalysis(rec: Recommendation): PresentedSection {
  const a = rec.analysis;
  return asSection(
    'analysis',
    'Analysis',
    [
      { label: 'Formula', value: a.formula },
      { label: 'Reduced formula', value: a.reduced_formula },
      { label: 'Sites', value: String(a.site_count) },
      { label: 'Elements', value: list(a.elements) },
      {
        label: 'Space group',
        value: a.space_group_symbol != null ? String(a.space_group_symbol) : '—',
      },
      { label: 'Dimensionality', value: a.dimensionality },
      { label: 'Electronic character', value: a.electronic_character },
    ],
    { raw: a },
  );
}

/** Smearing broadening advice. */
export function presentSmearing(rec: Recommendation): PresentedSection {
  const s = rec.advice.smearing;
  return asSection(
    'smearing',
    'Smearing',
    [
      {
        label: 'Smearing type',
        value: s.smearing_type ?? '—',
      },
      {
        label: 'Smearing width',
        value: s.width_ry != null ? num(s.width_ry) : '—',
        unit: s.width_ry != null ? 'Ry' : undefined,
      },
    ],
    { provenance: provenanceOf(s.provenance), raw: s },
  );
}

/** Magnetism advice. */
export function presentMagnetism(rec: Recommendation): PresentedSection {
  const m = rec.advice.magnetism;
  return asSection(
    'magnetism',
    'Magnetism',
    [
      { label: 'Spin polarised', value: m.spin_polarized ? 'Yes' : 'No' },
      { label: 'Magnetic elements', value: list(m.magnetic_elements) },
    ],
    { provenance: provenanceOf(m.provenance), raw: m },
  );
}

/** Spin–orbit coupling advice. */
export function presentSpinOrbit(rec: Recommendation): PresentedSection {
  const so = rec.advice.spin_orbit;
  return asSection(
    'spin_orbit',
    'Spin–orbit',
    [
      { label: 'Spin–orbit coupling', value: so.enabled ? 'Enabled' : 'Off' },
      {
        label: 'Consider heavy elements',
        value: list(so.heavy_elements),
      },
    ],
    { provenance: provenanceOf(so.provenance), raw: so },
  );
}

/** Pseudopotential family advice. */
export function presentPseudopotentials(rec: Recommendation): PresentedSection {
  const p = rec.advice.pseudopotentials;
  return asSection(
    'pseudopotentials',
    'Pseudopotentials',
    [
      { label: 'Exchange–correlation', value: p.functional },
      { label: 'Pseudo mode', value: p.pseudo_mode },
      { label: 'Pseudo type', value: p.pseudo_type ?? '—' },
      { label: 'Relativistic', value: p.relativistic_mode },
    ],
    { provenance: provenanceOf(p.provenance), raw: p },
  );
}

/** SCF convergence advice. */
export function presentConvergence(rec: Recommendation): PresentedSection {
  const c = rec.advice.convergence;
  return asSection(
    'convergence',
    'Convergence',
    [
      { label: 'Convergence threshold', value: num(c.conv_thr), unit: 'Ry' },
      { label: 'Mixing beta', value: num(c.mixing_beta, 3) },
      { label: 'Max steps', value: String(c.electron_maxstep) },
    ],
    { provenance: provenanceOf(c.provenance), raw: c },
  );
}

/** Dispersion-correction (vdW) advice. */
export function presentVdw(rec: Recommendation): PresentedSection {
  const v = rec.advice.vdw;
  return asSection(
    'vdw',
    'Dispersion',
    [
      {
        label: 'Dispersion correction',
        value: v.use_vdw ? (v.method ?? 'Enabled') : 'Off',
      },
    ],
    { provenance: provenanceOf(v.provenance), raw: v },
  );
}

/** Compose every advice category into the single Advice section Guided shows. */
export function presentAdvice(rec: Recommendation): PresentedSection {
  const categories = [
    presentSmearing(rec),
    presentMagnetism(rec),
    presentSpinOrbit(rec),
    presentPseudopotentials(rec),
    presentConvergence(rec),
    presentVdw(rec),
  ];
  return asSection(
    'advice',
    'Advice',
    categories.flatMap((section) => section.values),
    {
      provenance: categories.find((section) => section.provenance)?.provenance,
      raw: rec.advice,
    },
  );
}

/** The recommended k-point mesh. */
export function presentKPoints(rec: Recommendation): PresentedSection {
  const k = rec.k_points;
  return asSection(
    'k_points',
    'K-points',
    [
      { label: 'Grid', value: grid(k.grid) },
      { label: 'Shift', value: grid(k.shift) },
      { label: 'Mesh type', value: k.mesh_type },
    ],
    { provenance: provenanceOf(k.provenance), raw: k },
  );
}

/** Pseudopotential selection and cutoffs. */
export function presentSelection(rec: Recommendation): PresentedSection {
  const values: PresentedValue[] = [];
  for (const p of rec.selection.pseudopotentials) {
    values.push({ label: `${p.element} pseudo`, value: p.filename ?? '—' });
    if (p.ecutwfc_ry != null) {
      values.push({
        label: `${p.element} ecutwfc`,
        value: num(p.ecutwfc_ry),
        unit: 'Ry',
      });
    }
    if (p.ecutrho_ry != null) {
      values.push({
        label: `${p.element} ecutrho`,
        value: num(p.ecutrho_ry),
        unit: 'Ry',
      });
    }
  }
  if (values.length === 0) {
    values.push({ label: 'Pseudopotentials', value: '—' });
  }
  return asSection('selection', 'Selection', values, {
    warnings: rec.selection.warnings,
    raw: rec.selection,
  });
}

/** The full guided review, composed from reusable record presenters. */
export function presentRecommendation(rec: Recommendation): PresentedRecommendation {
  const sections: PresentedSection[] = [
    presentAnalysis(rec),
    presentAdvice(rec),
    presentKPoints(rec),
    presentSelection(rec),
  ];

  const warnings = [
    ...rec.warnings,
    ...(rec.analysis?.disorder_warnings ?? []),
    ...(rec.analysis?.analysis_warnings ?? []),
    ...(rec.selection?.warnings ?? []),
  ];

  return {
    formula: rec.analysis.formula,
    reducedFormula: rec.analysis.reduced_formula,
    sections,
    warnings,
  };
}
