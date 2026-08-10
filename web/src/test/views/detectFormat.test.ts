import { describe, expect, it } from 'vitest';
import { detectFormat } from '../../views/GuidedView/GuidedView';
import { siCif } from '../mocks/fixtures';

const poscar = [
  'Si diamond structure',
  '1.0',
  '5.4310000000 0.0000000000 0.0000000000',
  '0.0000000000 5.4310000000 0.0000000000',
  '0.0000000000 0.0000000000 5.4310000000',
  'Si',
  '8',
  'direct',
].join('\n');

describe('detectFormat', () => {
  it('detects a CIF with a leading comment line', () => {
    expect(detectFormat(siCif)).toBe('cif');
  });

  it('detects a plain CIF data block', () => {
    expect(detectFormat('data_Si\n_cell_length_a 5.43\n')).toBe('cif');
  });

  it('detects a POSCAR even with a non-VASP comment header', () => {
    expect(detectFormat(poscar)).toBe('poscar');
  });

  it('leaves an unrecognised snippet undefined for backend auto-detection', () => {
    expect(detectFormat('not a structure at all')).toBeUndefined();
  });
});
