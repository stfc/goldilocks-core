import { strFromU8, unzipSync } from 'fflate';
import { describe, expect, it } from 'vitest';
import { buildInputArchive } from '../../archive/InputArchive';
import { siCif, siRecommendation, siStructureDocument } from '../mocks/fixtures';

async function unzip(blob: Blob): Promise<Record<string, Uint8Array>> {
  return unzipSync(new Uint8Array(await blob.arrayBuffer()));
}

describe('buildInputArchive', () => {
  it('produces a ZIP with generated inputs, the original structure, and a manifest', async () => {
    const blob = buildInputArchive({
      files: [
        {
          path: 'inputs/qe.in',
          content: '&control\n  calculation="scf"\n/\n',
          role: 'input',
        },
      ],
      structure: siStructureDocument,
      request: {
        structure: { content: siCif, format: 'cif' },
        hints: { k_grid: [4, 4, 4] },
      },
      recommendation: siRecommendation,
      meta: {
        coreVersion: '0.1.0',
        model: 'test-model',
        generatedBy: 'goldilocks-workbench',
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    });

    const entries = await unzip(blob);

    // Original structure content preserved verbatim.
    expect(strFromU8(entries['structure.cif'])).toBe(siCif);

    // Generated input present.
    expect(strFromU8(entries['inputs/qe.in'])).toContain('calculation="scf"');

    // Manifest carries intent, hints, records, provenance, warnings, identifiers.
    const manifest = JSON.parse(strFromU8(entries['goldilocks.json']));
    expect(manifest.schema).toBe('goldilocks/manifest');
    expect(manifest.core_version).toBe('0.1.0');
    expect(manifest.model).toBe('test-model');
    expect(manifest.generated_by).toBe('goldilocks-workbench');
    expect(manifest.request.intent.functional).toBe('PBEsol');
    expect(manifest.request.hints.k_grid).toEqual([4, 4, 4]);
    expect(manifest.records.k_points.grid).toEqual([4, 4, 4]);
    expect(manifest.provenance.k_points.source).toBeDefined();
    expect(manifest.warnings.length).toBeGreaterThan(0);
  });

  it('names a POSCAR archive entry structure.vasp', async () => {
    const blob = buildInputArchive({
      files: [],
      structure: siStructureDocument,
      request: { structure: { content: 'Si', format: 'poscar' } },
      recommendation: siRecommendation,
      meta: {
        coreVersion: '0.1.0',
        generatedBy: 'goldilocks-workbench',
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    });
    const entries = await unzip(blob);
    expect(strFromU8(entries['structure.vasp'])).toBe('Si');
  });
});
