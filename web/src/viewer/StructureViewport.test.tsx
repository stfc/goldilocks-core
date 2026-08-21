import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { inspection } from "../test/workbenchFixtures";
import { StructureViewport } from "./StructureViewport";
import type { StructureViewerFactory } from "./structureViewer";

describe("StructureViewport", () => {
  it("owns the viewer lifecycle and updates canonical structure content", () => {
    const show = vi.fn();
    const dispose = vi.fn();
    const createViewer: StructureViewerFactory = vi.fn(() => ({
      show,
      dispose,
    }));
    const { rerender, unmount } = render(
      <StructureViewport inspection={inspection} createViewer={createViewer} />,
    );

    expect(createViewer).toHaveBeenCalledOnce();
    expect(show).toHaveBeenLastCalledWith("data_Si");

    rerender(
      <StructureViewport
        inspection={{ ...inspection, canonical_cif: "data_Si_updated" }}
        createViewer={createViewer}
      />,
    );
    expect(show).toHaveBeenLastCalledWith("data_Si_updated");

    unmount();
    expect(dispose).toHaveBeenCalledOnce();
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

    expect(screen.getByText("3D preview unavailable")).toBeInTheDocument();
    expect(screen.getByText("Si")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry 3D preview" }));

    expect(createViewer).toHaveBeenCalledTimes(2);
    expect(show).toHaveBeenCalledWith("data_Si");
    expect(screen.queryByText("3D preview unavailable")).not.toBeVisible();
  });
});
