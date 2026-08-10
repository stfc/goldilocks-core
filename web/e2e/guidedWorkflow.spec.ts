// Critical Guided workflow through the real FastAPI transport and Vite build:
// load structure -> recommend -> override/stale -> regenerate -> download ZIP.
import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { strFromU8, unzipSync } from 'fflate';
import { loadStructure, setKGrid } from './helpers';

test('guided: load CIF, recommend, override, regenerate, download reproducible ZIP', async ({
  page,
}) => {
  await page.goto('/');
  await loadStructure(page);

  // Use an explicit k-grid so no ML model is consulted.
  await setKGrid(page, '3 3 3');

  await page.getByRole('button', { name: 'Recommend parameters' }).click();
  await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Advice', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'K-points', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Selection', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('3 × 3 × 3')).toBeVisible();

  // Override the grid: the recommendation becomes stale.
  const grid = page.getByLabel('Grid');
  await grid.fill('4 4 4');
  await expect(page.getByText('Stale', { exact: true }).first()).toBeVisible();

  // Re-run the recommendation: the fresh grid is presented, stale clears.
  await page.getByRole('button', { name: 'Re-run recommendation' }).click();
  await expect(page.getByText('4 × 4 × 4')).toBeVisible();
  await expect(page.getByText('Stale', { exact: true })).toHaveCount(0);

  // Generate and capture the downloadable archive.
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Generate input archive' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('Si-inputs.zip');

  // Independently inspect the ZIP entries and manifest.
  const buffer = readFileSync(await download.path());
  const entries = unzipSync(new Uint8Array(buffer));
  expect(Object.keys(entries)).toEqual(
    expect.arrayContaining(['inputs/qe.in', 'structure.cif', 'goldilocks.json']),
  );

  const manifest = JSON.parse(strFromU8(entries['goldilocks.json']));
  expect(manifest.schema).toBe('goldilocks/manifest');
  expect(manifest.structure.reduced_formula).toBe('Si');
  expect(manifest.records.k_points.grid).toEqual([4, 4, 4]);
  expect(strFromU8(entries['inputs/qe.in'])).toContain("calculation = 'scf'");
});
