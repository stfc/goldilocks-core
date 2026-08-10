import { strFromU8, unzipSync } from 'fflate';
import { describe, expect, it, vi } from 'vitest';
import {
  buildInputArchive,
  downloadInputArchive,
  inputArchiveName,
} from '../../archive/InputArchive';
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

  it('includes provenance for every advice category in the manifest', async () => {
    const blob = buildInputArchive({
      files: [],
      structure: siStructureDocument,
      request: { structure: { content: siCif, format: 'cif' } },
      recommendation: siRecommendation,
      meta: {
        generatedBy: 'goldilocks-workbench',
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    });
    const entries = await unzip(blob);
    const manifest = JSON.parse(strFromU8(entries['goldilocks.json']));
    expect(manifest.provenance.smearing.source).toBe('goldilocks:smearing');
    expect(manifest.provenance.magnetism.source).toBe('goldilocks:magnetism');
    expect(manifest.provenance.spin_orbit.source).toBe('goldilocks:soc');
    expect(manifest.provenance.pseudopotentials.source).toBe('goldilocks:pseudo');
    expect(manifest.provenance.convergence.source).toBe('goldilocks:convergence');
    expect(manifest.provenance.vdw.source).toBe('goldilocks:vdw');
    expect(manifest.provenance.k_points.source).toBe('goldilocks:kpoints');
  });

  it('omits core_version from the manifest when no version is available', async () => {
    const blob = buildInputArchive({
      files: [],
      structure: siStructureDocument,
      request: { structure: { content: siCif, format: 'cif' } },
      recommendation: siRecommendation,
      meta: {
        generatedBy: 'goldilocks-workbench',
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    });
    const entries = await unzip(blob);
    const manifest = JSON.parse(strFromU8(entries['goldilocks.json']));
    expect(manifest.core_version).toBeUndefined();
  });

  it('names the archive after the structure formula', () => {
    expect(inputArchiveName(siStructureDocument)).toBe('Si-inputs.zip');
  });

  it('downloads the archive under the formula name', () => {
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValue('blob:goldilocks');
    const revokeObjectURL = vi
      .spyOn(URL, 'revokeObjectURL')
      .mockImplementation(() => {});
    let downloadedName = '';
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloadedName = this.download;
      });

    downloadInputArchive({
      files: [{ path: 'inputs/qe.in', content: '&control\n', role: 'input' }],
      structure: siStructureDocument,
      request: { structure: { content: siCif, format: 'cif' } },
      recommendation: siRecommendation,
      meta: {
        generatedBy: 'goldilocks-workbench',
        createdAt: '2026-01-01T00:00:00.000Z',
      },
    });

    expect(click).toHaveBeenCalledTimes(1);
    expect(downloadedName).toBe('Si-inputs.zip');
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
