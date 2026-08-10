// Shared helpers for Playwright e2e against the real FastAPI transport.
import { expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

export const siCif = readFileSync(join(here, 'fixtures', 'si.cif'), 'utf8');

/** Paste a known CIF and load it through Core's validation. */
export async function loadStructure(page: Page) {
  await page.getByLabel(/structure content/i).fill(siCif);
  await page.getByRole('button', { name: 'Load structure' }).click();
  await expect(page.getByText(/8 sites/i)).toBeVisible();
  await expect(page.getByText('Volume (Å³)')).toBeVisible();
}

/**
 * Set an explicit k-grid hint so the real backend never consults the ML model
 * (no network, no private data). The workspace is shared, so this persists
 * into both Guided and Graph compute requests.
 */
export async function setKGrid(page: Page, grid = '3 3 3') {
  await page.getByRole('button', { name: /calculation overrides/i }).click();
  const gridInput = page.getByLabel('Grid');
  await gridInput.fill(grid);
}
