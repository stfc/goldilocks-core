// Graph view against the real backend: load catalogue, select output records,
// run them through Core, and inspect returned values without editing topology.
import { expect, test } from '@playwright/test';
import { loadStructure, setKGrid } from './helpers';

test('graph: catalogue loads, records run, values and raw records are inspectable', async ({
  page,
}) => {
  await page.goto('/');
  await loadStructure(page);
  // Explicit k-grid so selecting k-points never consults the ML model.
  await setKGrid(page, '3 3 3');

  // The visible SegmentedControl label (its radio input is visually hidden).
  await page.getByText('Graph', { exact: true }).click();

  // Backend-owned task topology renders.
  await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();
  await expect(page.getByText(/Single-point SCF/i)).toBeVisible();

  // Select output records; required dependency stages are pulled in.
  await page.getByRole('checkbox', { name: 'Compute record Analyze' }).check();
  await page.getByRole('checkbox', { name: 'Compute record Advise' }).check();
  await page.getByRole('checkbox', { name: 'Compute record Resolve k-points' }).check();

  await page.getByRole('button', { name: 'Run selected records' }).click();
  await expect(page.getByRole('heading', { name: 'Record results' })).toBeVisible();

  // Presented values include the resolved k-point grid from the hint.
  await expect(page.getByText('3 × 3 × 3')).toBeVisible();

  // Raw record inspection without developer tools.
  await page.getByRole('button', { name: /raw records/i }).click();
  await expect(page.getByText(/reduced_formula/i)).toBeVisible();
});
