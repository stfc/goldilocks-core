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
  let startup: Promise<void> | null = null;
  let sourceEpoch = 0;
  let draftRevision = 0;

  function start(): Promise<void> {
    if (store.getState().capabilities !== null) return Promise.resolve();
    if (startup !== null) return startup;
    const epoch = sourceEpoch;
    store.setState({
      operation: "capabilities",
      failure: null,
      failureOperation: null,
    });
    startup = core.capabilities().then(
      (capabilities) => {
        if (epoch !== sourceEpoch) return;
        store.setState({
          capabilities,
          operation: null,
          failure: null,
          failureOperation: null,
        });
      },
      (error: unknown) => {
        startup = null;
        if (epoch !== sourceEpoch) return;
        if (!(error instanceof CoreFailure)) {
          store.setState({ operation: null });
          throw error;
        }
        store.setState({
          operation: null,
          failure: error,
          failureOperation: "capabilities",
        });
      },
    );
    return startup;
  }

  async function openSource(source: StructureSource): Promise<void> {
    const capabilities = store.getState().capabilities;
    if (capabilities === null) return;
    sourceEpoch += 1;
    const epoch = sourceEpoch;
    store.setState({
      attemptedSource: source,
      operation: "inspect",
      failure: null,
      failureOperation: null,
    });
    try {
      const inspection = await core.inspectStructure(source);
      if (epoch !== sourceEpoch) return;
      draftRevision = 0;
      store.setState({
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
        operation: null,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (epoch !== sourceEpoch) return;
      if (!(error instanceof CoreFailure)) {
        store.setState({ operation: null });
        throw error;
      }
      store.setState({
        operation: null,
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
    const epoch = sourceEpoch;
    const revision = draftRevision;
    const submittedDraft = snapshot.draft;
    store.setState({
      operation: "compute",
      failure: null,
      failureOperation: null,
    });
    try {
      const result = await core.compute(
        {
          draft: submittedDraft,
          selection: { preset: "generate" },
        },
        { kind: "memory" },
      );
      if (epoch !== sourceEpoch) return;
      store.setState({
        reviewed: { draft: submittedDraft, result },
        outOfDate: revision !== draftRevision,
        operation: null,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (epoch !== sourceEpoch) return;
      if (!(error instanceof CoreFailure)) {
        store.setState({ operation: null });
        throw error;
      }
      store.setState({
        operation: null,
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
    const epoch = sourceEpoch;
    const revision = draftRevision;
    const reviewedDraft = snapshot.reviewed.draft;
    store.setState({
      operation: "download",
      failure: null,
      failureOperation: null,
    });
    try {
      const archive = await core.compute(
        {
          draft: reviewedDraft,
          selection: { preset: "generate" },
        },
        { kind: "archive" },
      );
      if (epoch !== sourceEpoch || revision !== draftRevision) {
        store.setState({ operation: null });
        return;
      }
      store.setState({
        lastDownload: archive,
        downloadOutOfDate: false,
        operation: null,
        failure: null,
        failureOperation: null,
      });
      saveArchive(archive);
    } catch (error) {
      if (epoch !== sourceEpoch || revision !== draftRevision) {
        store.setState({ operation: null });
        return;
      }
      if (!(error instanceof CoreFailure)) {
        store.setState({ operation: null });
        throw error;
      }
      store.setState({
        operation: null,
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
        store.setState({
          attemptedSource: null,
          failure: null,
          failureOperation: null,
        });
        return;
      case "workspace.reset":
        sourceEpoch += 1;
        draftRevision = 0;
        startup = null;
        store.setState(EMPTY_SNAPSHOT, true);
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
