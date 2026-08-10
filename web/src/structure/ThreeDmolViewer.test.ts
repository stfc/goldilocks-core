import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureDocument } from '../client/types';
import { siStructureDocument } from '../test/mocks/fixtures';
import { DEFAULT_VIEWER_OPTIONS } from './CrystalViewer';
import { ThreeDmolViewer } from './ThreeDmolViewer';

/**
 * The 3Dmol module is mocked so the real adapter's behaviour — building atoms
 * and the unit cell from the canonical Structure Document, applying options,
 * invalidating stale loads, and disposing — can be exercised under jsdom.
 * Real WebGL/GPU release is browser integration verification, not proven here.
 */

const mockModule = vi.hoisted(() => ({ createViewer: vi.fn() }));

vi.mock('3dmol', () => mockModule);

function makeFakeViewer() {
  const model = {
    addAtoms: vi.fn(),
    setCrystData: vi.fn(),
  };
  const viewer = {
    addModel: vi.fn(() => model),
    removeAllModels: vi.fn(),
    setStyle: vi.fn(),
    replicateUnitCell: vi.fn(),
    addUnitCell: vi.fn(),
    zoomTo: vi.fn(),
    render: vi.fn(),
    clear: vi.fn(),
    pngURI: vi.fn(() => 'data:image/png;base64,AAAA'),
    removeAllShapes: vi.fn(),
    removeAllLabels: vi.fn(),
    removeAllSurfaces: vi.fn(),
    show: vi.fn(),
  };
  return { model, viewer };
}

type ModuleLike = typeof import('3dmol');

function mount(container: HTMLElement, loader?: () => Promise<ModuleLike>) {
  return new ThreeDmolViewer(container, loader);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => (resolve = res));
  return { promise, resolve };
}

describe('ThreeDmolViewer', () => {
  beforeEach(() => {
    mockModule.createViewer.mockReset();
  });

  it('builds atoms and the unit cell from the canonical structure', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    await adapter.load(siStructureDocument);

    expect(mockModule.createViewer).toHaveBeenCalledTimes(1);
    expect(mockModule.createViewer).toHaveBeenCalledWith(
      container,
      expect.objectContaining({ antialias: true }),
    );
    expect(viewer.addModel).toHaveBeenCalledTimes(1);
    const atoms = viewer.addModel.mock.results[0].value.addAtoms.mock.calls[0][0];
    expect(atoms).toHaveLength(8);
    // Representative element per site from the canonical species/occupancy.
    expect(atoms[0].elem).toBe('Si');
    expect(atoms[0].x).toBeCloseTo(2.7155);
    expect(viewer.addModel.mock.results[0].value.setCrystData).toHaveBeenCalledWith(
      5.431,
      5.431,
      5.431,
      90,
      90,
      90,
    );
    expect(viewer.addUnitCell).toHaveBeenCalledTimes(1);
    expect(viewer.setStyle).toHaveBeenCalledTimes(1);
    expect(viewer.zoomTo).toHaveBeenCalled();
    expect(viewer.render).toHaveBeenCalled();
  });

  it('uses the highest-occupancy species as the representative element', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    const disordered: StructureDocument = {
      ...siStructureDocument,
      sites: [
        {
          label: 'A',
          species: [
            { element: 'Ge', occupancy: 0.2 },
            { element: 'Si', occupancy: 0.8 },
          ],
          abc: [0, 0, 0],
          xyz: [1, 2, 3],
        },
      ],
    };

    await adapter.load(disordered);

    const atoms = viewer.addModel.mock.results[0].value.addAtoms.mock.calls[0][0];
    expect(atoms).toHaveLength(1);
    expect(atoms[0].elem).toBe('Si');
  });

  it('does not draw the unit cell when hidden', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    adapter.setOptions({ ...DEFAULT_VIEWER_OPTIONS, showCell: false });
    await adapter.load(siStructureDocument);

    expect(viewer.addUnitCell).not.toHaveBeenCalled();
  });

  it('replicates the unit cell when requested', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    adapter.setOptions({ ...DEFAULT_VIEWER_OPTIONS, repetitions: [2, 2, 1] });
    await adapter.load(siStructureDocument);

    expect(viewer.replicateUnitCell).toHaveBeenCalledWith(2, 2, 1, expect.anything());
  });

  it('re-renders existing models when options change', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    await adapter.load(siStructureDocument);
    const renderCallsBefore = viewer.render.mock.calls.length;

    adapter.setOptions({ ...DEFAULT_VIEWER_OPTIONS, representation: 'spacefill' });
    // setOptions re-renders asynchronously; wait for the model replacement.
    await vi.waitFor(() => expect(viewer.removeAllModels).toHaveBeenCalledTimes(2));

    expect(viewer.render.mock.calls.length).toBeGreaterThan(renderCallsBefore);
    expect(viewer.setStyle).toHaveBeenLastCalledWith(
      {},
      expect.objectContaining({ sphere: expect.anything() }),
    );
  });

  it('ignores a stale load that resolves after a newer one', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    const modulePromise = deferred<ModuleLike>();
    // Both loads await the same, intentionally slow module import.
    const adapter = mount(container, () => modulePromise.promise);

    const firstLoad = adapter.load(siStructureDocument);
    const secondLoad = adapter.load(siStructureDocument);
    // Neither load has rendered yet because the module import is pending.
    expect(viewer.render).not.toHaveBeenCalled();

    mockModule.createViewer.mockReturnValue(viewer);
    modulePromise.resolve({
      createViewer: mockModule.createViewer,
    } as unknown as ModuleLike);
    await Promise.all([firstLoad, secondLoad]);

    // Only the latest load rendered; the stale one never reached the viewer.
    expect(mockModule.createViewer).toHaveBeenCalledTimes(1);
    expect(viewer.render).toHaveBeenCalledTimes(1);
    expect(viewer.addModel).toHaveBeenCalledTimes(1);
  });

  it('resets the camera to the default framing', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    await adapter.load(siStructureDocument);
    adapter.resetCamera();

    expect(viewer.zoomTo).toHaveBeenCalledTimes(2);
  });

  it('exposes PNG export by converting the canvas URI to a blob', async () => {
    const blob = new Blob(['x'], { type: 'image/png' });
    const fetchMock = vi.fn().mockResolvedValue({ blob: () => Promise.resolve(blob) });
    vi.stubGlobal('fetch', fetchMock);

    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    try {
      await adapter.load(siStructureDocument);
      const png = adapter.exportPng();
      expect(png).not.toBeNull();
      await expect(png).resolves.toBe(blob);
      expect(fetchMock).toHaveBeenCalledWith('data:image/png;base64,AAAA');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('returns null from exportPng before the viewer exists', async () => {
    const container = document.createElement('div');
    const adapter = mount(container);
    expect(adapter.exportPng()).toBeNull();
  });

  it('clears the viewer and removes container children on dispose', async () => {
    const container = document.createElement('div');
    container.appendChild(document.createElement('canvas'));
    const { viewer } = makeFakeViewer();
    mockModule.createViewer.mockReturnValue(viewer);
    const adapter = mount(container);

    await adapter.load(siStructureDocument);
    adapter.dispose();

    expect(viewer.clear).toHaveBeenCalledTimes(1);
    // The library-owned canvas is removed from the container.
    expect(container.hasChildNodes()).toBe(false);
  });

  it('ignores in-flight loads after dispose', async () => {
    const container = document.createElement('div');
    const { viewer } = makeFakeViewer();
    const modulePromise = deferred<ModuleLike>();
    const adapter = mount(container, () => modulePromise.promise);

    const pending = adapter.load(siStructureDocument);
    adapter.dispose();
    mockModule.createViewer.mockReturnValue(viewer);
    modulePromise.resolve({
      createViewer: mockModule.createViewer,
    } as unknown as ModuleLike);
    await pending;

    // The superseded load never rendered.
    expect(viewer.render).not.toHaveBeenCalled();
  });

  it('exposes a stable default viewer configuration', () => {
    expect(DEFAULT_VIEWER_OPTIONS).toEqual({
      representation: 'ball-stick',
      repetitions: [1, 1, 1],
      showCell: true,
    });
    void mockModule;
  });
});
