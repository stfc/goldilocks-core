import { MantineProvider } from "@mantine/core";
import {
  act,
  render as renderComponent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { inspection } from "../support/workbenchFixtures";
import { StructureViewport } from "../../src/viewer/StructureViewport";
import type {
  StructureViewer,
  StructureViewerFactory,
} from "../../src/viewer/structureViewer";

function render(component: ReactElement) {
  return renderComponent(component, {
    wrapper: ({ children }) => (
      <MantineProvider env="test">{children}</MantineProvider>
    ),
  });
}

describe("StructureViewport", () => {
  it("owns the viewer lifecycle and updates canonical structure content", async () => {
    const show = vi.fn();
    const dispose = vi.fn();
    const createViewer: StructureViewerFactory = vi.fn(() => ({
      show,
      refreshTheme: vi.fn(),
      dispose,
    }));
    const { rerender, unmount } = render(
      <StructureViewport inspection={inspection} createViewer={createViewer} />,
    );

    await waitFor(() => {
      expect(createViewer).toHaveBeenCalledOnce();
      expect(show).toHaveBeenLastCalledWith("data_Si");
    });

    rerender(
      <StructureViewport
        inspection={{ ...inspection, canonical_cif: "data_Si_updated" }}
        createViewer={createViewer}
      />,
    );
    await waitFor(() => {
      expect(show).toHaveBeenLastCalledWith("data_Si_updated");
    });

    unmount();
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("disposes a lazily loaded viewer that resolves after unmount", async () => {
    const show = vi.fn();
    const dispose = vi.fn();
    let resolveViewer: (viewer: StructureViewer) => void = () => undefined;
    const createViewer: StructureViewerFactory = vi.fn(
      () =>
        new Promise<StructureViewer>((resolve) => {
          resolveViewer = resolve;
        }),
    );
    const { unmount } = render(
      <StructureViewport inspection={inspection} createViewer={createViewer} />,
    );

    unmount();
    await act(async () => {
      resolveViewer({ show, refreshTheme: vi.fn(), dispose });
      await Promise.resolve();
    });

    expect(dispose).toHaveBeenCalledOnce();
    expect(show).not.toHaveBeenCalled();
  });

  it("retries viewer initialization without losing the workspace", async () => {
    const user = userEvent.setup();
    const show = vi.fn();
    const dispose = vi.fn();
    const createViewer: StructureViewerFactory = vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("WebGL unavailable");
      })
      .mockReturnValue({ show, refreshTheme: vi.fn(), dispose });
    render(
      <StructureViewport inspection={inspection} createViewer={createViewer} />,
    );

    const fallback = screen.getByRole("status", {
      name: "3D structure preview unavailable",
    });
    expect(fallback).toHaveTextContent("Si · 1 atomic site");

    await user.click(screen.getByRole("button", { name: "Retry 3D preview" }));

    expect(createViewer).toHaveBeenCalledTimes(2);
    expect(show).toHaveBeenCalledWith("data_Si");
    expect(fallback).not.toBeVisible();
  });

  it("exposes canonical mixed and partial occupancies before computation", async () => {
    const user = userEvent.setup();
    const createViewer: StructureViewerFactory = () => ({
      show: vi.fn(),
      refreshTheme: vi.fn(),
      dispose: vi.fn(),
    });
    render(
      <StructureViewport
        inspection={{
          ...inspection,
          structure: {
            ...inspection.structure,
            site_count: 2,
            sites: [
              {
                fractional_coordinates: [0.123456789, 0, 0],
                cartesian_coordinates_angstrom: [0.493827156, 0, 0],
                species: [
                  {
                    symbol: "Fe",
                    label: "Fe2+",
                    occupancy: 0.25,
                    oxidation_state: 2,
                  },
                  {
                    symbol: "Mn",
                    label: "Mn2+",
                    occupancy: 0.75,
                    oxidation_state: 2,
                  },
                ],
              },
              {
                fractional_coordinates: [0.5, 0.5, 0.5],
                cartesian_coordinates_angstrom: [2, 2, 2],
                species: [
                  {
                    symbol: "O",
                    label: "O2-",
                    occupancy: 0.6,
                    oxidation_state: -2,
                  },
                ],
              },
            ],
          },
        }}
        createViewer={createViewer}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(/approximation/);
    await user.click(
      screen.getByRole("button", {
        name: "Inspect canonical sites and occupancies",
      }),
    );
    const details = screen.getByRole("dialog", {
      name: "Canonical sites and occupancies",
    });
    const mixedSite = within(details).getByRole("region", { name: "Site 1" });
    expect(mixedSite).toHaveTextContent("0.123456789, 0, 0");
    expect(
      within(mixedSite).getByRole("row", { name: "Fe2+ Fe 0.25" }),
    ).toBeVisible();
    expect(
      within(mixedSite).getByRole("row", { name: "Mn2+ Mn 0.75" }),
    ).toBeVisible();
    const partialSite = within(details).getByRole("region", { name: "Site 2" });
    expect(
      within(partialSite).getByRole("row", { name: "O2- O 0.6" }),
    ).toBeVisible();
  });

  it("discloses a single partially occupied species without requiring mixed species", () => {
    render(
      <StructureViewport
        inspection={{
          ...inspection,
          structure: {
            ...inspection.structure,
            sites: inspection.structure.sites.map((site) => ({
              ...site,
              species: site.species.map((species) => ({
                ...species,
                occupancy: 0.5,
              })),
            })),
          },
        }}
        createViewer={() => ({
          show: vi.fn(),
          refreshTheme: vi.fn(),
          dispose: vi.fn(),
        })}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(/partial occupancy/);
  });

  it("does not describe a fully occupied ordered structure as approximate", () => {
    render(
      <StructureViewport
        inspection={inspection}
        createViewer={() => ({
          show: vi.fn(),
          refreshTheme: vi.fn(),
          dispose: vi.fn(),
        })}
      />,
    );
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Inspect canonical sites and occupancies",
      }),
    ).toBeVisible();
  });
});
