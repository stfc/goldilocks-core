import { StrictMode, type ReactElement } from 'react';
import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { theme } from '../app/theme';
import type { StructureDocument } from '../client/types';
import { siStructureDocument } from '../test/mocks/fixtures';
import {
  DEFAULT_VIEWER_OPTIONS,
  type CrystalViewerAdapter,
  type CrystalViewerAdapterFactory,
  type ViewerOptions,
} from './CrystalViewer';
import { StructureViewer } from './StructureViewer';

/**
 * A configurable fake adapter standing in for the 3Dmol-backed implementation
 * at the component's injected factory seam. It records every call so tests
 * verify the component drives the narrow adapter lifecycle without any real
 * WebGL library (jsdom cannot prove GPU cleanup; that is final browser
 * integration verification).
 */
class FakeAdapter implements CrystalViewerAdapter {
  load = vi.fn<(structure: StructureDocument) => Promise<void>>();
  setOptions = vi.fn<(options: ViewerOptions) => void>();
  resetCamera = vi.fn<() => void>();
  exportPng = vi.fn<() => Promise<Blob> | null>();
  dispose = vi.fn<() => void>();

  constructor(public container: HTMLElement) {
    this.load.mockResolvedValue(undefined);
    this.exportPng.mockReturnValue(null);
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Builds a factory returning fresh fake adapters, one deferred per adapter. */
function createFakeFactory() {
  const adapters: FakeAdapter[] = [];
  const deferreds: ReturnType<typeof deferred<void>>[] = [];
  const factory: CrystalViewerAdapterFactory = (container) => {
    const adapter = new FakeAdapter(container);
    const pending = deferred<void>();
    adapter.load.mockReturnValue(pending.promise);
    adapters.push(adapter);
    deferreds.push(pending);
    return adapter;
  };
  return { factory, adapters, deferreds };
}

function wrap(node: ReactElement): ReactElement {
  return <MantineProvider theme={theme}>{node}</MantineProvider>;
}

function disorderedStructure(): StructureDocument {
  return {
    ...siStructureDocument,
    sites: [
      ...siStructureDocument.sites.slice(0, 1),
      {
        label: 'Si1',
        species: [
          { element: 'Si', occupancy: 0.8 },
          { element: 'Ge', occupancy: 0.2 },
        ],
        abc: [0.25, 0.25, 0.25],
        xyz: [1.35775, 1.35775, 1.35775],
      },
      ...siStructureDocument.sites.slice(2),
    ],
  };
}

const controls = {
  cell: () => screen.getByRole('switch', { name: /unit cell/i }),
  representation: (name: string) =>
    screen.getByRole('radio', { name: new RegExp(name, 'i') }),
  reset: () => screen.getByRole('button', { name: /reset view/i }),
  exportPng: () => screen.getByRole('button', { name: /export png/i }),
};

describe('StructureViewer', () => {
  it('creates one adapter per mounted container and loads the structure', async () => {
    const { factory, adapters } = createFakeFactory();
    render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );

    expect(adapters).toHaveLength(1);
    await waitFor(() =>
      expect(adapters[0].load).toHaveBeenCalledWith(siStructureDocument),
    );
  });

  it('shows the 3D container and controls once the adapter is ready', async () => {
    const { factory, adapters, deferreds } = createFakeFactory();
    render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );

    expect(screen.getByText(/loading 3d viewer/i)).toBeInTheDocument();
    deferreds[0].resolve();
    await waitFor(() =>
      expect(screen.getByLabelText(/3d structure viewer/i)).toBeInTheDocument(),
    );

    expect(controls.reset()).toBeInTheDocument();
    expect(controls.exportPng()).toBeInTheDocument();
    expect(controls.cell()).toBeInTheDocument();
    expect(adapters[0].setOptions).toHaveBeenCalled();
  });

  it('updates rather than recreating the viewer on option changes', async () => {
    const user = userEvent.setup();
    const { factory, adapters, deferreds } = createFakeFactory();
    render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );
    deferreds[0].resolve();
    await waitFor(() =>
      expect(screen.getByLabelText(/3d structure viewer/i)).toBeInTheDocument(),
    );

    await user.click(controls.representation('spacefill'));
    await user.click(controls.cell());
    await user.click(controls.reset());

    // One adapter is reused for all option changes; the same viewer instance
    // is updated, never replaced.
    expect(adapters).toHaveLength(1);
    expect(adapters[0].setOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ representation: 'spacefill', showCell: false }),
    );
    expect(adapters[0].resetCamera).toHaveBeenCalledTimes(1);
  });

  it('disposes the previous adapter when the structure changes', async () => {
    const { factory, adapters, deferreds } = createFakeFactory();
    const { rerender } = render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );
    deferreds[0].resolve();

    rerender(
      wrap(
        <StructureViewer structure={disorderedStructure()} adapterFactory={factory} />,
      ),
    );

    expect(adapters).toHaveLength(2);
    expect(adapters[0].dispose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(adapters[1].load).toHaveBeenCalledWith(disorderedStructure()),
    );
  });

  it('survives React Strict Mode remounts by disposing the first adapter', () => {
    const { factory, adapters } = createFakeFactory();
    // StrictMode must be the outermost wrapper for its mount → cleanup →
    // mount effect cycle to apply.
    render(
      <StrictMode>
        <MantineProvider theme={theme}>
          <StructureViewer structure={siStructureDocument} adapterFactory={factory} />
        </MantineProvider>
      </StrictMode>,
    );

    // Strict Mode runs setup → cleanup → setup on the initial mount, so two
    // adapters are created and the first is disposed immediately.
    expect(adapters.length).toBeGreaterThanOrEqual(2);
    expect(adapters[0].dispose).toHaveBeenCalledTimes(1);
    for (const adapter of adapters.slice(1)) {
      expect(adapter.dispose).not.toHaveBeenCalled();
    }
  });

  it('ignores stale async completion from a superseded adapter', async () => {
    const { factory, adapters, deferreds } = createFakeFactory();
    const { rerender } = render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );
    // A stale load never resolves before the structure changes.
    rerender(
      wrap(
        <StructureViewer structure={disorderedStructure()} adapterFactory={factory} />,
      ),
    );

    expect(adapters[0].dispose).toHaveBeenCalled();
    // The first adapter's load completes late; its cancelled/disposed state
    // must not flip the view to ready or error for a superseded structure.
    deferreds[0].resolve();
    await waitFor(() =>
      expect(screen.getByText(/loading 3d viewer/i)).toBeInTheDocument(),
    );

    // The current adapter then completes and reaches ready.
    deferreds[1].resolve();
    await waitFor(() =>
      expect(screen.getByLabelText(/3d structure viewer/i)).toBeInTheDocument(),
    );
    expect(adapters[1].load).toHaveBeenCalledWith(disorderedStructure());
  });

  it('disposes the adapter on unmount', () => {
    const { factory, adapters } = createFakeFactory();
    const { unmount } = render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );
    expect(adapters[0].dispose).not.toHaveBeenCalled();
    unmount();
    expect(adapters[0].dispose).toHaveBeenCalledTimes(1);
  });

  it('falls back to a textual table when the adapter fails without crashing', async () => {
    const { adapters } = createFakeFactory();
    const failing: CrystalViewerAdapterFactory = (container) => {
      const adapter = new FakeAdapter(container);
      adapter.load.mockRejectedValue(new Error('WebGL context unavailable'));
      adapters.push(adapter);
      return adapter;
    };
    render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={failing} />,
      ),
    );

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText(/could not render the 3d view/i)).toBeInTheDocument();
    expect(screen.getByText(/webgl context unavailable/i)).toBeInTheDocument();
    // The textual site table is still available so inspection is not lost.
    expect(screen.getByText(/cartesian/i)).toBeInTheDocument();
    expect(screen.getByText('2.716, 0.000, 2.716')).toBeInTheDocument();
  });

  it('keeps the disorder disclosure visible alongside the 3D view', async () => {
    const { factory, deferreds } = createFakeFactory();
    render(
      wrap(
        <StructureViewer structure={disorderedStructure()} adapterFactory={factory} />,
      ),
    );
    deferreds[0].resolve();
    await waitFor(() =>
      expect(screen.getByLabelText(/3d structure viewer/i)).toBeInTheDocument(),
    );

    expect(screen.getAllByText(/mixed occupancy/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/canonical structure preserves every species/i),
    ).toBeInTheDocument();
  });

  it('exposes PNG export that defers to the adapter', async () => {
    const user = userEvent.setup();
    const { factory, adapters, deferreds } = createFakeFactory();
    render(
      wrap(
        <StructureViewer structure={siStructureDocument} adapterFactory={factory} />,
      ),
    );
    deferreds[0].resolve();
    await waitFor(() =>
      expect(screen.getByLabelText(/3d structure viewer/i)).toBeInTheDocument(),
    );

    await user.click(controls.exportPng());
    expect(adapters[0].exportPng).toHaveBeenCalledTimes(1);
  });

  it('defaults to a gold-on-stone themed card with a visible cell', () => {
    expect(DEFAULT_VIEWER_OPTIONS).toEqual({
      representation: 'ball-stick',
      repetitions: [1, 1, 1],
      showCell: true,
    });
  });
});
