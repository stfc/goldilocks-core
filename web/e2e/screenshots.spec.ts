// Captures visual-review screenshots at supported widths into a gitignored
// test-output path. The screenshots are for the human/orchestrator to inspect;
// they are never committed. Assertions are minimal — they only confirm each
// view actually rendered so we never ship a blank screenshot.
import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadStructure, setKGrid } from './helpers';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, '..', 'test-output', 'screenshots');

const WIDTHS = {
  phone: 390,
  tablet: 768,
  desktop: 1280,
} as const;

test('capture Guided view at phone, tablet, and desktop widths', async ({ page }) => {
  mkdirSync(outDir, { recursive: true });
  await page.goto('/');
  await loadStructure(page);
  await setKGrid(page, '3 3 3');
  await page.getByRole('button', { name: 'Recommend parameters' }).click();
  await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();

  for (const [name, width] of Object.entries(WIDTHS)) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(150);
    await page.screenshot({
      path: resolve(outDir, `guided-${name}.png`),
      fullPage: true,
    });
  }
});

test('capture Graph view at tablet and desktop widths', async ({ page }) => {
  mkdirSync(outDir, { recursive: true });
  await page.goto('/');
  await loadStructure(page);
  await setKGrid(page, '3 3 3');
  await page.getByRole('button', { name: 'Recommend parameters' }).click();
  await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();

  await page.getByText('Graph', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Compute record Analyze' }).check();
  await page.getByRole('checkbox', { name: 'Compute record Advise' }).check();
  await page.getByRole('checkbox', { name: 'Compute record Resolve k-points' }).check();
  await page.getByRole('button', { name: 'Run selected records' }).click();
  await expect(page.getByRole('heading', { name: 'Record results' })).toBeVisible();

  for (const [name, width] of Object.entries({
    tablet: WIDTHS.tablet,
    desktop: WIDTHS.desktop,
  })) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(200);
    await page.screenshot({
      path: resolve(outDir, `graph-${name}.png`),
      fullPage: true,
    });
  }
});
