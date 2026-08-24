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
  it("exposes one named workflow with ordered setup, structure, and review regions", async () => {
    const workspace = createWorkspace(
      new CoreStub(Promise.resolve(capabilities)),
    );

    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    const main = await screen.findByRole("main", {
      name: "Goldilocks guided SCF preparation",
    });
    expect(main).toContainElement(
      screen.getByRole("heading", {
        level: 1,
        name: "Goldilocks guided SCF preparation",
      }),
    );
    expect(screen.getByRole("region", { name: "Calculation setup" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Structure workspace" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recommendation review" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Choose a CIF or POSCAR structure",
      }),
    ).toHaveAccessibleDescription("CIF or POSCAR · 5 MB maximum file size");
  });

  it("announces the current Workbench operation in a persistent status", async () => {
    const core = new CoreStub(Promise.resolve(capabilities));
    let finishInspection: (value: StructureInspection) => void = () => undefined;
    core.inspectionResults = [
      new Promise((resolve) => {
        finishInspection = resolve;
      }),
    ];
    const workspace = createWorkspace(core);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });

    expect(screen.getByRole("status", { name: "Workbench status" })).toHaveTextContent(
      "Ready",
    );
    await userEvent.upload(structureInput(container), structureFile());
    expect(screen.getByRole("status", { name: "Workbench status" })).toHaveTextContent(
      "Inspecting structure",
    );

    finishInspection(inspection);
  });

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
    expect(
      screen.getByRole("status", { name: "Archive status" }),
    ).toHaveTextContent("goldilocks-inputs.zip is ready");
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
    expect(
      screen.getByRole("status", { name: "Recommendation status" }),
    ).toHaveTextContent(/Review out of date.*Recompute before creating an archive\./);
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
    expect(screen.getByRole("status", { name: "Review state" })).toHaveTextContent(
      "Current",
    );
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

  it("announces scientific warnings returned with a recommendation", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.memoryResults = [
      Promise.resolve({
        ...computationResult,
        warnings: ["Review smearing before production use."],
      }),
    ];
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

    expect(
      await screen.findByRole("status", { name: "Scientific warnings" }),
    ).toHaveTextContent("Review smearing before production use.");
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

  it("opens only the latest file when an earlier read resolves last", async () => {
    const user = userEvent.setup();
    let finishFirstRead: (content: string) => void = () => undefined;
    const firstRead = new Promise<string>((resolve) => {
      finishFirstRead = resolve;
    });
    const first = new File(["A"], "A.cif");
    Object.defineProperty(first, "text", { value: () => firstRead });
    const second = new File(["B"], "B.cif");
    Object.defineProperty(second, "text", {
      value: () => Promise.resolve("structure B"),
    });
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    const workspace = createWorkspace(core);
    const { container } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    await screen.findByRole("button", {
      name: "Choose a CIF or POSCAR structure",
    });

    await user.upload(structureInput(container), first);
    await user.upload(structureInput(container), second);
    await waitFor(() => {
      expect(core.inspectedSources).toEqual([
        {
          kind: "inline",
          name: "B.cif",
          format: "cif",
          content: "structure B",
        },
      ]);
    });
    finishFirstRead("structure A");
    await firstRead;
    await Promise.resolve();

    expect(core.inspectedSources).toHaveLength(1);
    expect(workspace.getSnapshot().source).toMatchObject({ name: "B.cif" });
  });

  it("keeps retry available and dismiss hidden for a Capabilities failure", async () => {
    const failure = new CoreFailure(
      "assets_unavailable",
      "Runtime assets are unavailable.",
      false,
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
    expect(
      screen.queryByRole("button", { name: "Dismiss error" }),
    ).not.toBeInTheDocument();
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
