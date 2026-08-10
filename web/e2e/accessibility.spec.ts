// Accessibility enforcement across the Workbench.
//
// Runs axe scans (serious/critical) on Guided view at phone and desktop and on
// Graph view at desktop, then asserts the behaviours that axe cannot prove:
// keyboard reachability, focus management on view switch, expandable state,
// and that status is never conveyed by colour alone. These test our behaviour
// over the real Mantine/React Flow surface — never those libraries' internals.
import { AxeBuilder } from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { loadStructure } from './helpers';

/** Run axe and return only the violations we gate on (serious + critical). */
async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations.filter((v) =>
    ['serious', 'critical'].includes(v.impact ?? ''),
  );
}

test.describe('Workbench accessibility', () => {
  test('Guided view meets WCAG AA on phone and desktop', async ({ page }) => {
    await page.goto('/');

    // Empty state (structure not yet loaded).
    expect(await seriousViolations(page)).toEqual([]);

    // Phone width, structure loaded + recommendation.
    await page.setViewportSize({ width: 390, height: 844 });
    await loadStructure(page);
    await page.getByRole('button', { name: 'Recommend parameters' }).click();
    await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();
    expect(await seriousViolations(page)).toEqual([]);

    // Desktop, overrides open (more controls on screen).
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole('button', { name: /calculation overrides/i }).click();
    expect(await seriousViolations(page)).toEqual([]);
  });

  test('Graph view meets WCAG AA at desktop width', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);
    await page.getByText('Graph', { exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();

    // Select output records so selected + required + unused nodes all render.
    await page.getByRole('checkbox', { name: 'Compute record Analyze' }).check();
    await page.getByRole('checkbox', { name: 'Compute record Advise' }).check();
    expect(await seriousViolations(page)).toEqual([]);
  });

  test('status is conveyed by text, never by colour alone', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);

    // Running state is announced as text, not just a spinner. (Covered in the
    // RTL suite with a deferred client, where the running state is held still;
    // here the recommendation completes too fast to observe it reliably.)
    await page.getByRole('button', { name: 'Recommend parameters' }).click();

    // Stale is a text badge, and override changes announce it.
    await page.getByRole('button', { name: /calculation overrides/i }).click();
    await page.getByLabel('Grid').fill('4 4 4');
    await expect(page.getByText('Stale', { exact: true }).first()).toBeVisible();

    // Graph nodes label their kind in text + icon (never colour only). The
    // legend itself is text-labelled.
    await page.getByText('Graph', { exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();
    await page.getByRole('checkbox', { name: 'Compute record Analyze' }).check();
    await expect(
      page.getByText('Selected output', { exact: true }).first(),
    ).toBeVisible();
  });

  test('focus moves into the view when switching Guided / Graph', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);

    await page.getByText('Graph', { exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Task Graph' })).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() => document.activeElement?.getAttribute('data-view')),
      )
      .toBe('graph');

    await page.getByText('Guided', { exact: true }).click();
    await expect(page.getByText('Load a structure')).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() => document.activeElement?.getAttribute('data-view')),
      )
      .toBe('guided');
  });

  test('expandable disclosures expose their state and content', async ({ page }) => {
    await page.goto('/');
    await loadStructure(page);
    await page.getByRole('button', { name: 'Recommend parameters' }).click();
    await expect(page.getByRole('heading', { name: 'Recommendation' })).toBeVisible();

    // Calculation overrides: collapsible, reflected in aria-expanded, and its
    // controls become available when open.
    const overrides = page.getByRole('button', { name: /calculation overrides/i });
    await expect(overrides).toHaveAttribute('aria-expanded', 'false');
    await overrides.click();
    await expect(overrides).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByLabel('Grid')).toBeVisible();

    // Raw record disclosure inside the recommendation.
    const raw = page.getByRole('button', { name: /raw analysis/i });
    await raw.click();
    await expect(raw).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByRole('button', { name: 'Copy' })).toBeVisible();
  });

  test('core workflow is keyboard-operable', async ({ page }) => {
    await page.goto('/');

    // The structure textarea is reachable by keyboard and labelled.
    const textarea = page.getByLabel(/structure content/i);
    await textarea.focus();
    await page.keyboard.type('data_Si\n_cell_length_a 5.4');

    // Tab forward from the textarea (bounded) until the Load action is
    // focused, then activate it with Enter (native button semantics).
    let reached = false;
    for (let i = 0; i < 8 && !reached; i += 1) {
      await page.keyboard.press('Tab');
      reached = await page
        .getByRole('button', { name: 'Load structure' })
        .evaluate((el) => el === document.activeElement);
    }
    expect(reached).toBe(true);
    await page.keyboard.press('Enter');
    // The partial CIF cannot parse, so the backend failure surfaces as an
    // alert — proving the Load action activates by keyboard.
    await expect(page.getByRole('alert').first()).toBeVisible();
  });
});
