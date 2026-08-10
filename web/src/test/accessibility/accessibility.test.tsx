// Behavioural accessibility assertions that axe cannot prove and that are too
// transient for e2e: running state is announced as text (never colour only),
// expandable toggles expose their state and reveal their controls, and focus
// moves into the freshly revealed view. A deferred CoreClient holds the
// running state still so the live region is observable. These test our
// behaviour only — never Mantine or Zustand internals.
import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { theme } from '../../app/theme';
import App from '../../App';
import type { ComputationRequest, Recommendation } from '../../client/types';
import { createWorkspaceStore } from '../../store/workspace';
import { FakeCoreClient } from '../mocks/FakeCoreClient';
import { siCif, siRecommendation } from '../mocks/fixtures';

const cif = { content: siCif, format: 'cif' as const };

/** Fake whose recommend() stays pending until the test releases it. */
class DeferredRecommendClient extends FakeCoreClient {
  resolveRecommend: ((value: Recommendation) => void) | null = null;

  async recommend(_request: ComputationRequest): Promise<Recommendation> {
    return new Promise<Recommendation>((resolve) => {
      this.resolveRecommend = resolve;
    });
  }
}

function renderApp() {
  const store = createWorkspaceStore(new FakeCoreClient());
  const view = render(
    <MantineProvider theme={theme} defaultColorScheme="light">
      <App store={store} />
    </MantineProvider>,
  );
  return { store, view };
}

async function loadStructureInto(store: ReturnType<typeof createWorkspaceStore>) {
  await store.getState().loadStructure(cif);
}

describe('Workbench accessibility behaviour', () => {
  it('announces the running state as text, not colour alone', async () => {
    const user = userEvent.setup();
    const client = new DeferredRecommendClient();
    const store = createWorkspaceStore(client);
    render(
      <MantineProvider theme={theme} defaultColorScheme="light">
        <App store={store} />
      </MantineProvider>,
    );

    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));

    // While the request is in flight the live region carries the running text.
    const status = screen.getByRole('status');
    expect(within(status).getByText(/running recommendation/i)).toBeInTheDocument();

    // Completing the request replaces the running region with results.
    client.resolveRecommend?.(siRecommendation);
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/running recommendation/i)).not.toBeInTheDocument();
  });

  it('exposes expandable state and reveals its controls', async () => {
    const user = userEvent.setup();
    const { store } = renderApp();
    await loadStructureInto(store);
    await user.click(screen.getByLabelText(/structure content/i));

    const toggle = screen.getByRole('button', { name: /calculation overrides/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByLabelText('Grid')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('Grid')).toBeInTheDocument();
  });

  it('moves focus into the revealed view on switch', async () => {
    const user = userEvent.setup();
    const { store } = renderApp();
    await loadStructureInto(store);

    await user.click(screen.getByText('Graph', { exact: true }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /task graph/i })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(document.activeElement?.getAttribute('data-view')).toBe('graph'),
    );

    await user.click(screen.getByText('Guided', { exact: true }));
    await waitFor(() =>
      expect(document.activeElement?.getAttribute('data-view')).toBe('guided'),
    );
  });
});
