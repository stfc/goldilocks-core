// Expected backend failures surface as useful, localised errors that never
// discard valid workspace state.
import { expect, test } from '@playwright/test';
import { loadStructure } from './helpers';

test('malformed structure surfaces a structured backend error', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel(/structure content/i).fill('this is not a cif or poscar');
  await page.getByRole('button', { name: 'Load structure' }).click();

  // The transport error is visible and diagnostic, not "something went wrong".
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(/invalid_request/)).toBeVisible();

  // No structure was accepted, so no recommendation controls appear.
  await expect(page.getByRole('button', { name: /recommend/i })).toHaveCount(0);
});

test('a failed recommendation keeps the loaded structure', async ({ page }) => {
  await page.goto('/');
  await loadStructure(page);

  // Corrupt the pasted content so Core fails structure parsing on re-load, then
  // confirm the previous valid structure is still shown after the error.
  await page.getByLabel(/structure content/i).fill('garbage');
  await page.getByRole('button', { name: 'Load structure' }).click();

  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(/8 sites/i)).toBeVisible();
});
