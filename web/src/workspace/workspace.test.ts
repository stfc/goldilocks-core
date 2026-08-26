import { describe, expect, it, vi } from "vitest";

import type {
  ArchiveDownload,
  Capabilities,
  ComputationResult,
  ComputeRequest,
  CoreClient,
  PreparedComputation,
  StructureInspection,
  StructureSource,
} from "../api/coreClient";
import { CoreFailure } from "../api/coreClient";
import {
  capabilities,
  computationResult,
  draft,
  inspection,
  source,
} from "../test/workbenchFixtures";
import { createWorkspace } from "./workspace";

class CoreStub implements CoreClient {
  capabilitiesResult: Promise<Capabilities> = Promise.resolve(capabilities);
  capabilitiesCalls = 0;
  inspectionResults: Promise<StructureInspection>[] = [
    Promise.resolve(inspection),
  ];
  inspectedSources: StructureSource[] = [];
  preparedResults: Promise<PreparedComputation>[] = [];
  computeCalls: ComputeRequest[] = [];

  capabilities(): Promise<Capabilities> {
    this.capabilitiesCalls += 1;
    return this.capabilitiesResult;
  }

  inspectStructure(sourceToInspect: StructureSource): Promise<StructureInspection> {
    this.inspectedSources.push(sourceToInspect);
    return (
      this.inspectionResults.shift() ??
      Promise.reject(new Error("inspection not configured"))
    );
  }

  compute(request: ComputeRequest): Promise<PreparedComputation> {
    this.computeCalls.push(request);
    return (
      this.preparedResults.shift() ??
      Promise.reject(new Error("prepared computation not configured"))
    );
  }
}

function prepared(
  result: ComputationResult = computationResult,
  archive: ArchiveDownload | null = {
    blob: new Blob(["zip"]),
    filename: "goldilocks-inputs.zip",
  },
): PreparedComputation {
  return { result, archive };
}

describe("Workspace", () => {
  it("retries a failed recomputation and replaces the reviewed snapshot", async () => {
    const failure = new CoreFailure(
      "temporary_failure",
      "Core failed temporarily.",
      true,
    );
    const replacementResult: ComputationResult = {
      ...computationResult,
      task_revision: "2",
    };
    const core = new CoreStub();
    core.preparedResults = [
      Promise.resolve(prepared()),
      Promise.reject(failure),
      Promise.resolve(prepared(replacementResult)),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({
      type: "draft.patch",
      hints: { k_grid: [5, 5, 5] },
    });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "failure.retry" });

    expect(core.computeCalls).toHaveLength(3);
    expect(workspace.getSnapshot()).toMatchObject({
      reviewed: { result: replacementResult },
      outOfDate: false,
      failure: null,
    });
  });

  it("reset ignores obsolete source work and retains Capabilities", async () => {
    let finishInspection: (value: StructureInspection) => void = () => undefined;
    const pendingInspection = new Promise<StructureInspection>((resolve) => {
      finishInspection = resolve;
    });
    const core = new CoreStub();
    core.inspectionResults = [pendingInspection];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    const opening = workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "workspace.reset" });
    finishInspection(inspection);
    await opening;

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      source: null,
      attemptedSource: null,
      inspection: null,
      draft: null,
      reviewed: null,
      operation: null,
      failure: null,
    });
  });

  it("does not pair an obsolete computation with a replacement source", async () => {
    const obsoleteComputation = deferred<PreparedComputation>();
    const replacement: StructureSource = {
      kind: "inline",
      name: "POSCAR",
      format: "poscar",
      content: "Silicon B",
    };
    const inspectedReplacement: StructureInspection = {
      ...inspection,
      canonical_cif: "replacement",
      source: {
        ...inspection.source,
        name: "POSCAR",
        format: "poscar",
        content: "Silicon B",
      },
    };
    const core = new CoreStub();
    core.inspectionResults = [
      Promise.resolve(inspection),
      Promise.resolve(inspectedReplacement),
    ];
    core.preparedResults = [
      Promise.resolve(prepared()),
      obsoleteComputation.promise,
    ];
    const workspace = createWorkspace(core, vi.fn());
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });

    const computing = workspace.dispatch({ type: "review.compute" });
    const replacing = workspace.dispatch({
      type: "source.open",
      source: replacement,
    });
    obsoleteComputation.resolve(
      prepared({ ...computationResult, task_revision: "obsolete" }),
    );
    await computing;
    await replacing;

    expect(core.computeCalls).toHaveLength(2);
    expect(workspace.getSnapshot()).toMatchObject({
      source: replacement,
      draft: { structure: replacement },
      reviewed: null,
      operation: null,
    });
  });

  it("downloads the archive paired with the reviewed computation", async () => {
    const archive: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks-inputs.zip",
    };
    const core = new CoreStub();
    core.preparedResults = [Promise.resolve(prepared(computationResult, archive))];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "review.download" });

    expect(core.computeCalls).toEqual([
      { draft, selection: { preset: "generate" } },
    ]);
    expect(saveArchive).toHaveBeenCalledWith(archive);
    expect(workspace.getSnapshot()).toMatchObject({
      lastDownload: archive,
      operation: null,
      failure: null,
    });
  });

  it("preserves the old Result when recomputation fails", async () => {
    const failure = new CoreFailure(
      "temporary_failure",
      "Core failed temporarily.",
      true,
    );
    const core = new CoreStub();
    core.preparedResults = [
      Promise.resolve(prepared()),
      Promise.reject(failure),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });
    await workspace.dispatch({
      type: "draft.patch",
      hints: { k_grid: [5, 5, 5] },
    });

    await workspace.dispatch({ type: "review.compute" });

    expect(workspace.getSnapshot()).toMatchObject({
      reviewed: { result: computationResult },
      outOfDate: true,
      operation: null,
      failure,
      failureOperation: "compute",
    });
  });

  it("preserves the reviewed Result and marks it out of date after a Draft edit", async () => {
    const core = new CoreStub();
    core.preparedResults = [Promise.resolve(prepared())];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({
      type: "draft.patch",
      hints: { k_grid: [5, 5, 5] },
    });

    expect(workspace.getSnapshot()).toMatchObject({
      draft: { hints: { k_grid: [5, 5, 5] } },
      reviewed: { result: computationResult },
      outOfDate: true,
    });
  });

  it("submits the exact Draft and stores its prepared computation", async () => {
    const core = new CoreStub();
    core.preparedResults = [Promise.resolve(prepared())];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });

    await workspace.dispatch({ type: "review.compute" });

    expect(core.computeCalls).toEqual([
      { draft, selection: { preset: "generate" } },
    ]);
    expect(workspace.getSnapshot()).toMatchObject({
      reviewed: { result: computationResult },
      outOfDate: false,
      operation: null,
      failure: null,
    });
  });

  it("ignores an obsolete inspection after rapid source replacement", async () => {
    let finishFirst: (value: StructureInspection) => void = () => undefined;
    const firstInspection = new Promise<StructureInspection>((resolve) => {
      finishFirst = resolve;
    });
    const replacement: StructureSource = {
      kind: "inline",
      name: "POSCAR",
      format: "poscar",
      content: "Silicon",
    };
    const replacementInspection: StructureInspection = {
      ...inspection,
      canonical_cif: "replacement",
      source: {
        ...inspection.source,
        name: "POSCAR",
        format: "poscar",
        content: "Silicon",
      },
    };
    const core = new CoreStub();
    core.inspectionResults = [
      firstInspection,
      Promise.resolve(replacementInspection),
    ];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    const first = workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "source.open", source: replacement });
    finishFirst(inspection);
    await first;

    expect(workspace.getSnapshot()).toMatchObject({
      source: replacement,
      inspection: replacementInspection,
      draft: { structure: replacement },
      operation: null,
    });
  });

  it("opens an inline Structure Source and initializes a canonical Draft", async () => {
    const core = new CoreStub();
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    await workspace.dispatch({ type: "source.open", source });

    expect(core.inspectedSources).toEqual([source]);
    expect(workspace.getSnapshot()).toMatchObject({
      source,
      attemptedSource: null,
      inspection,
      draft,
      operation: null,
      failure: null,
    });
  });

  it("does not dismiss a Capabilities failure before Capabilities are usable", async () => {
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
      true,
    );
    const core = new CoreStub();
    core.capabilitiesResult = Promise.reject(failure);
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });

    await workspace.dispatch({ type: "failure.dismiss" });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      failure,
      failureOperation: "capabilities",
      operation: null,
    });
  });

  it("keeps a typed startup failure retryable", async () => {
    const core = new CoreStub();
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
      true,
    );
    core.capabilitiesResult = Promise.reject(failure);
    const workspace = createWorkspace(core);

    await workspace.dispatch({ type: "workspace.start" });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      operation: null,
      failure,
      failureOperation: "capabilities",
    });

    core.capabilitiesResult = Promise.resolve(capabilities);
    await workspace.dispatch({ type: "failure.retry" });
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      failure: null,
      failureOperation: null,
    });
  });

  it("retains pending Capabilities ownership across reset and accepts its result", async () => {
    const pendingCapabilities = deferred<Capabilities>();
    const core = new CoreStub();
    core.capabilitiesResult = pendingCapabilities.promise;
    const workspace = createWorkspace(core);

    const starting = workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "workspace.reset" });

    expect(workspace.getSnapshot()).toMatchObject({
      capabilities: null,
      operation: "capabilities",
      failure: null,
    });
    pendingCapabilities.resolve(capabilities);
    await starting;

    expect(core.capabilitiesCalls).toBe(1);
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      operation: null,
      failure: null,
    });
  });

  it("loads and stores one immutable Capabilities snapshot at startup", async () => {
    const core = new CoreStub();
    const workspace = createWorkspace(core);

    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "workspace.start" });

    expect(core.capabilitiesCalls).toBe(1);
    expect(workspace.getSnapshot()).toMatchObject({
      capabilities,
      operation: null,
      failure: null,
    });
  });
});

function deferred<T>(): {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
} {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}
