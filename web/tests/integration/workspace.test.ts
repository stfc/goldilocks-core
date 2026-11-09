import { describe, expect, it, onTestFinished, vi } from "vitest";

import type {
  ArchiveDownload,
  Capabilities,
  ComputeRequest,
  CoreClient,
  ExplainResult,
  MagneticOrderingsRequest,
  RankingJob,
  MagneticOrderingsResult,
  RunResult,
  StructureInput,
  StructureInspection,
} from "../../src/api/coreClient";
import { CoreFailure } from "../../src/api/coreClient";
import {
  buildArchive,
  capabilities,
  draft,
  explainResult,
  inspection,
  structureInput,
} from "../support/workbenchFixtures";
import {
  bannerFailure,
  currentArchive,
  currentExplain,
} from "../../src/workspace/pipelineStatus";
import {
  createWorkspace,
  currentOrderings,
} from "../../src/workspace/workspace";

class CoreStub implements CoreClient {
  capabilitiesResult: Promise<Capabilities> = Promise.resolve(capabilities);
  capabilitiesCalls = 0;
  inspectionResults: Promise<StructureInspection>[] = [
    Promise.resolve(inspection),
  ];
  inspectedInputs: StructureInput[] = [];
  explainResults: Promise<ExplainResult>[] = [];
  explainCalls: ComputeRequest[] = [];
  archiveResults: Promise<ArchiveDownload>[] = [];
  archiveCalls: ComputeRequest[] = [];
  magneticOrderingsResults: Promise<MagneticOrderingsResult>[] = [];
  magneticOrderingsCalls: MagneticOrderingsRequest[] = [];
  magneticOrderingsSignals: (AbortSignal | undefined)[] = [];
  rankingSubmissions: Promise<RankingJob>[] = [];
  rankingStatuses: Promise<RankingJob>[] = [];
  rankingCalls: MagneticOrderingsRequest[] = [];
  rankingStatusCalls: string[] = [];
  cancelledRankings: string[] = [];

  capabilities(): Promise<Capabilities> {
    this.capabilitiesCalls += 1;
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
    return (
      this.explainResults.shift() ??
      Promise.reject(new Error("explain not configured"))
    );
  }

  run(): Promise<RunResult> {
    return Promise.reject(new Error("run not configured"));
  }

  runArchive(request: ComputeRequest): Promise<ArchiveDownload> {
    this.archiveCalls.push(request);
    return (
      this.archiveResults.shift() ??
      Promise.reject(new Error("archive not configured"))
    );
  }

  /** Records the signal and, like a client that ignores it, still settles
   * the queued result; tests reject it with `signal.reason` where they
   * stand in for fetch, which rejects an aborted request that way. */
  magneticOrderings(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<MagneticOrderingsResult> {
    this.magneticOrderingsCalls.push(request);
    this.magneticOrderingsSignals.push(signal);
    return (
      this.magneticOrderingsResults.shift() ??
      Promise.reject(new Error("magnetic orderings not configured"))
    );
  }

  submitRanking(request: MagneticOrderingsRequest): Promise<RankingJob> {
    this.rankingCalls.push(request);
    return (
      this.rankingSubmissions.shift() ??
      Promise.reject(new Error("ranking not configured"))
    );
  }

  rankingStatus(jobId: string): Promise<RankingJob> {
    this.rankingStatusCalls.push(jobId);
    return (
      this.rankingStatuses.shift() ??
      Promise.reject(new Error("ranking status not configured"))
    );
  }

  cancelRanking(jobId: string): Promise<void> {
    this.cancelledRankings.push(jobId);
    return Promise.resolve();
  }
}

const replacementInput: StructureInput = {
  structure_content: "Silicon B",
  structure_name: "POSCAR",
  structure_format: "poscar",
};

/** A listing of `labels`, each a cell of `natoms` atoms. */
function orderingsListing(
  natoms: number,
  ...labels: readonly string[]
): MagneticOrderingsResult {
  return {
    ranked: false,
    candidates: labels.map((label) => ({
      label,
      formula: "Si",
      natoms,
      energy_per_atom_ev: null,
      status: null,
      is_recommended: false,
      overrides: { magnetic_ordering: label },
    })),
    warnings: [],
  };
}

function baseRequest(): ComputeRequest {
  return {
    structure_content: structureInput.structure_content,
    structure_name: structureInput.structure_name,
    structure_format: "cif",
    code: draft.code,
    task: draft.task,
    hpc: draft.hpc,
    overrides: draft.overrides,
    fetch_missing: draft.fetchMissing,
  };
}

describe("Workspace", () => {
  it("opens an inline structure input and initializes a canonical draft", async () => {
    const core = new CoreStub();
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    await workspace.dispatch({ type: "source.open", input: structureInput });

    expect(core.inspectedInputs).toEqual([structureInput]);
    expect(workspace.getSnapshot()).toMatchObject({
      structureInput,
      inspection,
      inspectFailure: null,
      draft,
      clearedOverrides: [],
      reviewed: null,
      explain: null,
      preview: null,
      operation: null,
    });
  });

  it("ignores a superseded inspection failure without releasing its replacement", async () => {
    const obsolete = deferred<StructureInspection>();
    const replacement = deferred<StructureInspection>();
    const core = new CoreStub();
    core.inspectionResults = [obsolete.promise, replacement.promise];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    const first = workspace.dispatch({
      type: "source.open",
      input: structureInput,
    });
    const replacementInput = {
      ...structureInput,
      structure_name: "replacement.cif",
    };
    const second = workspace.dispatch({
      type: "source.open",
      input: replacementInput,
    });
    obsolete.reject(
      new CoreFailure("invalid_structure", "Obsolete source failed"),
    );
    await first;

    expect(workspace.getSnapshot()).toMatchObject({
      operation: "inspect",
      inspectFailure: null,
    });
    replacement.resolve(inspection);
    await second;
    expect(workspace.getSnapshot()).toMatchObject({
      structureInput: replacementInput,
      operation: null,
      inspectFailure: null,
    });
  });

  it("keeps the open structure when another fails to open, and Retry opens the one that failed", async () => {
    const unreadable = new CoreFailure(
      "invalid_structure",
      "Unreadable structure.",
      {},
      422,
    );
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.reject(unreadable),
      Promise.resolve(inspection),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });

    await workspace.dispatch({ type: "source.open", input: replacementInput });

    expect(workspace.getSnapshot()).toMatchObject({
      structureInput,
      inspectFailure: { input: replacementInput, failure: unreadable },
    });
    expect(bannerFailure(workspace.getSnapshot())).toEqual({
      operation: "inspect",
      failure: unreadable,
    });

    await workspace.dispatch({ type: "failure.retry", operation: "inspect" });

    expect(core.inspectedInputs).toEqual([
      structureInput,
      replacementInput,
      replacementInput,
    ]);
    expect(workspace.getSnapshot()).toMatchObject({
      structureInput: replacementInput,
      inspectFailure: null,
    });
  });

  it("keeps the task, HPC profile and structure-independent overrides for the next structure, and lists the overrides it clears", async () => {
    // #188: opening another structure replaced the whole draft with the
    // default, so the task, the account and the functional went too, without
    // a word. It now clears only the settings capabilities marks
    // structure_specific, and every fact override.
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    core.explainResults = [Promise.resolve(explainResult)];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({
      type: "draft.patch",
      task: "relax",
      hpc: "scarf",
      overrides: {
        functional: "PBE",
        k_grid: [5, 5, 5],
        account: "acct-001",
        spin_orbit_coupling: true,
        is_metal: "metal",
        u_by_element: { Si: 2 },
      },
    });

    await workspace.dispatch({ type: "source.open", input: replacementInput });

    const snapshot = workspace.getSnapshot();
    expect(snapshot.draft).toEqual({
      ...draft,
      task: "relax",
      hpc: "scarf",
      overrides: { functional: "PBE", account: "acct-001" },
    });
    expect(snapshot.clearedOverrides).toEqual([
      "k_grid",
      "spin_orbit_coupling",
      "is_metal",
      "u_by_element",
    ]);
    await workspace.dispatch({ type: "review.compute" });
    expect(core.explainCalls).toEqual([
      {
        ...baseRequest(),
        structure_content: replacementInput.structure_content,
        structure_name: replacementInput.structure_name,
        structure_format: "poscar",
        task: "relax",
        hpc: "scarf",
        overrides: { functional: "PBE", account: "acct-001" },
      },
    ]);

    await workspace.dispatch({ type: "workspace.reset" });
    expect(workspace.getSnapshot().clearedOverrides).toEqual([]);
  });

  it("submits the exact request and stores the explain preview", async () => {
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });

    await workspace.dispatch({ type: "review.compute" });

    expect(core.explainCalls).toEqual([baseRequest()]);
    const snapshot = workspace.getSnapshot();
    expect(snapshot).toMatchObject({
      reviewed: explainResult,
      operation: null,
    });
    expect(currentExplain(snapshot)).toEqual({
      key: { input: structureInput, revision: snapshot.revision },
      status: "result",
      value: explainResult,
    });
  });

  it("merges overrides and marks the review out of date after a draft edit", async () => {
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });

    const snapshot = workspace.getSnapshot();
    expect(snapshot).toMatchObject({
      draft: { overrides: { k_grid: [5, 5, 5] } },
      reviewed: explainResult,
    });
    // The review on screen is of the draft before the edit.
    expect(currentExplain(snapshot)).toBeNull();
  });

  it("sends only the overrides that apply to the draft's task", async () => {
    // #154: the core refuses a setting no step of the task reads, so a
    // relax-only override kept in the draft must not reach an scf request.
    const core = new CoreStub();
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.resolve(explainResult),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({
      type: "draft.patch",
      task: "relax",
      overrides: { ion_dynamics: "fire", k_grid: [5, 5, 5], is_metal: "metal" },
    });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "draft.patch", task: "scf_single_point" });
    await workspace.dispatch({ type: "review.compute" });

    expect(core.explainCalls.map((request) => request.overrides)).toEqual([
      { ion_dynamics: "fire", k_grid: [5, 5, 5], is_metal: "metal" },
      { k_grid: [5, 5, 5], is_metal: "metal" },
    ]);
    expect(workspace.getSnapshot().draft?.overrides).toEqual({
      ion_dynamics: "fire",
      k_grid: [5, 5, 5],
      is_metal: "metal",
    });
  });

  it("clears an override back to automatic when patched with undefined", async () => {
    const core = new CoreStub();
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });

    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: undefined },
    });

    expect(workspace.getSnapshot().draft?.overrides).toEqual({});
  });

  it("retries a failed recomputation and replaces the reviewed snapshot", async () => {
    const failure = new CoreFailure(
      "advice_incomplete",
      "Core failed temporarily.",
    );
    const replacementResult: ExplainResult = {
      ...explainResult,
      warnings: [
        {
          code: "job.retry",
          level: "info",
          category: "job",
          message: "retried",
          record: "job",
        },
      ],
    };
    const core = new CoreStub();
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.reject(failure),
      Promise.resolve(replacementResult),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "failure.retry", operation: "explain" });

    expect(core.explainCalls).toHaveLength(3);
    const snapshot = workspace.getSnapshot();
    expect(snapshot.reviewed).toBe(replacementResult);
    expect(currentExplain(snapshot)).toMatchObject({
      status: "result",
      value: replacementResult,
    });
    expect(bannerFailure(snapshot)).toBeNull();
  });

  it("preserves the old review when recomputation fails", async () => {
    const failure = new CoreFailure(
      "advice_incomplete",
      "Core failed temporarily.",
    );
    const core = new CoreStub();
    core.explainResults = [
      Promise.resolve(explainResult),
      Promise.reject(failure),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });

    await workspace.dispatch({ type: "review.compute" });

    const snapshot = workspace.getSnapshot();
    expect(snapshot).toMatchObject({
      reviewed: explainResult,
      operation: null,
    });
    expect(currentExplain(snapshot)).toEqual({
      key: { input: structureInput, revision: snapshot.revision },
      status: "failure",
      failure,
      dismissed: false,
    });
  });

  it("downloads the archive previewed for the exact reviewed request", async () => {
    const archive = buildArchive();
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    core.archiveResults = [Promise.resolve(archive)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({ type: "review.refreshArchive" });
    expect(saveArchive).not.toHaveBeenCalled();

    await workspace.dispatch({ type: "review.download" });

    // Download saves the preview's own archive: one /run in total.
    expect(core.archiveCalls).toEqual([baseRequest()]);
    expect(saveArchive).toHaveBeenCalledOnce();
    expect(saveArchive.mock.calls[0]?.[0]).toBe(archive);
    expect(currentArchive(workspace.getSnapshot())).toBe(archive);
    expect(workspace.getSnapshot().operation).toBeNull();
  });

  it("retries a failed automatic preview without saving the archive", async () => {
    // #189: Retry used to route a failed preview through review.download,
    // which fetched the archive and saved it as a file nobody asked for.
    const unavailable = new CoreFailure(
      "http_error",
      "The Goldilocks Core server rejected the request (503).",
      { status: 503 },
      503,
    );
    const archive = buildArchive();
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    core.archiveResults = [
      Promise.reject(unavailable),
      Promise.resolve(archive),
    ];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({ type: "review.refreshArchive" });
    expect(bannerFailure(workspace.getSnapshot())).toEqual({
      operation: "preview",
      failure: unavailable,
    });

    await workspace.dispatch({ type: "failure.retry", operation: "preview" });

    expect(saveArchive).not.toHaveBeenCalled();
    expect(core.archiveCalls).toEqual([baseRequest(), baseRequest()]);
    const snapshot = workspace.getSnapshot();
    expect(currentArchive(snapshot)).toBe(archive);
    expect(bannerFailure(snapshot)).toBeNull();
    expect(snapshot.operation).toBeNull();
  });

  it("keeps a refused preview as its revision's outcome, so Dismiss and Download send no /run", async () => {
    // #150: a 422 from the automatic /run was only a dismissible banner.
    // Dismiss cleared it, so the auto-preview sent the same /run again.
    const refused = new CoreFailure(
      "generation_error",
      "Rutile TiO2 cannot be generated.",
      {},
      422,
    );
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    core.archiveResults = [
      Promise.reject(refused),
      Promise.resolve(buildArchive()),
    ];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({ type: "review.refreshArchive" });

    await workspace.dispatch({ type: "failure.dismiss", operation: "preview" });
    await workspace.dispatch({ type: "review.download" });
    // What the automatic preview dispatches once nothing is in flight.
    await workspace.dispatch({ type: "review.refreshArchive" });

    expect(core.archiveCalls).toEqual([baseRequest()]);
    expect(saveArchive).not.toHaveBeenCalled();
    const snapshot = workspace.getSnapshot();
    expect(snapshot.preview).toEqual({
      key: { input: structureInput, revision: snapshot.revision },
      status: "failure",
      failure: refused,
      dismissed: true,
    });
  });

  it("keeps a failed /explain for its revision until Retry sends it once", async () => {
    // #150: Dismiss cleared the failure, so the same /explain went out again.
    const rejected = new CoreFailure(
      "invalid_setting",
      "is_metal must be metal or non_metal.",
      {},
      422,
    );
    const core = new CoreStub();
    core.explainResults = [
      Promise.reject(rejected),
      Promise.resolve(explainResult),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "failure.dismiss", operation: "explain" });
    // What the automatic recompute dispatches once nothing is in flight.
    await workspace.dispatch({ type: "review.compute" });
    expect(core.explainCalls).toHaveLength(1);

    await workspace.dispatch({ type: "failure.retry", operation: "explain" });
    // The retried /explain succeeded: nothing is left to retry.
    await workspace.dispatch({ type: "failure.retry", operation: "explain" });

    expect(core.explainCalls).toEqual([baseRequest(), baseRequest()]);
    const snapshot = workspace.getSnapshot();
    expect(snapshot).toMatchObject({
      reviewed: explainResult,
      explain: {
        key: { input: structureInput, revision: snapshot.revision },
        status: "result",
        value: explainResult,
      },
    });
  });

  it("sends a new /explain when the same structure input is opened again after a failure", async () => {
    // #150: a failed /explain is its draft's outcome and is not sent again.
    // An embedder can open the very same StructureInput object again; the
    // revision never repeats, so the old failure is not the new draft's.
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    core.explainResults = [
      Promise.reject(
        new CoreFailure("advice_incomplete", "Core failed.", {}, 422),
      ),
      Promise.resolve(explainResult),
      Promise.resolve(explainResult),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({ type: "review.compute" });
    expect(core.explainCalls).toHaveLength(1);
    const failedRevision = workspace.getSnapshot().revision;

    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });

    expect(core.explainCalls).toHaveLength(2);
    const snapshot = workspace.getSnapshot();
    expect(snapshot.revision).toBeGreaterThan(failedRevision);
    expect(snapshot).toMatchObject({ structureInput, reviewed: explainResult });
  });

  it("keeps counting revisions across reset, so no key repeats", async () => {
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    const opened = workspace.getSnapshot().revision;

    await workspace.dispatch({ type: "workspace.reset" });
    expect(workspace.getSnapshot().revision).toBe(opened);
    await workspace.dispatch({ type: "source.open", input: structureInput });

    expect(workspace.getSnapshot().revision).toBeGreaterThan(opened);
  });

  it("sends no /run for a draft whose /explain verdict blocks", async () => {
    // #165: /explain returns the reasons /run would refuse for, so the
    // preview /run of that draft could only fail.
    const blocked: ExplainResult = {
      ...explainResult,
      blocking: [
        {
          code: "parallelisation.npool_does_not_divide_ntasks",
          fields: ["npool", "ntasks"],
          message: "npool=7 does not divide ntasks=8.",
          summary:
            "npool must divide the job's task count: choose a divisor, or leave npool automatic.",
          remedies: [{ npool: null }],
        },
      ],
    };
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(blocked)];
    core.archiveResults = [Promise.resolve(buildArchive())];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "review.refreshArchive" });
    await workspace.dispatch({ type: "review.download" });

    expect(core.archiveCalls).toEqual([]);
    expect(saveArchive).not.toHaveBeenCalled();
    expect(workspace.getSnapshot()).toMatchObject({
      reviewed: blocked,
      preview: null,
    });
  });

  it("saves nothing and sends no /run when Download has no current archive", async () => {
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    core.archiveResults = [Promise.resolve(buildArchive())];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "review.download" });

    expect(core.archiveCalls).toEqual([]);
    expect(saveArchive).not.toHaveBeenCalled();
    expect(workspace.getSnapshot()).toMatchObject({
      preview: null,
      operation: null,
    });
  });

  it("downloads each selected ordering as the listed structure plus its label", async () => {
    // #170: a candidate is generated by its label on the structure that
    // was listed; it carries no structure of its own, and the draft's
    // starting_magnetization (keyed to the uploaded cell's sites) would
    // refuse the candidate's own species or override its seeds. #149: each
    // bundle is named after the listing's own structure.
    const fm = buildArchive("Si.cif-fm-scf_single_point.zip");
    const afm = buildArchive("Si.cif-afm-1-scf_single_point.zip");
    const core = new CoreStub();
    core.magneticOrderingsResults = [
      Promise.resolve(orderingsListing(2, "fm", "afm-1", "afm-2")),
    ];
    core.archiveResults = [Promise.resolve(fm), Promise.resolve(afm)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: {
        spin_polarized: true,
        starting_magnetization: { Si0: 0.5 },
        magnetic_ordering: "afm",
      },
    });
    await workspace.dispatch({ type: "magneticOrderings.list" });

    await workspace.dispatch({
      type: "magneticOrderings.downloadSelected",
      labels: ["fm", "afm-1"],
    });

    expect(core.archiveCalls).toEqual([
      {
        ...baseRequest(),
        structure_name: `${structureInput.structure_name}-fm`,
        overrides: { spin_polarized: true, magnetic_ordering: "fm" },
      },
      {
        ...baseRequest(),
        structure_name: `${structureInput.structure_name}-afm-1`,
        overrides: { spin_polarized: true, magnetic_ordering: "afm-1" },
      },
    ]);
    expect(saveArchive.mock.calls).toEqual([[fm], [afm]]);
  });

  it("lists a replacement structure itself and drops the old structure's late listing", async () => {
    // #149: a listing that arrived after another structure opened was shown
    // for that structure, kept it from being listed itself, and Download
    // selected then named the old structure's bundles after the new one.
    const obsoleteListing = deferred<MagneticOrderingsResult>();
    const replacementResult = orderingsListing(1, "fm");
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    core.magneticOrderingsResults = [
      obsoleteListing.promise,
      Promise.resolve(replacementResult),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    const listing = workspace.dispatch({ type: "magneticOrderings.list" });
    await workspace.dispatch({ type: "source.open", input: replacementInput });

    // A client that ignores the abort still delivers the old listing.
    obsoleteListing.resolve(orderingsListing(8, "fm", "afm-1"));
    await listing;
    expect(currentOrderings(workspace.getSnapshot())).toBeNull();
    await workspace.dispatch({
      type: "magneticOrderings.downloadSelected",
      labels: ["afm-1"],
    });
    expect(core.archiveCalls).toEqual([]);

    await workspace.dispatch({ type: "magneticOrderings.list" });

    expect(
      core.magneticOrderingsCalls.map((request) => request.structure_content),
    ).toEqual([
      structureInput.structure_content,
      replacementInput.structure_content,
    ]);
    expect(currentOrderings(workspace.getSnapshot())).toEqual({
      input: replacementInput,
      operation: null,
      result: replacementResult,
      error: null,
      ranking: null,
    });
  });

  it("aborts a listing in flight once another structure opens, and on reset", async () => {
    // #149: nothing could abort a listing, so it ran on after its structure
    // was replaced. An inspection that fails replaces nothing, so the
    // listing of the structure still open runs on.
    const unreadable = deferred<StructureInspection>();
    const obsoleteListing = deferred<MagneticOrderingsResult>();
    const replacementListing = deferred<MagneticOrderingsResult>();
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      unreadable.promise,
      Promise.resolve(inspection),
    ];
    core.magneticOrderingsResults = [
      obsoleteListing.promise,
      replacementListing.promise,
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    const listing = workspace.dispatch({ type: "magneticOrderings.list" });
    const [signal] = core.magneticOrderingsSignals;
    expect(signal).toBeInstanceOf(AbortSignal);

    const failedOpen = workspace.dispatch({
      type: "source.open",
      input: replacementInput,
    });
    unreadable.reject(
      new CoreFailure("invalid_structure", "Unreadable structure."),
    );
    await failedOpen;
    expect(signal?.aborted).toBe(false);
    expect(currentOrderings(workspace.getSnapshot())).toMatchObject({
      input: structureInput,
      operation: "list",
    });

    await workspace.dispatch({ type: "source.open", input: replacementInput });
    expect(signal?.aborted).toBe(true);
    // fetch rejects an aborted request with the signal's reason.
    obsoleteListing.reject(signal?.reason);
    await listing;
    expect(workspace.getSnapshot().magneticOrderings).toBeNull();

    const replacing = workspace.dispatch({ type: "magneticOrderings.list" });
    await workspace.dispatch({ type: "workspace.reset" });
    const replacementSignal = core.magneticOrderingsSignals[1];
    expect(replacementSignal?.aborted).toBe(true);
    replacementListing.reject(replacementSignal?.reason);
    await replacing;
    expect(workspace.getSnapshot().magneticOrderings).toBeNull();
  });

  it.each([
    {
      outcome: "is saved",
      settle: (archive: Deferred<ArchiveDownload>) => {
        archive.resolve(buildArchive("Si.cif-afm-1-scf_single_point.zip"));
      },
      saved: 1,
    },
    {
      outcome: "fails",
      settle: (archive: Deferred<ArchiveDownload>) => {
        archive.reject(
          new CoreFailure("advice_incomplete", "afm-1 is incomplete."),
        );
      },
      saved: 0,
    },
  ])(
    "leaves the replacement's listing alone when an old candidate download $outcome",
    async ({ settle, saved }) => {
      // #149: Download selected for the old structure finished by clearing
      // the replacement listing's busy flag (and showing its own error
      // there), so the replacement was listed a second time. The old
      // structure's archives are still saved, named and built from its own
      // listing.
      const candidateArchive = deferred<ArchiveDownload>();
      const replacementListing = deferred<MagneticOrderingsResult>();
      const replacementResult = orderingsListing(1, "fm");
      const core = new CoreStub();
      core.inspectionResults = [
        Promise.resolve(inspection),
        Promise.resolve(inspection),
      ];
      core.magneticOrderingsResults = [
        Promise.resolve(orderingsListing(4, "fm", "afm-1")),
        replacementListing.promise,
      ];
      core.archiveResults = [candidateArchive.promise];
      const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
      const workspace = createWorkspace(core, saveArchive);
      await workspace.dispatch({ type: "workspace.start" });
      await workspace.dispatch({ type: "source.open", input: structureInput });
      await workspace.dispatch({ type: "magneticOrderings.list" });
      const downloading = workspace.dispatch({
        type: "magneticOrderings.downloadSelected",
        labels: ["afm-1"],
      });
      await workspace.dispatch({
        type: "source.open",
        input: replacementInput,
      });
      const listing = workspace.dispatch({ type: "magneticOrderings.list" });

      settle(candidateArchive);
      await downloading;
      // The replacement's listing is still in flight, so it is not re-sent.
      await workspace.dispatch({ type: "magneticOrderings.list" });
      replacementListing.resolve(replacementResult);
      await listing;

      expect(
        core.magneticOrderingsCalls.map((request) => request.structure_name),
      ).toEqual([
        structureInput.structure_name,
        replacementInput.structure_name,
      ]);
      expect(
        core.archiveCalls.map((request) => [
          request.structure_name,
          request.structure_content,
        ]),
      ).toEqual([["Si.cif-afm-1", structureInput.structure_content]]);
      expect(saveArchive).toHaveBeenCalledTimes(saved);
      expect(currentOrderings(workspace.getSnapshot())).toEqual({
        input: replacementInput,
        operation: null,
        result: replacementResult,
        error: null,
        ranking: null,
      });
    },
  );

  it("keeps the listing on screen while a ranking job is queued, runs and finishes", async () => {
    // #261: the ranking is a server job, polled every 2 s; the listing
    // shows where it stands meanwhile.
    vi.useFakeTimers();
    onTestFinished(() => {
      vi.useRealTimers();
    });
    const listing = orderingsListing(4, "fm", "afm-1");
    const rankedListing = { ...listing, ranked: true };
    const core = new CoreStub();
    core.magneticOrderingsResults = [Promise.resolve(listing)];
    core.rankingSubmissions = [
      Promise.resolve({ job_id: "j1", state: "queued", position: 1 }),
    ];
    core.rankingStatuses = [
      Promise.resolve({
        job_id: "j1",
        state: "running",
        progress: { done: 1, total: 2 },
      }),
      Promise.resolve({ job_id: "j1", state: "done", report: rankedListing }),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "magneticOrderings.list" });

    const ranking = workspace.dispatch({ type: "magneticOrderings.rank" });
    await vi.advanceTimersByTimeAsync(0);

    expect(core.rankingCalls).toEqual([
      {
        structure_content: structureInput.structure_content,
        structure_name: structureInput.structure_name,
        structure_format: structureInput.structure_format,
      },
    ]);
    expect(currentOrderings(workspace.getSnapshot())).toEqual({
      input: structureInput,
      operation: "rank",
      result: listing,
      error: null,
      ranking: { job_id: "j1", state: "queued", position: 1 },
    });
    await vi.advanceTimersByTimeAsync(2000);
    expect(currentOrderings(workspace.getSnapshot())?.ranking).toEqual({
      job_id: "j1",
      state: "running",
      progress: { done: 1, total: 2 },
    });
    await vi.advanceTimersByTimeAsync(2000);
    await ranking;
    expect(currentOrderings(workspace.getSnapshot())).toEqual({
      input: structureInput,
      operation: null,
      result: rankedListing,
      error: null,
      ranking: null,
    });
    expect(core.rankingStatusCalls).toEqual(["j1", "j1"]);
    expect(core.cancelledRankings).toEqual([]);
  });

  it("cancels the ranking job when another structure opens", async () => {
    vi.useFakeTimers();
    onTestFinished(() => {
      vi.useRealTimers();
    });
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspection),
    ];
    core.magneticOrderingsResults = [
      Promise.resolve(orderingsListing(4, "fm", "afm-1")),
    ];
    core.rankingSubmissions = [
      Promise.resolve({ job_id: "j1", state: "queued", position: 3 }),
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "magneticOrderings.list" });
    const ranking = workspace.dispatch({ type: "magneticOrderings.rank" });
    await vi.advanceTimersByTimeAsync(0);

    await workspace.dispatch({ type: "source.open", input: replacementInput });
    await ranking;

    expect(core.cancelledRankings).toEqual(["j1"]);
    expect(core.rankingStatusCalls).toEqual([]);
    expect(currentOrderings(workspace.getSnapshot())).toBeNull();
  });

  it("says a ranking the server lost can be run again", async () => {
    vi.useFakeTimers();
    onTestFinished(() => {
      vi.useRealTimers();
    });
    const listing = orderingsListing(4, "fm", "afm-1");
    const lost =
      "No ranking job j1 on this server: it was cancelled, finished long " +
      "ago, or the server restarted. Run the ranking again.";
    const core = new CoreStub();
    core.magneticOrderingsResults = [Promise.resolve(listing)];
    core.rankingSubmissions = [
      Promise.resolve({ job_id: "j1", state: "queued", position: 0 }),
    ];
    const lostJob = Promise.reject(
      new CoreFailure("unknown_ranking", lost, {}, 404),
    );
    // Read only after the 2 s poll; handled up front so the wait is not
    // reported as an unhandled rejection.
    lostJob.catch(() => undefined);
    core.rankingStatuses = [lostJob];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "magneticOrderings.list" });

    const ranking = workspace.dispatch({ type: "magneticOrderings.rank" });
    await vi.advanceTimersByTimeAsync(2000);
    await ranking;

    expect(currentOrderings(workspace.getSnapshot())).toEqual({
      input: structureInput,
      operation: null,
      result: listing,
      error: lost,
      ranking: null,
    });
  });

  it("refuses to download while the review is out of date", async () => {
    const archive = buildArchive();
    const core = new CoreStub();
    core.explainResults = [Promise.resolve(explainResult)];
    core.archiveResults = [Promise.resolve(archive)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({ type: "review.refreshArchive" });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });

    await workspace.dispatch({ type: "review.download" });

    // The archive in hand belongs to the draft before the edit.
    const snapshot = workspace.getSnapshot();
    expect(snapshot.preview).toMatchObject({
      key: { input: structureInput, revision: snapshot.revision - 1 },
      value: archive,
    });
    expect(currentArchive(snapshot)).toBeNull();
    expect(saveArchive).not.toHaveBeenCalled();
    expect(core.archiveCalls).toHaveLength(1);
  });

  it("does not pair an obsolete explain with a replacement structure", async () => {
    const obsoleteExplain = deferred<ExplainResult>();
    const replacementInput: StructureInput = {
      structure_content: "Silicon B",
      structure_name: "POSCAR",
      structure_format: "poscar",
    };
    const inspectedReplacement: StructureInspection = {
      ...inspection,
      canonical_cif: "replacement",
    };
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspectedReplacement),
    ];
    core.explainResults = [
      Promise.resolve(explainResult),
      obsoleteExplain.promise,
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", input: structureInput });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({
      type: "draft.patch",
      overrides: { k_grid: [5, 5, 5] },
    });

    const computing = workspace.dispatch({ type: "review.compute" });
    const replacing = workspace.dispatch({
      type: "source.open",
      input: replacementInput,
    });
    obsoleteExplain.resolve({ ...explainResult, warnings: [] });
    await computing;
    await replacing;

    expect(core.explainCalls).toHaveLength(2);
    expect(workspace.getSnapshot()).toMatchObject({
      structureInput: replacementInput,
      reviewed: null,
      explain: null,
      operation: null,
    });
  });

  it("reset ignores obsolete source work and retains capabilities", async () => {
    let finishInspection: (value: StructureInspection) => void = () =>
      undefined;
    const pendingInspection = new Promise<StructureInspection>((resolve) => {
      finishInspection = resolve;
    });
    const core = new CoreStub();
    core.inspectionResults = [pendingInspection];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    const opening = workspace.dispatch({
      type: "source.open",
      input: structureInput,
    });
    await workspace.dispatch({ type: "workspace.reset" });
    finishInspection(inspection);
    await opening;

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      structureInput: null,
      inspection: null,
      inspectFailure: null,
      draft: null,
      reviewed: null,
      explain: null,
      preview: null,
      operation: null,
    });
  });

  it("does not dismiss a capabilities failure before capabilities are usable", async () => {
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
    );
    const core = new CoreStub();
    core.capabilitiesResult = Promise.reject(failure);
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    await workspace.dispatch({
      type: "failure.dismiss",
      operation: "capabilities",
    });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      startupFailure: failure,
      operation: null,
    });
    expect(bannerFailure(workspace.getSnapshot())).toEqual({
      operation: "capabilities",
      failure,
    });
  });

  it("keeps a typed startup failure retryable", async () => {
    const core = new CoreStub();
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
    );
    core.capabilitiesResult = Promise.reject(failure);
    const workspace = createWorkspace(core);

    await workspace.dispatch({ type: "workspace.start" });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      operation: null,
      startupFailure: failure,
    });

    core.capabilitiesResult = Promise.resolve(capabilities);
    await workspace.dispatch({
      type: "failure.retry",
      operation: "capabilities",
    });
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      startupFailure: null,
    });
  });

  it("retains pending capabilities ownership across reset and accepts its result", async () => {
    const pendingCapabilities = deferred<Capabilities>();
    const core = new CoreStub();
    core.capabilitiesResult = pendingCapabilities.promise;
    const workspace = createWorkspace(core);

    const starting = workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "workspace.reset" });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      operation: "capabilities",
      startupFailure: null,
    });
    pendingCapabilities.resolve(capabilities);
    await starting;

    expect(core.capabilitiesCalls).toBe(1);
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      operation: null,
      startupFailure: null,
    });
  });

  it("loads and stores one immutable capabilities snapshot at startup", async () => {
    const core = new CoreStub();
    const workspace = createWorkspace(core);

    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "workspace.start" });

    expect(core.capabilitiesCalls).toBe(1);
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      operation: null,
      startupFailure: null,
    });
  });
});

interface Deferred<T> {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason: unknown) => void = () => undefined;
  const promise = new Promise<T>((finish, fail) => {
    resolve = finish;
    reject = fail;
  });
  return { promise, resolve, reject };
}
