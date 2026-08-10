import { describe, expect, it } from 'vitest';
import type { RecordQuery, RecordSet } from '../../client/types';
import { createWorkspaceStore } from '../../store/workspace';
import { FakeCoreClient } from '../mocks/FakeCoreClient';
import { siCif, siRecommendation, siTaskGraph } from '../mocks/fixtures';

const cif = { content: siCif, format: 'cif' as const };

function defer(): { promise: Promise<void>; release: () => void } {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

describe('Workspace store — task catalogue', () => {
  it('loads the backend-owned task catalogue through CoreClient', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    const pending = store.getState().loadTaskCatalogue();
    expect(store.getState().catalogueStatus).toBe('running');
    await pending;
    const state = store.getState();
    expect(state.catalogueStatus).toBe('complete');
    expect(state.catalogueFailure).toBeNull();
    expect(state.catalogue?.tasks[0].id).toBe(siTaskGraph.id);
  });

  it('records a localised catalogue failure and leaves the catalogue empty', async () => {
    const store = createWorkspaceStore(new FakeCoreClient({ failDescribe: true }));
    await store.getState().loadTaskCatalogue();
    const state = store.getState();
    expect(state.catalogueStatus).toBe('failed');
    expect(state.catalogueFailure?.kind).toBe('unavailable');
    expect(state.catalogue).toBeNull();
  });
});

describe('Workspace store — record selection and execution', () => {
  it('toggles the set of selected output records', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    store.getState().setSelectedRecords(['analysis', 'k_points']);
    expect(store.getState().selectedRecordIds).toEqual(['analysis', 'k_points']);
    store.getState().setSelectedRecords(['selection']);
    expect(store.getState().selectedRecordIds).toEqual(['selection']);
  });

  it('runs the selected records through CoreClient.compute and stores results', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    store.getState().setSelectedRecords(['analysis', 'k_points']);

    const pending = store.getState().runSelectedRecords();
    expect(store.getState().graphStatus).toBe('running');
    await pending;

    const state = store.getState();
    expect(state.graphStatus).toBe('complete');
    expect(state.graphFailure).toBeNull();
    expect(state.graphRecords?.analysis).toEqual(siRecommendation.analysis);
    expect(state.graphRecords?.k_points).toEqual(siRecommendation.k_points);
    expect(state.graphRecords?.selection).toBeUndefined();
    // CoreClient was asked for exactly the selected records.
    const queries = client.queries;
    expect(queries[queries.length - 1].outputs).toEqual(['analysis', 'k_points']);
  });

  it('does not run when no structure is loaded', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    store.getState().setSelectedRecords(['analysis']);
    await store.getState().runSelectedRecords();
    expect(client.calls.compute).toBe(0);
    expect(store.getState().graphStatus).toBe('idle');
  });

  it('does not run when no records are selected', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().runSelectedRecords();
    expect(client.calls.compute).toBe(0);
  });

  it('records a localised execution failure without disturbing guided state', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    const guidedRecords = store.getState().records;
    store.getState().setSelectedRecords(['analysis']);

    client.failCompute = true;
    await store.getState().runSelectedRecords();

    const state = store.getState();
    expect(state.graphStatus).toBe('failed');
    expect(state.graphFailure?.kind).toBe('unavailable');
    expect(state.graphRecords).toBeNull();
    // Guided recommendation is untouched.
    expect(state.records).toBe(guidedRecords);
    expect(state.recordsStatus).toBe('complete');
  });

  it('marks graph results stale when an override lands mid-flight', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    store.getState().setSelectedRecords(['analysis']);

    const gate = defer();
    const originalCompute = client.compute.bind(client);
    client.compute = async (query: RecordQuery): Promise<RecordSet> => {
      await gate.promise;
      return originalCompute(query);
    };

    const pending = store.getState().runSelectedRecords();
    store.getState().setHints({ k_grid: [6, 6, 6] });

    gate.release();
    await pending;
    expect(store.getState().graphStatus).toBe('complete');
    // The in-flight result reflects pre-override inputs; it must stay stale.
    expect(store.getState().graphStale).toBe(true);
  });

  it('keeps in-flight results stale when the selection changes mid-flight', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    store.getState().setSelectedRecords(['analysis']);

    const gate = defer();
    const originalCompute = client.compute.bind(client);
    client.compute = async (query: RecordQuery): Promise<RecordSet> => {
      await gate.promise;
      return originalCompute(query);
    };

    const pending = store.getState().runSelectedRecords();
    // Changing the selection mid-flight is a query-input change like any other.
    store.getState().setSelectedRecords(['analysis', 'advice']);

    gate.release();
    await pending;
    expect(store.getState().graphStatus).toBe('complete');
    // The in-flight result reflects the pre-change selection; it must stay stale.
    expect(store.getState().graphStale).toBe(true);
  });

  it('marks graph results stale when the selection changes', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    store.getState().setSelectedRecords(['analysis']);
    await store.getState().runSelectedRecords();
    expect(store.getState().graphStale).toBe(false);

    store.getState().setSelectedRecords(['analysis', 'advice']);
    expect(store.getState().graphStale).toBe(true);
  });

  it('clears graph results when a new structure loads', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    store.getState().setSelectedRecords(['analysis']);
    await store.getState().runSelectedRecords();
    expect(store.getState().graphRecords).not.toBeNull();

    await store.getState().loadStructure({ content: 'data_New\n', format: 'cif' });

    const state = store.getState();
    expect(state.graphRecords).toBeNull();
    expect(state.graphStatus).toBe('idle');
    expect(state.graphFailure).toBeNull();
    expect(state.graphStale).toBe(false);
    // Selection is a query preference and survives the structure change.
    expect(state.selectedRecordIds).toEqual(['analysis']);
  });
});
