// Purposeful but restrained motion, and its reduced-motion override.
//
// The view change animates with a short fade + rise; users who ask for reduced
// motion get the same view instantly (the global `prefers-reduced-motion`
// block nulls animation/transition durations). We assert both the motion exists
// and that it is disabled under the preference — never that a fake backend
// progress bar animates.
import { expect, test } from '@playwright/test';
import { loadStructure } from './helpers';

/** Parse a CSS time ("200ms", "0.2s", "1e-05s") into milliseconds. */
function durationMs(value: string): number {
  if (value.endsWith('ms')) return Number.parseFloat(value);
  if (value.endsWith('s')) return Number.parseFloat(value) * 1000;
  return Number.NaN;
}

test.describe('Workbench motion', () => {
  test('view change animates by default', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);

    await page.getByText('Graph', { exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();

    // The freshly mounted view panel carries the entrance animation (~200 ms).
    const duration = await page
      .locator('[data-view="graph"]')
      .evaluate((el) => getComputedStyle(el as Element).animationDuration);
    expect(durationMs(duration)).toBeGreaterThan(100);
  });

  test('prefers-reduced-motion disables the view transition', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await loadStructure(page);

    await page.getByText('Graph', { exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();

    // The global reduced-motion rule collapses the animation to effectively 0.
    const duration = await page
      .locator('[data-view="graph"]')
      .evaluate((el) => getComputedStyle(el as Element).animationDuration);
    expect(durationMs(duration)).toBeLessThan(1);
  });

  test('no fake per-stage backend progress is shown', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);

    // Running recommendation is a single honest "Running…" live region, not a
    // fabricated node-by-node progress bar.
    await page.getByRole('button', { name: 'Recommend parameters' }).click();
    await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();
    await expect(page.locator('[role="progressbar"]')).toHaveCount(0);
  });
});
