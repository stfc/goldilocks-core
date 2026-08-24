import { createStore } from "zustand/vanilla";

import type {
  ArchiveDownload,
  CalculationDraft,
  Capabilities,
  ComputationResult,
  CoreClient,
  StructureInspection,
  StructureSource,
} from "../api/coreClient";
import { CoreFailure } from "../api/coreClient";

export type WorkspaceOperation =
  | "capabilities"
  | "inspect"
  | "compute"
  | "download";

export interface ReviewedComputation {
  readonly draft: CalculationDraft;
  readonly result: ComputationResult;
}

export interface WorkspaceSnapshot {
  readonly capabilities: Capabilities | null;
  readonly source: StructureSource | null;
  readonly attemptedSource: StructureSource | null;
  readonly inspection: StructureInspection | null;
  readonly draft: CalculationDraft | null;
  readonly reviewed: ReviewedComputation | null;
  readonly outOfDate: boolean;
  readonly lastDownload: ArchiveDownload | null;
  readonly downloadOutOfDate: boolean;
  readonly operation: WorkspaceOperation | null;
  readonly failure: CoreFailure | null;
  readonly failureOperation: WorkspaceOperation | null;
}

export type WorkspaceAction =
  | { readonly type: "workspace.start" }
  | { readonly type: "source.open"; readonly source: StructureSource }
  | {
      readonly type: "draft.patch";
      readonly intent?: Partial<NonNullable<CalculationDraft["intent"]>>;
      readonly hints?: Partial<NonNullable<CalculationDraft["hints"]>>;
      readonly pseudoTable?: string | null;
    }
  | { readonly type: "review.compute" }
  | { readonly type: "review.download" }
  | { readonly type: "failure.retry" }
  | { readonly type: "failure.dismiss" }
  | { readonly type: "workspace.reset" };

export interface Workspace {
  getSnapshot(): WorkspaceSnapshot;
  subscribe(listener: () => void): () => void;
  dispatch(action: WorkspaceAction): Promise<void>;
}

type ArchiveSink = (archive: ArchiveDownload) => void;

interface OperationOwner {
  readonly operation: WorkspaceOperation;
}

const EMPTY_SNAPSHOT: WorkspaceSnapshot = {
  capabilities: null,
  source: null,
  attemptedSource: null,
  inspection: null,
  draft: null,
  reviewed: null,
  outOfDate: false,
  lastDownload: null,
  downloadOutOfDate: false,
  operation: null,
  failure: null,
  failureOperation: null,
};

export function createWorkspace(
  core: CoreClient,
  saveArchive: ArchiveSink = saveArchiveToBrowser,
): Workspace {
  const store = createStore<WorkspaceSnapshot>(() => EMPTY_SNAPSHOT);
  let activeOperation: OperationOwner | null = null;
  let startup: {
    readonly owner: OperationOwner;
    readonly promise: Promise<void>;
  } | null = null;
  let draftRevision = 0;

  function beginOperation(operation: WorkspaceOperation): OperationOwner {
    const owner = { operation };
    activeOperation = owner;
    store.setState({
      operation,
      failure: null,
      failureOperation: null,
    });
    return owner;
  }

  function completeOperation(
    owner: OperationOwner,
    update: Partial<WorkspaceSnapshot> = {},
  ): boolean {
    if (activeOperation !== owner) return false;
    activeOperation = null;
    store.setState({ ...update, operation: null });
    return true;
  }

  function start(): Promise<void> {
    if (store.getState().capabilities !== null) return Promise.resolve();
    if (startup !== null) return startup.promise;
    const owner = beginOperation("capabilities");
    const promise = core.capabilities().then(
      (capabilities) => {
        if (startup?.owner === owner) startup = null;
        completeOperation(owner, {
          capabilities,
          failure: null,
          failureOperation: null,
        });
      },
      (error: unknown) => {
        if (startup?.owner === owner) startup = null;
        if (activeOperation !== owner) return;
        if (!(error instanceof CoreFailure)) {
          completeOperation(owner);
          throw error;
        }
        completeOperation(owner, {
          failure: error,
          failureOperation: "capabilities",
        });
      },
    );
    startup = { owner, promise };
    return promise;
  }

  async function openSource(source: StructureSource): Promise<void> {
    const capabilities = store.getState().capabilities;
    if (capabilities === null) return;
    const owner = beginOperation("inspect");
    store.setState({ attemptedSource: source });
    try {
      const inspection = await core.inspectStructure(source);
      if (activeOperation !== owner) return;
      draftRevision = 0;
      completeOperation(owner, {
        source,
        attemptedSource: null,
        inspection,
        draft: {
          structure: source,
          intent: { ...capabilities.default_intent },
          hints: { ...capabilities.default_hints },
        },
        reviewed: null,
        outOfDate: false,
        lastDownload: null,
        downloadOutOfDate: false,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (activeOperation !== owner) return;
      if (!(error instanceof CoreFailure)) {
        completeOperation(owner);
        throw error;
      }
      completeOperation(owner, {
        failure: error,
        failureOperation: "inspect",
      });
    }
  }

  function patchDraft(
    action: Extract<WorkspaceAction, { type: "draft.patch" }>,
  ): void {
    const snapshot = store.getState();
    const currentDraft = snapshot.draft;
    if (
      currentDraft?.intent === null ||
      currentDraft?.intent === undefined ||
      currentDraft.hints === null ||
      currentDraft.hints === undefined ||
      snapshot.operation === "inspect"
    ) {
      return;
    }
    draftRevision += 1;
    const draft: CalculationDraft = {
      ...currentDraft,
      intent: { ...currentDraft.intent, ...action.intent },
      hints: { ...currentDraft.hints, ...action.hints },
      ...("pseudoTable" in action
        ? { pseudo_table: action.pseudoTable }
        : {}),
    };
    store.setState({
      draft,
      outOfDate: snapshot.reviewed !== null,
      downloadOutOfDate: snapshot.lastDownload !== null,
      failure: null,
      failureOperation: null,
    });
  }

  async function computeReview(): Promise<void> {
    const snapshot = store.getState();
    if (snapshot.draft === null || snapshot.operation !== null) return;
    const revision = draftRevision;
    const submittedDraft = snapshot.draft;
    const owner = beginOperation("compute");
    try {
      const result = await core.compute(
        {
          draft: submittedDraft,
          selection: { preset: "generate" },
        },
        { kind: "memory" },
      );
      completeOperation(owner, {
        reviewed: { draft: submittedDraft, result },
        outOfDate: revision !== draftRevision,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (activeOperation !== owner) return;
      if (!(error instanceof CoreFailure)) {
        completeOperation(owner);
        throw error;
      }
      completeOperation(owner, {
        failure: error,
        failureOperation: "compute",
      });
    }
  }

  async function downloadReviewed(): Promise<void> {
    const snapshot = store.getState();
    if (
      snapshot.reviewed === null ||
      snapshot.outOfDate ||
      snapshot.operation !== null
    ) {
      return;
    }
    const revision = draftRevision;
    const reviewedDraft = snapshot.reviewed.draft;
    const owner = beginOperation("download");
    try {
      const archive = await core.compute(
        {
          draft: reviewedDraft,
          selection: { preset: "generate" },
        },
        { kind: "archive" },
      );
      if (activeOperation !== owner) return;
      if (revision !== draftRevision) {
        completeOperation(owner);
        return;
      }
      completeOperation(owner, {
        lastDownload: archive,
        downloadOutOfDate: false,
        failure: null,
        failureOperation: null,
      });
      saveArchive(archive);
    } catch (error) {
      if (activeOperation !== owner) return;
      if (revision !== draftRevision) {
        completeOperation(owner);
        return;
      }
      if (!(error instanceof CoreFailure)) {
        completeOperation(owner);
        throw error;
      }
      completeOperation(owner, {
        failure: error,
        failureOperation: "download",
      });
    }
  }

  async function dispatch(action: WorkspaceAction): Promise<void> {
    switch (action.type) {
      case "workspace.start":
        await start();
        return;
      case "source.open":
        await openSource(action.source);
        return;
      case "draft.patch":
        patchDraft(action);
        return;
      case "review.compute":
        await computeReview();
        return;
      case "review.download":
        await downloadReviewed();
        return;
      case "failure.retry": {
        const snapshot = store.getState();
        switch (snapshot.failureOperation) {
          case "capabilities":
            await start();
            return;
          case "inspect":
            if (snapshot.attemptedSource !== null) {
              await openSource(snapshot.attemptedSource);
            }
            return;
          case "compute":
            await computeReview();
            return;
          case "download":
            await downloadReviewed();
            return;
          case null:
            return;
        }
        return;
      }
      case "failure.dismiss":
        if (store.getState().capabilities === null) return;
        store.setState({
          attemptedSource: null,
          failure: null,
          failureOperation: null,
        });
        return;
      case "workspace.reset": {
        const capabilities = store.getState().capabilities;
        const pendingStartup =
          startup !== null && activeOperation === startup.owner ? startup : null;
        draftRevision = 0;
        if (pendingStartup === null) {
          activeOperation = null;
          startup = null;
        }
        store.setState(
          {
            ...EMPTY_SNAPSHOT,
            capabilities,
            operation: pendingStartup?.owner.operation ?? null,
          },
          true,
        );
        if (capabilities === null && pendingStartup === null) await start();
        return;
      }
    }
  }

  return {
    getSnapshot: store.getState,
    subscribe(listener): () => void {
      return store.subscribe(listener);
    },
    dispatch,
  };
}

export function saveArchiveToBrowser(archive: ArchiveDownload): void {
  const url = URL.createObjectURL(archive.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = archive.filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
