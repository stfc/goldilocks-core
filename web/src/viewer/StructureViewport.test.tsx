import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { inspection } from "../test/workbenchFixtures";
import { StructureViewport } from "./StructureViewport";
import type {
  StructureViewer,
  StructureViewerFactory,
} from "./structureViewer";

describe("StructureViewport", () => {
  it("owns the viewer lifecycle and updates canonical structure content", async () => {
    const show = vi.fn();
    const dispose = vi.fn();
    const createViewer: StructureViewerFactory = vi.fn(() => ({
      show,
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
      resolveViewer({ show, dispose });
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
      .mockReturnValue({ show, dispose });
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
    expect(screen.queryByText("3D preview unavailable")).not.toBeVisible();
  });
});
