import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { posix } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { strFromU8, unzipSync } from "fflate";

import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

const SILICON_CIF = fileURLToPath(
  new URL(
    "../../src/goldilocks_core/examples/structures/Si.cif",
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

test("prepares and downloads a real Core calculation", async ({ page }) => {
  const computeRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/compute") {
      computeRequests.push(request.method());
    }
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("8 atomic sites", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(page.getByText("inputs/qe.in", { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      "Electronic character could not be inferred from structure facts alone.",
    ),
  ).toHaveCount(0);
  await expect(
    page.getByText("Metallicity was inferred from structure-only heuristics."),
  ).toHaveCount(0);
  await expectNoAxeViolations(page);
  await page.getByRole("button", { name: "Dark mode" }).click();
  await expectNoAxeViolations(page);

  const downloadStarted = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download \.zip/ }).click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toMatch(/\.zip$/);
  const path = await download.path();
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    sourceName: "Si.cif",
    tableId: "pseudodojo-pbesol-efficiency-sr",
    tableVersion: "0.4",
  });
  expect(computeRequests).toEqual(["POST"]);
});

test("applies a paired smearing treatment and width override", async ({ page }) => {
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

  await expect(page.getByText("Review out of date")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Download \.zip/ })).toBeDisabled();
  await expectNoAxeViolations(page);

  await page.getByRole("button", { name: "Recompute recommendation" }).click();
  await expect(page.getByText("Review out of date")).toBeHidden();
  await expect(page.getByLabel("Generated input inputs/qe.in")).toContainText(
    "1 1 1",
  );
  await expect(page.getByRole("button", { name: /Download \.zip/ })).toBeEnabled();
});

test("has no Axe violations in empty, failure, and viewer fallback states", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectNoAxeViolations(page);

  const themeToggle = page.getByRole("button", { name: "Dark mode" });
  await themeToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(themeToggle).toHaveAttribute("aria-pressed", "true");
  await expectNoAxeViolations(page);
  await themeToggle.click();

  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.route("**/compute", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          kind: "server_busy",
          message: "Another calculation is using the compute slot.",
          retryable: true,
          details: {},
        },
      }),
    });
  }, { times: 1 });
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Workbench is busy");
  await expect(alert).toContainText(
    "Another calculation is using the compute slot.",
  );
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

  const generate = page.getByRole("button", { name: "Generate recommendation" });
  await generate.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const overrides = page.getByText("Scientific overrides");
  await overrides.press("Enter");
  await expect(page.locator(".advanced-controls")).toHaveAttribute("open");
  const explicitGrid = page.getByRole("checkbox", { name: "Set an explicit grid" });
  await explicitGrid.press("Space");
  await expect(explicitGrid).toBeChecked();
  await expect(
    page.getByRole("status", { name: "Recommendation status" }),
  ).toContainText("Review out of date");

  const firstRecord = page.locator(".record-card").first();
  await firstRecord.locator("summary").press("Enter");
  await expect(firstRecord).toHaveAttribute("open");
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
  await expect(page.getByRole("button", { name: "Dark mode" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const box = await browse.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  expect(box?.width).toBeGreaterThanOrEqual(44);
  await expect(browse).toHaveCSS("outline-style", "solid");
  await expect(browse).toHaveCSS("outline-width", "3px");
});

test("resizes desktop sidebars with pointer and keyboard input", async ({
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
  expect(initialControls).not.toBeNull();
  expect(initialStructure).not.toBeNull();
  expect(handle).not.toBeNull();

  await page.mouse.move(
    (handle?.x ?? 0) + (handle?.width ?? 0) / 2,
    (handle?.y ?? 0) + 200,
  );
  await page.mouse.down();
  await page.mouse.move((handle?.x ?? 0) + 120, (handle?.y ?? 0) + 200);
  await page.mouse.up();

  const resizedControls = await controls.boundingBox();
  const resizedStructure = await structure.boundingBox();
  expect((resizedControls?.width ?? 0) - (initialControls?.width ?? 0)).toBeGreaterThan(80);
  expect((initialStructure?.width ?? 0) - (resizedStructure?.width ?? 0)).toBeGreaterThan(80);

  const reviewHandle = page.getByRole("separator", {
    name: "Resize review panel",
  });
  await reviewHandle.press("ArrowLeft");
  await expect(reviewHandle).toHaveAttribute("aria-valuenow", "34");
});

test("provides a document scrollbar when desktop panes exceed the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1180, height: 700 });
  await page.goto("/");

  const dimensions = await page.evaluate<{
    readonly scrollWidth: number;
    readonly viewportWidth: number;
  }>(`({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  })`);
  expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.viewportWidth);
  await page.evaluate("window.scrollTo(document.body.scrollWidth, 0)");
  expect(await page.evaluate<number>("window.scrollX")).toBeGreaterThan(0);
});

test("reflows intermediate widths without horizontal clipping", async ({ page }) => {
  await page.setViewportSize({ width: 1050, height: 900 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const workspace = await page.getByRole("main").boundingBox();
  const review = await page
    .getByRole("region", { name: "Recommendation review" })
    .boundingBox();
  expect(workspace).not.toBeNull();
  expect(review).not.toBeNull();
  expect((workspace?.x ?? 0) + (workspace?.width ?? 0)).toBeLessThanOrEqual(
    1050,
  );
  expect((review?.x ?? 0) + (review?.width ?? 0)).toBeLessThanOrEqual(1050);
});

test("uses the document scrollbar for long desktop content", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const documentScrolls = await page.evaluate<{
    readonly overflow: string;
    readonly scrollHeight: number;
    readonly viewportHeight: number;
  }>(`({
    overflow: getComputedStyle(document.body).overflow,
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  })`);
  expect(documentScrolls.overflow).toBe("auto");
  expect(documentScrolls.scrollHeight).toBeGreaterThan(
    documentScrolls.viewportHeight,
  );
  await page.evaluate("window.scrollTo(0, document.body.scrollHeight)");
  await expect(page.getByRole("button", { name: /Download \.zip/ })).toBeVisible();
});

test("reflows at effective 200 percent zoom without clipping", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 500 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  await expect(page.locator(".app-header")).toHaveCount(0);
  const mainBox = await page.getByRole("main").boundingBox();
  expect(mainBox).not.toBeNull();
  expect((mainBox?.x ?? 0) + (mainBox?.width ?? 0)).toBeLessThanOrEqual(720);
});

test("removes nonessential animation when reduced motion is requested", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route("**/inspect", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2_000));
    await route.continue();
  }, { times: 1 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const spinner = page.locator(".spinning-icon");
  await spinner.waitFor();

  await expect(spinner).toHaveCSS("animation-name", "none");
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
  await expect(page.locator(".pseudo-table-id code")).toHaveText(
    "sssp-pbesol-efficiency-sr",
  );
  const downloadStarted = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download \.zip/ }).click();
  const download = await downloadStarted;
  const path = await download.path();
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  verifyArchive(entries, {
    sourceName: "POSCAR",
    tableId: "sssp-pbesol-efficiency-sr",
    tableVersion: "1.3.0",
  });
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
    "licences/qrf-kpoints-QRF95.md",
    "licences/metallicity-cgcnn-1.md",
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
