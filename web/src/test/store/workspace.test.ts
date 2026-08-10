import { describe, expect, it } from 'vitest';
import { createWorkspaceStore } from '../../store/workspace';
import type { ComputationRequest, Recommendation } from '../../client/types';
import { FakeCoreClient } from '../mocks/FakeCoreClient';
import { siCif, siStructureDocument } from '../mocks/fixtures';

const cif = { content: siCif, format: 'cif' as const };

function defer(): { promise: Promise<void>; release: () => void } {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

describe('Workspace store', () => {
  it('loads a structure and transitions through honest states', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    const pending = store.getState().loadStructure(cif);
    expect(store.getState().structureStatus).toBe('running');
    await pending;
    const state = store.getState();
    expect(state.structureStatus).toBe('complete');
    expect(state.structure?.formula).toBe(siStructureDocument.formula);
    expect(state.structureFailure).toBeNull();
    expect(state.source).toEqual(cif);
  });

  it('records the failure but leaves the source unset when a fresh load fails', async () => {
    const store = createWorkspaceStore(new FakeCoreClient({ failLoad: true }));
    await store.getState().loadStructure(cif);
    const state = store.getState();
    expect(state.structureStatus).toBe('failed');
    expect(state.structureFailure?.kind).toBe('unavailable');
    expect(state.source).toBeNull();
    expect(state.structure).toBeNull();
  });

  it('preserves the prior valid pair when loading a new structure fails', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    const priorSource = store.getState().source;
    const priorStructure = store.getState().structure;
    const priorRecords = store.getState().records;

    client.failLoad = true;
    await store.getState().loadStructure({ content: 'garbage', format: 'cif' });

    const state = store.getState();
    expect(state.structureStatus).toBe('failed');
    expect(state.source).toBe(priorSource);
    expect(state.structure).toBe(priorStructure);
    expect(state.records).toBe(priorRecords);
    expect(state.recordsStale).toBe(false);
  });

  it('invalidates prior recommendation and generated data when a new structure loads', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    expect(store.getState().records).not.toBeNull();
    expect(store.getState().generated).not.toBeNull();

    await store.getState().loadStructure({ content: 'data_New\n', format: 'cif' });

    const state = store.getState();
    expect(state.records).toBeNull();
    expect(state.recordsStatus).toBe('idle');
    expect(state.recordsStale).toBe(false);
    expect(state.generated).toBeNull();
    expect(state.generationStatus).toBe('idle');
    expect(state.generatedStale).toBe(false);
    expect(state.structure).not.toBeNull();
  });

  it('marks records and generated output stale when an override changes', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    expect(store.getState().recordsStale).toBe(false);
    expect(store.getState().generatedStale).toBe(false);

    store.getState().setHints({ k_grid: [6, 6, 6] });
    expect(store.getState().recordsStale).toBe(true);
    expect(store.getState().generatedStale).toBe(true);

    store.getState().setIntent({ functional: 'PBE' });
    expect(store.getState().recordsStale).toBe(true);
  });

  it('does not mark records stale when nothing exists yet', () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    store.getState().setHints({ k_grid: [6, 6, 6] });
    expect(store.getState().recordsStale).toBe(false);
    expect(store.getState().generatedStale).toBe(false);
  });

  it('does not clear the stale flag when an override happens mid-flight', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    expect(store.getState().recordsStale).toBe(false);

    // Defer the next recommend so an override can land while it is running.
    const gate = defer();
    const originalRecommend = client.recommend.bind(client);
    client.recommend = async (request: ComputationRequest): Promise<Recommendation> => {
      await gate.promise;
      return originalRecommend(request);
    };

    const pending = store.getState().recommend();
    store.getState().setHints({ k_grid: [6, 6, 6] });
    expect(store.getState().recordsStale).toBe(true);

    gate.release();
    await pending;

    expect(store.getState().recordsStatus).toBe('complete');
    // The in-flight result reflects pre-override inputs; it must stay stale.
    expect(store.getState().recordsStale).toBe(true);
  });

  it('retains the previously generated archive when an unrelated recommend re-runs', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    const generatedBefore = store.getState().generated;
    expect(generatedBefore).not.toBeNull();

    await store.getState().recommend();

    expect(store.getState().generated).toBe(generatedBefore);
    expect(store.getState().generatedStale).toBe(false);
  });

  it('keeps the generated archive stale-marked after a recommend that follows an override', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    const generatedBefore = store.getState().generated;

    store.getState().setHints({ k_grid: [6, 6, 6] });
    expect(store.getState().generatedStale).toBe(true);
    await store.getState().recommend();

    const state = store.getState();
    expect(state.generated).toBe(generatedBefore);
    expect(state.recordsStale).toBe(false);
    expect(state.generatedStale).toBe(true);
  });

  it('preserves prior records when a recomputation fails', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    const prior = store.getState().records;

    client.failRecommend = true;
    await store.getState().recommend();
    const state = store.getState();
    expect(state.recordsStatus).toBe('failed');
    expect(state.records).toBe(prior);
    expect(state.recordsFailure?.kind).toBe('unavailable');
  });

  it('retrying a recommendation does not re-upload the structure', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    const loadsAfterLoad = client.calls.loadStructure;

    client.failRecommend = true;
    await store.getState().recommend();
    expect(store.getState().recordsStatus).toBe('failed');

    client.failRecommend = false;
    await store.getState().recommend();
    expect(store.getState().recordsStatus).toBe('complete');
    expect(client.calls.loadStructure).toBe(loadsAfterLoad);
  });

  it('completes generation and exposes the generated input set', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();

    const state = store.getState();
    expect(state.generationStatus).toBe('complete');
    expect(state.generated).not.toBeNull();
    expect(state.generated?.generated_files.length).toBeGreaterThan(0);
    expect(state.generationFailure).toBeNull();
    expect(state.generatedStale).toBe(false);
  });

  it('retains the recommendation and prior archive when generation fails, then retries', async () => {
    const client = new FakeCoreClient();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    const priorGenerated = store.getState().generated;
    const priorRecords = store.getState().records;

    client.failGenerate = true;
    await store.getState().generate();
    const failed = store.getState();
    expect(failed.generationStatus).toBe('failed');
    expect(failed.generationFailure?.kind).toBe('unavailable');
    // The recommendation and any prior archive survive the failed generation.
    expect(failed.generated).toBe(priorGenerated);
    expect(failed.records).toBe(priorRecords);

    client.failGenerate = false;
    await store.getState().generate();
    expect(store.getState().generationStatus).toBe('complete');
    expect(store.getState().generated).not.toBeNull();
    expect(store.getState().generationFailure).toBeNull();
  });

  it('clears the stale flag when the archive is regenerated for the current request', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();
    expect(store.getState().generatedStale).toBe(false);

    store.getState().setHints({ k_grid: [6, 6, 6] });
    expect(store.getState().generatedStale).toBe(true);

    await store.getState().generate();
    expect(store.getState().generationStatus).toBe('complete');
    expect(store.getState().generatedStale).toBe(false);
  });

  it('marks the archive stale when intent changes and recomputation does not refresh it', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    await store.getState().loadStructure(cif);
    await store.getState().recommend();
    await store.getState().generate();

    store.getState().setIntent({ functional: 'PBE' });
    expect(store.getState().generatedStale).toBe(true);
    await store.getState().recommend();
    // Re-running the recommendation refreshes records but not the archive.
    expect(store.getState().recordsStale).toBe(false);
    expect(store.getState().generatedStale).toBe(true);
  });
});
