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
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Start with a structure" }),
  ).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByLabel("Crystal structure viewer")).toBeVisible();
  await expect(page.getByText("8 atomic sites", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(page.getByText("inputs/qe.in", { exact: true })).toBeVisible();
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
    page.getByRole("heading", { name: "Start with a structure" }),
  ).toBeVisible();
  await expectNoAxeViolations(page);

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
  await expect(page.getByRole("alert")).toBeVisible();
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
  await expect(page.getByRole("link", { name: "Goldilocks Workbench home" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(browse).toBeFocused();
  const box = await browse.boundingBox();
  expect(box).not.toBeNull();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  expect(box?.width).toBeGreaterThanOrEqual(44);
  await expect(browse).toHaveCSS("outline-style", "solid");
  await expect(browse).toHaveCSS("outline-width", "3px");
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

test("keeps the desktop workspace contained to the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();

  const header = await page.locator(".app-header").boundingBox();
  const workspace = await page.getByRole("main").boundingBox();
  expect(header).not.toBeNull();
  expect(workspace).not.toBeNull();
  expect((header?.height ?? 0) + (workspace?.height ?? 0)).toBeLessThanOrEqual(
    1000,
  );
});

test("reflows without an overlaying header at effective 200 percent zoom", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 500 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Start with a structure" }),
  ).toBeVisible();

  await expect(page.locator(".app-header")).toHaveCSS("position", "static");
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
