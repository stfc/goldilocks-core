import { describe, expect, it } from 'vitest';
import {
  presentAdvice,
  presentConvergence,
  presentMagnetism,
  presentPseudopotentials,
  presentRecommendation,
  presentSmearing,
  presentSpinOrbit,
  presentVdw,
} from '../../records/presenters';
import { siRecommendation } from '../mocks/fixtures';

describe('presentRecommendation', () => {
  it('derives analysis, advice, k-points, selection, and warnings sections', () => {
    const presented = presentRecommendation(siRecommendation);
    expect(presented.formula).toBe('Si8');
    expect(presented.reducedFormula).toBe('Si');

    const ids = presented.sections.map((section) => section.id);
    expect(ids).toEqual(['analysis', 'advice', 'k_points', 'selection']);
  });

  it('formats the k-point grid with multiplication symbols', () => {
    const presented = presentRecommendation(siRecommendation);
    const kPoints = presented.sections.find((section) => section.id === 'k_points');
    expect(kPoints?.values.find((value) => value.label === 'Grid')?.value).toBe(
      '4 × 4 × 4',
    );
  });

  it('includes advice provenance and recommendation warnings', () => {
    const presented = presentRecommendation(siRecommendation);
    const advice = presented.sections.find((section) => section.id === 'advice');
    expect(advice?.provenance?.source).toBeDefined();
    expect(presented.warnings.length).toBeGreaterThan(0);
  });

  it('retains the grouped section ids for the Guided view layout', () => {
    const presented = presentRecommendation(siRecommendation);
    expect(presented.sections.map((section) => section.id)).toEqual([
      'analysis',
      'advice',
      'k_points',
      'selection',
    ]);
  });

  it('presents the vdw dispersion recommendation when it is enabled', () => {
    const withVdw = {
      ...siRecommendation,
      advice: {
        ...siRecommendation.advice,
        vdw: {
          use_vdw: true,
          method: 'd3bj',
          provenance: {
            source: 'goldilocks:vdw',
            reason: 'Dispersion-sensitive layered material.',
          },
        },
      },
    };
    const presented = presentRecommendation(withVdw);
    const advice = presented.sections.find((section) => section.id === 'advice');
    const dispersion = advice?.values.find(
      (value) => value.label === 'Dispersion correction',
    );
    expect(dispersion?.value).toBe('d3bj');
  });

  it('reports a disabled dispersion correction', () => {
    const presented = presentRecommendation(siRecommendation);
    const advice = presented.sections.find((section) => section.id === 'advice');
    const dispersion = advice?.values.find(
      (value) => value.label === 'Dispersion correction',
    );
    expect(dispersion?.value).toBe('Off');
  });

  it('aggregates disorder and selection warnings alongside top-level warnings', () => {
    const withDisorder = {
      ...siRecommendation,
      analysis: {
        ...siRecommendation.analysis,
        disorder_warnings: ['Site Si0 has partial occupancy.'],
      },
      selection: {
        ...siRecommendation.selection,
        warnings: ['Using fallback cutoff.'],
      },
    };
    const presented = presentRecommendation(withDisorder);
    expect(presented.warnings).toContain('Site Si0 has partial occupancy.');
    expect(presented.warnings).toContain('Using fallback cutoff.');
  });

  it('exposes every advice category as a reusable presented section', () => {
    expect(presentSmearing(siRecommendation).id).toBe('smearing');
    expect(presentMagnetism(siRecommendation).id).toBe('magnetism');
    expect(presentSpinOrbit(siRecommendation).id).toBe('spin_orbit');
    expect(presentPseudopotentials(siRecommendation).id).toBe('pseudopotentials');
    expect(presentConvergence(siRecommendation).id).toBe('convergence');
    expect(presentVdw(siRecommendation).id).toBe('vdw');
  });

  it('exposes a serializable raw value on every presented section', () => {
    const presented = presentRecommendation(siRecommendation);
    expect(presented.sections.length).toBeGreaterThan(0);
    for (const section of presented.sections) {
      expect(section.raw).toBeDefined();
      expect(() => JSON.stringify(section.raw)).not.toThrow();
    }
  });

  it('keeps per-category provenance on reusable advice sections', () => {
    expect(presentVdw(siRecommendation).provenance?.source).toBe('goldilocks:vdw');
    expect(presentSmearing(siRecommendation).provenance?.source).toBe(
      'goldilocks:smearing',
    );
    expect(presentMagnetism(siRecommendation).provenance?.source).toBe(
      'goldilocks:magnetism',
    );
  });

  it('presents the vdw method through the reusable category presenter', () => {
    const withVdw = {
      ...siRecommendation,
      advice: {
        ...siRecommendation.advice,
        vdw: {
          use_vdw: true,
          method: 'd3bj',
          provenance: {
            source: 'goldilocks:vdw',
            reason: 'Dispersion-sensitive layered material.',
          },
        },
      },
    };
    const dispersion = presentVdw(withVdw).values.find(
      (value) => value.label === 'Dispersion correction',
    );
    expect(dispersion?.value).toBe('d3bj');
  });

  it('composes every advice category into a single Advice section for Guided view', () => {
    const advice = presentAdvice(siRecommendation);
    const labels = advice.values.map((value) => value.label);
    expect(advice.id).toBe('advice');
    expect(labels).toEqual(
      expect.arrayContaining([
        'Smearing type',
        'Spin polarised',
        'Spin–orbit coupling',
        'Exchange–correlation',
        'Convergence threshold',
        'Dispersion correction',
      ]),
    );
  });
});
