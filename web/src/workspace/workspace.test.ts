import { describe, expect, it, vi } from "vitest";

import type {
  ArchiveDownload,
  ArchiveOutput,
  Capabilities,
  ComputationResult,
  ComputeRequest,
  CoreClient,
  MemoryOutput,
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
  memoryResults: Promise<ComputationResult>[] = [];
  archiveResults: Promise<ArchiveDownload>[] = [];
  computeCalls: { request: ComputeRequest; output: MemoryOutput | ArchiveOutput }[] = [];

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

  compute(
    _request: ComputeRequest,
    _output: MemoryOutput,
  ): Promise<ComputationResult>;
  compute(
    _request: ComputeRequest,
    _output: ArchiveOutput,
  ): Promise<ArchiveDownload>;
  compute(
    request: ComputeRequest,
    output: MemoryOutput | ArchiveOutput,
  ): Promise<ComputationResult | ArchiveDownload> {
    this.computeCalls.push({ request, output });
    if (output.kind === "archive") {
      return (
        this.archiveResults.shift() ??
        Promise.reject(new Error("archive not configured"))
      );
    }
    return (
      this.memoryResults.shift() ??
      Promise.reject(new Error("memory compute not configured"))
    );
  }
}

describe("Workspace", () => {
  it("retries a failed recomputation and replaces the reviewed snapshot", async () => {
    const failure = new CoreFailure("server_busy", "Core is busy.", true);
    const replacementResult: ComputationResult = {
      ...computationResult,
      task_revision: "2",
    };
    const core = new CoreStub();
    core.memoryResults = [
      Promise.resolve(computationResult),
      Promise.reject(failure),
      Promise.resolve(replacementResult),
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
      reviewed: {
        draft: { hints: { k_grid: [5, 5, 5] } },
        result: replacementResult,
      },
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

  it("downloads by resubmitting the exact reviewed Draft for archive output", async () => {
    const archive: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks-inputs.zip",
    };
    const core = new CoreStub();
    core.memoryResults = [Promise.resolve(computationResult)];
    core.archiveResults = [Promise.resolve(archive)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.compute" });

    await workspace.dispatch({ type: "review.download" });

    expect(core.computeCalls[1]).toEqual({
      request: { draft, selection: { preset: "generate" } },
      output: { kind: "archive" },
    });
    expect(saveArchive).toHaveBeenCalledWith(archive);
    expect(workspace.getSnapshot()).toMatchObject({
      lastDownload: archive,
      downloadOutOfDate: false,
      operation: null,
      failure: null,
    });
  });

  it("preserves the old Result when recomputation fails", async () => {
    const failure = new CoreFailure("server_busy", "Core is busy.", true);
    const core = new CoreStub();
    core.memoryResults = [
      Promise.resolve(computationResult),
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
      reviewed: { draft, result: computationResult },
      outOfDate: true,
      operation: null,
      failure,
      failureOperation: "compute",
    });
  });

  it("preserves the reviewed Result and marks it out of date after a Draft edit", async () => {
    const core = new CoreStub();
    core.memoryResults = [Promise.resolve(computationResult)];
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
      reviewed: { draft, result: computationResult },
      outOfDate: true,
    });
  });

  it("stores the exact submitted Draft with a generation Result", async () => {
    const core = new CoreStub();
    core.memoryResults = [Promise.resolve(computationResult)];
    const workspace = createWorkspace(core);
    await workspace.dispatch({ type: "workspace.start" });
    await workspace.dispatch({ type: "source.open", source });

    await workspace.dispatch({ type: "review.compute" });

    expect(core.computeCalls).toEqual([
      {
        request: { draft, selection: { preset: "generate" } },
        output: { kind: "memory" },
      },
    ]);
    expect(workspace.getSnapshot()).toMatchObject({
      reviewed: { draft, result: computationResult },
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
