import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { posix } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { strFromU8, unzipSync } from "fflate";

import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

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

test("serves concurrent computations through one real Core runtime", async ({
  request,
}) => {
  const structure = await readFile(SILICON_CIF, "utf8");
  const body = {
    draft: {
      structure: {
        name: "Si.cif",
        content: structure,
        format: "cif",
      },
    },
    selection: { records: ["k_points"] },
  };

  const responses = await Promise.all(
    Array.from({ length: 8 }, () => request.post("/compute", { data: body })),
  );
  const payloads = await Promise.all(
    responses.map(async (response) => {
      expect(response.status()).toBe(200);
      expect(response.headers()["content-type"]).toContain(
        "multipart/form-data",
      );
      return response.text();
    }),
  );
  const grids = payloads.map(
    (payload) => /"grid":\[([0-9]+,[0-9]+,[0-9]+)\]/.exec(payload)?.[1],
  );
  expect(grids.every((grid) => grid !== undefined)).toBe(true);
  expect(new Set(grids).size).toBe(1);
});

test("prepares and downloads a real Core calculation", async ({ page }) => {
  const computeRequests: {
    readonly method: string;
    readonly body: string | null;
  }[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/compute") {
      computeRequests.push({
        method: request.method(),
        body: request.postData(),
      });
    }
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("8 atomic sites", { exact: true })).toBeVisible();
  await page
    .getByLabel("Pseudopotential table")
    .selectOption("pseudodojo-pbesol-efficiency-sr");

  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  const generatedInput = page.getByLabel("Generated input inputs/qe.in");
  await expect(generatedInput).toBeInViewport();
  await expect(
    page.getByRole("button", { name: "Download input files (.zip)" }),
  ).toBeInViewport();

  const inputResize = page.getByRole("separator", {
    name: "Resize generated input",
  });
  const initialInput = await generatedInput.boundingBox();
  const resizeBox = await inputResize.boundingBox();
  assert(initialInput, "Generated input must have a layout box");
  assert(resizeBox, "Generated input resize handle must have a layout box");
  const resizeX = resizeBox.x + resizeBox.width / 2;
  const resizeY = resizeBox.y + resizeBox.height / 2;
  await page.mouse.move(resizeX, resizeY);
  await page.mouse.down();
  await page.mouse.move(resizeX, resizeY + 64, { steps: 4 });
  await page.mouse.up();
  const resizedInput = await generatedInput.boundingBox();
  assert(resizedInput, "Resizing must retain the generated input");
  expect(resizedInput.height - initialInput.height).toBeGreaterThan(40);

  await inputResize.press("End");
  await expect(inputResize).toHaveAttribute(
    "aria-valuetext",
    "Full input file visible",
  );
  await expect(
    page.getByText(
      "Electronic character could not be inferred from structure facts alone.",
    ),
  ).toHaveCount(0);
  await expect(
    page.getByText("Metallicity was inferred from structure-only heuristics."),
  ).toHaveCount(0);
  await expectNoAxeViolations(page);

  await page.getByRole("button", { name: "Back to structure" }).click();
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Recommendation results" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Recommendation", exact: true })
    .click();

  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expectNoAxeViolations(page);

  const downloadStarted = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download input files (.zip)" })
    .click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toMatch(/\.zip$/);
  const path = await download.path();
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    sourceName: "Si.cif",
    tableId: "pseudodojo-pbesol-efficiency-sr",
    tableVersion: "0.4",
  });
  expect(computeRequests).toHaveLength(1);
  expect(computeRequests[0]?.method).toBe("POST");
  expect(computeRequests[0]?.body).toContain(
    '"pseudo_table":"pseudodojo-pbesol-efficiency-sr"',
  );
  for (const forbiddenField of [
    "pseudo_root",
    "pseudo_metadata",
    "kmesh_model",
  ]) {
    expect(computeRequests[0]?.body).not.toContain(forbiddenField);
  }
});

test("opens and closes scientific details with the keyboard", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();

  const sampling = page.getByRole("button", { name: /^K Points/ });
  await expect(sampling).toHaveAttribute("aria-expanded", "false");
  await sampling.press("Enter");
  await expect(page.getByText("QE shift flags", { exact: true })).toBeVisible();
  await expectNoAxeViolations(page);
  await sampling.press("Enter");
  await expect(page.getByText("QE shift flags", { exact: true })).toBeHidden();
});

test("applies a paired smearing treatment and width override", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByText("Scientific overrides").click();
  await page.getByLabel("Smearing treatment").selectOption("cold");
  await page.getByLabel("Smearing width · Ry").fill("0.02");

  await page.getByRole("button", { name: "Generate recommendation" }).click();

  const input = page.getByLabel("Generated input inputs/qe.in");
  await expect(input).toContainText("smearing = 'cold'");
  await expect(input).toContainText("degauss = 0.02");
});

test("keeps an old Result visible until an edited Draft is recomputed", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  await page.getByText("Scientific overrides").click();
  await page.getByRole("checkbox", { name: "Set an explicit grid" }).check();

  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toContainText(
    "Your settings changed. Update the recommendation before downloading.",
  );
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Download input files (.zip)" }),
  ).toBeDisabled();
  await expectNoAxeViolations(page);

  await page.getByRole("button", { name: "Update recommendation" }).click();
  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toBeHidden();
  await expect(page.getByLabel("Generated input inputs/qe.in")).toContainText(
    "1 1 1",
  );
  await expect(
    page.getByRole("button", { name: "Download input files (.zip)" }),
  ).toBeEnabled();
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

  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.route(
    "**/compute",
    async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            kind: "temporary_failure",
            message: "Core failed temporarily.",
            retryable: true,
            details: {},
          },
        }),
      });
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Calculation failed");
  await expect(alert).toContainText("Core failed temporarily.");
  const status = page.getByRole("status", { name: "Workbench status" });
  await expect(status).toHaveText("Needs attention");
  await expect(status).not.toContainText("Ready");
  await expect(status).not.toContainText("Another calculation");
  await expectNoAxeViolations(page);

  await page.addInitScript({
    content: `
      const originalGetContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...args) {
        if (String(type).startsWith("webgl")) return null;
        return originalGetContext.call(this, type, ...args);
      };
    `,
  });
  await page.reload();
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
  const browse = page.getByRole("button", {
    name: "Choose a CIF or POSCAR structure",
  });
  await browse.waitFor();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const chooserPromise = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const chooser = await chooserPromise;
  await chooser.setFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();

  const generate = page.getByRole("button", {
    name: "Generate recommendation",
  });
  await generate.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const overrides = page.getByRole("button", { name: "Scientific overrides" });
  await overrides.press("Enter");
  await expect(overrides).toHaveAttribute("aria-expanded", "true");
  const explicitGrid = page.getByRole("checkbox", {
    name: "Set an explicit grid",
  });
  await explicitGrid.press("Space");
  await expect(explicitGrid).toBeChecked();
  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toContainText(
    "Your settings changed. Update the recommendation before downloading.",
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
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const box = await browse.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  expect(box?.width).toBeGreaterThanOrEqual(44);
  await expect(browse).toHaveCSS("outline-style", "solid");
  await expect(browse).toHaveCSS("outline-width", "3px");
});

test("resizes the two-panel layout with pointer and keyboard input", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");

  const controls = page.getByRole("region", { name: "Calculation setup" });
  const structure = page.getByRole("region", { name: "Structure workspace" });
  const controlsHandle = page.getByRole("separator", {
    name: "Resize calculation setup",
  });
  const initialControls = await controls.boundingBox();
  const initialStructure = await structure.boundingBox();
  const handle = await controlsHandle.boundingBox();
  assert(initialControls, "Calculation panel must have a layout box");
  assert(initialStructure, "Structure panel must have a layout box");
  assert(handle, "Panel resize handle must have a layout box");
  await page.mouse.move(handle.x + handle.width / 2, handle.y + 200);
  await page.mouse.down();
  await page.mouse.move(handle.x + 120, handle.y + 200);
  await page.mouse.up();

  const resizedControls = await controls.boundingBox();
  const resizedStructure = await structure.boundingBox();
  assert(resizedControls, "Resizing must retain the calculation panel");
  assert(resizedStructure, "Resizing must retain the structure panel");
  expect(resizedControls.width - initialControls.width).toBeGreaterThan(80);
  expect(initialStructure.width - resizedStructure.width).toBeGreaterThan(80);

  expect(await page.getByRole("separator").count()).toBe(1);
  await controlsHandle.press("Home");
  await expect(controlsHandle).toHaveAttribute("aria-valuenow", "24");
});

test("constrains resized desktop panes without clipping", async ({ page }) => {
  await page.setViewportSize({ width: 920, height: 700 });
  await page.goto("/");
  const resize = page.getByRole("separator", {
    name: "Resize calculation setup",
  });
  await resize.press("End");
  await expect(resize).toHaveAttribute("aria-valuenow", "42");

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
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const workspace = await page.getByRole("main").boundingBox();
  const review = await page
    .getByRole("region", { name: "Recommendation results" })
    .boundingBox();
  expect(workspace).not.toBeNull();
  expect(review).not.toBeNull();
  expect((workspace?.x ?? 0) + (workspace?.width ?? 0)).toBeLessThanOrEqual(
    1050,
  );
  expect((review?.x ?? 0) + (review?.width ?? 0)).toBeLessThanOrEqual(1050);
});

test("uses the document scrollbar for long desktop content", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const documentScrolls = await page.evaluate<{
    readonly scrollHeight: number;
    readonly viewportHeight: number;
  }>(`({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  })`);
  expect(documentScrolls.scrollHeight).toBeGreaterThan(
    documentScrolls.viewportHeight,
  );
  await page.evaluate("window.scrollTo(0, document.body.scrollHeight)");
  await expect(page.locator(".record-card").last()).toBeInViewport();
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
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(SILICON_POSCAR),
  });

  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("1 atomic sites")).toBeVisible();
  await page
    .getByLabel("Pseudopotential table")
    .selectOption("sssp-pbesol-efficiency-sr");
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(page.getByLabel("Pseudopotential set")).toHaveText(
    "sssp-pbesol-efficiency-sr",
  );
  const downloadStarted = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download input files (.zip)" })
    .click();
  const download = await downloadStarted;
  const path = await download.path();
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    sourceName: "POSCAR",
    tableId: "sssp-pbesol-efficiency-sr",
    tableVersion: "1.3.0",
  });
});

test("every eligible table override produces an archive with its treatment", async ({
  page,
  request,
}) => {
  const response = await request.get("/capabilities");
  const catalog = (await response.json()) as {
    pseudopotential_sets: {
      id: string;
      version: string;
      functional: string;
      accuracy: string;
      relativistic_treatment: string;
      supported_elements: string[];
    }[];
  };
  const tables = catalog.pseudopotential_sets.filter((table) =>
    table.supported_elements.includes("Si"),
  );
  expect(
    tables
      .filter((table) => table.relativistic_treatment === "full")
      .map((table) => table.id),
  ).toEqual([
    "pseudodojo-pbe-efficiency-fr",
    "pseudodojo-pbe-precision-fr",
    "pseudodojo-pbesol-efficiency-fr",
    "pseudodojo-pbesol-precision-fr",
  ]);
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  for (const table of tables) {
    await test.step(table.id, async () => {
      await page.getByLabel("Functional").selectOption(table.functional);
      await page.getByLabel("Accuracy").selectOption(table.accuracy);
      await page.getByLabel("Pseudopotential table").selectOption(table.id);
      const computed = page.waitForResponse(
        (response) => new URL(response.url()).pathname === "/compute",
      );
      await page.locator('button[type="submit"]').click();
      expect((await computed).status()).toBe(200);
      await expect(page.getByLabel("Pseudopotential set")).toHaveText(table.id);
      const downloadStarted = page.waitForEvent("download");
      await page
        .getByRole("button", { name: "Download input files (.zip)" })
        .click();
      const download = await downloadStarted;
      const entries = unzipSync(
        new Uint8Array(await readFile(await download.path())),
      );
      verifyArchive(entries, {
        sourceName: "Si.cif",
        tableId: table.id,
        tableVersion: table.version,
      });
      const result = JSON.parse(textEntry(entries, "goldilocks.json")) as {
        records: {
          selection: {
            pseudopotentials: { relativistic: string; filename: string }[];
          };
        };
      };
      const pseudos = result.records.selection.pseudopotentials;
      expect(pseudos.map((pseudo) => pseudo.relativistic)).toEqual([
        table.relativistic_treatment,
      ]);
      const input = textEntry(entries, "inputs/qe.in");
      expect(input).not.toMatch(/lspinorb\s*=\s*\.true\./i);
      for (const pseudo of pseudos) {
        expect(input).toContain(pseudo.filename);
        expect(Object.keys(entries)).toContain(`pseudo/${pseudo.filename}`);
      }
    });
  }
});

test("table treatment resets with Automatic and functional changes", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const expectedTables: Record<string, string> = {
    automatic: "pseudodojo-pbesol-efficiency-sr",
    functional: "pseudodojo-lda-efficiency-sr",
    accuracy: "pseudodojo-pbesol-precision-sr",
  };
  for (const [reset, expectedTable] of Object.entries(expectedTables)) {
    await page.getByLabel("Functional").selectOption("PBEsol");
    await page.getByLabel("Accuracy").selectOption("efficiency");
    await page
      .getByLabel("Pseudopotential table")
      .selectOption("pseudodojo-pbesol-efficiency-fr");
    if (reset === "automatic") {
      await page.getByLabel("Pseudopotential table").selectOption("");
    } else if (reset === "functional") {
      await page.getByLabel("Functional").selectOption("LDA");
    } else {
      await page.getByLabel("Accuracy").selectOption("precision");
    }
    await page.locator('button[type="submit"]').click();
    await expect(page.getByLabel("Pseudopotential set")).toHaveText(
      expectedTable,
    );
  }
});

test("table choices exclude unsupported elements and disallowed lanthanide tables", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByLabel("Functional").selectOption("PBE");
  const table = page.getByLabel("Pseudopotential table");
  await expect(
    table.locator('option[value="pseudodojo-pbe-lanthanides-sr"]'),
  ).toHaveCount(0);
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Cerium\n1.0\n5.16 0 0\n0 5.16 0\n0 0 5.16\nCe\n1\nDirect\n0 0 0\n",
    ),
  });
  await expect(page.getByText("Ce1", { exact: true })).toBeVisible();
  await page.getByLabel("Functional").selectOption("PBE");
  await expect(table.locator("option")).toHaveText([
    "Automatic",
    "SSSP_1.3.0_PBE_efficiency · PBE · efficiency · scalar",
  ]);
  await table.selectOption("sssp-pbe-efficiency-sr");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByLabel("Pseudopotential set")).toHaveText(
    "sssp-pbe-efficiency-sr",
  );
});

interface ArchiveManifest {
  readonly pseudopotential_set: {
    readonly id: string;
    readonly version: string;
  };
  readonly selected_artifacts: readonly {
    readonly path: string;
    readonly sha256: string;
  }[];
  readonly runtime: {
    readonly core_version: string;
    readonly assets: readonly {
      readonly id: string;
      readonly version: string;
      readonly files: readonly { readonly sha256: string }[];
    }[];
  };
  readonly files: Readonly<
    Record<string, { readonly sha256: string; readonly size_bytes: number }>
  >;
}

function verifyArchive(
  entries: Readonly<Record<string, Uint8Array>>,
  expected: {
    readonly sourceName: string;
    readonly tableId: string;
    readonly tableVersion: string;
  },
): void {
  const names = new Set(Object.keys(entries));
  for (const required of [
    "README.md",
    "CITATIONS.md",
    "checksums.sha256",
    "goldilocks.json",
    "inputs/qe.in",
    `source/${expected.sourceName}`,
    `licences/${expected.tableId}.txt`,
    "licences/models_qrf-kpoints-QRF95.md",
    "licences/models_metallicity-cgcnn-1.md",
    "structure/canonical.cif",
  ]) {
    expect(names).toContain(required);
  }

  const manifest = JSON.parse(
    textEntry(entries, "goldilocks.json"),
  ) as ArchiveManifest;
  expect(manifest.pseudopotential_set.id).toBe(expected.tableId);
  expect(manifest.pseudopotential_set.version).toBe(expected.tableVersion);
  expect(manifest.runtime.core_version).toMatch(/^\d+\.\d+\.\d+/);
  expect(manifest.runtime.assets.length).toBeGreaterThan(0);
  expect(
    manifest.runtime.assets.every((asset) =>
      asset.files.every((file) => file.sha256.length === 64),
    ),
  ).toBe(true);

  for (const pseudo of manifest.selected_artifacts) {
    expect(pseudo.path).toMatch(/^pseudo\//);
    expect(names).toContain(pseudo.path);
    expect(sha256(entry(entries, pseudo.path))).toBe(pseudo.sha256);
  }
  for (const [name, facts] of Object.entries(manifest.files)) {
    const payload = entry(entries, name);
    expect(sha256(payload)).toBe(facts.sha256);
    expect(payload.byteLength).toBe(facts.size_bytes);
  }

  const checksumLines = textEntry(entries, "checksums.sha256")
    .trim()
    .split("\n");
  const checkedNames = new Set<string>();
  for (const line of checksumLines) {
    const separator = line.indexOf("  ");
    expect(separator).toBe(64);
    const digest = line.slice(0, separator);
    const name = line.slice(separator + 2);
    expect(sha256(entry(entries, name))).toBe(digest);
    checkedNames.add(name);
  }
  expect(checkedNames).toEqual(
    new Set([...names].filter((name) => name !== "checksums.sha256")),
  );

  const input = textEntry(entries, "inputs/qe.in");
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

test("keeps the crystal title clear of lattice details", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const viewer = page.getByRole("region", { name: "Crystal structure viewer" });
  await expect(viewer.locator("canvas")).toBeVisible();
  const title = await viewer
    .getByRole("heading", { name: "Si", exact: true })
    .boundingBox();
  const lattice = await viewer.locator("dl").boundingBox();
  assert(title, "Crystal title must have a layout box");
  assert(lattice, "Lattice details must have a layout box");
  expect(lattice.y).toBeGreaterThan(title.y + title.height);
});
