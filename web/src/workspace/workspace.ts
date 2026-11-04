import { createStore } from "zustand/vanilla";

import type {
  ArchiveDownload,
  CalcTask,
  Capabilities,
  ComputeRequest,
  CoreClient,
  ExplainResult,
  MagneticOrderingsRequest,
  MagneticOrderingsResult,
  StructureInput,
  StructureInspection,
} from "../api/coreClient";
import { CoreFailure } from "../api/coreClient";
import {
  currentArchive,
  explainDue,
  previewDue,
  recordedFailure,
} from "./pipelineStatus";

/** The Core request in flight. `preview` is the automatic `/run` that fetches
 * the current draft's archive; saving a file is not an operation, since
 * `review.download` only saves an archive already fetched. */
export type WorkspaceOperation =
  "capabilities" | "inspect" | "explain" | "preview";

/** Independent of `WorkspaceOperation`: listing/ranking/downloading
 * magnetic-ordering candidates is an opt-in side-quest a user runs from
 * the Advisors card, not the main structure -> compute -> download
 * pipeline -- it must not disable the rest of that pipeline's controls
 * (or vice versa) while in flight. One nullable field, same idiom as
 * `WorkspaceOperation` itself, covering its own three concerns. */
export type MagneticOrderingsOperation = "list" | "rank" | "download";

/** A magnetic-ordering listing and the structure it was requested for.
 * `result`, `error` and the request in flight (`operation`) belong to
 * `input` alone: read them through `currentOrderings`, which returns the
 * listing only while `input` is the open structure, and candidate bundles
 * take their structure and name from `input` (#149). */
export interface MagneticOrderingsListing {
  readonly input: StructureInput;
  readonly operation: MagneticOrderingsOperation | null;
  /** The last listing or ranking that arrived; kept while a new request
   * for the same structure runs. */
  readonly result: MagneticOrderingsResult | null;
  /** Shown inline in the Magnetic Orderings card, not the global
   * `FailureBanner` -- this is a side-quest failure, not a reason to
   * block the main pipeline the banner exists for. Not re-sent on its
   * own: the card lists a structure only when it has no listing, or when
   * the user presses its Retry listing. */
  readonly error: string | null;
}

/** The v2 request shape has no `intent`/`hints` vocabulary: every tunable
 * knob is a flat `overrides` entry reflected from `capabilities().settings`/
 * `.facts` (see `capabilities.py`'s own "add an advisor, its settings
 * automatically appear" design goal). A key's absence from `overrides`
 * means "let the heuristic/ml/llm chain decide" -- there is no separate
 * "automatic" sentinel value, matching `--set`'s own semantics. Opening
 * another structure keeps the draft except the overrides that describe the
 * structure it replaces (`carryOverDraft`, #188). */
export interface CalculationDraft {
  readonly code: string;
  readonly task: CalcTask;
  readonly hpc: string | null;
  readonly overrides: Readonly<Record<string, unknown>>;
  readonly fetchMissing: boolean;
}

/** The open structure and draft revision an `/explain` or preview `/run`
 * was sent for. A revision never repeats within a workspace, so neither
 * does a key. */
export interface PipelineKey {
  readonly input: StructureInput;
  readonly revision: number;
}

/** How the request sent for `key` settled. A failure stays the outcome of
 * its key: nothing sends that request again until the key changes or
 * `failure.retry` clears it, and `dismissed` only hides it from the banner
 * (#150). Read the current draft's outcomes through `pipelineStatus.ts`. */
export type PipelineOutcome<T> =
  | { readonly key: PipelineKey; readonly status: "result"; readonly value: T }
  | {
      readonly key: PipelineKey;
      readonly status: "failure";
      readonly failure: CoreFailure;
      readonly dismissed: boolean;
    };

/** A structure that could not be opened, and why. The open structure, if
 * any, stays open. */
export interface InspectFailure {
  readonly input: StructureInput;
  readonly failure: CoreFailure;
}

export interface WorkspaceSnapshot {
  readonly capabilities: Capabilities | null;
  /** Why loading capabilities failed; cleared when they are requested
   * again. */
  readonly startupFailure: CoreFailure | null;
  readonly structureInput: StructureInput | null;
  readonly inspection: StructureInspection | null;
  /** The last structure that failed to open; cleared by the next open,
   * Dismiss or Retry. */
  readonly inspectFailure: InspectFailure | null;
  readonly draft: CalculationDraft | null;
  /** The override keys cleared from the draft when the open structure was
   * opened, in draft order: structure-specific settings and facts, which
   * described the structure it replaced (`carryOverDraft`, #188). Empty
   * before the first structure opens and after reset; a structure that
   * fails to open changes nothing. */
  readonly clearedOverrides: readonly string[];
  /** Counts every opened structure and every draft change for the
   * workspace's lifetime and is never reset, so every `PipelineKey` is
   * new, even when an embedder opens the same `StructureInput` again. */
  readonly revision: number;
  /** The last `/explain` result for the open structure -- records, warnings
   * and the `blocking` verdict, no files. It stays on screen while a later
   * revision is recomputed or after that revision's `/explain` failed, and
   * is the current draft's only while `currentExplain` holds it.
   * `/explain` never calls `generate()`, so it succeeds even when a `/run`
   * would refuse with `advice_incomplete`, and `blocking` then lists the
   * reasons; no preview `/run` is sent for such a draft. */
  readonly reviewed: ExplainResult | null;
  /** How the last `/explain` settled; see `currentExplain`. */
  readonly explain: PipelineOutcome<ExplainResult> | null;
  /** How the last preview `/run` settled; see `currentPreview` and
   * `currentArchive`. */
  readonly preview: PipelineOutcome<ArchiveDownload> | null;
  readonly operation: WorkspaceOperation | null;
  /** Read through `currentOrderings`. */
  readonly magneticOrderings: MagneticOrderingsListing | null;
}

export type WorkspaceAction =
  | { readonly type: "workspace.start" }
  /** Inspects `input` and, once it parses, makes it the open structure,
   * with the draft carried over (`carryOverDraft`) and the outcomes and
   * listing of the structure it replaces dropped. */
  | { readonly type: "source.open"; readonly input: StructureInput }
  | {
      readonly type: "draft.patch";
      readonly code?: string;
      readonly task?: CalcTask;
      readonly hpc?: string | null;
      /** Shallow-merged into the current overrides. A value of
       * `undefined` clears that key back to "automatic" rather than
       * setting it to `undefined` on the wire. */
      readonly overrides?: Readonly<Record<string, unknown>>;
    }
  /** Sends the current draft's `/explain` when it is due (`explainDue`):
   * not while a request is in flight, and not once the draft has an
   * outcome, a failure included. */
  | { readonly type: "review.compute" }
  /** Fetches the current draft's archive for the live preview without
   * saving it, once its recommendation arrived with no blocking reason and
   * while no preview has settled for it (`previewDue`) -- the auto-preview
   * effect calls this, not a user action. */
  | { readonly type: "review.refreshArchive" }
  /** Saves the current draft's archive (`currentArchive`) through the
   * archive sink. Sends no request: with no current archive it does
   * nothing, so a file is only ever saved by this explicit action. */
  | { readonly type: "review.download" }
  | { readonly type: "magneticOrderings.list" }
  | { readonly type: "magneticOrderings.rank" }
  | {
      readonly type: "magneticOrderings.downloadSelected";
      readonly labels: readonly string[];
    }
  /** Clears the failure recorded for `operation` and sends that request
   * again, once. */
  | { readonly type: "failure.retry"; readonly operation: WorkspaceOperation }
  /** Hides the failure recorded for `operation` from the banner without
   * sending anything; an `/explain` or preview failure stays its draft's
   * outcome. A capabilities failure cannot be dismissed. */
  | {
      readonly type: "failure.dismiss";
      readonly operation: WorkspaceOperation;
    }
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
  startupFailure: null,
  structureInput: null,
  inspection: null,
  inspectFailure: null,
  draft: null,
  clearedOverrides: [],
  revision: 0,
  reviewed: null,
  explain: null,
  preview: null,
  operation: null,
  magneticOrderings: null,
};

function defaultDraft(capabilities: Capabilities): CalculationDraft {
  return {
    code: capabilities.codes[0]?.id ?? "quantum_espresso",
    task:
      (capabilities.tasks[0]?.id as CalcTask | undefined) ?? "scf_single_point",
    hpc: null,
    overrides: {},
    fetchMissing: false,
  };
}

/** The draft for a newly opened structure: `previous` with the code, task,
 * HPC profile and `fetchMissing` kept, and only the overrides of settings
 * that `capabilities` marks not `structure_specific` (#188). The other
 * overrides are cleared and listed in `cleared`, in draft order: those of
 * structure-specific settings, of facts (judgements about the structure by
 * definition) and of any key that is not a setting. */
function carryOverDraft(
  previous: CalculationDraft,
  capabilities: Capabilities,
): { readonly draft: CalculationDraft; readonly cleared: readonly string[] } {
  const kept = new Set(
    capabilities.settings
      .filter((setting) => !setting.structure_specific)
      .map((setting) => setting.key),
  );
  const entries = Object.entries(previous.overrides);
  return {
    draft: {
      ...previous,
      overrides: Object.fromEntries(entries.filter(([key]) => kept.has(key))),
    },
    cleared: entries.map(([key]) => key).filter((key) => !kept.has(key)),
  };
}

/** The request for `draft`. An override of a setting that does not apply
 * to the draft's task is left out, since the core refuses it (#154); the
 * draft keeps it, so switching back to a task it applies to sends it again.
 * A key that is not a setting (a fact such as `is_metal`) is always sent. */
function toComputeRequest(
  capabilities: Capabilities,
  structureInput: StructureInput,
  draft: CalculationDraft,
): ComputeRequest {
  const settings = new Map(
    capabilities.settings.map((setting) => [setting.key, setting]),
  );
  const overrides = Object.fromEntries(
    Object.entries(draft.overrides).filter(
      ([key]) => settings.get(key)?.tasks.includes(draft.task) ?? true,
    ),
  );
  return {
    structure_content: structureInput.structure_content,
    structure_name: structureInput.structure_name,
    ...(structureInput.structure_format
      ? { structure_format: structureInput.structure_format }
      : {}),
    code: draft.code,
    task: draft.task,
    hpc: draft.hpc,
    overrides,
    fetch_missing: draft.fetchMissing,
  };
}

function toMagneticOrderingsRequest(
  structureInput: StructureInput,
  rankWithMmace: boolean,
): MagneticOrderingsRequest {
  return {
    structure_content: structureInput.structure_content,
    structure_name: structureInput.structure_name,
    ...(structureInput.structure_format
      ? { structure_format: structureInput.structure_format }
      : {}),
    rank_with_mmace: rankWithMmace,
  };
}

function mergeOverrides(
  current: Readonly<Record<string, unknown>>,
  patch: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  const merged = { ...current, ...patch };
  return Object.fromEntries(
    Object.entries(merged).filter(([, value]) => value !== undefined),
  );
}

/** `outcome` with its failure hidden from the banner. */
function dismissed<T>(
  outcome: PipelineOutcome<T> | null,
): PipelineOutcome<T> | null {
  return outcome?.status === "failure"
    ? { ...outcome, dismissed: true }
    : outcome;
}

/** The magnetic-ordering listing of the open structure, or null when it
 * has none (nothing requested yet, or the listing belongs to another
 * structure). The card lists the open structure whenever this is null. */
export function currentOrderings(
  snapshot: WorkspaceSnapshot,
): MagneticOrderingsListing | null {
  const listing = snapshot.magneticOrderings;
  return listing?.input === snapshot.structureInput ? listing : null;
}

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
  // Aborts the listing request in flight; only the open structure's
  // listing can be in flight, since opening another structure aborts it.
  let orderingsRequest: AbortController | null = null;

  function beginOperation(
    operation: WorkspaceOperation,
    update: Partial<WorkspaceSnapshot> = {},
  ): OperationOwner {
    const owner = { operation };
    activeOperation = owner;
    store.setState({ ...update, operation });
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

  /** Settles `owner` with the fields `record` makes of a `CoreFailure`;
   * any other error propagates once `owner` is no longer busy. */
  function failOperation(
    owner: OperationOwner,
    error: unknown,
    record: (failure: CoreFailure) => Partial<WorkspaceSnapshot>,
  ): void {
    if (activeOperation !== owner) return;
    if (!(error instanceof CoreFailure)) {
      completeOperation(owner);
      throw error;
    }
    completeOperation(owner, record(error));
  }

  function start(): Promise<void> {
    if (store.getState().capabilities !== null) return Promise.resolve();
    if (startup !== null) return startup.promise;
    const owner = beginOperation("capabilities", { startupFailure: null });
    const promise = core.capabilities().then(
      (capabilities) => {
        if (startup?.owner === owner) startup = null;
        completeOperation(owner, {
          capabilities,
          draft: defaultDraft(capabilities),
        });
      },
      (error: unknown) => {
        if (startup?.owner === owner) startup = null;
        failOperation(owner, error, (failure) => ({ startupFailure: failure }));
      },
    );
    startup = { owner, promise };
    return promise;
  }

  async function openSource(input: StructureInput): Promise<void> {
    const capabilities = store.getState().capabilities;
    if (capabilities === null) return;
    // A new attempt replaces the last structure that failed to open.
    const owner = beginOperation("inspect", { inspectFailure: null });
    try {
      const inspection = await core.inspectStructure(input);
      if (activeOperation !== owner) return;
      // Only now is the open structure replaced: an inspection that fails
      // leaves it, its draft, its outcomes and the listing request in flight
      // for it in place. The draft is null only after reset.
      abortOrderingsRequest();
      const { draft, cleared } = carryOverDraft(
        store.getState().draft ?? defaultDraft(capabilities),
        capabilities,
      );
      completeOperation(owner, {
        structureInput: input,
        inspection,
        draft,
        clearedOverrides: cleared,
        revision: store.getState().revision + 1,
        reviewed: null,
        explain: null,
        preview: null,
        magneticOrderings: null,
      });
    } catch (error) {
      failOperation(owner, error, (failure) => ({
        inspectFailure: { input, failure },
      }));
    }
  }

  function patchDraft(
    action: Extract<WorkspaceAction, { type: "draft.patch" }>,
  ): void {
    const snapshot = store.getState();
    const currentDraft = snapshot.draft;
    if (currentDraft === null || snapshot.operation === "inspect") return;
    const draft: CalculationDraft = {
      ...currentDraft,
      ...("code" in action ? { code: action.code } : {}),
      ...("task" in action ? { task: action.task } : {}),
      ...("hpc" in action ? { hpc: action.hpc } : {}),
      overrides:
        action.overrides === undefined
          ? currentDraft.overrides
          : mergeOverrides(currentDraft.overrides, action.overrides),
    };
    store.setState({ draft, revision: snapshot.revision + 1 });
  }

  /** Sends `operation`'s request for the current draft when `due` says it
   * is due, and records how it settled against the key it was sent for --
   * a result or a `CoreFailure` alike, so the same request is not sent
   * again for that key. */
  async function settleForCurrentDraft<T>(
    operation: "explain" | "preview",
    due: (snapshot: WorkspaceSnapshot) => boolean,
    send: (request: ComputeRequest) => Promise<T>,
    record: (outcome: PipelineOutcome<T>) => Partial<WorkspaceSnapshot>,
  ): Promise<void> {
    const snapshot = store.getState();
    const { capabilities, structureInput, draft, revision } = snapshot;
    if (
      capabilities === null ||
      structureInput === null ||
      draft === null ||
      !due(snapshot)
    ) {
      return;
    }
    const key: PipelineKey = { input: structureInput, revision };
    const request = toComputeRequest(capabilities, structureInput, draft);
    const owner = beginOperation(operation);
    try {
      const value = await send(request);
      completeOperation(owner, record({ key, status: "result", value }));
    } catch (error) {
      failOperation(owner, error, (failure) =>
        record({ key, status: "failure", failure, dismissed: false }),
      );
    }
  }

  /** The `explain` operation. A result that arrives after the draft changed
   * still replaces `reviewed`: it is the latest recommendation, shown as
   * out of date until the current draft's arrives. */
  function computeReview(): Promise<void> {
    return settleForCurrentDraft(
      "explain",
      explainDue,
      (request) => core.explain(request),
      (explain) =>
        explain.status === "result"
          ? { explain, reviewed: explain.value }
          : { explain },
    );
  }

  /** The `preview` operation: fetches the current draft's archive, so
   * `GeneratedInputReview` shows a live preview with no separate "generate"
   * step. Never saves it. The auto-preview effect and Retry after a failed
   * preview call this. */
  function refreshArchive(): Promise<void> {
    return settleForCurrentDraft(
      "preview",
      previewDue,
      (request) => core.runArchive(request),
      (preview) => ({ preview }),
    );
  }

  /** Saves the current archive, the one the preview shows. Fetches nothing:
   * without a current archive there is nothing to save (#189). */
  function downloadReviewed(): void {
    const archive = currentArchive(store.getState());
    if (archive !== null) saveArchive(archive);
  }

  function abortOrderingsRequest(): void {
    orderingsRequest?.abort();
    orderingsRequest = null;
  }

  /** Clears the busy state of the listing `pending` and applies `update`,
   * while `pending` is still the stored listing: the same owner rule as
   * `completeOperation`, so the outcome of a request for a structure that
   * is no longer open (or was reset away) is dropped. */
  function completeOrderings(
    pending: MagneticOrderingsListing,
    update: Partial<Pick<MagneticOrderingsListing, "result" | "error">> = {},
  ): void {
    if (store.getState().magneticOrderings !== pending) return;
    store.setState({
      magneticOrderings: { ...pending, ...update, operation: null },
    });
  }

  /** As `failOperation`: a `CoreFailure` becomes the listing's error, any
   * other error propagates once the listing is no longer busy. */
  function failOrderings(
    pending: MagneticOrderingsListing,
    error: unknown,
  ): void {
    if (store.getState().magneticOrderings !== pending) return;
    if (!(error instanceof CoreFailure)) {
      completeOrderings(pending);
      throw error;
    }
    completeOrderings(pending, { error: error.message });
  }

  /** Lists (or mMACE-ranks) the open structure's candidate orderings.
   * Refused while that structure's listing is busy; a result it already
   * has stays on screen until the new one arrives. */
  async function listMagneticOrderings(rankWithMmace: boolean): Promise<void> {
    const snapshot = store.getState();
    const input = snapshot.structureInput;
    const current = currentOrderings(snapshot);
    if (input === null || (current !== null && current.operation !== null)) {
      return;
    }
    const pending: MagneticOrderingsListing = {
      input,
      operation: rankWithMmace ? "rank" : "list",
      result: current?.result ?? null,
      error: null,
    };
    const request = new AbortController();
    orderingsRequest = request;
    store.setState({ magneticOrderings: pending });
    try {
      const result = await core.magneticOrderings(
        toMagneticOrderingsRequest(input, rankWithMmace),
        request.signal,
      );
      completeOrderings(pending, { result });
    } catch (error) {
      failOrderings(pending, error);
    }
  }

  /** Generates and downloads each selected candidate's DFT input bundle
   * -- one `runArchive` call per candidate, one browser download per
   * archive. A candidate is the listing's own structure (`input`, which
   * also names the bundle) with the draft's overrides plus its own
   * `magnetic_ordering` label (#170), which asks for a spin-polarized
   * run, `fm` included. The draft's `starting_magnetization` is left out
   * of every candidate: it is keyed by the uploaded cell's site labels,
   * which an ordered cell does not have, so each candidate starts from
   * its own ordering's seeds. Archives that arrive after another
   * structure opened are still saved; only the listing's busy state is
   * dropped with it. */
  async function downloadSelectedOrderings(
    labels: readonly string[],
  ): Promise<void> {
    const snapshot = store.getState();
    const { capabilities, draft } = snapshot;
    const listing = currentOrderings(snapshot);
    if (
      capabilities === null ||
      draft === null ||
      listing?.result == null ||
      listing.operation !== null ||
      labels.length === 0
    ) {
      return;
    }
    const { input, result } = listing;
    const pending: MagneticOrderingsListing = {
      ...listing,
      operation: "download",
      error: null,
    };
    store.setState({ magneticOrderings: pending });
    const overrides = Object.fromEntries(
      Object.entries(draft.overrides).filter(
        ([key]) => key !== "starting_magnetization",
      ),
    );
    let archives: readonly ArchiveDownload[];
    try {
      archives = await Promise.all(
        result.candidates
          .filter((candidate) => labels.includes(candidate.label))
          .map((candidate) =>
            core.runArchive({
              ...toComputeRequest(capabilities, input, {
                ...draft,
                overrides: { ...overrides, ...candidate.overrides },
              }),
              structure_name: `${input.structure_name}-${candidate.label}`,
            }),
          ),
      );
    } catch (error) {
      failOrderings(pending, error);
      return;
    }
    completeOrderings(pending);
    for (const archive of archives) saveArchive(archive);
  }

  /** Clears the failure recorded for `operation` and sends that request
   * again, once: an outcome cleared while another request is in flight is
   * sent by the auto effect once that request settles. Does nothing when
   * `operation` has no recorded failure. */
  async function retryFailure(operation: WorkspaceOperation): Promise<void> {
    const snapshot = store.getState();
    if (recordedFailure(snapshot, operation) === null) return;
    switch (operation) {
      case "capabilities":
        await start();
        return;
      case "inspect":
        if (snapshot.inspectFailure !== null) {
          await openSource(snapshot.inspectFailure.input);
        }
        return;
      case "explain":
        store.setState({ explain: null });
        await computeReview();
        return;
      case "preview":
        store.setState({ preview: null });
        await refreshArchive();
        return;
    }
  }

  /** Hides the failure recorded for `operation` from the banner. An
   * `/explain` or preview failure stays its draft's outcome, so nothing is
   * sent again; a structure that failed to open shows nowhere else, so its
   * failure is dropped. A capabilities failure stays, since the Workbench
   * cannot be used without capabilities. */
  function dismissFailure(operation: WorkspaceOperation): void {
    const snapshot = store.getState();
    switch (operation) {
      case "capabilities":
        return;
      case "inspect":
        store.setState({ inspectFailure: null });
        return;
      case "explain":
        store.setState({ explain: dismissed(snapshot.explain) });
        return;
      case "preview":
        store.setState({ preview: dismissed(snapshot.preview) });
        return;
    }
  }

  async function reset(): Promise<void> {
    const { capabilities, revision } = store.getState();
    const pendingStartup =
      startup !== null && activeOperation === startup.owner ? startup : null;
    abortOrderingsRequest();
    if (pendingStartup === null) {
      activeOperation = null;
      startup = null;
    }
    store.setState(
      {
        ...EMPTY_SNAPSHOT,
        capabilities,
        revision,
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
        await openSource(action.input);
        return;
      case "draft.patch":
        patchDraft(action);
        return;
      case "review.compute":
        await computeReview();
        return;
      case "review.refreshArchive":
        await refreshArchive();
        return;
      case "review.download":
        downloadReviewed();
        return;
      case "magneticOrderings.list":
        await listMagneticOrderings(false);
        return;
      case "magneticOrderings.rank":
        await listMagneticOrderings(true);
        return;
      case "magneticOrderings.downloadSelected":
        await downloadSelectedOrderings(action.labels);
        return;
      case "failure.retry":
        return retryFailure(action.operation);
      case "failure.dismiss":
        dismissFailure(action.operation);
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
