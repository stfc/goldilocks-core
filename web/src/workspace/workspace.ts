import { createStore } from "zustand/vanilla";

import type {
  ArchiveDownload,
  GuidedRequest,
  Recommendation,
  StructureInspection,
  StructureSource,
  WorkbenchClient,
} from "../api/workbenchClient";
import { WorkbenchFailure } from "../api/workbenchClient";

type Operation = "inspect" | "review" | "archive";
type Intent = GuidedRequest["intent"];
type Hints = GuidedRequest["hints"];

export interface WorkspaceSnapshot {
  readonly source: StructureSource | null;
  readonly inspection: StructureInspection | null;
  readonly draft: GuidedRequest | null;
  readonly review: Recommendation | null;
  readonly reviewStale: boolean;
  readonly archive: ArchiveDownload | null;
  readonly archiveStale: boolean;
  readonly operation: Operation | null;
  readonly failure: WorkbenchFailure | null;
  readonly failureOperation: Operation | null;
}

export type WorkspaceAction =
  | { readonly type: "source.open"; readonly source: StructureSource }
  | {
      readonly type: "draft.patch";
      readonly intent?: Partial<Intent>;
      readonly hints?: Partial<Hints>;
      readonly pseudoTableId?: string | null;
    }
  | { readonly type: "review.recompute" }
  | { readonly type: "archive.download" }
  | { readonly type: "failure.dismiss" }
  | { readonly type: "failure.retry" }
  | { readonly type: "workspace.reset" };

export interface Workspace {
  getSnapshot(): WorkspaceSnapshot;
  subscribe(listener: () => void): () => void;
  dispatch(action: WorkspaceAction): Promise<void>;
}

type ArchiveSink = (archive: ArchiveDownload) => void;

const EMPTY_SNAPSHOT: WorkspaceSnapshot = {
  source: null,
  inspection: null,
  draft: null,
  review: null,
  reviewStale: false,
  archive: null,
  archiveStale: false,
  operation: null,
  failure: null,
  failureOperation: null,
};

export function createWorkspace(
  client: WorkbenchClient,
  saveArchive: ArchiveSink = saveArchiveToBrowser,
): Workspace {
  const store = createStore<WorkspaceSnapshot>(() => EMPTY_SNAPSHOT);
  let sourceEpoch = 0;
  let draftRevision = 0;

  async function openSource(source: StructureSource): Promise<void> {
    sourceEpoch += 1;
    draftRevision = 0;
    const epoch = sourceEpoch;
    store.setState({
      ...EMPTY_SNAPSHOT,
      source,
      operation: "inspect",
    });
    try {
      const inspection = await client.inspect(source);
      if (epoch !== sourceEpoch) return;
      const draft = initialDraft(source, inspection);
      store.setState({
        source,
        inspection,
        draft,
        review: null,
        reviewStale: false,
        archive: null,
        archiveStale: false,
        operation: null,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (epoch !== sourceEpoch) return;
      if (!(error instanceof WorkbenchFailure)) {
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

  function patchDraft(action: Extract<WorkspaceAction, { type: "draft.patch" }>) {
    const snapshot = store.getState();
    if (
      snapshot.draft === null ||
      snapshot.inspection === null ||
      snapshot.operation === "inspect"
    ) {
      return;
    }
    draftRevision += 1;
    const intent: Intent = { ...snapshot.draft.intent, ...action.intent };
    const compatible = compatibleTables(snapshot.inspection, intent);
    const selectedTable =
      "pseudoTableId" in action
        ? compatible.find((table) => table.id === action.pseudoTableId)
        : compatible.find(
            (table) => table.id === snapshot.draft?.pseudo_table_id,
          ) ?? preferredTable(compatible);
    const draft: GuidedRequest = {
      source: snapshot.draft.source,
      intent,
      hints: { ...snapshot.draft.hints, ...action.hints },
      ...(selectedTable === undefined
        ? {}
        : { pseudo_table_id: selectedTable.id }),
    };
    store.setState({
      draft,
      reviewStale: snapshot.review !== null,
      archiveStale: snapshot.archive !== null,
      failure: null,
      failureOperation: null,
    });
  }

  async function recompute(): Promise<void> {
    const snapshot = store.getState();
    if (snapshot.draft === null || snapshot.operation !== null) return;
    const epoch = sourceEpoch;
    const revision = draftRevision;
    const request = snapshot.draft;
    store.setState({
      operation: "review",
      failure: null,
      failureOperation: null,
    });
    try {
      const review = await client.review(request);
      if (epoch !== sourceEpoch) return;
      const stale = revision !== draftRevision;
      const current = store.getState();
      store.setState({
        review,
        reviewStale: stale,
        archiveStale:
          current.archive === null ||
          current.review?.review_digest === review.review_digest
            ? current.archiveStale
            : true,
        operation: null,
        failure: null,
        failureOperation: null,
      });
    } catch (error) {
      if (epoch !== sourceEpoch) return;
      if (!(error instanceof WorkbenchFailure)) {
        store.setState({ operation: null });
        throw error;
      }
      store.setState({
        operation: null,
        failure: error,
        failureOperation: "review",
      });
    }
  }

  async function downloadArchive(): Promise<void> {
    const snapshot = store.getState();
    if (
      snapshot.draft === null ||
      snapshot.review === null ||
      snapshot.reviewStale ||
      snapshot.operation !== null
    ) {
      return;
    }
    const epoch = sourceEpoch;
    const digest = snapshot.review.review_digest;
    store.setState({
      operation: "archive",
      failure: null,
      failureOperation: null,
    });
    try {
      const archive = await client.archive(snapshot.draft, digest);
      if (epoch !== sourceEpoch) return;
      store.setState({
        archive,
        archiveStale: false,
        operation: null,
        failure: null,
        failureOperation: null,
      });
      saveArchive(archive);
    } catch (error) {
      if (epoch !== sourceEpoch) return;
      if (!(error instanceof WorkbenchFailure)) {
        store.setState({ operation: null });
        throw error;
      }
      store.setState({
        operation: null,
        failure: error,
        failureOperation: "archive",
      });
    }
  }

  async function retryFailure(): Promise<void> {
    const snapshot = store.getState();
    switch (snapshot.failureOperation) {
      case "inspect":
        if (snapshot.source !== null) await openSource(snapshot.source);
        return;
      case "review":
        await recompute();
        return;
      case "archive":
        await downloadArchive();
        return;
      case null:
        return;
    }
  }

  async function dispatch(action: WorkspaceAction): Promise<void> {
    switch (action.type) {
      case "source.open":
        await openSource(action.source);
        return;
      case "draft.patch":
        patchDraft(action);
        return;
      case "review.recompute":
        await recompute();
        return;
      case "archive.download":
        await downloadArchive();
        return;
      case "failure.retry":
        await retryFailure();
        return;
      case "failure.dismiss":
        store.setState({ failure: null, failureOperation: null });
        return;
      case "workspace.reset":
        sourceEpoch += 1;
        draftRevision = 0;
        store.setState(EMPTY_SNAPSHOT, true);
        return;
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

function initialDraft(
  source: StructureSource,
  inspection: StructureInspection,
): GuidedRequest {
  const selected = preferredTable(
    compatibleTables(inspection, inspection.defaults.intent),
  );
  return {
    source,
    intent: inspection.defaults.intent,
    hints: inspection.defaults.hints,
    ...(selected === undefined ? {} : { pseudo_table_id: selected.id }),
  };
}

type PseudoTable = StructureInspection["pseudo_tables"][number];

function compatibleTables(
  inspection: StructureInspection,
  intent: Intent,
): readonly PseudoTable[] {
  const elements = new Set(
    inspection.structure.sites.flatMap((site) =>
      site.species.map((species) => species.symbol),
    ),
  );
  return inspection.pseudo_tables.filter(
    (table) =>
      table.functional === intent.functional &&
      table.accuracy === intent.pseudo_accuracy &&
      [...elements].every((element) => table.elements.includes(element)),
  );
}

function preferredTable(tables: readonly PseudoTable[]): PseudoTable | undefined {
  return tables.find((table) => table.default) ?? tables[0];
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
