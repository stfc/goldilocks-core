import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type {
  ArchiveDownload,
  ArchiveOutput,
  Capabilities,
  ComputationResult,
  ComputeRequest,
  CoreClient,
  MemoryOutput,
  StructureInspection,
  StructureSource,
} from "./api/coreClient";
import { CoreFailure } from "./api/coreClient";
import {
  capabilities,
  computationResult,
  draft,
  inspection,
} from "./test/workbenchFixtures";
import { WorkspaceProvider } from "./workspace/WorkspaceProvider";
import { createWorkspace } from "./workspace/workspace";

vi.mock("./viewer/StructureViewport", () => ({
  StructureViewport: () => (
    <div aria-label="Crystal structure viewer">3D crystal</div>
  ),
}));

class CoreStub implements CoreClient {
  inspectionResults: Promise<StructureInspection>[] = [];
  memoryResults: Promise<ComputationResult>[] = [];
  archiveResults: Promise<ArchiveDownload>[] = [];
  inspectedSources: StructureSource[] = [];
  computeCalls: {
    request: ComputeRequest;
    output: MemoryOutput | ArchiveOutput;
  }[] = [];

  constructor(readonly capabilitiesResult: Promise<Capabilities>) {}

  capabilities(): Promise<Capabilities> {
    return this.capabilitiesResult;
  }

  inspectStructure(source: StructureSource): Promise<StructureInspection> {
    this.inspectedSources.push(source);
    return (
      this.inspectionResults.shift() ??
      Promise.reject(new Error("inspection not configured"))
    );
  }

  compute(
    _request: ComputeRequest,
    _output: MemoryOutput,
  ): Promise<ComputationResult>;
  compute(
    _request: ComputeRequest,
    _output: ArchiveOutput,
  ): Promise<ArchiveDownload>;
  compute(
    request: ComputeRequest,
    output: MemoryOutput | ArchiveOutput,
  ): Promise<ComputationResult | ArchiveDownload> {
    this.computeCalls.push({ request, output });
    return output.kind === "archive"
      ? (this.archiveResults.shift() ??
          Promise.reject(new Error("archive not configured")))
      : (this.memoryResults.shift() ??
          Promise.reject(new Error("memory compute not configured")));
  }
}

describe("Goldilocks Workbench", () => {
  it("recomputes edits before downloading the reviewed Draft", async () => {
    const user = userEvent.setup();
    const archive: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks-inputs.zip",
    };
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.memoryResults = [
      Promise.resolve(computationResult),
      Promise.resolve(computationResult),
    ];
    core.archiveResults = [Promise.resolve(archive)];
    const saveArchive = vi.fn<(download: ArchiveDownload) => void>();
    const workspace = createWorkspace(core, saveArchive);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });
    await user.upload(structureInput(container), structureFile());
    await user.click(
      await screen.findByRole("button", { name: "Generate recommendation" }),
    );
    await screen.findByText("Recommended setup");
    await user.click(screen.getByText("Scientific overrides"));
    await user.selectOptions(screen.getByLabelText("Spin treatment"), "true");

    await user.click(
      screen.getByRole("button", { name: "Recompute recommendation" }),
    );
    await waitFor(() => {
      expect(screen.queryByText("Review out of date")).not.toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /Download \.zip/ }));

    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledWith(archive);
    });
    expect(core.computeCalls.slice(1)).toEqual([
      {
        request: {
          draft: {
            ...draft,
            hints: { spin_polarized: true },
          },
          selection: { preset: "generate" },
        },
        output: { kind: "memory" },
      },
      {
        request: {
          draft: {
            ...draft,
            hints: { spin_polarized: true },
          },
          selection: { preset: "generate" },
        },
        output: { kind: "archive" },
      },
    ]);
  });

  it("keeps the old Result visible and disables download after an edit", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.memoryResults = [Promise.resolve(computationResult)];
    const workspace = createWorkspace(core, vi.fn());
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });
    await user.upload(structureInput(container), structureFile());
    await user.click(
      await screen.findByRole("button", { name: "Generate recommendation" }),
    );
    await screen.findByText("Recommended setup");

    await user.click(screen.getByText("Scientific overrides"));
    await user.selectOptions(screen.getByLabelText("Spin treatment"), "true");

    expect(screen.getByText("Review out of date")).toBeInTheDocument();
    expect(screen.getByText("Recommended setup")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download \.zip/ })).toBeDisabled();
  });

  it("computes generation and renders canonical Core Records", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.memoryResults = [Promise.resolve(computationResult)];
    const workspace = createWorkspace(core);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });
    await user.upload(structureInput(container), structureFile());

    await user.click(
      await screen.findByRole("button", { name: "Generate recommendation" }),
    );

    expect(await screen.findByText("Recommended setup")).toBeInTheDocument();
    expect(core.computeCalls[0]).toEqual({
      request: { draft, selection: { preset: "generate" } },
      output: { kind: "memory" },
    });
    expect(screen.getByText("K Points")).toBeInTheDocument();
    expect(screen.getByText("Si.upf")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Generated input inputs/qe.in"),
    ).toHaveTextContent("&CONTROL");
  });

  it("opens a CIF and builds calculation controls from Capabilities", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const workspace = createWorkspace(core);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    const file = new File(["data_Si"], "Si.cif", {
      type: "chemical/x-cif",
    });
    Object.defineProperty(file, "text", {
      value: () => Promise.resolve("data_Si"),
    });

    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });
    await user.upload(structureInput(container), file);

    expect(await screen.findByText("Si1")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Crystal structure viewer"),
    ).toBeInTheDocument();
    expect(core.inspectedSources).toEqual([
      {
        kind: "inline",
        name: "Si.cif",
        format: "cif",
        content: "data_Si",
      },
    ]);
    expect(screen.getByLabelText("Pseudopotential table")).toHaveTextContent(
      "pseudodojo · PseudoDojo fixture",
    );
  });

  it("presents a typed Capabilities failure with a retry action", async () => {
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
      true,
    );
    const workspace = createWorkspace(new CoreStub(Promise.reject(failure)));

    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Runtime assets unavailable",
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("announces Capabilities loading at startup", async () => {
    const pending = new Promise<Capabilities>(() => undefined);
    const workspace = createWorkspace(new CoreStub(pending));

    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "Loading Core capabilities" }),
    ).toBeInTheDocument();
  });
});

function structureFile(): File {
  const file = new File(["data_Si"], "Si.cif", {
    type: "chemical/x-cif",
  });
  Object.defineProperty(file, "text", {
    value: () => Promise.resolve("data_Si"),
  });
  return file;
}

function structureInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) throw new Error("structure input missing");
  return input;
}
