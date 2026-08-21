import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type {
  ArchiveDownload,
  Recommendation,
  WorkbenchClient,
} from "./api/workbenchClient";
import { inspection, recommendation } from "./test/workbenchFixtures";
import { WorkspaceProvider } from "./workspace/WorkspaceProvider";
import { createWorkspace } from "./workspace/workspace";

const viewerState = vi.hoisted(() => ({ fails: false }));

vi.mock("./viewer/StructureViewport", () => ({
  StructureViewport: () => {
    if (viewerState.fails) throw new Error("viewer failed");
    return <div aria-label="Crystal structure viewer">3D crystal</div>;
  },
}));

describe("Goldilocks Workbench", () => {
  beforeEach(() => {
    viewerState.fails = false;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("guides a structure through review, stale override, recompute, and archive", async () => {
    const user = userEvent.setup();
    const archive: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks.zip",
    };
    const reviewRequest = vi
      .fn<WorkbenchClient["review"]>()
      .mockResolvedValue(recommendation);
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: reviewRequest,
      archive: vi.fn().mockResolvedValue(archive),
    };
    const saveArchive = vi.fn();
    const workspace = createWorkspace(client, saveArchive);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    const file = new File(["data_Si"], "Si.cif", { type: "chemical/x-cif" });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve("data_Si"),
    });
    await user.upload(structureInput(container), file);

    expect(await screen.findByText("Si1")).toBeInTheDocument();
    expect(
      await screen.findByLabelText("Crystal structure viewer"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Generate recommendation" }),
    );

    expect(await screen.findByText("Recommended setup")).toBeInTheDocument();
    expect(screen.getByText("Si.upf")).toBeInTheDocument();
    expect(screen.getByText(/&CONTROL/)).toBeInTheDocument();

    await user.click(screen.getByText("Scientific overrides"));
    await user.click(
      screen.getByRole("checkbox", { name: "Set an explicit grid" }),
    );
    expect(screen.getByLabelText("K-point grid x")).toHaveValue(1);
    expect(screen.getByLabelText("K-point grid y")).toHaveValue(1);
    expect(screen.getByLabelText("K-point grid z")).toHaveValue(1);
    await user.selectOptions(screen.getByLabelText("Spin treatment"), "true");
    expect(screen.getByText("Review out of date")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Download \.zip/ }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Recompute recommendation" }),
    );
    await waitFor(() => {
      expect(reviewRequest).toHaveBeenCalledTimes(2);
      expect(reviewRequest.mock.lastCall?.[0].hints).toMatchObject({
        k_grid: [1, 1, 1],
        spin_polarized: true,
      });
      expect(screen.queryByText("Review out of date")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Download \.zip/ }));
    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledWith(archive);
    });
  });

  it("reports recommendation progress in the review rail", async () => {
    const user = userEvent.setup();
    let finishReview: (value: Recommendation) => void = () => undefined;
    const pendingReview = new Promise<Recommendation>((resolve) => {
      finishReview = resolve;
    });
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: vi.fn().mockReturnValue(pendingReview),
      archive: vi.fn(),
    };
    const workspace = createWorkspace(client, vi.fn());
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    await user.upload(structureInput(container), structureFile());
    await user.click(
      screen.getByRole("button", { name: "Generate recommendation" }),
    );

    expect(
      await screen.findByText("Computing recommendation"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Recommendation review")).toHaveAttribute(
      "aria-busy",
      "true",
    );

    finishReview(recommendation);
    expect(await screen.findByText("Recommended setup")).toBeInTheDocument();
  });

  it("contains viewer failures without losing the scientific workflow", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    viewerState.fails = true;
    const user = userEvent.setup();
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: vi.fn(),
      archive: vi.fn(),
    };
    const workspace = createWorkspace(client, vi.fn());
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    await user.upload(structureInput(container), structureFile());

    expect(
      await screen.findByText("3D preview unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Si · 1 atomic sites/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Generate recommendation" }),
    ).toBeEnabled();

    viewerState.fails = false;
    await user.click(screen.getByRole("button", { name: "Retry 3D preview" }));
    expect(await screen.findByText("3D crystal")).toBeInTheDocument();
  });

  it("disables calculation settings while inspecting a replacement", async () => {
    const user = userEvent.setup();
    let finishReplacement: (value: typeof inspection) => void = () => undefined;
    const pendingReplacement = new Promise<typeof inspection>((resolve) => {
      finishReplacement = resolve;
    });
    const client: WorkbenchClient = {
      inspect: vi
        .fn()
        .mockResolvedValueOnce(inspection)
        .mockReturnValueOnce(pendingReplacement),
      review: vi.fn(),
      archive: vi.fn(),
    };
    const workspace = createWorkspace(client, vi.fn());
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    await user.upload(structureInput(container), structureFile());
    expect(await screen.findByLabelText("Functional")).toBeEnabled();

    const replacement = new File(["Silicon"], "POSCAR", {
      type: "text/plain",
    });
    Object.defineProperty(replacement, "text", {
      value: () => Promise.resolve("Silicon"),
    });
    await user.upload(structureInput(container), replacement);

    expect(screen.getByLabelText("Functional")).toBeDisabled();
    expect(
      screen.getByText(/Inspecting the replacement structure/),
    ).toHaveAttribute("role", "status");

    finishReplacement(inspection);
    await waitFor(() => {
      expect(screen.getByLabelText("Functional")).toBeEnabled();
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

function structureInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) throw new Error("structure input missing");
  return input;
}

function structureFile(): File {
  const file = new File(["data_Si"], "Si.cif", { type: "chemical/x-cif" });
  Object.defineProperty(file, "text", {
    value: () => Promise.resolve("data_Si"),
  });
  return file;
}
