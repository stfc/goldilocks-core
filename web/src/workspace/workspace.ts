import { createStore } from "zustand/vanilla";

import type {
  ArchiveDownload,
  CalculationDraft,
  Capabilities,
  CoreClient,
  PreparedComputation,
  StructureInspection,
  StructureSource,
} from "../api/coreClient";
import { CoreFailure } from "../api/coreClient";

export type WorkspaceOperation = "capabilities" | "inspect" | "compute";

export interface WorkspaceSnapshot {
  readonly capabilities: Capabilities | null;
  readonly source: StructureSource | null;
  readonly attemptedSource: StructureSource | null;
  readonly inspection: StructureInspection | null;
  readonly draft: CalculationDraft | null;
  readonly reviewed: PreparedComputation | null;
  readonly outOfDate: boolean;
  readonly lastDownload: ArchiveDownload | null;
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
  ): void {
    if (activeOperation !== owner) return;
    activeOperation = null;
    store.setState({ ...update, operation: null });
  }

  function failOperation(owner: OperationOwner, error: unknown): void {
    if (activeOperation !== owner) return;
    if (!(error instanceof CoreFailure)) {
      completeOperation(owner);
      throw error;
    }
    completeOperation(owner, {
      failure: error,
      failureOperation: owner.operation,
    });
  }

  function start(): Promise<void> {
    if (store.getState().capabilities !== null) return Promise.resolve();
    if (startup !== null) return startup.promise;
    const owner = beginOperation("capabilities");
    const promise = core.capabilities().then(
      (capabilities) => {
        if (startup?.owner === owner) startup = null;
        completeOperation(owner, { capabilities });
      },
      (error: unknown) => {
        if (startup?.owner === owner) startup = null;
        failOperation(owner, error);
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
          intent: capabilities.default_intent,
          hints: capabilities.default_hints,
        },
        reviewed: null,
        outOfDate: false,
        lastDownload: null,
      });
    } catch (error) {
      failOperation(owner, error);
    }
  }

  function patchDraft(
    action: Extract<WorkspaceAction, { type: "draft.patch" }>,
  ): void {
    const snapshot = store.getState();
    const currentDraft = snapshot.draft;
    if (
      !currentDraft?.intent ||
      !currentDraft.hints ||
      snapshot.operation === "inspect"
    ) {
      return;
    }
    draftRevision += 1;
    const draft: CalculationDraft = {
      ...currentDraft,
      intent: { ...currentDraft.intent, ...action.intent },
      hints: { ...currentDraft.hints, ...action.hints },
      ...("pseudoTable" in action ? { pseudo_table: action.pseudoTable } : {}),
    };
    store.setState({
      draft,
      outOfDate: snapshot.reviewed !== null,
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
      const prepared = await core.compute({
        draft: submittedDraft,
        selection: { preset: "generate" },
      });
      completeOperation(owner, {
        reviewed: prepared,
        outOfDate: revision !== draftRevision,
        lastDownload: null,
      });
    } catch (error) {
      failOperation(owner, error);
    }
  }

  function downloadReviewed(): void {
    const snapshot = store.getState();
    const archive = snapshot.reviewed?.archive;
    if (!archive || snapshot.outOfDate) return;
    store.setState({ lastDownload: archive });
    saveArchive(archive);
  }

  async function retryFailure(): Promise<void> {
    const { failureOperation, attemptedSource } = store.getState();
    switch (failureOperation) {
      case "capabilities":
        return start();
      case "inspect":
        if (attemptedSource !== null) await openSource(attemptedSource);
        return;
      case "compute":
        return computeReview();
      case null:
        return;
    }
  }

  async function reset(): Promise<void> {
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
        downloadReviewed();
        return;
      case "failure.retry":
        return retryFailure();
      case "failure.dismiss":
        if (store.getState().capabilities === null) return;
        store.setState({
          attemptedSource: null,
          failure: null,
          failureOperation: null,
        });
        return;
      case "workspace.reset":
        return reset();
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
