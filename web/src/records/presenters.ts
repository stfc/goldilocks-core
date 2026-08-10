// Record presentation.
//
// Turns a Core Recommendation into a stable, renderable shape that Guided and
// Graph views both consume. Presenters are the single place that decides what
// a scientific value means and how it is worded; views only lay out the
// returned sections.

import type { Recommendation } from '../client/types';

export interface PresentedValue {
  label: string;
  value: string;
  unit?: string;
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

function presentAnalysis(rec: Recommendation): PresentedSection {
  const a = rec.analysis;
  return {
    id: 'analysis',
    title: 'Analysis',
    values: [
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
  };
}

function presentAdvice(rec: Recommendation): PresentedSection {
  const advice = rec.advice;
  return {
    id: 'advice',
    title: 'Advice',
    values: [
      {
        label: 'Smearing',
        value: advice.smearing.smearing_type ?? '—',
        unit: advice.smearing.width_ry != null ? 'Ry' : undefined,
      },
      {
        label: 'Smearing width',
        value: advice.smearing.width_ry != null ? num(advice.smearing.width_ry) : '—',
        unit: advice.smearing.width_ry != null ? 'Ry' : undefined,
      },
      {
        label: 'Spin polarised',
        value: advice.magnetism.spin_polarized ? 'Yes' : 'No',
      },
      {
        label: 'Magnetic elements',
        value: list(advice.magnetism.magnetic_elements),
      },
      {
        label: 'Spin–orbit coupling',
        value: advice.spin_orbit.enabled ? 'Enabled' : 'Off',
      },
      {
        label: 'Dispersion correction',
        value: advice.vdw.use_vdw ? (advice.vdw.method ?? 'Enabled') : 'Off',
      },
      {
        label: 'Exchange–correlation',
        value: advice.pseudopotentials.functional,
      },
      { label: 'Pseudo mode', value: advice.pseudopotentials.pseudo_mode },
      { label: 'Relativistic', value: advice.pseudopotentials.relativistic_mode },
      {
        label: 'Convergence threshold',
        value: num(advice.convergence.conv_thr),
        unit: 'Ry',
      },
      { label: 'Mixing beta', value: num(advice.convergence.mixing_beta, 3) },
      {
        label: 'Max steps',
        value: String(advice.convergence.electron_maxstep),
      },
    ],
    provenance: {
      source: advice.pseudopotentials.provenance.source,
      reason: advice.pseudopotentials.provenance.reason,
      confidence: advice.pseudopotentials.provenance.confidence,
    },
  };
}

function presentKPoints(rec: Recommendation): PresentedSection {
  const k = rec.k_points;
  return {
    id: 'k_points',
    title: 'K-points',
    values: [
      { label: 'Grid', value: grid(k.grid) },
      { label: 'Shift', value: grid(k.shift) },
      { label: 'Mesh type', value: k.mesh_type },
    ],
    provenance: {
      source: k.provenance.source,
      reason: k.provenance.reason,
      confidence: k.provenance.confidence,
    },
  };
}

function presentSelection(rec: Recommendation): PresentedSection {
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
  return {
    id: 'selection',
    title: 'Selection',
    values,
    warnings: rec.selection.warnings,
  };
}
