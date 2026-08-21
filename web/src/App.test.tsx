import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type {
  ArchiveDownload,
  WorkbenchClient,
} from "./api/workbenchClient";
import {
  inspection,
  recommendation,
} from "./test/workbenchFixtures";
import { WorkspaceProvider } from "./workspace/WorkspaceProvider";
import { createWorkspace } from "./workspace/workspace";

vi.mock("./viewer/StructureViewport", () => ({
  StructureViewport: () => <div aria-label="Crystal structure viewer">3D crystal</div>,
}));

describe("Goldilocks Workbench", () => {
  it("guides a structure through review, stale override, recompute, and archive", async () => {
    const user = userEvent.setup();
    const archive: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks.zip",
    };
    const reviewRequest = vi.fn().mockResolvedValue(recommendation);
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: reviewRequest,
      archive: vi.fn().mockResolvedValue(archive),
    };
    const saveArchive = vi.fn();
    const workspace = createWorkspace(client, saveArchive);
    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    const file = new File(["data_Si"], "Si.cif", { type: "chemical/x-cif" });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve("data_Si"),
    });
    await user.upload(screen.getByLabelText("Choose a CIF or POSCAR structure"), file);

    expect(await screen.findByText("Si1")).toBeInTheDocument();
    expect(await screen.findByLabelText("Crystal structure viewer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate recommendation" }));

    expect(await screen.findByText("Recommended setup")).toBeInTheDocument();
    expect(screen.getByText("Si.upf")).toBeInTheDocument();
    expect(screen.getByText(/&CONTROL/)).toBeInTheDocument();

    await user.click(screen.getByText("Scientific overrides"));
    await user.click(screen.getByRole("checkbox", { name: "Spin polarized" }));
    expect(screen.getByText("Review out of date")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download \.zip/ })).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Recompute recommendation" }),
    );
    await waitFor(() => {
      expect(reviewRequest).toHaveBeenLastCalledWith(
        expect.objectContaining({ hints: { spin_polarized: true } }),
      );
      expect(screen.queryByText("Review out of date")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Download \.zip/ }));
    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledWith(archive);
    });
  });

  it("has no detectable accessibility violations before a structure is loaded", async () => {
    const client: WorkbenchClient = {
      inspect: vi.fn(),
      review: vi.fn(),
      archive: vi.fn(),
    };
    const workspace = createWorkspace(client, vi.fn());
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
