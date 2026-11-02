import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { posix } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { strFromU8, unzipSync } from "fflate";

import {
  expect,
  test,
  type Locator,
  type Page,
  type Request,
} from "@playwright/test";
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
const IRON_BCC_CIF = fileURLToPath(
  new URL(
    "../../../src/goldilocks_core/examples/structures/Fe_bcc.cif",
    import.meta.url,
  ),
);
const PLATINUM_FCC_CIF = fileURLToPath(
  new URL(
    "../../../src/goldilocks_core/examples/structures/Pt_fcc.cif",
    import.meta.url,
  ),
);
/** A finding of Core's `/explain` verdict and of a refused `/run` (#151). */
interface BlockingFindingDocument {
  readonly code: string;
  readonly fields: readonly string[];
  readonly message: string;
  readonly remedies: readonly Readonly<Record<string, unknown>>[];
}

/** One-atom fcc Ni, the cell of MC3D mc3d-4988. */
const NICKEL_FCC_POSCAR = `Nickel fcc primitive
3.524
0 0.5 0.5
0.5 0 0.5
0.5 0.5 0
Ni
1
Direct
0 0 0
`;
/** One-atom fcc Al: 3 valence electrons, an odd count that fixed occupations
 * without spin polarization cannot fill. */
const ALUMINIUM_FCC_POSCAR = `Aluminium fcc primitive
4.05
0 0.5 0.5
0.5 0 0.5
0.5 0.5 0
Al
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
    structureName: "Si.cif",
    structureBytes: new Uint8Array(await readFile(SILICON_CIF)),
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

test("corrects the metallicity classification from the Analysis card", async ({
  page,
}) => {
  // #139: every value the is_metal select offers was a 422 that disabled
  // Download.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  const corrected = page.waitForResponse((response) => {
    if (new URL(response.url()).pathname !== "/explain") return false;
    const body = response.request().postDataJSON() as {
      overrides?: Record<string, unknown>;
    } | null;
    return body?.overrides?.is_metal === "non_metal";
  });
  await page
    .getByRole("region", { name: "Goldilocks analysis" })
    .getByRole("combobox", { name: "is metal" })
    .selectOption("non_metal");
  expect((await corrected).status()).toBe(200);

  await waitForBundleReady(page);
  await expect(page.getByText("Check your overrides")).toHaveCount(0);
  await page.getByRole("button", { name: /^scf\.in/ }).click();
  await expect(page.getByLabel("Generated input scf.in")).toContainText(
    "occupations = 'fixed'",
  );
});

test("shows needs soc as read-only advice beside the spin-orbit setting", async ({
  page,
}) => {
  // #186: needs_soc was an On/Off select whose value changed no generated
  // file. spin_orbit_coupling is the one SOC setting, and the advice is a
  // note in its group.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(PLATINUM_FCC_CIF);
  await waitForBundleReady(page);

  const analysis = page.getByRole("region", { name: "Goldilocks analysis" });
  const needsSoc = analysis.getByRole("group", { name: "needs soc" });
  await expect(needsSoc.getByText("Yes", { exact: true })).toBeVisible();
  await expect(needsSoc).toHaveAccessibleDescription(
    /spin_orbit_coupling setting enables it\. · Heuristic default$/,
  );
  await expect(
    analysis.getByRole("combobox", { name: "needs soc" }),
  ).toHaveCount(0);
  await expect(
    analysis.getByRole("combobox", { name: "needs correlation", exact: true }),
  ).toBeEnabled();

  await expandAdvisorGroup(page, "Magnetic");
  const magnetic = page.getByRole("region", { name: "Magnetic", exact: true });
  await expect(
    magnetic.getByRole("combobox", { name: "spin orbit coupling" }),
  ).toBeEnabled();
  await expect(
    magnetic.getByText(/consider enabling spin_orbit_coupling/),
  ).toBeVisible();
  await expectNoAxeViolations(page);
});

test("shows each setting's recorded value, captioned only by the tier that set it", async ({
  page,
}) => {
  // #187: the Workbench read record.value[setting.key], so spin orbit
  // coupling (recorded as spin_orbit_enabled) and magnetic ordering
  // (ordering.applied) showed nothing under a tier caption, and pinning spin
  // polarized captioned the untouched tot magnetization "Your override".
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(IRON_BCC_CIF);
  await waitForBundleReady(page);

  await expandAdvisorGroup(page, "Magnetic");
  const magnetic = page.getByRole("region", { name: "Magnetic", exact: true });
  await pinOverride(
    page,
    magnetic.getByRole("combobox", { name: "spin polarized" }),
    "true",
    { spin_polarized: true },
  );
  const spinOrbit = magnetic.getByRole("combobox", {
    name: "spin orbit coupling",
  });
  await expect(spinOrbit).toHaveValue("false");
  await expect(spinOrbit).toHaveAccessibleDescription(
    /never auto-enabled\)\. · Heuristic default$/,
  );
  const ordering = magnetic.getByRole("textbox", { name: "magnetic ordering" });
  await expect(ordering).toHaveValue("fm");
  await expect(ordering).toHaveAccessibleDescription(/ · Heuristic default$/);
  const moment = magnetic.getByRole("spinbutton", {
    name: "tot magnetization",
  });
  await expect(moment).toHaveValue("");
  await expect(moment).toHaveAccessibleDescription(
    /bands\.x stops on the two Fermi energies it gives\.$/,
  );
  await expect(
    magnetic.getByRole("combobox", { name: "spin polarized" }),
  ).toHaveAccessibleDescription(/ · Your override$/);
  await expectNoAxeViolations(page);
});

test("shows no magnetic ordering for a run without spin polarization", async ({
  page,
}) => {
  // #187: such a run applies no ordering, yet magnetic ordering read "fm"
  // under "Heuristic default" next to spin polarized off, and "fm" as an
  // override asks for spin polarization.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  await expandAdvisorGroup(page, "Magnetic");
  const magnetic = page.getByRole("region", { name: "Magnetic", exact: true });
  await expect(
    magnetic.getByRole("combobox", { name: "spin polarized" }),
  ).toHaveValue("false");
  const ordering = magnetic.getByRole("textbox", { name: "magnetic ordering" });
  await expect(ordering).toHaveValue("");
  await expect(ordering).toHaveAccessibleDescription(
    /that is not listed is refused\.$/,
  );
});

test("lists a dos task's nscf decisions under their step in Advisors", async ({
  page,
}) => {
  // #187: a record counted as an advisor's only when its key equalled a
  // settings group, so the nscf_ records landed under Analysis.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);

  const explained = page.waitForResponse((response) => {
    if (new URL(response.url()).pathname !== "/explain") return false;
    const body = response.request().postDataJSON() as { task?: string } | null;
    return body?.task === "dos";
  });
  await page.getByLabel("Task", { exact: true }).selectOption("dos");
  expect((await explained).status()).toBe(200);
  await waitForBundleReady(page);

  const advisors = page.getByRole("region", { name: "Goldilocks advisors" });
  const nscf = advisors.getByRole("region", { name: "nscf step" });
  await expect(nscf.getByRole("button")).toHaveText([
    /^Nscf Occupations\s*nscf_occupations$/,
    /^Nscf K Sampling\s*nscf_k_sampling$/,
    /^Nscf N Irr K\s*nscf_n_irr_k$/,
    /^Nscf Nbnd\s*nscf_nbnd$/,
    /^Nscf Convergence\s*nscf_convergence$/,
    /^Nscf Parallelisation\s*nscf_parallelisation$/,
  ]);
  await expect(
    advisors.getByRole("button", { name: "Pseudopotentials pseudopotentials" }),
  ).toBeVisible();
  const analysis = page.getByRole("region", { name: "Goldilocks analysis" });
  await expect(analysis.getByRole("button", { name: /nscf_/ })).toHaveCount(0);
  await expect(
    analysis.getByRole("button", { name: /relativistic/ }),
  ).toHaveCount(0);
  await expectNoAxeViolations(page);
});

test("resets every kind of pinned select to automatic with a mouse click", async ({
  page,
}) => {
  // #158: NativeSelect's right section passes pointer events through to the
  // <select> so that its chevron opens it, and the reset button in that
  // section inherited this, so a mouse click only focused the select.
  // locator.click() without force fails while the <select> intercepts it.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);
  for (const group of ["Convergence", "Pseudopotential table", "Functional"]) {
    await expandAdvisorGroup(page, group);
  }
  const analysis = page.getByRole("region", { name: "Goldilocks analysis" });
  const advisors = page.getByRole("region", { name: "Goldilocks advisors" });
  const table = advisors.getByRole("combobox", {
    name: "Pseudopotential table",
    exact: true,
  });
  const automaticTable = await table.inputValue();

  // A boolean fact, an enum setting and the pseudopotential table.
  for (const { scope, field, option, key, value } of [
    {
      scope: analysis,
      field: "needs correlation",
      option: "true",
      key: "needs_correlation",
      value: true,
    },
    {
      scope: advisors,
      field: "mixing mode",
      option: "local-TF",
      key: "mixing_mode",
      value: "local-TF",
    },
    {
      scope: advisors,
      field: "Pseudopotential table",
      option: "sssp-pbesol-efficiency-sr",
      key: "pseudo_table_id",
      value: "sssp-pbesol-efficiency-sr",
    },
  ]) {
    const select = scope.getByRole("combobox", { name: field, exact: true });
    const automatic = await select.inputValue();
    await pinOverride(page, select, option, { [key]: value });
    await expect(select).toHaveAccessibleDescription(/Your override/);

    const reset = scope.getByRole("button", {
      name: `Reset ${field} to automatic`,
    });
    expect(await clickForNextExplain(page, reset)).not.toHaveProperty(key);
    await expect(reset).toHaveCount(0);
    await expect(select).toHaveValue(automatic);
    await expect(select).not.toHaveAccessibleDescription(/Your override/);
    expect(await rightSectionClickTarget(select)).toBe("SELECT");
  }

  // The functional: its reset also drops the table pinned under it.
  const functional = advisors.getByRole("combobox", {
    name: "Functional",
    exact: true,
  });
  const automaticFunctional = await functional.inputValue();
  await pinOverride(page, functional, "PBE", { functional: "PBE" });
  await pinOverride(page, table, "sssp-pbe-efficiency-sr", {
    functional: "PBE",
    pseudo_table_id: "sssp-pbe-efficiency-sr",
  });
  const overrides = await clickForNextExplain(
    page,
    advisors.getByRole("button", { name: "Reset Functional to automatic" }),
  );
  expect(overrides).not.toHaveProperty("functional");
  expect(overrides).not.toHaveProperty("pseudo_table_id");
  await expect(functional).toHaveValue(automaticFunctional);
  await expect(table).toHaveValue(automaticTable);
  await expect(
    advisors.getByRole("button", { name: /^Reset .* to automatic$/ }),
  ).toHaveCount(0);
  expect(await rightSectionClickTarget(functional)).toBe("SELECT");
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
  // recomputes on its own; just wait for it to settle again.
  await expect(
    page.getByRole("status", { name: "Recommendation notice" }),
  ).toBeHidden({ timeout: 20_000 });
  await expect(downloadButton).toBeEnabled();
  await page.getByRole("button", { name: /^scf\.in/ }).click();
  await expect(page.getByLabel("Generated input scf.in")).toContainText(
    "1 1 1",
  );
});

test("retries a failed preview without downloading its archive", async ({
  page,
}) => {
  // #189: Retry on a failed automatic preview used to save the refetched
  // archive as a browser download, although Download was never pressed.
  const downloads: string[] = [];
  page.on("download", (download) => {
    downloads.push(download.suggestedFilename());
  });
  let runs = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/run") runs += 1;
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.route(
    "**/run",
    async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "text/plain",
        body: "Service Unavailable",
      });
    },
    { times: 1 },
  );
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const alert = page.getByRole("alert");
  await expect(alert).toContainText(
    "The Goldilocks Core server rejected the request (503).",
    { timeout: 20_000 },
  );
  const downloadButton = page.getByRole("button", { name: "Download (.zip)" });
  await expect(downloadButton).toBeDisabled();

  await alert.getByRole("button", { name: "Retry" }).click();
  await expect(
    page.getByRole("status", { name: "Archive status" }),
  ).toContainText("is ready", { timeout: 20_000 });
  await expect(alert).toHaveCount(0);
  expect(downloads).toEqual([]);

  const downloadStarted = page.waitForEvent("download");
  await downloadButton.click();
  await downloadStarted;
  expect(downloads).toHaveLength(1);
  // The failed preview and its retry; Download sent no /run of its own.
  expect(runs).toBe(2);
});

test("keeps a refused /run as the draft's outcome without re-sending it", async ({
  page,
}) => {
  // #150: after a 422 from the automatic /run, Dismiss re-sent it within about
  // 200 ms, Download stayed enabled and re-sent it on every click, and the
  // Bundle card still promised the files.
  let runs = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/run") runs += 1;
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.route("**/run", async (route) => {
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          kind: "generation_error",
          message: "Core cannot generate these inputs.",
        },
      }),
    });
  });
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Core cannot generate these inputs.", {
    timeout: 20_000,
  });
  await expect(alert.getByRole("button", { name: "Retry" })).toBeEnabled();
  const download = page.getByRole("button", { name: "Download (.zip)" });
  await expect(download).toBeDisabled();
  await expect(download).toHaveAccessibleDescription(
    "Input generation failed for the current settings: Core cannot generate these inputs.",
  );
  await expect(
    page.getByRole("status", { name: "Input generation failed" }),
  ).toContainText("Core cannot generate these inputs.");
  await expect(
    page.getByText(
      "No input files were generated: generation failed for the current settings.",
    ),
  ).toBeVisible();
  await expectNoAxeViolations(page);

  await alert.getByRole("button", { name: "Dismiss error" }).click();
  await page.waitForTimeout(2_000);

  await expect(alert).toHaveCount(0);
  await expect(download).toBeDisabled();
  expect(runs).toBe(1);

  // Retry, here from the card, sends that /run once more and no more.
  await page.getByRole("button", { name: "Retry generation" }).click();
  await expect(alert).toContainText("Core cannot generate these inputs.", {
    timeout: 20_000,
  });
  await page.waitForTimeout(1_000);
  expect(runs).toBe(2);
});

test("sends no /run for a draft the /explain verdict refuses", async ({
  page,
}) => {
  // #165: /explain returns the reasons /run would refuse for. A refused draft
  // still got the automatic /run, and Download stayed enabled until its 422.
  let runs = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/run") runs += 1;
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);
  await expandAdvisorGroup(page, "Occupations");
  await pinOverride(
    page,
    page.getByRole("combobox", { name: "occupations", exact: true }),
    "fixed",
    { occupations: "fixed" },
  );

  // Fixed occupations for a collinear spin-polarized run need an explicit
  // tot_magnetization, so check() refuses this draft.
  await expandAdvisorGroup(page, "Magnetic");
  const refused = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/explain" &&
      requestOverrides(response.request()).spin_polarized === true,
  );
  await page.getByLabel("spin polarized").selectOption("true");
  const verdict = (await (await refused).json()) as {
    readonly blocking: readonly BlockingFindingDocument[];
  };
  expect(verdict.blocking).toEqual([
    expect.objectContaining({
      code: "occupations.fixed_needs_tot_magnetization",
      fields: ["occupations", "tot_magnetization"],
      remedies: [{ occupations: "smearing" }],
    }),
  ]);
  const message = verdict.blocking[0]?.message ?? "";
  const runsBeforeVerdict = runs;
  await page.waitForTimeout(2_000);

  expect(runs).toBe(runsBeforeVerdict);
  const download = page.getByRole("button", { name: "Download (.zip)" });
  await expect(download).toBeDisabled();
  await expect(download).toHaveAccessibleDescription(
    `Input files cannot be generated for the current settings: ${message}`,
  );
  const notice = page.getByRole("status", {
    name: "Cannot generate input files",
  });
  await expect(notice).toContainText(message);
  await expect(
    page.getByRole("note", { name: "Blocks input generation: occupations" }),
  ).toContainText(message);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expectNoAxeViolations(page);

  // #151: the finding's remedy is a button; it patches the draft, and Core
  // accepts the result, so the preview /run follows.
  const overrides = await clickForNextExplain(
    page,
    notice.getByRole("button", { name: "Apply occupations = smearing" }),
  );

  expect(overrides).toMatchObject({
    occupations: "smearing",
    spin_polarized: true,
  });
  await waitForBundleReady(page);
  await expect(notice).toHaveCount(0);
});

test("offers a refused /run's remedies and sends the chosen one with the next /explain", async ({
  page,
}) => {
  // #151: the 422 banner showed the gate's prose and named neither the
  // setting nor the override that fixes it.
  const finding: BlockingFindingDocument = {
    code: "occupations.fixed_needs_tot_magnetization",
    fields: ["occupations", "tot_magnetization"],
    message:
      "occupations=fixed on a collinear spin-polarized run needs an integer tot_magnetization of the electron count's parity, and none was set or derived. Set occupations=smearing, or set tot_magnetization.",
    remedies: [{ occupations: "smearing" }],
  };
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.route(
    "**/run",
    async (route) => {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          error: {
            kind: "advice_incomplete",
            message: `cannot generate a runnable input: ${finding.message} Remedy overrides: {"occupations": "smearing"}.`,
            details: { findings: [finding] },
          },
        }),
      });
    },
    { times: 1 },
  );
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);

  const alert = page.getByRole("alert");
  await expect(alert).toContainText(finding.message, { timeout: 20_000 });
  await expect(alert).not.toContainText("Remedy overrides");
  const remedy = alert.getByRole("button", {
    name: "Apply occupations = smearing",
  });
  await expect(remedy).toBeVisible();
  await expandAdvisorGroup(page, "Occupations");
  await expect(
    page.getByRole("note", { name: "Blocks input generation: occupations" }),
  ).toContainText(finding.message);
  await expectNoAxeViolations(page);

  const overrides = await clickForNextExplain(page, remedy);

  expect(overrides).toEqual({ occupations: "smearing" });
  await waitForBundleReady(page);
  await expect(alert).toHaveCount(0);
});

test("wraps a finding's remedy buttons within a control's note at the column floor", async ({
  page,
}) => {
  // #151: remedy labels never wrapped. At 1440 px wide every narrow column
  // sits at its 20rem floor, where this finding's widest label ran past the
  // note under the occupations control, which cut it and the message above it
  // off mid-word, with nothing to scroll.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(ALUMINIUM_FCC_POSCAR),
  });
  await waitForBundleReady(page);
  await expandAdvisorGroup(page, "Occupations");
  const refused = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/explain" &&
      requestOverrides(response.request()).occupations === "fixed",
  );
  await page
    .getByRole("combobox", { name: "occupations", exact: true })
    .selectOption("fixed");
  const verdict = (await (await refused).json()) as {
    readonly blocking: readonly BlockingFindingDocument[];
  };
  expect(verdict.blocking.map((finding) => finding.code)).toEqual([
    "occupations.fixed_needs_even_electron_count",
  ]);
  const note = page.getByRole("note", {
    name: "Blocks input generation: occupations",
  });
  await expect(
    note.getByRole("button", {
      name: "Apply spin_polarized = true, occupations = smearing",
    }),
  ).toBeVisible();

  const clipped = await page.evaluate<readonly string[]>(`(() => {
    const notes = [...document.querySelectorAll('.card-advisors [role="note"]')];
    return notes
      .flatMap((note) => [note, ...note.querySelectorAll("button, .mantine-Button-label")])
      .filter(
        (element) =>
          element.scrollWidth > element.clientWidth ||
          element.scrollHeight > element.clientHeight,
      )
      .map((element) => element.textContent);
  })()`);
  expect(clipped).toEqual([]);
  // Wrapping keeps each remedy button, one line or two, at least as tall as
  // the theme's 44 px minimum for a target.
  const remedies = note.getByRole("button");
  await expect(remedies).toHaveCount(2);
  for (const remedy of await remedies.all()) {
    expect((await remedy.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  }
});

test("keeps a failed listing's error visible and lists again only on Retry", async ({
  page,
}) => {
  // #150: a failed /magnetic-orderings listing was re-sent about 80 times a
  // second (665 requests in 8.2 s) and its error was never on screen.
  let listings = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/magnetic-orderings") {
      listings += 1;
    }
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.route(
    "**/magnetic-orderings",
    async (route) => {
      await route.abort();
    },
    { times: 1 },
  );
  await page.locator('input[type="file"]').setInputFiles(IRON_BCC_CIF);
  const orderings = page.getByRole("region", { name: "Magnetic orderings" });
  const error = orderings.getByRole("alert");
  await expect(error).toContainText("Cannot reach Goldilocks Core", {
    timeout: 20_000,
  });
  await page.waitForTimeout(2_000);
  await expect(error).toBeVisible();
  expect(listings).toBe(1);

  await orderings.getByRole("button", { name: "Retry listing" }).click();

  await expect(
    orderings.getByRole("checkbox", { name: "Select fm for download" }),
  ).toBeVisible({ timeout: 20_000 });
  await expect(error).toHaveCount(0);
  expect(listings).toBe(2);
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

  await expectDocumentWithinViewportHeight(page);

  // The structure records are the Analysis card's; relativistic and
  // symmetry_eff are system advice, read-only in the Advisors card (#187).
  const records = {
    analysis: [
      "Composition composition",
      "Geometry geometry",
      "Symmetry symmetry",
    ],
    advisors: ["Relativistic relativistic", "Symmetry Eff symmetry_eff"],
  } as const;
  for (const [card, names] of Object.entries(records)) {
    const region = page.getByRole("region", { name: `Goldilocks ${card}` });
    for (const name of names) {
      await region.getByRole("button", { name }).click();
    }
  }
  await expectDocumentWithinViewportHeight(page);
  for (const card of Object.keys(records)) {
    const body = page.locator(`.card-${card} .card-body`);
    const lastRecord = page.locator(`.card-${card} .record-card`).last();
    // The card body is focusable so keyboard users can scroll it (App.css),
    // and End takes it to its last record. The string evaluate this replaces
    // was evaluated as an expression and never called, so the card never
    // scrolled and only a last record already in view passed.
    await body.focus();
    await page.keyboard.press("End");
    await expect(lastRecord).toBeInViewport();
  }
});

test("fits all five columns once the viewport clears their floors", async ({
  page,
}) => {
  // #190: the grid was capped at 120rem, below the 126rem that five column
  // floors, their gaps and the padding need, so with Magnetic orderings open
  // it scrolled sideways at every window width and cut off the Bundle card.
  await page.setViewportSize({ width: 2400, height: 1100 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(IRON_BCC_CIF);
  await expect(
    page.getByRole("region", { name: "Magnetic orderings" }),
  ).toBeVisible({ timeout: 20_000 });
  await waitForBundleReady(page);

  const grid = await page.evaluate<{
    readonly scrollWidth: number;
    readonly clientWidth: number;
  }>(`(() => {
    const grid = document.querySelector("main");
    return { scrollWidth: grid.scrollWidth, clientWidth: grid.clientWidth };
  })()`);
  expect(grid.scrollWidth).toBe(grid.clientWidth);
  await expectDocumentWithinViewportHeight(page);

  // The Structure card sits at its 20rem floor, where its status line and the
  // Replace file button share one row: neither may be cut off (#194).
  await expect(page.locator("#structure-source-help")).toHaveText(
    "2 sites · parsed",
  );
  const clipped = await page.evaluate<readonly string[]>(`(() => {
    const status = document.getElementById("structure-source-help");
    const replace = document.querySelector(
      'button[aria-label="Replace structure file"] .mantine-Button-label',
    );
    return [status, replace]
      .filter((element) => element.scrollWidth > element.clientWidth)
      .map((element) => element.textContent);
  })()`);
  expect(clipped).toEqual([]);
});

test("keeps the failure banner and the cards within one screen", async ({
  page,
}) => {
  // #190: the grid's height left room for the header alone, so the failure
  // banner above it pushed the grid below the fold.
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.route("**/explain", async (route) => {
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
  });
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(page.getByRole("alert")).toContainText(
    "Core failed temporarily.",
    { timeout: 20_000 },
  );

  await expectDocumentWithinViewportHeight(page);
  const grid = await page.getByRole("main").boundingBox();
  assert(grid, "The grid must have a layout box");
  expect(grid.y + grid.height).toBeLessThanOrEqual(700);
});

test("keeps a refused preview's long failure notice within one screen", async ({
  page,
}) => {
  // #190: once a long failure notice pushed Download below the Bundle card's
  // fold, the hidden reason Download is disabled for, positioned against the
  // page rather than the card, made the page scroll.
  await page.setViewportSize({ width: 1440, height: 700 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const message = `cannot generate a runnable input: ${"the writer could not render this structure's settings into an input pw.x accepts, and nothing it was given resolves that. ".repeat(6)}`;
  await page.route("**/run", async (route) => {
    await route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ error: { kind: "generation_error", message } }),
    });
  });
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await expect(
    page.getByRole("button", { name: "Download (.zip)" }),
  ).toHaveAccessibleDescription(
    /^Input generation failed for the current settings: /,
    { timeout: 20_000 },
  );

  await expectDocumentWithinViewportHeight(page);
});

test("keeps the header in view while the narrow layout scrolls", async ({
  page,
}) => {
  // Below 47.5rem the cards stack at their own height and the document
  // scrolls; the sticky header stays at the top past the first screen.
  await page.setViewportSize({ width: 720, height: 500 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "No structure selected" }),
  ).toBeVisible();

  const scrollY = await page.evaluate<number>(
    "window.scrollTo(0, 2 * window.innerHeight), window.scrollY",
  );
  expect(scrollY).toBe(1000);
  const header = await page.getByRole("banner").boundingBox();
  assert(header, "The header must have a layout box");
  expect(header.y).toBe(0);
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
  await expect(page.getByText("1 atomic site", { exact: true })).toBeVisible();
  await expect(page.getByText("1 site · parsed")).toBeVisible();
  // No periodicity token: /inspect reports every POSCAR fully periodic.
  await expect(page.getByLabel("Inspected structure summary")).toHaveText(
    "Si1 · Si · 160.2 Å³",
  );
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
    structureName: "POSCAR",
    structureBytes: new Uint8Array(Buffer.from(SILICON_POSCAR)),
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
  // The functional is not specific to a structure, so it carries over
  // (#188).
  await expect(
    page.getByRole("combobox", { name: "Functional", exact: true }),
  ).toHaveValue("PBE");
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

test("lists the cell angles of a non-orthogonal cell from /inspect", async ({
  page,
}) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  // The two-atom fcc primitive cell of silicon: alpha = beta = gamma = 60.
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(`Silicon primitive
5.431
0 0.5 0.5
0.5 0 0.5
0.5 0.5 0
Si
2
Direct
0 0 0
0.25 0.25 0.25
`),
  });
  await page
    .getByRole("region", { name: "Crystal structure viewer" })
    .getByRole("button", { name: "Inspect lattice, sites and occupancies" })
    .click();
  const lattice = page.getByRole("region", { name: "Lattice parameters" });
  await expect(lattice.getByRole("term")).toHaveText([
    "a",
    "b",
    "c",
    "α",
    "β",
    "γ",
    "V",
  ]);
  await expect(lattice.getByRole("definition")).toHaveText([
    "3.840 Å",
    "3.840 Å",
    "3.840 Å",
    "60.000°",
    "60.000°",
    "60.000°",
    "40.05 Å³",
  ]);
});

test("centres and fits the unit cell in the viewer, also after the card narrows", async ({
  page,
}) => {
  // The issue's window and sequence: the viewer frames the cell while the grid
  // has four columns, then the magnetic record from /explain adds the Magnetic
  // orderings column, which narrows the Structure card. Holding /explain
  // fixes that order.
  await page.setViewportSize({ width: 2400, height: 1100 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  let releaseExplain = (): void => undefined;
  const explainHeld = new Promise<void>((resolve) => {
    releaseExplain = resolve;
  });
  await page.route("**/explain", async (route) => {
    await explainHeld;
    await route.continue();
  });
  // fcc Ni's only atom sits on a cell corner, so centring on the atoms pushes
  // the cell box off-centre.
  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(NICKEL_FCC_POSCAR),
  });
  const canvas = page
    .getByRole("region", { name: "Crystal structure viewer" })
    .locator("canvas");
  await expect(canvas).toBeVisible();
  const framed = { centroid: "at the canvas centre", cornersOffCanvas: 0 };
  await expect.poll(async () => describeCellFraming(page)).toEqual(framed);
  const fourColumnWidth = (await canvas.boundingBox())?.width ?? 0;

  releaseExplain();
  await expect(
    page.getByRole("region", { name: "Magnetic orderings" }),
  ).toBeVisible();
  await expect
    .poll(async () => (await canvas.boundingBox())?.width)
    .toBeLessThan(fourColumnWidth);
  await expect.poll(async () => describeCellFraming(page)).toEqual(framed);
});

test("lists and bundles the open structure's own magnetic orderings", async ({
  page,
}) => {
  // #149: a listing still in flight when another structure opened was shown
  // for that structure, which was then never listed itself, and Download
  // selected filed the old structure's candidates under the new name. Opening
  // a structure now aborts the listing of the one it replaces.
  const listed: string[] = [];
  const failed: string[] = [];
  const listedName = (request: Request): string =>
    (request.postDataJSON() as { structure_name: string }).structure_name;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/magnetic-orderings") {
      listed.push(listedName(request));
    }
  });
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).pathname === "/magnetic-orderings") {
      failed.push(
        `${listedName(request)} ${request.failure()?.errorText ?? "no error"}`,
      );
    }
  });
  let releaseListing = (): void => undefined;
  const listingHeld = new Promise<void>((resolve) => {
    releaseListing = resolve;
  });
  await page.route(
    "**/magnetic-orderings",
    async (route) => {
      await listingHeld;
      await route.continue();
    },
    { times: 1 },
  );
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(IRON_BCC_CIF);
  const orderings = page.getByRole("region", { name: "Magnetic orderings" });
  await expect(orderings.getByText("Listing candidates…")).toBeVisible({
    timeout: 20_000,
  });

  await page.locator('input[type="file"]').setInputFiles({
    name: "POSCAR",
    mimeType: "text/plain",
    buffer: Buffer.from(NICKEL_FCC_POSCAR),
  });
  const fm = orderings.getByRole("checkbox", {
    name: "Select fm for download",
  });
  await expect(fm).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => failed).toEqual(["Fe_bcc.cif net::ERR_ABORTED"]);
  releaseListing();
  // Atoms: the one-atom Ni cell, not Fe_bcc.cif's two.
  const fmRow = orderings.getByRole("row").filter({
    has: page.getByRole("checkbox", { name: "Select fm for download" }),
  });
  await expect(fmRow.getByRole("cell").nth(2)).toHaveText("1");

  await fm.check();
  const downloadStarted = page.waitForEvent("download");
  await orderings
    .getByRole("button", { name: "Download selected (1)" })
    .click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toBe("POSCAR-fm-scf_single_point.zip");
  const path = await download.path();
  assert(path, "Download must have a local path");
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  const manifest = JSON.parse(
    textEntry(entries, "goldilocks.json"),
  ) as InputManifest;
  expect(manifest.request.structure).toMatchObject({
    name: "POSCAR-fm",
    sha256: sha256(new Uint8Array(Buffer.from(NICKEL_FCC_POSCAR))),
  });
  expect(listed).toEqual(["Fe_bcc.cif", "POSCAR"]);
});

test("keeps the task, account and functional when the structure is replaced", async ({
  page,
}) => {
  // #188: Replace file reset the whole draft, so the next bundle was a
  // calculation='scf' input with no #SBATCH --account line under the
  // heuristic functional, and nothing said so. Only the structure-specific
  // overrides are reset now, and the Advisors card names them.
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.locator('input[type="file"]').setInputFiles(SILICON_CIF);
  await waitForBundleReady(page);
  await page.getByLabel("Task", { exact: true }).selectOption("relax");
  for (const group of ["Job", "Functional", "K sampling"]) {
    await expandAdvisorGroup(page, group);
  }
  const advisors = page.getByRole("region", { name: "Goldilocks advisors" });
  await advisors.getByLabel("account", { exact: true }).fill("e2e-acct-001");
  await advisors
    .getByRole("combobox", { name: "Functional", exact: true })
    .selectOption("PBE");
  const pinned = page.waitForRequest((request) => {
    if (new URL(request.url()).pathname !== "/explain") return false;
    return "k_grid" in requestOverrides(request);
  });
  await advisors.getByLabel("K-point grid x").fill("5");
  expect(requestOverrides(await pinned)).toMatchObject({
    account: "e2e-acct-001",
    functional: "PBE",
    k_grid: [5, expect.any(Number), expect.any(Number)],
  });
  // The notice must be in view wherever the user left the settings list.
  await advisors
    .locator(".card-body")
    .evaluate((body: { scrollTop: number; readonly scrollHeight: number }) => {
      body.scrollTop = body.scrollHeight;
    });

  const replaced = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === "/explain" &&
      (request.postDataJSON() as { structure_name: string }).structure_name ===
        "Pt_fcc.cif",
  );
  await page.locator('input[type="file"]').setInputFiles(PLATINUM_FCC_CIF);
  const request = await replaced;
  expect(request.postDataJSON()).toMatchObject({ task: "relax" });
  expect(requestOverrides(request)).toEqual({
    account: "e2e-acct-001",
    functional: "PBE",
  });
  await expect(page.getByLabel("Task", { exact: true })).toHaveValue("relax");
  await expect(advisors.getByLabel("account", { exact: true })).toHaveValue(
    "e2e-acct-001",
  );
  const notice = advisors.getByRole("status", {
    name: "Structure-specific overrides reset",
  });
  await expect(notice.getByRole("listitem")).toHaveText(["K-point grid"]);
  await expect(notice).toBeInViewport();

  await waitForBundleReady(page);
  await expectNoAxeViolations(page);
  await notice.getByRole("button", { name: "Dismiss notice" }).click();
  await expect(notice).toHaveCount(0);
  const downloadStarted = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download (.zip)" }).click();
  const download = await downloadStarted;
  expect(download.suggestedFilename()).toBe("Pt_fcc.cif-relax.zip");
  const path = await download.path();
  assert(path, "Download must have a local path");
  const entries = unzipSync(new Uint8Array(await readFile(path)));
  expect(textEntry(entries, "relax.in")).toMatch(/calculation\s*=\s*'relax'/);
  expect(textEntry(entries, "submit.sh")).toContain(
    "#SBATCH --account=e2e-acct-001",
  );
  const manifest = JSON.parse(textEntry(entries, "goldilocks.json")) as {
    readonly records: {
      readonly functional?: {
        readonly value?: string;
        readonly source?: string;
      };
    };
  };
  expect(manifest.records.functional).toMatchObject({
    value: "PBE",
    source: "human",
  });
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

/** The `overrides` a /explain or /run request body carries. */
function requestOverrides(request: Request): Readonly<Record<string, unknown>> {
  const body = request.postDataJSON() as {
    overrides?: Record<string, unknown>;
  } | null;
  return body?.overrides ?? {};
}

/** Picks `option` on `select`, then waits for the /explain whose overrides
 * hold every entry of `pinned` and for the bundle that follows it. */
async function pinOverride(
  page: Page,
  select: Locator,
  option: string,
  pinned: Readonly<Record<string, unknown>>,
): Promise<void> {
  const reviewed = page.waitForResponse((response) => {
    if (new URL(response.url()).pathname !== "/explain") return false;
    const overrides = requestOverrides(response.request());
    return Object.entries(pinned).every(
      ([key, value]) => overrides[key] === value,
    );
  });
  await select.selectOption(option);
  expect((await reviewed).status()).toBe(200);
  await waitForBundleReady(page);
}

/** Clicks `target` with the mouse (no `force`, so Playwright first checks
 * that nothing else would receive the click) and returns the overrides of
 * the /explain that follows. */
async function clickForNextExplain(
  page: Page,
  target: Locator,
): Promise<Readonly<Record<string, unknown>>> {
  const next = page.waitForRequest(
    (request) => new URL(request.url()).pathname === "/explain",
  );
  await target.click();
  return requestOverrides(await next);
}

/** The tag of the element a click at the centre of a select's right section
 * lands on. That section holds the chevron while nothing is pinned, and must
 * then pass the click through to the <select>. */
async function rightSectionClickTarget(select: Locator): Promise<string> {
  await select.scrollIntoViewIfNeeded();
  const section = await select
    .locator("xpath=../*[@data-position='right']")
    .boundingBox();
  assert(section, "The select's right section must have a layout box");
  const x = String(section.x + section.width / 2);
  const y = String(section.y + section.height / 2);
  return select
    .page()
    .evaluate<string>(`document.elementFromPoint(${x}, ${y})?.tagName`);
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

/** Asserts that the document does not scroll vertically: the wide layout fits
 * one screen, and each card scrolls its own body instead. */
async function expectDocumentWithinViewportHeight(page: Page): Promise<void> {
  const { scrollHeight, viewportHeight } = await page.evaluate<{
    readonly scrollHeight: number;
    readonly viewportHeight: number;
  }>(`({
    scrollHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  })`);
  expect(scrollHeight).toBeLessThanOrEqual(viewportHeight);
}

/** Projects the shown unit cell's centroid and eight corners through the live
 * 3Dmol camera and reports where they land on the viewer canvas. 3Dmol tags
 * its canvas with the viewer (`_3dmol_viewer`); its model's crystal matrix
 * holds the lattice vectors as columns, in the frame the box was drawn in. */
async function describeCellFraming(page: Page): Promise<{
  readonly centroid: string;
  readonly cornersOffCanvas: number;
}> {
  const { width, height, centroid, corners } = await page.evaluate<{
    readonly width: number;
    readonly height: number;
    readonly centroid: { readonly x: number; readonly y: number };
    readonly corners: readonly { readonly x: number; readonly y: number }[];
  }>(`(() => {
    const canvas = document.querySelector(
      '[aria-label="Crystal structure viewer"] canvas',
    );
    const viewer = canvas._3dmol_viewer;
    const m = viewer.getModel().getCrystData().matrix.elements;
    const point = (i, j, k) => ({
      x: i * m[0] + j * m[3] + k * m[6],
      y: i * m[1] + j * m[4] + k * m[7],
      z: i * m[2] + j * m[5] + k * m[8],
    });
    const corners = [];
    for (const i of [0, 1])
      for (const j of [0, 1])
        for (const k of [0, 1]) corners.push(point(i, j, k));
    // modelToScreen returns page coordinates.
    const rect = canvas.getBoundingClientRect();
    const onCanvas = ({ x, y }) => ({
      x: x - rect.left - window.scrollX,
      y: y - rect.top - window.scrollY,
    });
    return {
      width: rect.width,
      height: rect.height,
      centroid: onCanvas(viewer.modelToScreen(point(0.5, 0.5, 0.5))),
      corners: viewer.modelToScreen(corners).map(onCanvas),
    };
  })()`);
  const dx = centroid.x - width / 2;
  const dy = centroid.y - height / 2;
  return {
    centroid:
      Math.hypot(dx, dy) <= 1
        ? "at the canvas centre"
        : `off centre by (${dx.toFixed(0)}, ${dy.toFixed(0)}) px`,
    cornersOffCanvas: corners.filter(
      ({ x, y }) => x < 0 || x > width || y < 0 || y > height,
    ).length,
  };
}

function verifyArchive(
  entries: Readonly<Record<string, Uint8Array>>,
  expected: {
    readonly tableId: string;
    readonly tableVersion: string;
    readonly structureName: string;
    readonly structureBytes: Uint8Array;
  },
): void {
  // bundle_files() emits the generation artifacts themselves (here
  // scf.in + pseudo/<file>), the selected table's licence beside the UPFs
  // (licences/<table-id>.txt, #157), submit.sh, and the three fixed meta
  // files -- v2 never copies the original/canonical structure into the
  // archive the way v1 did (no source/ or structure/ paths).
  const names = new Set(Object.keys(entries));
  const licence = `licences/${expected.tableId}.txt`;
  for (const required of [
    "README.md",
    "CITATIONS.md",
    "goldilocks.json",
    "scf.in",
    "submit.sh",
    licence,
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
  // The request the bundle answers (#176): the uploaded file by name and
  // the sha256 of its bytes.
  expect(manifest.schema_version).toBe(2);
  expect(manifest.request.code).toBe("quantum_espresso");
  expect(manifest.request.structure).toMatchObject({
    name: expected.structureName,
    sha256: sha256(expected.structureBytes),
    size_bytes: expected.structureBytes.byteLength,
  });
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
  expect(
    Object.entries(manifest.files)
      .filter(([, facts]) => facts.role === "licence")
      .map(([name]) => name),
  ).toEqual([licence]);
  expect(textEntry(entries, "CITATIONS.md")).toContain(`- \`${licence}\``);
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
