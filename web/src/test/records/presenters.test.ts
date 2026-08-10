import { describe, expect, it } from 'vitest';
import { presentRecommendation } from '../../records/presenters';
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
});
