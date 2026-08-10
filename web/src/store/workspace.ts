// The tab-lifetime Workspace store.
//
// A vanilla Zustand store with narrow domain actions and selectors. It owns the
// operation state machines, stale-state semantics, and operation-local
// failures. Modules interact through actions and state selectors only; the
// store never exposes unrestricted `setState` to callers. It is deliberately
// framework-independent (imports only `zustand/vanilla`) so it can be unit
// tested without React.

import { createStore, type StoreApi } from 'zustand/vanilla';
import type { CoreClient } from '../client/CoreClient';
import { toCoreFailure, type CoreFailure } from '../client/failures';
import type {
  ComputationRequest,
  GeneratedInputSet,
  Hints,
  Intent,
  RecordName,
  RecordSet,
  Recommendation,
  StructureDocument,
  StructureSource,
  TaskCatalogue,
} from '../client/types';

/** Honest operation state. `running` reflects an in-flight request only; it
 * never claims backend work stopped when a browser wait is cancelled. */
export type OpStatus = 'idle' | 'running' | 'complete' | 'failed';

export const DEFAULT_INTENT: Intent = {
  code: 'quantum_espresso',
  task: 'scf_single_point',
  functional: 'PBEsol',
  pseudo_mode: 'efficiency',
};

export const DEFAULT_HINTS: Hints = {};

export interface WorkspaceState {
  // Structure
  source: StructureSource | null;
  structureStatus: OpStatus;
  structure: StructureDocument | null;
  structureFailure: CoreFailure | null;

  // Calculation request (editable)
  intent: Intent;
  hints: Hints;

  // Recommendation records
  recordsStatus: OpStatus;
  records: Recommendation | null;
  recordsFailure: CoreFailure | null;
  recordsStale: boolean;

  // Generated input archive data
  generationStatus: OpStatus;
  generated: GeneratedInputSet | null;
  generationFailure: CoreFailure | null;
  generatedStale: boolean;

  // Task catalogue (backend-owned graph topology)
  catalogueStatus: OpStatus;
  catalogue: TaskCatalogue | null;
  catalogueFailure: CoreFailure | null;

  // Graph view: explicit output-record selection and execution
  selectedRecordIds: RecordName[];
  graphStatus: OpStatus;
  graphRecords: RecordSet | null;
  graphFailure: CoreFailure | null;
  graphStale: boolean;

  // Actions
  loadStructure(source: StructureSource): Promise<void>;
  recommend(): Promise<void>;
  generate(): Promise<void>;
  setIntent(patch: Partial<Intent>): void;
  setHints(patch: Partial<Hints>): void;
  loadTaskCatalogue(): Promise<void>;
  setSelectedRecords(ids: RecordName[]): void;
  runSelectedRecords(): Promise<void>;
}

/** The store as exposed to the app: state access, selectors, and the narrow
 * action set. `setState` is deliberately removed so no caller can mutate the
 * store outside the transition rules the actions encode. */
export type WorkspaceStore = Omit<StoreApi<WorkspaceState>, 'setState'>;

function requestFor(
  source: StructureSource,
  intent: Intent,
  hints: Hints,
): ComputationRequest {
  return {
    structure: { content: source.content, format: source.format },
    intent,
    hints,
  };
}

export function createWorkspaceStore(client: CoreClient): WorkspaceStore {
  // Monotonic generation counter for the editable request inputs (Intent,
  // Hints, and the loaded structure). Captured at the start of an in-flight
  // request, it lets a completing request detect that inputs changed while it
  // was running, so it never marks results fresh for a request that no longer
  // matches the current inputs. It is a closure, not state: no selector reads
  // it and it never triggers renders.
  let requestRevision = 0;

  return createStore<WorkspaceState>()((set, get) => ({
    source: null,
    structureStatus: 'idle',
    structure: null,
    structureFailure: null,

    intent: { ...DEFAULT_INTENT },
    hints: {},

    recordsStatus: 'idle',
    records: null,
    recordsFailure: null,
    recordsStale: false,

    generationStatus: 'idle',
    generated: null,
    generationFailure: null,
    generatedStale: false,

    catalogueStatus: 'idle',
    catalogue: null,
    catalogueFailure: null,

    selectedRecordIds: [],
    graphStatus: 'idle',
    graphRecords: null,
    graphFailure: null,
    graphStale: false,

    loadStructure: async (source) => {
      // A running load keeps the previous (structure, source, records,
      // generated) pair untouched until it succeeds; a failure must never
      // overwrite `source` with content that does not match the structure and
      // results still shown.
      set({ structureStatus: 'running', structureFailure: null });
      try {
        const structure = await client.loadStructure(source);
        // A new structure invalidates every prior result outright: records and
        // generated output describe the old structure and cannot apply.
        requestRevision += 1;
        set({
          source,
          structure,
          structureStatus: 'complete',
          structureFailure: null,
          records: null,
          recordsStatus: 'idle',
          recordsFailure: null,
          recordsStale: false,
          generated: null,
          generationStatus: 'idle',
          generationFailure: null,
          generatedStale: false,
          // Graph results describe the old structure and cannot apply. The
          // record selection is a query preference and survives the change.
          graphRecords: null,
          graphStatus: 'idle',
          graphFailure: null,
          graphStale: false,
        });
      } catch (error) {
        set({ structureStatus: 'failed', structureFailure: toCoreFailure(error) });
      }
    },

    setIntent: (patch) => {
      requestRevision += 1;
      set((state) => ({
        intent: { ...state.intent, ...patch },
        recordsStale: state.records !== null,
        generatedStale: state.generated !== null,
        graphStale: state.graphRecords !== null,
      }));
    },

    setHints: (patch) => {
      requestRevision += 1;
      set((state) => ({
        hints: { ...state.hints, ...patch },
        recordsStale: state.records !== null,
        generatedStale: state.generated !== null,
        graphStale: state.graphRecords !== null,
      }));
    },

    recommend: async () => {
      const state = get();
      const source = state.source;
      if (!state.structure || !source) return;
      // Keep prior records visible until replacement succeeds; a fresh request
      // replaces them only on success.
      const revisionAtStart = requestRevision;
      set({ recordsStatus: 'running', recordsFailure: null });
      try {
        const records = await client.recommend(
          requestFor(source, state.intent, state.hints),
        );
        set({
          records,
          recordsStatus: 'complete',
          recordsFailure: null,
          // Only clear the stale flag if no override/structure load happened
          // while the request was in flight; otherwise the results describe
          // inputs that no longer match the workspace.
          recordsStale: requestRevision !== revisionAtStart,
        });
      } catch (error) {
        set({ recordsStatus: 'failed', recordsFailure: toCoreFailure(error) });
      }
    },

    generate: async () => {
      const state = get();
      const source = state.source;
      if (!state.structure || !source) return;
      const revisionAtStart = requestRevision;
      set({ generationStatus: 'running', generationFailure: null });
      try {
        const generated = await client.generate(
          requestFor(source, state.intent, state.hints),
        );
        set({
          generated,
          generationStatus: 'complete',
          generationFailure: null,
          generatedStale: requestRevision !== revisionAtStart,
        });
      } catch (error) {
        set({ generationStatus: 'failed', generationFailure: toCoreFailure(error) });
      }
    },

    loadTaskCatalogue: async () => {
      set({ catalogueStatus: 'running', catalogueFailure: null });
      try {
        const catalogue = await client.describeTasks();
        set({ catalogue, catalogueStatus: 'complete', catalogueFailure: null });
      } catch (error) {
        set({ catalogueStatus: 'failed', catalogueFailure: toCoreFailure(error) });
      }
    },

    setSelectedRecords: (ids) => {
      set((state) => ({
        selectedRecordIds: [...ids],
        // A different selection means prior results describe a different query.
        graphStale: state.graphRecords !== null,
      }));
    },

    runSelectedRecords: async () => {
      const state = get();
      const source = state.source;
      if (!state.structure || !source) return;
      if (state.selectedRecordIds.length === 0) return;
      const revisionAtStart = requestRevision;
      set({ graphStatus: 'running', graphFailure: null });
      try {
        const result = await client.compute({
          structure: { content: source.content, format: source.format },
          outputs: state.selectedRecordIds,
          intent: state.intent,
          hints: state.hints,
        });
        set({
          graphRecords: result,
          graphStatus: 'complete',
          graphFailure: null,
          graphStale: requestRevision !== revisionAtStart,
        });
      } catch (error) {
        set({ graphStatus: 'failed', graphFailure: toCoreFailure(error) });
      }
    },
  }));
}
