import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../../App';
import { clipboard } from '../../records/RawJson';
import { createWorkspaceStore } from '../../store/workspace';
import { FakeCoreClient } from '../mocks/FakeCoreClient';
import { siCif } from '../mocks/fixtures';

describe('Guided workflow tracer', () => {
  it('loads a CIF, shows a canonical structure summary, and renders a recommendation', async () => {
    const user = userEvent.setup();
    const store = createWorkspaceStore(new FakeCoreClient());
    render(<App store={store} />);

    // Load a known inline CIF through the fake CoreClient.
    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));

    // Canonical structure summary renders.
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());
    expect(screen.getByText('Volume (Å³)')).toBeInTheDocument();

    // Request a recommendation.
    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));

    // Recommendation presents formula, advice, k-points, selection, warnings.
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getAllByText('Si8').length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: /advice/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /k-points/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /selection/i })).toBeInTheDocument();
    expect(screen.getByText('4 × 4 × 4')).toBeInTheDocument();
    expect(screen.getByText(/k-point spacing/i)).toBeInTheDocument();
  });

  it('shows the recommendation failure without losing the loaded structure', async () => {
    const client = new FakeCoreClient();
    const user = userEvent.setup();
    const store = createWorkspaceStore(client);
    render(<App store={store} />);

    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());

    client.failRecommend = true;
    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    // The structure summary is still present.
    expect(screen.getByText(/8 sites/i)).toBeInTheDocument();
  });

  it('loads a structure dropped onto the panel', async () => {
    const store = createWorkspaceStore(new FakeCoreClient());
    render(<App store={store} />);

    const textarea = screen.getByLabelText(/structure content/i);
    const file = new File([siCif], 'silicon.cif', { type: 'text/plain' });
    fireEvent.drop(textarea, {
      dataTransfer: { files: [file], dropEffect: 'copy' },
    });

    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());
    expect(screen.getByText('Volume (Å³)')).toBeInTheDocument();
  });

  it('generates and downloads a formula-named input archive after recommendation', async () => {
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValue('blob:goldilocks');
    const revokeObjectURL = vi
      .spyOn(URL, 'revokeObjectURL')
      .mockImplementation(() => {});
    let downloadedName = '';
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloadedName = this.download;
    });

    const user = userEvent.setup();
    const store = createWorkspaceStore(new FakeCoreClient());
    render(<App store={store} />);

    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: /generate input archive/i }));

    await waitFor(() => expect(downloadedName).toBe('Si-inputs.zip'));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it('overrides a hint, re-runs the recommendation, and regenerates the archive', async () => {
    const user = userEvent.setup();
    const store = createWorkspaceStore(new FakeCoreClient());
    render(<App store={store} />);

    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );

    // Override the k-point grid via progressive disclosure.
    await user.click(screen.getByRole('button', { name: /calculation overrides/i }));
    const grid = await screen.findByLabelText('Grid');
    await user.clear(grid);
    await user.type(grid, '6 6 6');
    await waitFor(() => expect(screen.getByText('Stale')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /re-run recommendation/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole('button', { name: /generate input archive/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /generate input archive/i }),
      ).toBeInTheDocument(),
    );
  });

  it('shows raw record JSON with copy and download controls', async () => {
    const writeText = vi.spyOn(clipboard, 'write').mockResolvedValue(undefined);
    let rawDownloadName = '';
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:raw');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      rawDownloadName = this.download;
    });

    const user = userEvent.setup();
    const store = createWorkspaceStore(new FakeCoreClient());
    render(<App store={store} />);

    await user.click(screen.getByLabelText(/structure content/i));
    await user.paste(siCif);
    await user.click(screen.getByRole('button', { name: /load structure/i }));
    await waitFor(() => expect(screen.getByText(/8 sites/i)).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /recommend parameters/i }));
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /recommendation/i }),
      ).toBeInTheDocument(),
    );

    // Open the first section's raw disclosure.
    await user.click(screen.getByRole('button', { name: /raw analysis/i }));
    expect(await screen.findByText(/".*reduced_formula.*Si"/s)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /copy/i }));
    expect(writeText).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /download json/i }));
    expect(rawDownloadName).toBe('analysis-record.json');
  });
});
