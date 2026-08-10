import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { theme } from '../../app/theme';
import { createWorkspaceStore, type WorkspaceStore } from '../../store/workspace';
import { WorkspaceProvider } from '../../store/WorkspaceContext';
import { GraphView } from '../../views/GraphView/GraphView';
import { FakeCoreClient } from '../mocks/FakeCoreClient';
import { siCif } from '../mocks/fixtures';

// React Flow does not render meaningfully in jsdom and its internals are out of
// scope to test. We mock the module so the test can assert that GraphView wires
// the canvas with the right (restricted) configuration and the right nodes, and
// that selection/execution flows around it.
const captured = vi.hoisted(() => ({
  lastProps: null as null | Record<string, unknown>,
  throwRender: false,
}));

vi.mock('@xyflow/react', () => {
  const ReactFlow = (props: Record<string, unknown>) => {
    if (captured.throwRender) throw new Error('canvas exploded');
    captured.lastProps = props;
    return <div data-testid="react-flow-canvas">canvas</div>;
  };
  return {
    ReactFlow,
    ReactFlowProvider: ({ children }: { children: ReactElement }) => children,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    useNodesState: (init: unknown[]) => [init, () => {}, () => {}],
    useEdgesState: (init: unknown[]) => [init, () => {}, () => {}],
  };
});

const cif = { content: siCif, format: 'cif' as const };

function renderGraph(store: WorkspaceStore) {
  return render(
    <MantineProvider theme={theme} defaultColorScheme="light">
      <WorkspaceProvider store={store}>
        <GraphView />
      </WorkspaceProvider>
    </MantineProvider>,
  );
}

async function withLoadedStructure() {
  const store = createWorkspaceStore(new FakeCoreClient());
  await store.getState().loadStructure(cif);
  renderGraph(store);
  return store;
}

beforeEach(() => {
  captured.lastProps = null;
  captured.throwRender = false;
});

describe('Graph view', () => {
  it('loads the backend-owned task catalogue and renders selectable record toggles', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    renderGraph(store);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /task graph/i })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('checkbox', {
        name: /compute record select pseudopotentials/i,
      }),
    ).toBeInTheDocument();
    expect(store.getState().catalogueStatus).toBe('complete');
  });

  it('shows the catalogue failure contained within the view, with a retry', async () => {
    const client = new FakeCoreClient({ failDescribe: true });
    const store = createWorkspaceStore(client);
    renderGraph(store);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText(/task graph unavailable/i)).toBeInTheDocument();

    client.failDescribe = false;
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );
  });

  it('configures React Flow with immutable topology: no connect, no reconnect, no delete', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    renderGraph(store);
    await waitFor(() => expect(captured.lastProps).not.toBeNull());

    const props = captured.lastProps!;
    expect(props.nodesConnectable).toBe(false);
    expect(props.edgesReconnectable).toBe(false);
    expect(props.deleteKeyCode).toBeNull();
    expect(props.nodesDraggable).toBe(true);
    expect(props.fitView).toBe(true);

    // Every backend stage is present as a node; dependencies are edges.
    const nodes = props.nodes as { id: string }[];
    const nodeIds = nodes.map((n) => n.id);
    expect(nodeIds).toEqual(
      expect.arrayContaining([
        'structure',
        'analysis',
        'k_points',
        'advice',
        'selection',
        'generated_files',
      ]),
    );
    const edges = props.edges as { source: string; target: string }[];
    expect(edges).toContainEqual(
      expect.objectContaining({ source: 'structure', target: 'analysis' }),
    );
  });

  it('runs the selected records through CoreClient and presents the results', async () => {
    const user = userEvent.setup();
    const store = await withLoadedStructure();

    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('checkbox', { name: /compute record analyze/i }));
    await user.click(screen.getByRole('checkbox', { name: /compute record advise/i }));
    await user.click(screen.getByRole('button', { name: /run selected records/i }));

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /record results/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { name: /advice/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /analysis/i })).toBeInTheDocument();
    // Only the selected records are presented.
    expect(
      screen.queryByRole('heading', { name: /k-points/i }),
    ).not.toBeInTheDocument();
    expect(store.getState().graphStatus).toBe('complete');
  });

  it('exposes the raw records through an advanced disclosure', async () => {
    const user = userEvent.setup();
    await withLoadedStructure();
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('checkbox', { name: /compute record analyze/i }));
    await user.click(screen.getByRole('button', { name: /run selected records/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /record results/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: /raw records show/i }));
    // The raw JSON exposes the canonical structure fields behind the disclosure.
    expect(screen.getAllByText(/Si8/).length).toBeGreaterThan(0);
    expect(screen.getByText(/reduced_formula/)).toBeInTheDocument();
  });

  it('contains an execution failure within the view', async () => {
    const client = new FakeCoreClient();
    const user = userEvent.setup();
    const store = createWorkspaceStore(client);
    await store.getState().loadStructure(cif);
    renderGraph(store);

    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole('checkbox', { name: /compute record analyze/i }));

    client.failCompute = true;
    await user.click(screen.getByRole('button', { name: /run selected records/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText(/did not complete/i)).toBeInTheDocument();
    expect(store.getState().graphStatus).toBe('failed');
    expect(store.getState().graphFailure?.kind).toBe('unavailable');
  });

  it('provides keyboard-accessible record toggles and disables run without a structure', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    renderGraph(store);
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: /compute record analyze/i }),
      ).toBeInTheDocument(),
    );

    const toggle = screen.getByRole('checkbox', { name: /compute record analyze/i });
    // A real native checkbox: keyboard-activatable and not aria-hidden.
    expect(toggle).not.toBeDisabled();
    expect(toggle).toHaveAttribute('type', 'checkbox');

    const run = screen.getByRole('button', { name: /run selected records/i });
    expect(run).toBeDisabled();
    expect(screen.getByText(/load a structure first/i)).toBeInTheDocument();
  });

  it('contains a canvas rendering failure within Graph view', async () => {
    const user = userEvent.setup();
    captured.throwRender = true;
    const store = createWorkspaceStore(new FakeCoreClient());
    renderGraph(store);

    await waitFor(() =>
      expect(screen.getByText(/graph canvas unavailable/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('react-flow-canvas')).not.toBeInTheDocument();
    // The failure is confined to the canvas; the rest of Graph view is intact.
    expect(
      screen.getByRole('checkbox', { name: /compute record analyze/i }),
    ).toBeInTheDocument();
    expect(store.getState().structure).toBeNull();

    // Retrying remounts the canvas and recovers.
    captured.throwRender = false;
    await user.click(screen.getByRole('button', { name: /retry canvas/i }));
    await waitFor(() =>
      expect(screen.getByTestId('react-flow-canvas')).toBeInTheDocument(),
    );
  });
});
