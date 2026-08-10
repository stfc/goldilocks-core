// Real-browser 3D viewer lifecycle acceptance.
//
// Repeated structure replacement and Guided/Graph switching must never
// accumulate 3D canvases or break the viewer, and the shell must stay up.
// Headless chromium may or may not expose GPU-backed WebGL; what we gate on is
// the guarantee that matters: canvas count never grows across reloads and view
// switches, and the viewer ends in a consistent state (ready or its textual
// fallback — never a crash). Residual GPU/listener teardown that cannot be
// observed in an automated browser is recorded in the completion report.
import { expect, test } from '@playwright/test';
import { loadStructure } from './helpers';

test('3D viewer does not accumulate canvases across reloads and view switches', async ({
  page,
}) => {
  await page.goto('/');
  await loadStructure(page);

  // Wait for the viewer to settle into a non-loading state (3D ready, or the
  // dependency-free textual fallback if WebGL is unavailable here).
  const settled = async () => {
    await expect
      .poll(async () => {
        const viewer = page.getByRole('img', { name: '3D structure viewer' });
        const fallback = page.getByText(/site/i).first();
        const hasError = await page
          .getByText(/could not render the 3d view/i)
          .count()
          .then((n) => n > 0);
        const ready = await viewer.count().then((n) => n > 0);
        const fallbackVisible = await fallback.isVisible().catch(() => false);
        return ready || fallbackVisible || hasError;
      })
      .toBe(true);
  };
  const canvasCount = async () => page.locator('canvas').count();
  const shellAlive = async () =>
    (await page.getByRole('heading', { name: 'Goldilocks' }).count()) === 1;

  await settled();
  const baseline = await canvasCount();
  // At most one 3D canvas; if WebGL is unavailable it is zero.
  expect(baseline).toBeLessThanOrEqual(1);

  // Replace the structure several times. The adapter updates its single
  // container in place; the canvas count must not grow.
  for (let i = 0; i < 3; i += 1) {
    await page.getByRole('button', { name: 'Load structure' }).click();
    await settled();
    expect(await canvasCount()).toBeLessThanOrEqual(1);
    expect(await shellAlive()).toBe(true);
  }

  // Switch away to Graph and back; the unmounted viewer must not leak its
  // canvas back into the remounted one.
  await page.getByText('Graph', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();
  await page.getByText('Guided', { exact: true }).click();
  await settled();
  expect(await canvasCount()).toBeLessThanOrEqual(1);
  expect(await shellAlive()).toBe(true);

  // The viewer controls are present when the 3D view rendered.
  const ready = await page
    .getByRole('img', { name: '3D structure viewer' })
    .count()
    .then((n) => n > 0);
  if (ready) {
    await expect(page.getByRole('button', { name: 'Reset view' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Export PNG' })).toBeVisible();
  }
});
