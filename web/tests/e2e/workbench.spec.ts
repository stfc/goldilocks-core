import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { posix } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { strFromU8, unzipSync } from "fflate";

import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import type { InputManifest } from "../../src/review/artifacts";

const SILICON_CIF = fileURLToPath(
  new URL(
    "../../../src/goldilocks_core/examples/structures/Si.cif",
    import.meta.url,
  ),
);
const SILICON_POSCAR = `Silicon
5.431
1 0 0
0 1 0
0 0 1
Si
1
Direct
0 0 0
`;

test("serves concurrent explains through one real Core runtime", async ({
  request,
}) => {
  const structure = await readFile(SILICON_CIF, "utf8");
  const body = {
    structure_content: structure,
    structure_name: "Si.cif",
    structure_format: "cif",
  };

  const responses = await Promise.all(
    Array.from({ length: 8 }, () => request.post("/explain", { data: body })),
  );
  const payloads = await Promise.all(
    responses.map(async (response) => {
      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain("application/json");
      return response.json() as Promise<{
        records: { k_sampling?: { value?: { mesh?: number[] } } };
      }>;
    }),
  );
  const meshes = payloads.map((payload) =>
    payload.records.k_sampling?.value?.mesh?.join(","),
  );
  expect(meshes.every((mesh) => mesh !== undefined)).toBe(true);
  expect(new Set(meshes).size).toBe(1);
});

test("prepares and downloads a real Core calculation", async ({ page }) => {
  const runRequests: {
    readonly method: string;
    readonly body: string | null;
  }[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/run") {
      runRequests.push({ method: request.method(), body: request.postData() });
    }
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("8 atomic sites", { exact: true })).toBeVisible();
  await expandAdvisorGroup(page, "Pseudopotential table");
  await page
    .getByRole("combobox", { name: "Pseudopotential table", exact: true })
    .selectOption("pseudodojo-pbesol-efficiency-sr");

  await waitForBundleReady(page);

  const downloadStarted = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download (.zip)" }).click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toMatch(/\.zip$/);

  // scf.in is the highest-ranked file (review order: .in, submit.sh,
  // README.md, .json, then everything else) -- each file is its own
  // collapsed Accordion.Item; expanding it renders a GeneratedInputPreview.
  await page.getByRole("button", { name: /^scf\.in/ }).click();
  const generatedInput = page.getByLabel("Generated input scf.in");
  await generatedInput.scrollIntoViewIfNeeded();
  await expect(generatedInput).toBeInViewport();

  const inputResize = page.getByRole("separator", {
    name: "Resize generated input",
  });
  await inputResize.scrollIntoViewIfNeeded();
  const initialInput = await generatedInput.boundingBox();
  const resizeBox = await inputResize.boundingBox();
  assert(initialInput, "Generated input must have a layout box");
  assert(resizeBox, "Generated input resize handle must have a layout box");
  const resizeX = resizeBox.x + resizeBox.width / 2;
  const resizeY = resizeBox.y + resizeBox.height / 2;
  // Drag upward (shrink), not downward -- the compact one-screen dashboard
  // leaves little room below the handle within the actual browser viewport.
  await page.mouse.move(resizeX, resizeY);
  await page.mouse.down();
  await page.mouse.move(resizeX, resizeY - 64, { steps: 4 });
  await page.mouse.up();
  const resizedInput = await generatedInput.boundingBox();
  assert(resizedInput, "Resizing must retain the generated input");
  expect(initialInput.height - resizedInput.height).toBeGreaterThan(40);

  await inputResize.press("End");
  await expect(inputResize).toHaveAttribute(
    "aria-valuetext",
    "Full input file visible",
  );
  await expectNoAxeViolations(page);

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expectNoAxeViolations(page);

  const path = await download.path();
  assert(path, "Download must have a local path");
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    tableId: "pseudodojo-pbesol-efficiency-sr",
    tableVersion: "0.4",
  });
  expect(runRequests.length).toBeGreaterThanOrEqual(1);
  const lastRun = runRequests[runRequests.length - 1];
  expect(lastRun?.method).toBe("POST");
  const runBody = JSON.parse(lastRun?.body ?? "{}") as {
    overrides?: Record<string, unknown>;
  };
  expect(runBody.overrides?.pseudo_table_id).toBe(
    "pseudodojo-pbesol-efficiency-sr",
  );
});

test("opens and closes scientific details with the keyboard", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  const sampling = page.getByRole("button", { name: /^K Sampling/i });
  await expect(sampling).toHaveAttribute("aria-expanded", "false");
  await sampling.press("Enter");
  await expect(sampling).toHaveAttribute("aria-expanded", "true");
  await expectNoAxeViolations(page);
  await sampling.press("Enter");
  await expect(sampling).toHaveAttribute("aria-expanded", "false");
});

test("applies a paired smearing treatment and width override", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Occupations" }).click();
  await page
    .getByRole("combobox", { name: "occupations", exact: true })
    .selectOption("smearing");
  await page.getByLabel("smearing type").selectOption("cold");
  await page.getByLabel("degauss · Ry").fill("0.02");

  await waitForBundleReady(page);
  await page.getByRole("button", { name: /^scf\.in/ }).click();

  const input = page.getByLabel("Generated input scf.in");
  await expect(input).toContainText("smearing = 'cold'");
  await expect(input).toContainText("degauss = 0.02");
});

test("keeps an old Result visible until the recommendation auto-recomputes", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);
  const downloadButton = page.getByRole("button", { name: "Download (.zip)" });
  await expect(downloadButton).toBeEnabled();

  await page.getByRole("button", { name: "K sampling", exact: true }).click();
  // No "set an explicit grid" checkbox any more -- each axis shows its
  // resolved value directly and pins the whole grid as soon as one axis
  // is edited (see KGridControl's own docstring).
  await page.getByLabel("K-point grid x").fill("1");
  await page.getByLabel("K-point grid y").fill("1");
  await page.getByLabel("K-point grid z").fill("1");

  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toContainText(
    "Settings changed — recomputing the recommendation automatically.",
  );
  await expect(downloadButton).toBeDisabled();
  await expectNoAxeViolations(page);

  // No manual "update" action exists any more -- the recommendation
  // recomputes on its own; wait for it to settle again. The notice
  // hiding is not a complete proxy for "ready to download": clearing
  // outOfDate also clears lastDownload in the same update (workspace.ts's
  // computeReview), which immediately arms useAutoCompute's second,
  // independently-debounced effect (review.refreshArchive) -- that
  // re-disables the button for the duration of its own network
  // round-trip, after the notice has already gone hidden. Reuse
  // waitForBundleReady, which already waits out both stages (it exists
  // for exactly this reason on the initial load), instead of a one-stage
  // wait that races the second fetch.
  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toBeHidden({ timeout: 20_000 });
  await waitForBundleReady(page);
  await page.getByRole("button", { name: /^scf\.in/ }).click();
  await expect(page.getByLabel("Generated input scf.in")).toContainText(
    "1 1 1",
  );
});

test("has no Axe violations in empty, failure, and viewer fallback states", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();
  await expectNoAxeViolations(page);

  const themeToggle = page.getByRole("button", {
    name: "Switch to dark mode",
  });
  await themeToggle.click();
  const lightMode = page.getByRole("button", { name: "Switch to light mode" });
  await expect(lightMode).toBeVisible();
  await expectNoAxeViolations(page);
  await lightMode.click();

  await page.waitForLoadState("networkidle");
  await page.route(
    "**/explain",
    async (route) => {
      await route.fulfill({
        status: 424,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            kind: "advice_incomplete",
            message: "Core failed temporarily.",
          },
        }),
      });
    },
    { times: 1 },
  );
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Recommendation incomplete");
  await expect(alert).toContainText("Core failed temporarily.");
  const status = page.getByRole("status", { name: "Workbench status" });
  await expect(status).toHaveText("Needs attention");
  await expect(status).not.toContainText("Ready");
  await expect(status).not.toContainText("Another calculation");
  await expectNoAxeViolations(page);

  await page.addInitScript({
    content: `
      for (const prototype of [
        HTMLCanvasElement.prototype,
        globalThis.OffscreenCanvas?.prototype,
      ]) {
        if (!prototype) continue;
        const originalGetContext = prototype.getContext;
        prototype.getContext = function (type, ...args) {
          if (String(type).includes("webgl")) return null;
          return originalGetContext.call(this, type, ...args);
        };
      }
    `,
  });
  await page.reload();
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(
    page.getByRole("status", { name: "3D structure preview unavailable" }),
  ).toBeVisible();
  await expectNoAxeViolations(page);
});

test("completes the preparation workflow with keyboard-only activation", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const browse = page.getByRole("button", {
    name: "Choose a CIF or POSCAR structure",
  });
  await browse.waitFor();
  // Tab 1: theme toggle. Tab 2: Structure card's scrollable .card-body
  // (focusable so keyboard users can scroll it, see App.css). Tab 3: browse.
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const chooserPromise = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const chooser = await chooserPromise;
  await chooser.setFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await waitForBundleReady(page);

  const kSampling = page.getByRole("button", {
    name: "K sampling",
    exact: true,
  });
  await kSampling.press("Enter");
  await expect(kSampling).toHaveAttribute("aria-expanded", "true");
  // No "set an explicit grid" checkbox any more -- Tab from the header
  // into the K-point grid's first axis (its own first focusable control)
  // and type a value, same keyboard-only spirit as the checkbox this
  // replaces.
  const gridX = page.getByLabel("K-point grid x");
  await page.keyboard.press("Tab");
  await expect(gridX).toBeFocused();
  await page.keyboard.type("1");
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toContainText(
    "Settings changed — recomputing the recommendation automatically.",
  );

  const firstRecord = page
    .locator(".record-card")
    .first()
    .getByRole("button")
    .first();
  await firstRecord.press("Enter");
  await expect(firstRecord).toHaveAttribute("aria-expanded", "true");
});

test("keeps keyboard focus visible and primary targets usable", async ({
  page,
}) => {
  await page.goto("/");
  const browse = page.getByRole("button", {
    name: "Choose a CIF or POSCAR structure",
  });
  await browse.waitFor();

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Switch to dark mode" }),
  ).toBeFocused();
  // Structure card's scrollable .card-body is the next stop (focusable so
  // keyboard users can scroll it, see App.css), then the browse button.
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const box = await browse.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  expect(box?.width).toBeGreaterThanOrEqual(44);
  await expect(browse).toHaveCSS("outline-style", "solid");
  await expect(browse).toHaveCSS("outline-width", "3px");
});

test("constrains a narrow desktop layout without clipping", async ({
  page,
}) => {
  await page.setViewportSize({ width: 920, height: 700 });
  await page.goto("/");

  const dimensions = await page.evaluate<{
    readonly scrollWidth: number;
    readonly viewportWidth: number;
  }>(`({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  })`);
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
});

test("reflows intermediate widths without horizontal clipping", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1050, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  const workspace = await page.getByRole("main").boundingBox();
  const bundle = await page
    .getByRole("region", { name: "Bundle" })
    .boundingBox();
  expect(workspace).not.toBeNull();
  expect(bundle).not.toBeNull();
  expect((workspace?.x ?? 0) + (workspace?.width ?? 0)).toBeLessThanOrEqual(
    1050,
  );
  expect((bundle?.x ?? 0) + (bundle?.width ?? 0)).toBeLessThanOrEqual(1050);
});

test("keeps the document static and scrolls long content inside its own card", async ({
  page,
}) => {
  // The 4-card dashboard is deliberately designed to fit one screen (no
  // document-level scrollbar); each card's own .card-body scrolls
  // internally instead once its content overflows.
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  const documentScrolls = await page.evaluate<{
    readonly scrollHeight: number;
    readonly viewportHeight: number;
  }>(`({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  })`);
  expect(documentScrolls.scrollHeight).toBeLessThanOrEqual(
    documentScrolls.viewportHeight,
  );

  for (const name of [
    "Composition composition",
    "Geometry geometry",
    "Symmetry symmetry",
    "Relativistic relativistic",
    "Symmetry Eff symmetry_eff",
  ]) {
    await page.getByRole("button", { name }).click();
  }
  const analysisBody = page.locator(".card-analysis .card-body");
  const lastRecord = page.locator(".card-analysis .record-card").last();
  await analysisBody.focus();
  await analysisBody.evaluate(
    "(element) => { element.scrollTop = element.scrollHeight; }",
  );
  await expect(lastRecord).toBeInViewport();
});

test("reflows at effective 200 percent zoom without clipping", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 500 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  const mainBox = await page.getByRole("main").boundingBox();
  expect(mainBox).not.toBeNull();
  expect((mainBox?.x ?? 0) + (mainBox?.width ?? 0)).toBeLessThanOrEqual(720);
});

test("removes nonessential animation when reduced motion is requested", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route(
    "**/inspect",
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      await route.continue();
    },
    { times: 1 },
  );
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(
    page.getByRole("status", { name: "Workbench status" }),
  ).toHaveText("Inspecting structure");
  const runningAnimations =
    await page.evaluate<number>(`document.getAnimations()
    .filter((animation) => animation.playState === "running").length`);
  expect(runningAnimations).toBe(0);
});

test("prepares a real Core recommendation from POSCAR", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(SILICON_POSCAR),
  });

  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("1 atomic sites")).toBeVisible();
  await expandAdvisorGroup(page, "Pseudopotential table");
  await page
    .getByRole("combobox", { name: "Pseudopotential table", exact: true })
    .selectOption("sssp-pbesol-efficiency-sr");
  await waitForBundleReady(page);
  await expandAdvisorGroup(page, "Pseudopotential table");
  // The pinned table's own id is the select's value, not rendered as
  // separate text anywhere -- PseudoTableControl shows the real
  // provider/functional/accuracy/relativistic label, not a raw id.
  await expect(
    page.getByRole("combobox", { name: "Pseudopotential table", exact: true }),
  ).toHaveValue("sssp-pbesol-efficiency-sr");

  const downloadStarted = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download (.zip)" }).click();
  const download = await downloadStarted;
  const path = await download.path();
  assert(path, "Download must have a local path");
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    tableId: "sssp-pbesol-efficiency-sr",
    tableVersion: "1.3.0",
  });
});

test("relax-only overrides stay hidden until the relax task is chosen", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByRole("button", { name: "Relax" })).not.toBeVisible();

  await page.getByLabel("Task", { exact: true }).selectOption("relax");
  await expect(page.getByRole("button", { name: "Relax" })).toBeVisible();
});

test("table treatment clears when the functional changes", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expandAdvisorGroup(page, "Pseudopotential table");
  await expandAdvisorGroup(page, "Functional");
  const table = page.getByRole("combobox", {
    name: "Pseudopotential table",
    exact: true,
  });

  await page
    .getByRole("combobox", { name: "Functional", exact: true })
    .selectOption("PBEsol");
  await table.selectOption("pseudodojo-pbesol-efficiency-fr");
  expect(await table.inputValue()).toBe("pseudodojo-pbesol-efficiency-fr");

  await page
    .getByRole("combobox", { name: "Functional", exact: true })
    .selectOption("LDA");
  expect(await table.inputValue()).toBe("");
  await expect(
    table.locator('option[value="pseudodojo-pbesol-efficiency-fr"]'),
  ).toHaveCount(0);
});

test("table choices exclude tables that don't cover the structure's elements", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expandAdvisorGroup(page, "Functional");
  await expandAdvisorGroup(page, "Pseudopotential table");
  await page
    .getByRole("combobox", { name: "Functional", exact: true })
    .selectOption("PBE");
  const table = page.getByRole("combobox", {
    name: "Pseudopotential table",
    exact: true,
  });
  await expect(
    table.locator('option[value="pseudodojo-pbe-lanthanides-sr"]'),
  ).toHaveCount(0);
  await waitForBundleReady(page);
  await page.waitForLoadState("networkidle");

  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Cerium\n1.0\n5.16 0 0\n0 5.16 0\n0 0 5.16\nCe\n1\nDirect\n0 0 0\n",
    ),
  });
  await expect(page.getByLabel("Inspected structure summary")).toContainText(
    "Ce1",
  );
  await page
    .getByRole("combobox", { name: "Functional", exact: true })
    .selectOption("PBE");
  // Confirmed against a live /capabilities call: three real tables cover
  // Ce+PBE (pseudodojo's own lanthanides table plus both sssp accuracy
  // levels). The frontend deliberately doesn't replicate the backend's
  // automatic-selection preference for sssp on lanthanides (that
  // heuristic lives in advisors/pseudo_selection.py, not duplicated
  // here) -- picking a table here is an explicit human override, not
  // automatic selection, so every element-eligible table is offered.
  // "—" (not a literal "Automatic" label) is the pseudopotential-table
  // control's own placeholder, shown only while nothing has resolved yet
  // -- see OverrideControl.tsx/CalculationForm.tsx's PseudoTableControl,
  // which otherwise pre-selects whichever table actually resolved.
  await expect(table.locator("option")).toHaveText([
    "—",
    "pseudodojo · PBE · efficiency · scalar",
    "sssp · PBE · efficiency · scalar",
    "sssp · PBE · precision · scalar",
  ]);
  await table.selectOption("sssp-pbe-efficiency-sr");
  await waitForBundleReady(page);
  await expandAdvisorGroup(page, "Pseudopotential table");
  await expect(table).toHaveValue("sssp-pbe-efficiency-sr");
});

test("keeps lattice details out of the crystal viewer until requested", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const viewer = page.getByRole("region", { name: "Crystal structure viewer" });
  await expect(viewer.locator("canvas")).toBeVisible();
  await expect(
    viewer.getByRole("heading", { name: "Si", exact: true }),
  ).toBeVisible();
  await expect(page.locator("dl")).toHaveCount(0);

  await viewer
    .getByRole("button", { name: "Inspect lattice, sites and occupancies" })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Lattice, sites and occupancies" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Lattice parameters" }).locator("dl"),
  ).toBeVisible();
});

/** Every settings-group Accordion.Panel is a `role="region"` whose
 * accessible name is its own control's text (Mantine's Accordion gives
 * the panel `aria-labelledby` pointing at the control) -- scoping by
 * role keeps this from also matching the group's own form control,
 * which can carry the identical accessible name (e.g. the
 * "Pseudopotential table" group's own select). */
async function expandAdvisorGroup(page: Page, name: string): Promise<void> {
  const control = page.getByRole("button", { name, exact: true });
  if ((await control.getAttribute("aria-expanded")) === "true") return;
  await control.click();
}

/** Waits for useAutoCompute's debounced recommendation to finish and the
 * archive to be fetched -- there is no manual "generate" action any more,
 * everything computes automatically once a structure loads or a setting
 * changes (see BundleCard.tsx). */
async function waitForBundleReady(page: Page): Promise<void> {
  await expect(page.getByText("No recommendation yet")).toHaveCount(0, {
    timeout: 20_000,
  });
  await expect(
    page.getByRole("button", { name: "Download (.zip)" }),
  ).toBeEnabled({ timeout: 20_000 });
}

function verifyArchive(
  entries: Readonly<Record<string, Uint8Array>>,
  expected: {
    readonly tableId: string;
    readonly tableVersion: string;
  },
): void {
  // Confirmed against a real /run call (respond_with: archive, 2026-09-14):
  // bundle_files() only ever emits the generation artifacts themselves
  // (here scf.in + pseudo/<file>), submit.sh, and the three fixed meta
  // files -- v2 never copies the original/canonical structure into the
  // archive the way v1 did (no source/, structure/, or licences/ paths).
  const names = new Set(Object.keys(entries));
  for (const required of [
    "README.md",
    "CITATIONS.md",
    "goldilocks.json",
    "scf.in",
    "submit.sh",
  ]) {
    expect(names).toContain(required);
  }

  const manifest = JSON.parse(
    textEntry(entries, "goldilocks.json"),
  ) as InputManifest & {
    readonly records: {
      readonly pseudo_table?: {
        readonly value?: { readonly id?: string; readonly version?: string };
      };
      readonly pseudopotentials?: {
        readonly value?: readonly { readonly filename: string | null }[];
      };
    };
  };
  expect(manifest.records.pseudo_table?.value?.id).toBe(expected.tableId);
  expect(manifest.records.pseudo_table?.value?.version).toBe(
    expected.tableVersion,
  );

  for (const pseudo of manifest.records.pseudopotentials?.value ?? []) {
    assert(
      pseudo.filename !== null,
      "Published pseudopotential needs a filename",
    );
    const path = `pseudo/${pseudo.filename}`;
    expect(names).toContain(path);
    expect(manifest.files[path]?.role).toBe("pseudopotential");
  }
  expect(new Set(Object.keys(manifest.files))).toEqual(
    new Set([...names].filter((name) => name !== "goldilocks.json")),
  );
  for (const [name, facts] of Object.entries(manifest.files)) {
    const payload = entry(entries, name);
    expect(sha256(payload)).toBe(facts.sha256);
    expect(payload.byteLength).toBe(facts.size_bytes);
  }

  const input = textEntry(entries, "scf.in");
  const pseudoDir = /pseudo_dir\s*=\s*'([^']+)'/.exec(input)?.[1];
  expect(pseudoDir).toBeDefined();
  expect(posix.normalize(pseudoDir ?? "")).toBe("pseudo");
}

function textEntry(
  entries: Readonly<Record<string, Uint8Array>>,
  name: string,
): string {
  return strFromU8(entry(entries, name));
}

function entry(
  entries: Readonly<Record<string, Uint8Array>>,
  name: string,
): Uint8Array {
  const payload = entries[name];
  if (payload === undefined) throw new Error(`archive entry missing: ${name}`);
  return payload;
}

async function expectNoAxeViolations(page: Page): Promise<void> {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
}

function sha256(payload: Uint8Array): string {
  return createHash("sha256").update(payload).digest("hex");
}
