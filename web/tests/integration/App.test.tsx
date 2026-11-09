import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { App } from "../../src/App";
import type {
  ArchiveDownload,
  BlockingFinding,
  Capabilities,
  ComputeRequest,
  CoreClient,
  ExplainResult,
  MagneticOrderingsRequest,
  MagneticOrderingsResult,
  PseudopotentialTable,
  ResolvedField,
  RunResult,
  Setting,
  StructureInput,
  StructureInspection,
} from "../../src/api/coreClient";
import { CoreFailure } from "../../src/api/coreClient";
import {
  buildArchive,
  capabilities,
  explainResult,
  inspection,
} from "../support/workbenchFixtures";
import { WorkspaceProvider } from "../../src/workspace/WorkspaceProvider";
import { createWorkspace } from "../../src/workspace/workspace";

const MATERIALS_PROJECT_CITATION =
  "Materials Project; A. Wang et al., Sci. Rep. 11, 15496 (2021), Table S3";

vi.mock("../../src/viewer/StructureViewport", () => ({
  StructureViewport: () => (
    <div aria-label="Crystal structure viewer">3D crystal</div>
  ),
}));

class CoreStub implements CoreClient {
  inspectionResults: Promise<StructureInspection>[] = [];
  explainResults: Promise<ExplainResult>[] = [];
  archiveResults: Promise<ArchiveDownload>[] = [];
  inspectedInputs: StructureInput[] = [];
  explainCalls: ComputeRequest[] = [];
  archiveCalls: ComputeRequest[] = [];
  magneticOrderingsResults: Promise<MagneticOrderingsResult>[] = [];
  magneticOrderingsCalls: MagneticOrderingsRequest[] = [];
  magneticOrderingsSignals: (AbortSignal | undefined)[] = [];

  constructor(readonly capabilitiesResult: Promise<Capabilities>) {}

  capabilities(): Promise<Capabilities> {
    return this.capabilitiesResult;
  }

  inspectStructure(input: StructureInput): Promise<StructureInspection> {
    this.inspectedInputs.push(input);
    return (
      this.inspectionResults.shift() ??
      Promise.reject(new Error("inspection not configured"))
    );
  }

  explain(request: ComputeRequest): Promise<ExplainResult> {
    this.explainCalls.push(request);
    // Unlike inspection/archive, a recommendation is now computed
    // automatically (see useAutoCompute) as soon as a structure loads
    // and after every later edit -- most tests don't care about its
    // content, so an unconfigured queue falls back to a real success
    // instead of forcing every structure-uploading test to populate it.
    return this.explainResults.shift() ?? Promise.resolve(explainResult);
  }

  run(): Promise<RunResult> {
    return Promise.reject(new Error("run not configured"));
  }

  runArchive(request: ComputeRequest): Promise<ArchiveDownload> {
    this.archiveCalls.push(request);
    // Like explain() above: the generated-input preview now refreshes
    // itself automatically (see useAutoCompute) as soon as a
    // recommendation is ready, so most tests never opted into this and
    // shouldn't have to.
    return this.archiveResults.shift() ?? Promise.resolve(buildArchive());
  }

  magneticOrderings(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<MagneticOrderingsResult> {
    this.magneticOrderingsCalls.push(request);
    this.magneticOrderingsSignals.push(signal);
    // Like explain()/runArchive() above: MagneticOrderingsPanel fetches
    // this automatically as soon as a structure loads, so most tests
    // never opted into this and shouldn't have to.
    return (
      this.magneticOrderingsResults.shift() ??
      Promise.resolve({ ranked: false, candidates: [], warnings: [] })
    );
  }
}

function renderApp(core: CoreStub, saveArchive = vi.fn()) {
  const workspace = createWorkspace(core, saveArchive);
  return render(
    <WorkspaceProvider workspace={workspace}>
      <App />
    </WorkspaceProvider>,
  );
}

async function openStructure(
  user: ReturnType<typeof userEvent.setup>,
  container: HTMLElement,
) {
  await screen.findByRole("button", {
    name: "Choose a CIF or POSCAR structure",
  });
  await user.upload(structureInputElement(container), structureFile());
  // Functional/pseudopotential table now live collapsed inside the
  // advisors accordion, so they're not a reliable "form is ready"
  // signal any more -- the always-visible Task selector is.
  await screen.findByLabelText("Task");
}

describe("Goldilocks Workbench", () => {
  it("filters the pseudopotential table by the chosen functional", async () => {
    const user = userEvent.setup();
    const pbesol = capabilities.pseudopotential_tables[0];
    const pbe = capabilities.pseudopotential_tables[1];
    if (pbesol === undefined || pbe === undefined) {
      throw new Error("Missing pseudopotential fixture");
    }
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await user.click(
      screen.getByRole("button", { name: "Pseudopotential table" }),
    );
    const table = screen.getByRole("combobox", {
      name: "Pseudopotential table",
    });
    expect(optionValues(table)).toEqual(["", pbesol.id, pbe.id]);

    await user.click(screen.getByRole("button", { name: "Functional" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Functional" }),
      "PBE",
    );

    expect(optionValues(table)).toEqual(["", pbe.id]);
  });

  it("shows the sole HPC profile's real name instead of a fake Automatic option", async () => {
    // resolve_hpc_profile (server-side) isn't a smart picker -- with none
    // given it uses the one installed profile because there is no
    // ambiguity, not because it "automatically" chose SCARF over some
    // alternative. The fixture only registers one profile.
    renderApp(new CoreStub(Promise.resolve(capabilities)));

    const hpc = await screen.findByRole("combobox", { name: "HPC profile" });
    expect(hpc).toHaveValue("scarf");
    expect(optionValues(hpc)).toEqual(["scarf"]);
    expect(screen.queryByText("Automatic")).not.toBeInTheDocument();
  });

  it("exposes all four workspace columns at once", async () => {
    renderApp(new CoreStub(Promise.resolve(capabilities)));

    expect(
      await screen.findByRole("region", { name: "Structure workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Goldilocks analysis" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Goldilocks advisors" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bundle" })).toBeInTheDocument();
    // Magnetic Orderings only pops in once the run is spin-polarized
    // (see "shows Magnetic Orderings..." below) -- absent here, it must
    // not silently count as a fifth always-present column.
    expect(
      screen.queryByRole("region", { name: "Magnetic orderings" }),
    ).not.toBeInTheDocument();
  });

  it("shows Magnetic Orderings between Advisors and Bundle once the run is spin-polarized, even for a structure classified non-magnetic", async () => {
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(
        magneticReview({ isMagnetic: "non_magnetic", spinPolarized: true }),
      ),
    ];
    const { container } = renderApp(core);

    await openStructure(userEvent.setup(), container);

    const magnetic = await screen.findByRole("region", {
      name: "Magnetic orderings",
    });
    const regions = screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(regions.indexOf("Goldilocks advisors")).toBeLessThan(
      regions.indexOf("Magnetic orderings"),
    );
    expect(regions.indexOf("Magnetic orderings")).toBeLessThan(
      regions.indexOf("Bundle"),
    );
    expect(magnetic).toBeInTheDocument();
  });

  it("hides Magnetic Orderings for a spin-unpolarized run of a structure classified magnetic", async () => {
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(
        magneticReview({ isMagnetic: "magnetic", spinPolarized: false }),
      ),
    ];
    const { container } = renderApp(core);

    await openStructure(userEvent.setup(), container);
    // The review has landed once Download appears.
    await screen.findByRole("button", { name: "Download (.zip)" });

    expect(core.explainCalls).toHaveLength(1);
    expect(
      screen.queryByRole("region", { name: "Magnetic orderings" }),
    ).not.toBeInTheDocument();
  });

  it("says under is_magnetic why the mMACE classifier was not run", async () => {
    // #259: above the server's atom limit the classifier is skipped, and the
    // record the heuristic resolves carries the reason as its source_note.
    const note =
      "The mMACE classifier was not run: 312 atoms is above this server's " +
      "200-atom limit for mMACE (GOLDILOCKS_MMACE_MAX_ATOMS), so the " +
      "local-moment heuristic decided.";
    const review = magneticReview({
      isMagnetic: "magnetic",
      spinPolarized: false,
    });
    const core = new CoreStub(
      Promise.resolve({
        ...capabilities,
        facts: [
          ...capabilities.facts,
          {
            key: "is_magnetic",
            type: "enum",
            values: ["magnetic", "non_magnetic"],
            ml_target: "is_magnetic",
            approaches: ["human", "ml", "heuristic"],
            overridable: true,
            description: "Whether the structure has local moments.",
          },
        ],
      }),
    );
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({
        ...review,
        records: {
          ...review.records,
          is_magnetic: {
            status: "resolved",
            value: "magnetic",
            source: "heuristic",
            source_note: note,
          },
        },
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(userEvent.setup(), container);

    const analysis = screen.getByRole("region", {
      name: "Goldilocks analysis",
    });
    expect(await within(analysis).findByText(note)).toBeInTheDocument();
  });

  it("says in the orderings card why a ranking was not run", async () => {
    const user = userEvent.setup();
    const message =
      "mMACE ranking was not run: candidate afm-1 has 312 atoms, above " +
      "this server's 200-atom limit for mMACE (GOLDILOCKS_MMACE_MAX_ATOMS)";
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [spinPolarizedReview()];
    core.magneticOrderingsResults = [
      Promise.resolve(orderingsListing(2, "fm", "afm-1")),
      Promise.resolve({
        ...orderingsListing(2, "fm", "afm-1"),
        warnings: [
          {
            code: "magnetic.ordering_ranking_unavailable",
            level: "warning",
            category: "magnetic",
            message,
          },
        ],
      }),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);
    const card = await orderingsCard();
    await within(card).findByRole("checkbox", {
      name: "Select afm-1 for download",
    });

    await user.click(within(card).getByRole("button", { name: "Run mMACE" }));

    expect(await within(card).findByText(message)).toBeInTheDocument();
    expect(within(card).getByText("Not yet ranked")).toBeInTheDocument();
  });

  it("lists and bundles a replacement structure's own orderings when the old listing lands late", async () => {
    // #149: the listing of a structure replaced while it was in flight was
    // shown on the new structure's card, kept the new structure from being
    // listed, and Download selected filed its candidates under the new name.
    const user = userEvent.setup();
    let finishObsoleteListing: (value: MagneticOrderingsResult) => void = () =>
      undefined;
    const obsoleteListing = new Promise<MagneticOrderingsResult>((resolve) => {
      finishObsoleteListing = resolve;
    });
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    core.explainResults = [spinPolarizedReview(), spinPolarizedReview()];
    core.magneticOrderingsResults = [
      obsoleteListing,
      Promise.resolve(orderingsListing(1, "fm", "afm-1")),
    ];
    const { container } = renderApp(core, saveArchive);
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });

    await user.upload(
      structureInputElement(container),
      structureFile("NiO.cif", "data_NiO"),
    );
    expect(
      await within(await orderingsCard()).findByText("Listing candidates…"),
    ).toBeInTheDocument();
    await user.upload(
      structureInputElement(container),
      structureFile("Fe.cif", "data_Fe"),
    );
    const afm = await within(await orderingsCard()).findByRole("checkbox", {
      name: "Select afm-1 for download",
    });

    expect(
      core.magneticOrderingsCalls.map((request) => request.structure_content),
    ).toEqual(["data_NiO", "data_Fe"]);
    expect(core.magneticOrderingsSignals[0]?.aborted).toBe(true);
    // A client that ignores the abort still delivers the old listing.
    await act(async () => {
      finishObsoleteListing(orderingsListing(2, "fm", "afm-1", "afm-2"));
      await obsoleteListing;
    });
    const card = await orderingsCard();
    expect(
      within(card).queryByRole("checkbox", {
        name: "Select afm-2 for download",
      }),
    ).not.toBeInTheDocument();
    expect(within(card).getAllByRole("row")).toHaveLength(3);

    await user.click(afm);
    await user.click(
      within(card).getByRole("button", { name: "Download selected (1)" }),
    );

    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledOnce();
    });
    const candidateRequests = core.archiveCalls.filter(
      (request) => request.overrides?.magnetic_ordering !== undefined,
    );
    expect(
      candidateRequests.map((request) => [
        request.structure_name,
        request.structure_content,
        request.overrides?.magnetic_ordering,
      ]),
    ).toEqual([["Fe.cif-afm-1", "data_Fe", "afm-1"]]);
  });

  it("keeps the ticked orderings after Download selected saves them", async () => {
    // Download selected marks the listing busy and then idle again; only a
    // new listing (another structure, a ranking) clears the selection.
    const user = userEvent.setup();
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [spinPolarizedReview()];
    core.magneticOrderingsResults = [
      Promise.resolve(orderingsListing(2, "fm", "afm-1")),
    ];
    const { container } = renderApp(core, saveArchive);
    await openStructure(user, container);
    const card = await orderingsCard();
    const afm = await within(card).findByRole("checkbox", {
      name: "Select afm-1 for download",
    });

    await user.click(afm);
    await user.click(
      within(card).getByRole("button", { name: "Download selected (1)" }),
    );

    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledOnce();
    });
    expect(afm).toBeChecked();
    expect(
      within(card).getByRole("button", { name: "Download selected (1)" }),
    ).toBeEnabled();
  });

  it("keeps a failed listing's error on its card and lists again only on Retry", async () => {
    // #150: a failed listing was re-sent without limit and its error never
    // stayed on screen. It is the open structure's listing: the card shows
    // its error, does not list the structure again on its own, and offers
    // Retry, which lists it once more.
    const user = userEvent.setup();
    let failListing: (reason: unknown) => void = () => undefined;
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [spinPolarizedReview()];
    core.magneticOrderingsResults = [
      new Promise((_, reject) => {
        failListing = reject;
      }),
      Promise.resolve(orderingsListing(2, "fm", "afm-1")),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);
    await waitFor(
      () => {
        expect(core.magneticOrderingsCalls).toHaveLength(1);
      },
      { timeout: 5000 },
    );

    failListing(
      new CoreFailure(
        "network_error",
        "Cannot reach Goldilocks Core: Failed to fetch",
      ),
    );

    const card = await orderingsCard();
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      "Cannot reach Goldilocks Core: Failed to fetch",
    );
    await pause(1000);
    expect(within(card).getByRole("alert")).toHaveTextContent(
      "Cannot reach Goldilocks Core: Failed to fetch",
    );
    expect(core.magneticOrderingsCalls).toHaveLength(1);

    await user.click(
      within(card).getByRole("button", { name: "Retry listing" }),
    );

    expect(
      await within(card).findByRole("checkbox", {
        name: "Select afm-1 for download",
      }),
    ).toBeInTheDocument();
    expect(within(card).queryByRole("alert")).not.toBeInTheDocument();
    expect(core.magneticOrderingsCalls).toHaveLength(2);
  });

  it("uses light mode by default and persists an explicit dark mode", async () => {
    const user = userEvent.setup();
    const { unmount } = renderApp(new CoreStub(Promise.resolve(capabilities)));
    const toggle = await screen.findByRole("button", {
      name: "Switch to dark mode",
    });

    await user.click(toggle);

    expect(
      screen.getByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();

    unmount();
    renderApp(new CoreStub(Promise.resolve(capabilities)));
    expect(
      await screen.findByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();
  });

  it("announces the current Workbench operation in a persistent status", async () => {
    const core = new CoreStub(Promise.resolve(capabilities));
    let finishInspection: (value: StructureInspection) => void = () =>
      undefined;
    core.inspectionResults = [
      new Promise((resolve) => {
        finishInspection = resolve;
      }),
    ];
    const { container } = renderApp(core);
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });

    expect(
      screen.getByRole("status", { name: "Workbench status" }),
    ).toHaveTextContent("Ready");
    await userEvent.upload(structureInputElement(container), structureFile());
    expect(
      screen.getByRole("status", { name: "Workbench status" }),
    ).toHaveTextContent("Inspecting structure");

    finishInspection(inspection);
  });

  it("preserves the inspected viewport when switching theme", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);
    await openStructure(user, container);
    const viewport = await screen.findByLabelText("Crystal structure viewer");
    await user.click(
      screen.getByRole("button", { name: "Switch to dark mode" }),
    );
    expect(screen.getByLabelText("Crystal structure viewer")).toBe(viewport);
    await user.click(
      screen.getByRole("button", { name: "Switch to light mode" }),
    );
    expect(screen.getByLabelText("Crystal structure viewer")).toBe(viewport);
  });

  it("opens only the latest file when an earlier read resolves last", async () => {
    let finishFirstRead: (content: string) => void = () => undefined;
    const firstRead = new Promise<string>((resolve) => {
      finishFirstRead = resolve;
    });
    const first = new File(["A"], "A.cif");
    Object.defineProperty(first, "text", { value: () => firstRead });
    const second = new File(["B"], "B.cif");
    Object.defineProperty(second, "text", {
      value: () => Promise.resolve("structure B"),
    });
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });

    await userEvent.upload(structureInputElement(container), first);
    await userEvent.upload(structureInputElement(container), second);
    await waitFor(() => {
      expect(core.inspectedInputs).toEqual([
        {
          structure_content: "structure B",
          structure_name: "B.cif",
          structure_format: "cif",
        },
      ]);
    });
    finishFirstRead("structure A");
    await firstRead;
    await Promise.resolve();

    expect(core.inspectedInputs).toHaveLength(1);
  });

  it("keeps the task and structure-independent settings after Replace file, and lists the overrides it reset", async () => {
    // #188: Replace file reset the Task, the account and the functional to
    // their defaults without a word. Only structure-specific overrides and
    // facts are reset now, and the Advisors card names them.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);
    await user.selectOptions(screen.getByLabelText("Task"), "relax");
    const advisors = advisorsPanel();
    for (const group of ["Job", "Functional", "Magnetic", "Hubbard"]) {
      await user.click(within(advisors).getByRole("button", { name: group }));
    }
    await user.type(within(advisors).getByLabelText("account"), "acct-001");
    await user.selectOptions(
      within(advisors).getByRole("combobox", { name: "Functional" }),
      "PBE",
    );
    await user.selectOptions(
      within(advisors).getByLabelText("spin orbit coupling"),
      "true",
    );
    await user.click(within(advisors).getByLabelText("u by element · eV"));
    await user.paste('{"Si": 2}');
    await user.selectOptions(
      within(
        screen.getByRole("region", { name: "Goldilocks analysis" }),
      ).getByLabelText("is metal"),
      "non_metal",
    );

    await user.upload(
      structureInputElement(container),
      structureFile("Al.cif", "data_Al"),
    );

    await waitFor(
      () => {
        expect(core.explainCalls.at(-1)?.structure_content).toBe("data_Al");
      },
      { timeout: 2000 },
    );
    expect(core.explainCalls.at(-1)).toMatchObject({ task: "relax" });
    expect(core.explainCalls.at(-1)?.overrides).toEqual({
      account: "acct-001",
      functional: "PBE",
    });
    expect(screen.getByLabelText("Task")).toHaveDisplayValue(
      "Ionic relaxation",
    );
    expect(within(advisors).getByLabelText("account")).toHaveValue("acct-001");
    expect(
      within(advisors).getByRole("combobox", { name: "Functional" }),
    ).toHaveValue("PBE");
    expect(
      within(advisors).queryByRole("button", {
        name: "Reset spin orbit coupling to automatic",
      }),
    ).not.toBeInTheDocument();
    expect(within(advisors).getByLabelText("u by element · eV")).toHaveValue(
      "",
    );
    // Each named by the label of its control.
    const notice = within(advisors).getByRole("status", {
      name: "Structure-specific overrides reset",
    });
    expect(
      within(notice)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["spin orbit coupling", "u by element · eV", "is metal"]);

    await user.click(
      within(notice).getByRole("button", { name: "Dismiss notice" }),
    );
    expect(notice).not.toBeInTheDocument();

    // The next structure's own reset brings the notice back.
    await user.selectOptions(
      within(advisors).getByLabelText("spin orbit coupling"),
      "true",
    );
    await user.upload(
      structureInputElement(container),
      structureFile("Pt.cif", "data_Pt"),
    );
    const next = await within(advisors).findByRole("status", {
      name: "Structure-specific overrides reset",
    });
    expect(
      within(next)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["spin orbit coupling"]);
  });

  it("recomputes edits before generating input files, then downloads the exact archive", async () => {
    const user = userEvent.setup();
    const archive = buildArchive();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.resolve(explainResult),
    ];
    core.archiveResults = [Promise.resolve(archive)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const { container } = renderApp(core, saveArchive);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    await user.click(within(advisorsPanel()).getByText("Magnetic"));
    await user.selectOptions(screen.getByLabelText("spin polarized"), "true");

    // No manual "update" action -- the edit above is picked up and
    // recomputed automatically (see useAutoCompute), after its debounce.
    // Wait for the recompute that carries the edit, not only for the notice
    // to be absent: during the debounce the notice may not have appeared
    // yet. The recompute drops the old draft's archive, and Download stays
    // disabled until the preview of the edited draft has arrived.
    await waitFor(
      () => {
        expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
          spin_polarized: true,
        });
        expect(
          screen.queryByRole("status", { name: "Recommendation notice" }),
        ).not.toBeInTheDocument();
      },
      { timeout: 5000 },
    );
    expect(
      await screen.findByRole("status", { name: "Archive status" }),
    ).toHaveTextContent(`${archive.filename} is ready`);
    const runs = core.archiveCalls.length;
    await user.click(screen.getByRole("button", { name: "Download (.zip)" }));

    expect(saveArchive).toHaveBeenCalledOnce();
    expect(saveArchive).toHaveBeenCalledWith(archive);
    // Download saved the archive of the last /run and sent none itself. An
    // auto-preview of the pre-edit draft may have run first on a slow
    // machine; that one is discarded when the edit's recompute lands.
    expect(core.archiveCalls).toHaveLength(runs);
    expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
      spin_polarized: true,
    });
    expect(core.archiveCalls.at(-1)?.overrides).toMatchObject({
      spin_polarized: true,
    });
  });

  it("keeps Download disabled until the preview archive arrives, and Retry saves nothing", async () => {
    // #189: Retry on a failed automatic preview used to save the refetched
    // archive as a file, although Download was never pressed.
    const user = userEvent.setup();
    const archive = buildArchive("Si-scf_single_point.zip");
    let failPreview: (reason: unknown) => void = () => undefined;
    let finishPreview: (value: ArchiveDownload) => void = () => undefined;
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.archiveResults = [
      new Promise((_, reject) => {
        failPreview = reject;
      }),
      new Promise((resolve) => {
        finishPreview = resolve;
      }),
    ];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const { container } = renderApp(core, saveArchive);
    await openStructure(user, container);

    await waitFor(
      () => {
        expect(core.archiveCalls).toHaveLength(1);
      },
      { timeout: 5000 },
    );
    const download = screen.getByRole("button", { name: "Download (.zip)" });
    expect(download).toBeDisabled();
    failPreview(
      new CoreFailure(
        "http_error",
        "The Goldilocks Core server rejected the request (503).",
        { status: 503 },
        503,
      ),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The Goldilocks Core server rejected the request (503).",
    );
    expect(download).toBeDisabled();

    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(
      screen.getByRole("status", { name: "Workbench status" }),
    ).toHaveTextContent("Generating input files");
    expect(download).toBeDisabled();
    finishPreview(archive);

    expect(
      await screen.findByRole("status", { name: "Archive status" }),
    ).toHaveTextContent("Si-scf_single_point.zip is ready");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(saveArchive).not.toHaveBeenCalled();
    expect(download).toBeEnabled();

    await user.click(download);

    expect(saveArchive).toHaveBeenCalledOnce();
    expect(saveArchive.mock.calls[0]?.[0]).toBe(archive);
    expect(core.archiveCalls).toHaveLength(2);
  });

  it("keeps a refused /run as the draft's outcome: Retry offered, Dismiss re-sends nothing, Download disabled", async () => {
    // #150: after a 422 from the automatic /run, Retry was not offered,
    // Dismiss re-sent the /run about 175 ms later, Download stayed enabled
    // and the card still promised the files.
    const user = userEvent.setup();
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const archive = buildArchive("Si-scf_single_point.zip");
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.archiveResults = [
      failing(
        new CoreFailure(
          "generation_error",
          "Rutile TiO2 cannot be generated.",
          {},
          422,
        ),
      ),
      Promise.resolve(archive),
    ];
    const { container } = renderApp(core, saveArchive);
    await openStructure(user, container);

    const alert = await screen.findByRole("alert", {}, { timeout: 5000 });
    expect(alert).toHaveTextContent("Rutile TiO2 cannot be generated.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    const download = screen.getByRole("button", { name: "Download (.zip)" });
    expect(download).toBeDisabled();
    expect(download).toHaveAccessibleDescription(
      "Input generation failed for the current settings: Rutile TiO2 cannot be generated.",
    );
    expect(
      screen.getByRole("status", { name: "Input generation failed" }),
    ).toHaveTextContent("Rutile TiO2 cannot be generated.");
    expect(screen.queryByText(/will appear here/)).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "No input files were generated: generation failed for the current settings.",
      ),
    ).toBeInTheDocument();

    await user.click(
      within(alert).getByRole("button", { name: "Dismiss error" }),
    );
    await pause(1000);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(core.archiveCalls).toHaveLength(1);
    expect(download).toBeDisabled();
    expect(saveArchive).not.toHaveBeenCalled();

    // The card still offers Retry once the banner is dismissed.
    await user.click(screen.getByRole("button", { name: "Retry generation" }));
    expect(
      await screen.findByRole("status", { name: "Archive status" }),
    ).toHaveTextContent("Si-scf_single_point.zip is ready");
    expect(download).toBeEnabled();
    expect(core.archiveCalls).toHaveLength(2);
    expect(saveArchive).not.toHaveBeenCalled();
  });

  it("keeps a failed /explain as the draft's outcome: no recomputing notice, Dismiss re-sends nothing, Retry sends one", async () => {
    // #150: after an /explain failure the card said "recomputing" although
    // nothing was sent, Retry was not offered for a 4xx, and Dismiss
    // re-sent the failing /explain.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(explainResult),
      failing(
        new CoreFailure(
          "invalid_setting",
          "spin_polarized cannot be set for this structure.",
          {},
          422,
        ),
      ),
      Promise.resolve(explainResult),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);
    const download = await screen.findByRole("button", {
      name: "Download (.zip)",
    });
    await waitFor(
      () => {
        expect(download).toBeEnabled();
      },
      { timeout: 5000 },
    );
    await user.click(within(advisorsPanel()).getByText("Magnetic"));
    await user.selectOptions(screen.getByLabelText("spin polarized"), "true");

    const alert = await screen.findByRole("alert", {}, { timeout: 5000 });
    expect(alert).toHaveTextContent(
      "spin_polarized cannot be set for this structure.",
    );
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(
      screen.queryByRole("status", { name: "Recommendation notice" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Recommendation failed" }),
    ).toHaveTextContent("spin_polarized cannot be set for this structure.");
    expect(download).toBeDisabled();
    expect(download).toHaveAccessibleDescription(
      "The recommendation for the current settings failed: spin_polarized cannot be set for this structure.",
    );

    await user.click(
      within(alert).getByRole("button", { name: "Dismiss error" }),
    );
    await pause(1000);
    expect(core.explainCalls).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Retry recommendation" }),
    );
    await waitFor(
      () => {
        expect(download).toBeEnabled();
      },
      { timeout: 5000 },
    );
    await pause(1000);
    expect(core.explainCalls).toHaveLength(3);
    expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
      spin_polarized: true,
    });
  });

  it("sends no /run for an /explain verdict that blocks, and says why Download is disabled", async () => {
    // #165: /explain returns the findings /run would refuse with. A refused
    // draft still got the automatic /run, and Download stayed enabled until
    // its 422 arrived.
    const core = new CoreStub(Promise.resolve(occupationsCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({ ...explainResult, blocking: [FIXED_WITHOUT_MOMENT] }),
    ];
    const { container } = renderApp(core);
    await openStructure(userEvent.setup(), container);
    const download = await screen.findByRole(
      "button",
      { name: "Download (.zip)" },
      { timeout: 5000 },
    );
    await pause(1000);

    expect(core.archiveCalls).toHaveLength(0);
    // #223: the finding offers a remedy, so the notice asks for a setting to
    // be confirmed, and shows the summary with the full message behind a
    // toggle.
    const notice = screen.getByRole("status", {
      name: "Confirm one setting to generate input files",
    });
    expect(notice).toHaveTextContent(FIXED_WITHOUT_MOMENT.summary);
    const details = within(notice).getByText(FIXED_WITHOUT_MOMENT.message);
    expect(details).not.toBeVisible();
    const toggle = within(notice).getByRole("button", {
      name: "Show the details",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(details).toBeVisible();
    expect(
      within(notice).getByRole("button", { name: "Hide the details" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      within(notice).getByRole("button", {
        name: "Apply occupations = smearing",
      }),
    ).toBeEnabled();
    expect(download).toBeDisabled();
    expect(download).toHaveAccessibleDescription(
      `Input files cannot be generated for the current settings: ${FIXED_WITHOUT_MOMENT.summary}`,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/will appear here/)).not.toBeInTheDocument();
    // The verdict alone, with no /run sent, turns the badge of the group its
    // finding concerns red.
    expect(groupBadgeStyle("Occupations")).toContain("red");
    expect(groupBadgeStyle("K sampling")).toContain("green");
  });

  it("shows a refused /run's finding in the banner and under its control, and sends its remedy with the next /explain", async () => {
    // #151: the 422 banner showed the gate's prose and named no setting or
    // override; its findings now carry the settings they concern and the
    // override patches that resolve them.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(occupationsCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.archiveResults = [
      failing(
        new CoreFailure(
          "advice_incomplete",
          `cannot generate a runnable input: ${FIXED_WITHOUT_MOMENT.message} Remedy overrides: {"occupations": "smearing"}.`,
          { findings: [FIXED_WITHOUT_MOMENT] },
          422,
        ),
      ),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);

    const alert = await screen.findByRole("alert", {}, { timeout: 5000 });
    expect(alert).toHaveTextContent("Recommendation incomplete");
    expect(alert).toHaveTextContent(FIXED_WITHOUT_MOMENT.summary);
    expect(alert).not.toHaveTextContent("Remedy overrides");
    await user.click(within(advisorsPanel()).getByText("Occupations"));
    // #223: under its control the finding is one line pointing to the
    // Bundle card, with no remedy of its own.
    const note = within(advisorsPanel()).getByRole("note", {
      name: "Blocks input generation: occupations",
    });
    expect(note).toHaveTextContent("Needs confirmation — see Bundle");
    expect(within(note).queryByRole("button")).not.toBeInTheDocument();
    // #165: the finding turns the badge of the group it concerns red.
    expect(groupBadgeStyle("Occupations")).toContain("red");
    expect(groupBadgeStyle("K sampling")).toContain("green");
    const explained = core.explainCalls.length;

    await user.click(
      within(alert).getByRole("button", {
        name: "Apply occupations = smearing",
      }),
    );

    await waitFor(
      () => {
        expect(core.explainCalls).toHaveLength(explained + 1);
      },
      { timeout: 2000 },
    );
    expect(core.explainCalls.at(-1)?.overrides).toEqual({
      occupations: "smearing",
    });
  });

  it("clears an override a remedy sets to automatic", async () => {
    const user = userEvent.setup();
    const pinnedWidth: BlockingFinding = {
      code: "occupations.width_rejected",
      fields: ["degauss"],
      message: "degauss=0.02 is not usable here. Unset degauss.",
      summary: "degauss=0.02 is not usable here: unset degauss.",
      remedies: [{ degauss: null }],
    };
    const core = new CoreStub(Promise.resolve(occupationsCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.resolve({ ...explainResult, blocking: [pinnedWidth] }),
    ];
    const { container } = renderApp(core);
    await openStructure(user, container);
    await waitFor(
      () => {
        expect(core.explainCalls).toHaveLength(1);
      },
      { timeout: 2000 },
    );
    await user.click(within(advisorsPanel()).getByText("Occupations"));
    fireEvent.change(screen.getByLabelText("degauss · Ry"), {
      target: { value: "0.02" },
    });
    const notice = await screen.findByRole(
      "status",
      { name: "Confirm one setting to generate input files" },
      { timeout: 5000 },
    );
    expect(
      within(advisorsPanel()).getByRole("note", {
        name: "Blocks input generation: degauss",
      }),
    ).toHaveTextContent("Needs confirmation — see Bundle");

    await user.click(
      within(notice).getByRole("button", { name: "Apply degauss = automatic" }),
    );

    await waitFor(
      () => {
        expect(core.explainCalls).toHaveLength(3);
      },
      { timeout: 2000 },
    );
    expect(core.explainCalls[1]?.overrides).toEqual({ degauss: 0.02 });
    expect(core.explainCalls[2]?.overrides).toEqual({});
  });

  it("submits smearing treatment and width as overrides in the occupations group", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await user.click(within(advisorsPanel()).getByText("Occupations"));
    await user.selectOptions(screen.getByLabelText("smearing type"), "cold");
    const degauss = screen.getByLabelText("degauss · Ry");
    expect(degauss).toBeEnabled();
    fireEvent.change(degauss, { target: { value: "0.02" } });

    // No manual "generate" action -- the edits above are picked up and
    // computed automatically (see useAutoCompute), after its debounce.
    await waitFor(
      () => {
        expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
          smearing_type: "cold",
          degauss: 0.02,
        });
      },
      { timeout: 2000 },
    );
  });

  it("submits an Analysis fact's advertised value unchanged", async () => {
    // #139: Core accepts exactly the values capabilities.facts advertises,
    // so the select's string goes out as chosen.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);
    const analysis = screen.getByRole("region", {
      name: "Goldilocks analysis",
    });
    await user.selectOptions(
      within(analysis).getByLabelText("is metal"),
      "non_metal",
    );

    await waitFor(
      () => {
        expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
          is_metal: "non_metal",
        });
      },
      { timeout: 2000 },
    );
  });

  it("shows a fact that takes no override as read-only advice", async () => {
    // #186: needs_soc was an On/Off select, yet no value of it changed the
    // input; spin_orbit_coupling is the one SOC setting.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({
        ...explainResult,
        records: {
          ...explainResult.records,
          needs_soc: { status: "resolved", value: true, source: "heuristic" },
        },
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    const analysis = screen.getByRole("region", {
      name: "Goldilocks analysis",
    });
    const needsSoc = within(analysis).getByRole("group", {
      name: "needs soc",
    });
    expect(
      await within(needsSoc).findByText("Yes", { exact: true }),
    ).toBeInTheDocument();
    expect(needsSoc).toHaveAccessibleDescription(
      /spin_orbit_coupling setting enables it\. · Heuristic default$/,
    );
    expect(
      within(analysis).queryByRole("combobox", { name: "needs soc" }),
    ).not.toBeInTheDocument();
    expect(
      within(analysis).queryByRole("button", {
        name: "Reset needs soc to automatic",
      }),
    ).not.toBeInTheDocument();
    // An overridable fact keeps its select.
    expect(
      within(analysis).getByRole("combobox", { name: "is metal" }),
    ).toBeEnabled();
  });

  it.each([
    {
      site: "a boolean setting",
      groups: ["Magnetic"],
      pins: [{ field: "spin polarized", option: "true" }],
      reset: "spin polarized",
      pinned: { spin_polarized: true },
    },
    {
      site: "an enum setting",
      groups: ["Occupations"],
      pins: [{ field: "smearing type", option: "cold" }],
      reset: "smearing type",
      pinned: { smearing_type: "cold" },
    },
    {
      site: "the pseudopotential table",
      groups: ["Pseudopotential table"],
      pins: [
        { field: "Pseudopotential table", option: "sssp-pbe-precision-sr" },
      ],
      reset: "Pseudopotential table",
      pinned: { pseudo_table_id: "sssp-pbe-precision-sr" },
    },
    {
      site: "the functional, with the table pinned under it",
      groups: ["Functional", "Pseudopotential table"],
      pins: [
        { field: "Functional", option: "PBE" },
        { field: "Pseudopotential table", option: "sssp-pbe-precision-sr" },
      ],
      reset: "Functional",
      pinned: { functional: "PBE", pseudo_table_id: "sssp-pbe-precision-sr" },
    },
  ])(
    "clears $site back to automatic with a pointer click on its reset button",
    async ({ groups, pins, reset, pinned }) => {
      // #158: the reset button sits in NativeSelect's right section.
      emulateNativeSelectSectionPointerEvents();
      const user = userEvent.setup();
      const core = new CoreStub(Promise.resolve(capabilities));
      core.inspectionResults = [Promise.resolve(inspection)];
      const { container } = renderApp(core);

      await openStructure(user, container);
      const calculation = advisorsPanel();
      for (const group of groups) {
        await user.click(
          within(calculation).getByRole("button", { name: group }),
        );
      }
      for (const { field, option } of pins) {
        await user.selectOptions(
          within(calculation).getByRole("combobox", { name: field }),
          option,
        );
      }
      await waitFor(
        () => {
          expect(core.explainCalls.at(-1)?.overrides).toMatchObject(pinned);
        },
        { timeout: 2000 },
      );
      const pinnedCalls = core.explainCalls.length;

      await user.click(
        within(calculation).getByRole("button", {
          name: `Reset ${reset} to automatic`,
        }),
      );

      await waitFor(
        () => {
          expect(core.explainCalls.length).toBeGreaterThan(pinnedCalls);
        },
        { timeout: 2000 },
      );
      const overrides = core.explainCalls[pinnedCalls]?.overrides ?? {};
      for (const key of Object.keys(pinned)) {
        expect(overrides).not.toHaveProperty(key);
      }
      expect(
        within(calculation).queryByRole("button", {
          name: /^Reset .* to automatic$/,
        }),
      ).not.toBeInTheDocument();
    },
  );

  it("keeps the old review visible and disables input generation after an edit", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core, vi.fn());

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });

    await user.click(within(advisorsPanel()).getByText("Magnetic"));
    await user.selectOptions(screen.getByLabelText("spin polarized"), "true");

    expect(
      screen.getByRole("status", { name: "Recommendation notice" }),
    ).toHaveTextContent(
      "Settings changed — recomputing the recommendation automatically.",
    );
    expect(
      screen.getByRole("button", { name: "Download (.zip)" }),
    ).toBeDisabled();
  });

  it("computes a recommendation and merges resolved records into their advisor groups", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [Promise.resolve(explainResult)];
    const { container } = renderApp(core);

    await openStructure(user, container);
    // Every card is always mounted (one always-visible dashboard) --
    // wait for the auto-computed content to actually land, rather than
    // for a region to appear.
    await screen.findByRole("button", { name: "Download (.zip)" });

    // Computing a recommendation doesn't navigate away from the
    // structure card.
    expect(
      screen.getByRole("region", { name: "Structure workspace" }),
    ).toBeInTheDocument();
    expect(core.explainCalls[0]).toMatchObject({
      structure_content: "data_Si",
      structure_name: "Si.cif",
      task: "scf_single_point",
    });

    // The k_sampling/cutoffs/magnetic records (all advisor-tier) merge
    // into their own settings-group accordion item rather than a
    // separate global list -- expanding "K sampling" shows each
    // setting's own control pre-filled with its actual resolved value,
    // not a separate read-only card next to an always-"Automatic" one.
    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("K sampling"));
    // 0.15 (the resolved k_distance) is shown directly inside its own
    // override control -- this codebase's "no separate card, the box
    // itself shows the real value" pattern, same as the Analysis facts.
    expect(within(calculation).getByLabelText("k distance · Å⁻¹")).toHaveValue(
      "0.15",
    );
    // n_irr_k (10) has no setting, so it is a read-only record after the
    // settings groups (#187, #225).
    await user.click(
      within(calculation).getByRole("button", { name: /^N Irr K\s*n_irr_k$/ }),
    );
    expect(
      within(calculation).getByRole("region", { name: /^N Irr K\s*n_irr_k$/ }),
    ).toHaveTextContent("10");
  });

  it("shows the k_distance interval instead of a fabricated point when k_index resolved the mesh", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({
        records: {
          ...explainResult.records,
          k_sampling: {
            status: "resolved",
            value: {
              mesh: [4, 4, 4],
              shift: [0, 0, 0],
              k_distance: null,
              k_distance_interval: [0.12, 0.18],
              k_index: 5,
              warnings: [],
            },
            source: "human",
          },
        },
        warnings: [],
        blocking: [],
        layout: explainResult.layout,
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });

    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("K sampling"));

    // k_distance itself has nothing to show (a whole interval maps to
    // one rung, not one point) -- the honest range appears as a plain
    // line instead of a fabricated single number in the box.
    expect(within(calculation).getByLabelText("k distance · Å⁻¹")).toHaveValue(
      "",
    );
    expect(
      within(calculation).getByText(/Δk ∈ \[0\.120, 0\.180\] Å⁻¹/),
    ).toBeInTheDocument();
  });

  it("shows the Gamma-only rung's interval as open above", async () => {
    // Rung 1 (the Gamma-only mesh) has no upper k-distance bound; the
    // record carries it as null (#137).
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({
        records: {
          ...explainResult.records,
          k_sampling: {
            status: "resolved",
            value: {
              mesh: [1, 1, 1],
              shift: [0, 0, 0],
              k_distance: null,
              k_distance_interval: [0.687, null],
              k_index: 1,
              warnings: [],
            },
            source: "human",
          },
        },
        warnings: [],
        blocking: [],
        layout: explainResult.layout,
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });

    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("K sampling"));

    expect(
      within(calculation).getByText(/Δk ≥ 0\.687 Å⁻¹/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Structure workspace" }),
    ).toBeInTheDocument();
  });

  it.each([
    {
      shows: "a built-in U with its citation",
      uValues: [
        {
          element: "Ni",
          manifold: "3d",
          u_ev: 6.2,
          value_source: "table",
          citation: MATERIALS_PROJECT_CITATION,
          doi: "10.1038/s41598-021-94550-5",
        },
      ],
      items: [`Ni 3d: 6.2 eV · ${MATERIALS_PROJECT_CITATION}`],
    },
    {
      shows: "u_by_element values as your override",
      uValues: [
        {
          element: "Fe",
          manifold: "3d",
          u_ev: 4.5,
          value_source: "human",
          citation: null,
          doi: null,
        },
        {
          element: "Ni",
          manifold: "3d",
          u_ev: 5,
          value_source: "human",
          citation: null,
          doi: null,
        },
      ],
      items: ["Fe 3d: 4.5 eV · Your override", "Ni 3d: 5 eV · Your override"],
    },
  ])("lists $shows in the Hubbard section", async ({ uValues, items }) => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(withHubbard({ u_values: uValues, warnings: [] })),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("Hubbard"));

    const applied = within(calculation).getByRole("list", {
      name: "Applied +U",
    });
    expect(
      within(applied)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(items);
    expectHubbardOverrideControls(calculation);
  });

  it("says when no element gets +U and names an element without a published U", async () => {
    const user = userEvent.setup();
    const missing =
      "No published Hubbard U value exists for Cf (5f), so Cf gets plain DFT.";
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(
        withHubbard({
          u_values: [],
          warnings: [
            {
              code: "hubbard.u_value_missing",
              level: "warning",
              category: "hubbard",
              message: missing,
            },
          ],
        }),
      ),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("Hubbard"));

    expect(
      within(calculation).getByText("No element gets +U."),
    ).toBeInTheDocument();
    expect(
      within(calculation).queryByRole("list", { name: "Applied +U" }),
    ).not.toBeInTheDocument();
    expect(within(calculation).getByText(missing)).toBeInTheDocument();
    expectHubbardOverrideControls(calculation);
  });

  it("shows each magnetic setting's recorded value, captioned only by the tier that set it", async () => {
    // #187: a setting's value was read as record.value[setting.key], but
    // the magnetic record holds spin_orbit_coupling as spin_orbit_enabled
    // and magnetic_ordering as ordering.applied, so both showed nothing
    // under a tier caption; and with spin_polarized pinned, the record's own
    // "human" captioned the untouched tot_magnetization "Your override".
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(magneticCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.resolve(ironReviewWithSpinPolarizedPinned()),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    const calculation = advisorsPanel();
    await user.click(
      within(calculation).getByRole("button", { name: "Magnetic" }),
    );
    await user.selectOptions(
      within(calculation).getByRole("combobox", { name: "spin polarized" }),
      "true",
    );

    const spinOrbit = within(calculation).getByRole("combobox", {
      name: "spin orbit coupling",
    });
    await waitFor(
      () => {
        expect(spinOrbit).toHaveValue("false");
      },
      { timeout: 2000 },
    );
    expect(spinOrbit).toHaveAccessibleDescription(
      "Enable noncollinear spin-orbit-coupling mode. · Heuristic default",
    );
    const ordering = within(calculation).getByRole("textbox", {
      name: "magnetic ordering",
    });
    expect(ordering).toHaveValue("fm");
    expect(ordering).toHaveAccessibleDescription(
      "Opt in to an antiferromagnetic ordering. · Heuristic default",
    );
    const moment = within(calculation).getByRole("spinbutton", {
      name: "tot magnetization",
    });
    expect(moment).toHaveValue("");
    expect(moment).toHaveAccessibleDescription(
      "Total magnetization of a collinear spin-polarized run.",
    );
    expect(
      within(calculation).getByRole("combobox", { name: "spin polarized" }),
    ).toHaveAccessibleDescription(
      "Force spin-polarized vs non-spin-polarized. · Your override",
    );
  });

  it("captions no setting whose record holds no value of it", async () => {
    // #187: hubbard lists the U values applied, so
    // hubbard_needs_correlation has no recorded value, yet it showed "—"
    // captioned "Heuristic default".
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(withHubbard({ u_values: [], warnings: [] })),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    const calculation = advisorsPanel();
    await user.click(within(calculation).getByText("Hubbard"));

    const needsCorrelation = within(calculation).getByRole("combobox", {
      name: "hubbard needs correlation",
    });
    expect(needsCorrelation).toHaveValue("");
    expect(needsCorrelation).toHaveAccessibleDescription(
      "Force whether a Hubbard +U correction is applied.",
    );
  });

  it("does not caption a value derived from another setting's override as yours", async () => {
    // #187: a record without per-setting sources reads "human" once any of
    // its settings is set, and that captioned the ecutrho_ry derived from a
    // pinned ecutwfc_ry "Your override".
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(cutoffsCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.resolve({
        ...explainResult,
        records: {
          ...explainResult.records,
          cutoffs: {
            status: "resolved",
            value: { ecutwfc_ry: 60, ecutrho_ry: 240, warnings: [] },
            source: "human",
          },
        },
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    const calculation = advisorsPanel();
    await user.click(
      within(calculation).getByRole("button", {
        name: "Pseudopotential table",
      }),
    );
    fireEvent.change(within(calculation).getByLabelText("ecutwfc ry · Ry"), {
      target: { value: "60" },
    });
    await waitFor(
      () => {
        expect(core.explainCalls.at(-1)?.overrides).toMatchObject({
          ecutwfc_ry: 60,
        });
      },
      { timeout: 2000 },
    );

    const ecutrho = within(calculation).getByLabelText("ecutrho ry · Ry");
    await waitFor(
      () => {
        expect(ecutrho).toHaveValue("240");
      },
      { timeout: 2000 },
    );
    expect(ecutrho).toHaveAccessibleDescription("Charge-density cutoff.");
    expect(
      within(calculation).getByLabelText("ecutwfc ry · Ry"),
    ).toHaveAccessibleDescription(
      "Plane-wave wavefunction kinetic-energy cutoff. · Your override",
    );
  });

  it("places each record in the card of the tier the response lays it out in", async () => {
    // #187: a record counted as an advisor's only when its key equalled a
    // settings group, so a dos task's nscf_ records, relativistic and
    // symmetry_eff landed under Analysis, the structure-only tier.
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(dosCapabilities()));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [Promise.resolve(explainResult), dosReview()];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await screen.findByRole("button", { name: "Download (.zip)" });
    await user.selectOptions(screen.getByLabelText("Task"), "dos");
    const calculation = advisorsPanel();
    const nscf = await within(calculation).findByRole(
      "region",
      { name: "nscf step" },
      { timeout: 2000 },
    );

    expect(
      within(nscf)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      "Nscf Occupationsnscf_occupations",
      "Nscf K Samplingnscf_k_sampling",
    ]);
    for (const name of [
      "Relativistic relativistic",
      "Symmetry Eff symmetry_eff",
    ]) {
      expect(
        within(calculation).getByRole("button", { name }),
      ).toBeInTheDocument();
    }
    // The dos record belongs to the dos settings, not a read-only row.
    expect(
      within(calculation).getByRole("button", { name: "Dos" }),
    ).toBeInTheDocument();
    expect(
      within(calculation).queryByRole("button", { name: "Dos dos" }),
    ).not.toBeInTheDocument();
    const analysis = screen.getByRole("region", {
      name: "Goldilocks analysis",
    });
    expect(
      within(analysis)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Compositioncomposition"]);
  });

  it("announces structured scientific warnings returned with a recommendation", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.explainResults = [
      Promise.resolve({
        ...explainResult,
        warnings: [
          {
            code: "occupations.smearing_defaulted",
            level: "warning",
            category: "occupations",
            message: "Review smearing before production use.",
            record: "occupations",
          },
        ],
      }),
    ];
    const { container } = renderApp(core);

    await openStructure(user, container);

    expect(
      await screen.findByRole("status", { name: "Warnings" }),
    ).toHaveTextContent("Review smearing before production use.");
  });

  it("opens a CIF and builds calculation controls from Capabilities", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);

    expect(await screen.findByText(/Si1/)).toBeInTheDocument();
    expect(
      screen.getByLabelText("Crystal structure viewer"),
    ).toBeInTheDocument();
    expect(screen.getByText("1 site · parsed")).toBeInTheDocument();
    expect(core.inspectedInputs).toEqual([
      {
        structure_content: "data_Si",
        structure_name: "Si.cif",
        structure_format: "cif",
      },
    ]);
    await user.click(
      screen.getByRole("button", { name: "Pseudopotential table" }),
    );
    const tableSelect = screen.getByRole("combobox", {
      name: "Pseudopotential table",
    });
    expect(optionValues(tableSelect)).toEqual([
      "",
      ...capabilities.pseudopotential_tables.map(
        (table: PseudopotentialTable) => table.id,
      ),
    ]);
    // Relax-only settings stay hidden for the default scf_single_point task.
    expect(screen.queryByText("Relax")).not.toBeInTheDocument();
  });

  it("reveals relax-only settings once the relax task is selected", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);
    await user.selectOptions(screen.getByLabelText("Task"), "relax");

    expect(screen.getByText("Relax")).toBeInTheDocument();
  });

  it("offers a setting for exactly the tasks it declares", async () => {
    // #154: visibility follows each setting's `tasks`, not its group name.
    const user = userEvent.setup();
    const relaxForEveryTask: Capabilities = {
      ...capabilities,
      settings: capabilities.settings.map((setting) =>
        setting.key === "ion_dynamics"
          ? { ...setting, tasks: ["scf_single_point", "relax"] }
          : setting,
      ),
    };
    const core = new CoreStub(Promise.resolve(relaxForEveryTask));
    core.inspectionResults = [Promise.resolve(inspection)];
    const { container } = renderApp(core);

    await openStructure(user, container);

    expect(screen.getByText("Relax")).toBeInTheDocument();
  });

  it("keeps retry available and dismiss hidden for a Capabilities failure", async () => {
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
    );
    renderApp(new CoreStub(Promise.reject(failure)));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Runtime assets unavailable");
    expect(alert).toHaveTextContent("Runtime assets are unavailable.");
    const status = screen.getByRole("status", { name: "Workbench status" });
    expect(status).toHaveTextContent("Needs attention");
    expect(status).not.toHaveTextContent("Ready");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Dismiss error" }),
    ).not.toBeInTheDocument();
  });

  it("announces Capabilities loading at startup", async () => {
    const pending = new Promise<Capabilities>(() => undefined);
    renderApp(new CoreStub(pending));

    expect(
      await screen.findByRole("heading", { name: "Loading Workbench" }),
    ).toBeInTheDocument();
  });
});

/** `explainResult` plus a resolved `hubbard` record shaped like
 * `advisors.hubbard_u.HubbardUDecision` on the wire. */
function withHubbard(decision: {
  readonly u_values: readonly Readonly<Record<string, unknown>>[];
  readonly warnings: readonly Readonly<Record<string, unknown>>[];
}): ExplainResult {
  return {
    ...explainResult,
    records: {
      ...explainResult.records,
      hubbard: { status: "resolved", value: decision, source: "heuristic" },
    },
  };
}

/** A settings entry of `capabilities` for every task, with what its tests
 * need declared. */
function setting(
  overrides: Pick<Setting, "key" | "group" | "type" | "resolved_in"> &
    Partial<Setting>,
): Setting {
  return {
    unit: null,
    codes: ["quantum_espresso"],
    tasks: ["scf_single_point", "relax"],
    steps: null,
    programs: null,
    scope: "system",
    structure_specific: true,
    ml_target: null,
    approaches: ["human", "heuristic"],
    description: "",
    ...overrides,
  };
}

/** The finding of an explicit occupations=fixed on a collinear
 * spin-polarized run without a moment, as Core returns it. */
const FIXED_WITHOUT_MOMENT: BlockingFinding = {
  code: "occupations.fixed_needs_tot_magnetization",
  fields: ["occupations", "tot_magnetization"],
  message:
    "occupations=fixed on a collinear spin-polarized run needs an integer tot_magnetization of the electron count's parity, and none was set or derived. Set occupations=smearing, or set tot_magnetization.",
  summary:
    "Fixed occupations on this spin-polarized run need an integer tot_magnetization: set one, or switch occupations to smearing.",
  remedies: [{ occupations: "smearing" }],
};

/** `capabilities` plus the occupations scheme, which the occupations group
 * holds next to the smearing settings. */
function occupationsCapabilities(): Capabilities {
  return {
    ...capabilities,
    settings: [
      ...capabilities.settings,
      setting({
        key: "occupations",
        group: "occupations",
        type: "string",
        enum: ["fixed", "smearing", "tetrahedra_opt"],
        steps: ["scf", "relax"],
        programs: ["pw.x"],
        scope: "per_step",
        structure_specific: true,
        resolved_in: { record: "occupations", path: ["occupations"] },
        description: "Occupation scheme.",
      }),
    ],
  };
}

/** `capabilities` plus the magnetic settings the magnetic record holds
 * under their own names or none. */
function magneticCapabilities(): Capabilities {
  return {
    ...capabilities,
    settings: [
      ...capabilities.settings,
      setting({
        key: "tot_magnetization",
        group: "magnetic",
        type: "number",
        resolved_in: { record: "magnetic", path: ["tot_magnetization"] },
        description: "Total magnetization of a collinear spin-polarized run.",
      }),
      setting({
        key: "magnetic_ordering",
        group: "magnetic",
        type: "string",
        resolved_in: { record: "magnetic", path: ["ordering", "applied"] },
        description: "Opt in to an antiferromagnetic ordering.",
      }),
    ],
  };
}

/** `capabilities` plus both cutoffs, which share one record. */
function cutoffsCapabilities(): Capabilities {
  return {
    ...capabilities,
    settings: [
      ...capabilities.settings,
      setting({
        key: "ecutwfc_ry",
        group: "cutoffs",
        type: "number",
        unit: "Ry",
        resolved_in: { record: "cutoffs", path: ["ecutwfc_ry"] },
        description: "Plane-wave wavefunction kinetic-energy cutoff.",
      }),
      setting({
        key: "ecutrho_ry",
        group: "cutoffs",
        type: "number",
        unit: "Ry",
        resolved_in: { record: "cutoffs", path: ["ecutrho_ry"] },
        description: "Charge-density cutoff.",
      }),
    ],
  };
}

/** `capabilities` with the dos task, every setting offered for it, and one
 * dos.x setting. */
function dosCapabilities(): Capabilities {
  return {
    ...capabilities,
    tasks: [
      ...capabilities.tasks,
      {
        id: "dos",
        name: "Density of states",
        description: "scf, then a denser nscf pass, then dos.x.",
        codes: ["quantum_espresso"],
        step_count: 3,
        executables: ["pw.x", "pw.x", "dos.x"],
      },
    ],
    settings: [
      ...capabilities.settings.map((entry) => ({
        ...entry,
        tasks: [...entry.tasks, "dos"],
      })),
      setting({
        key: "delta_e",
        group: "dos",
        type: "number",
        unit: "eV",
        tasks: ["dos"],
        steps: ["dos"],
        programs: ["dos.x"],
        scope: "per_step",
        structure_specific: false,
        resolved_in: { record: "dos", path: ["delta_e"] },
        description: "dos.x energy step of the DOS grid.",
      }),
    ],
  };
}

/** bcc Fe's magnetic record (MC3D mc3d-17673) as /explain returns it with
 * spin_polarized pinned on. */
function ironReviewWithSpinPolarizedPinned(): ExplainResult {
  return {
    ...explainResult,
    records: {
      ...explainResult.records,
      magnetic: {
        status: "resolved",
        value: {
          cell: { formula: "Fe2", nat: 2 },
          ordering: {
            requested: null,
            applied: "fm",
            criterion: "identity",
            alternatives: [],
          },
          spin_polarized: true,
          magnetic_elements: ["Fe"],
          starting_magnetization: { Fe: 0.3125 },
          compensated: false,
          tot_magnetization: null,
          spin_orbit_enabled: false,
          angle1: null,
          angle2: null,
          seeded_moment: 10,
          moment_direction: null,
          site_labels: ["Fe0", "Fe1"],
          human_seeded_labels: [],
          warnings: [],
        },
        source: "human",
        field_sources: {
          spin_polarized: "human",
          spin_orbit_coupling: "heuristic",
          magnetic_ordering: "heuristic",
          starting_magnetization: "heuristic",
        },
        derived_from: [],
      },
    },
  };
}

/** A dos task's review: its nscf step's records under nscf_ names, the
 * dos.x record, a structure record and two system records no setting
 * resolves into, laid out as /explain lays them out. */
function dosReview(): Promise<ExplainResult> {
  const resolved = (value: unknown): ResolvedField => ({
    status: "resolved",
    value,
    source: "heuristic",
  });
  return Promise.resolve({
    records: {
      ...explainResult.records,
      composition: resolved({ elements: ["Si"] }),
      relativistic: resolved("scalar"),
      symmetry_eff: resolved({ space_group_number: 227 }),
      nscf_occupations: resolved({ occupations: "tetrahedra_opt" }),
      nscf_k_sampling: resolved({ mesh: [12, 12, 12], shift: [0, 0, 0] }),
      dos: resolved({ delta_e: 0.01 }),
    },
    warnings: [],
    blocking: [],
    layout: {
      analysis: ["composition"],
      system: ["relativistic", "magnetic", "symmetry_eff", "cutoffs"],
      steps: [
        { name: "scf", records: ["k_sampling", "n_irr_k"] },
        { name: "nscf", records: ["nscf_occupations", "nscf_k_sampling"] },
        { name: "dos", records: ["dos"] },
      ],
    },
  });
}

/** The Hubbard section keeps both override controls next to the decision:
 * they are how a missing or unwanted U is fixed. */
function expectHubbardOverrideControls(calculation: HTMLElement): void {
  expect(within(calculation).getByLabelText("u by element · eV")).toBeVisible();
  expect(
    within(calculation).getByLabelText("hubbard needs correlation"),
  ).toBeVisible();
}

/** jsdom applies no Mantine stylesheet (and cannot resolve its var() chain),
 * so this restores what a browser computes for every NativeSelect's right
 * section: `pointer-events: none`, Mantine's default, which passes a click on
 * the chevron through to the <select> and which the section's content
 * inherits. user-event then refuses a click that a browser would not deliver
 * to that content. */
function emulateNativeSelectSectionPointerEvents(): void {
  const style = document.createElement("style");
  style.textContent =
    '.mantine-NativeSelect-section[data-position="right"] { pointer-events: none; }';
  document.head.append(style);
  onTestFinished(() => {
    style.remove();
  });
}

function structureFile(name = "Si.cif", content = "data_Si"): File {
  const file = new File([content], name, { type: "chemical/x-cif" });
  Object.defineProperty(file, "text", {
    value: () => Promise.resolve(content),
  });
  return file;
}

function structureInputElement(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) throw new Error("structure input missing");
  return input;
}

function optionValues(select: HTMLElement): string[] {
  return Array.from(
    select.querySelectorAll<HTMLOptionElement>("option"),
    (option) => option.value,
  );
}

/** A review whose is_magnetic classification and magnetic decision are
 * set independently, as a spin_polarized or magnetic_ordering setting can
 * make them disagree (#145). */
function magneticReview({
  isMagnetic,
  spinPolarized,
}: {
  readonly isMagnetic: "magnetic" | "non_magnetic";
  readonly spinPolarized: boolean;
}): ExplainResult {
  return {
    records: {
      ...explainResult.records,
      is_magnetic: { status: "resolved", value: isMagnetic, source: "ml" },
      magnetic: {
        status: "resolved",
        value: { spin_polarized: spinPolarized },
        source: "human",
      },
    },
    warnings: [],
    blocking: [],
    layout: explainResult.layout,
  };
}

/** A spin-polarized review, which shows the Magnetic Orderings card. */
function spinPolarizedReview(): Promise<ExplainResult> {
  return Promise.resolve(
    magneticReview({ isMagnetic: "magnetic", spinPolarized: true }),
  );
}

/** A listing of `labels`, each a cell of `natoms` atoms. */
function orderingsListing(
  natoms: number,
  ...labels: readonly string[]
): MagneticOrderingsResult {
  return {
    ranked: false,
    candidates: labels.map((label) => ({
      label,
      formula: "Fe",
      natoms,
      energy_per_atom_ev: null,
      status: null,
      is_recommended: false,
      overrides: { magnetic_ordering: label },
    })),
    warnings: [],
  };
}

function orderingsCard(): Promise<HTMLElement> {
  return screen.findByRole("region", { name: "Magnetic orderings" });
}

/** A queued request that fails with `failure` when the stub hands it out.
 * Marked handled up front: it waits in the queue past the debounce timers,
 * and an unhandled rejection that long would be reported as an error. */
function failing<T>(failure: CoreFailure): Promise<T> {
  const request = Promise.reject(failure);
  void request.catch(() => undefined);
  return request;
}

/** Lets `milliseconds` of real time pass, long enough for any debounced
 * automatic request (400 ms /explain, 150 ms preview) to go out. */
async function pause(milliseconds: number): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, milliseconds));
  });
}

/** The inline style of the status badge on an Advisors group's header, which
 * carries the badge's colour. */
function groupBadgeStyle(group: string): string {
  const header = within(advisorsPanel()).getByRole("button", { name: group });
  return (
    header.querySelector(".mantine-Badge-root")?.getAttribute("style") ?? ""
  );
}

/** A settings group's humanized name (e.g. "Magnetic") can collide with
 * a scientific record's own humanized name once results render -- both
 * are independently derived from real, unrelated vocabularies (an
 * override group vs. an advisor's record key). Scoping to this region
 * disambiguates in tests the same way a sighted user would from layout. */
function advisorsPanel(): HTMLElement {
  return screen.getByRole("region", { name: "Goldilocks advisors" });
}
