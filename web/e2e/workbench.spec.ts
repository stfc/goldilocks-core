import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { posix } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { strFromU8, unzipSync } from "fflate";

import { expect, test } from "@playwright/test";
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
  await expect(page.getByText("8 atomic sites")).toBeVisible();

  await page.getByRole("button", { name: "Generate recommendation" }).click();
  await expect(
    page.getByRole("heading", { name: "Recommended setup" }),
  ).toBeVisible();
  await expect(page.getByText("inputs/qe.in", { exact: true })).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

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

  await page.getByRole("button", { name: "Recompute recommendation" }).click();
  await expect(page.getByText("Review out of date")).toBeHidden();
  await expect(page.getByLabel("Generated input inputs/qe.in")).toContainText(
    "1 1 1",
  );
  await expect(page.getByRole("button", { name: /Download \.zip/ })).toBeEnabled();
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

function sha256(payload: Uint8Array): string {
  return createHash("sha256").update(payload).digest("hex");
}
