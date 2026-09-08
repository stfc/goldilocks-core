import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../../src/App";
import type {
  ArchiveDownload,
  Capabilities,
  ComputationResult,
  ComputeRequest,
  CoreClient,
  PreparedComputation,
  StructureInspection,
  StructureSource,
} from "../../src/api/coreClient";
import { CoreFailure } from "../../src/api/coreClient";
import {
  capabilities,
  computationResult,
  draft,
  inspection,
} from "../support/workbenchFixtures";
import { WorkspaceProvider } from "../../src/workspace/WorkspaceProvider";
import { createWorkspace } from "../../src/workspace/workspace";

vi.mock("../../src/viewer/StructureViewport", () => ({
  StructureViewport: () => (
    <div aria-label="Crystal structure viewer">3D crystal</div>
  ),
}));

class CoreStub implements CoreClient {
  inspectionResults: Promise<StructureInspection>[] = [];
  preparedResults: Promise<PreparedComputation>[] = [];
  inspectedSources: StructureSource[] = [];
  computeCalls: ComputeRequest[] = [];

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

  compute(request: ComputeRequest): Promise<PreparedComputation> {
    this.computeCalls.push(request);
    return (
      this.preparedResults.shift() ??
      Promise.reject(new Error("prepared computation not configured"))
    );
  }
}

function prepared(
  result: ComputationResult = computationResult,
  archive: ArchiveDownload | null = {
    blob: new Blob(["zip"]),
    filename: "goldilocks-inputs.zip",
  },
): PreparedComputation {
  return { result, archive };
}

describe("Goldilocks Workbench", () => {
  it("keeps table choices aligned with functional and accuracy changes", async () => {
    const user = userEvent.setup();
    const base = capabilities.pseudopotential_sets[0];
    if (base === undefined) throw new Error("Missing pseudopotential fixture");
    const tables = [
      base,
      { ...base, id: "pbe-efficiency", functional: "PBE" },
      {
        ...base,
        id: "pbe-precision",
        functional: "PBE",
        accuracy: "precision",
      },
    ];
    const core = new CoreStub(
      Promise.resolve({
        ...capabilities,
        pseudopotential_sets: tables,
      }),
    );
    core.inspectionResults = [Promise.resolve(inspection)];
    core.preparedResults = [Promise.resolve(prepared())];
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
    const table = await screen.findByLabelText("Pseudopotential table");
    await user.selectOptions(table, base.id);
    await user.selectOptions(screen.getByLabelText("Functional"), "PBE");
    expect(table).toHaveValue("");
    expect(
      within(table).queryByRole("option", { name: /PBEsol/ }),
    ).not.toBeInTheDocument();
    await user.selectOptions(table, "pbe-efficiency");
    await user.selectOptions(screen.getByLabelText("Accuracy"), "precision");
    expect(table).toHaveValue("");
    expect(
      within(table).queryByRole("option", { name: /efficiency/ }),
    ).not.toBeInTheDocument();
    await user.selectOptions(table, "pbe-precision");
    await user.click(
      screen.getByRole("button", { name: "Generate recommendation" }),
    );
    await screen.findByText("Recommended setup");
    expect(core.computeCalls[0]?.draft).toMatchObject({
      intent: { functional: "PBE", pseudo_accuracy: "precision" },
      pseudo_table: "pbe-precision",
    });
  });

  it("exposes a resizable two-panel structure workflow", async () => {
    const workspace = createWorkspace(
      new CoreStub(Promise.resolve(capabilities)),
    );

    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );

    expect(
      await screen.findByRole("region", { name: "Calculation setup" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Structure workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Recommendation results" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("separator", { name: "Resize calculation setup" }),
    ).toHaveAttribute("aria-valuenow", "34");
    expect(screen.getAllByRole("separator")).toHaveLength(1);
    expect(
      screen.getByRole("button", {
        name: "Choose a CIF or POSCAR structure",
      }),
    ).toHaveAccessibleDescription("CIF or POSCAR · 5 MB maximum file size");
  });

  it("uses light mode by default and persists an explicit dark mode", async () => {
    const user = userEvent.setup();
    const workspace = createWorkspace(
      new CoreStub(Promise.resolve(capabilities)),
    );
    const { unmount } = render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    const toggle = await screen.findByRole("button", {
      name: "Switch to dark mode",
    });

    await user.click(toggle);

    expect(
      screen.getByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();

    unmount();
    const restoredWorkspace = createWorkspace(
      new CoreStub(Promise.resolve(capabilities)),
    );
    render(
      <WorkspaceProvider workspace={restoredWorkspace}>
        <App />
      </WorkspaceProvider>,
    );
    expect(
      await screen.findByRole("button", { name: "Switch to light mode" }),
    ).toBeInTheDocument();
  });

  it("preserves the inspected viewport when switching theme", async () => {
    const user = userEvent.setup();
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
    await user.upload(structureInput(container), structureFile());
    const viewport = await screen.findByLabelText("Crystal structure viewer");
    await user.click(
      screen.getByRole("button", { name: "Switch to dark mode" }),
    );
    expect(screen.getByLabelText("Crystal structure viewer")).toBe(viewport);
    await user.click(
      screen.getByRole("button", { name: "Switch to light mode" }),
    );
    expect(screen.getByLabelText("Crystal structure viewer")).toBe(viewport);
  });

  it("resizes the calculation panel from the keyboard", async () => {
    const user = userEvent.setup();
    const workspace = createWorkspace(
      new CoreStub(Promise.resolve(capabilities)),
    );
    render(
      <WorkspaceProvider workspace={workspace}>
        <App />
      </WorkspaceProvider>,
    );
    const controls = await screen.findByRole("separator", {
      name: "Resize calculation setup",
    });
    controls.focus();
    await user.keyboard("{ArrowRight}");
    expect(controls).toHaveAttribute("aria-valuenow", "36");
    await user.keyboard("{ArrowLeft}");
    expect(controls).toHaveAttribute("aria-valuenow", "34");
  });

  it("announces the current Workbench operation in a persistent status", async () => {
    const core = new CoreStub(Promise.resolve(capabilities));
    let finishInspection: (value: StructureInspection) => void = () =>
      undefined;
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

    expect(
      screen.getByRole("status", { name: "Workbench status" }),
    ).toHaveTextContent("Ready");
    await userEvent.upload(structureInput(container), structureFile());
    expect(
      screen.getByRole("status", { name: "Workbench status" }),
    ).toHaveTextContent("Inspecting structure");

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
    core.preparedResults = [
      Promise.resolve(prepared(computationResult, archive)),
      Promise.resolve(prepared(computationResult, archive)),
    ];
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
      screen.getByRole("button", { name: "Update recommendation" }),
    );
    await waitFor(() => {
      expect(
        screen.queryByRole("status", { name: "Recommendation notice" }),
      ).not.toBeInTheDocument();
    });
    await user.click(
      screen.getByRole("button", { name: "Download input files (.zip)" }),
    );

    await waitFor(() => {
      expect(saveArchive).toHaveBeenCalledWith(archive);
    });
    expect(
      screen.getByRole("status", { name: "Archive status" }),
    ).toHaveTextContent("goldilocks-inputs.zip is ready");
    expect(core.computeCalls.slice(1)).toMatchObject([
      {
        draft: { hints: { spin_polarized: true } },
        selection: { preset: "generate" },
      },
    ]);
  });

  it("submits smearing treatment and width as one valid override", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.preparedResults = [Promise.resolve(prepared())];
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
    await user.click(screen.getByText("Scientific overrides"));
    await user.selectOptions(
      screen.getByLabelText("Smearing treatment"),
      "cold",
    );
    const width = screen.getByLabelText("Smearing width · Ry");
    expect(width).toBeEnabled();
    fireEvent.change(width, { target: { value: "0.02" } });

    await user.click(
      screen.getByRole("button", { name: "Generate recommendation" }),
    );

    expect(core.computeCalls[0]).toMatchObject({
      draft: {
        hints: {
          smearing_type: "cold",
          smearing_width_ry: 0.02,
        },
      },
      selection: { preset: "generate" },
    });
  });

  it("keeps the old Result visible and disables download after an edit", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.preparedResults = [Promise.resolve(prepared())];
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

    expect(
      screen.getByRole("status", { name: "Recommendation notice" }),
    ).toHaveTextContent(
      "Your settings changed. Update the recommendation before downloading.",
    );
    expect(screen.getByText("Recommended setup")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download input files (.zip)" }),
    ).toBeDisabled();
  });

  it("computes generation and renders canonical Core Records", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.preparedResults = [Promise.resolve(prepared())];
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
    const recommendation = screen.getByRole("region", {
      name: "Recommendation results",
    });
    expect(recommendation).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Structure workspace" }),
    ).not.toBeInTheDocument();
    expect(core.computeCalls[0]).toEqual({
      draft,
      selection: { preset: "generate" },
    });
    expect(screen.getByText("K Points")).toBeInTheDocument();
    expect(screen.getByText("Si.upf")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Generated input inputs/qe.in"),
    ).toHaveTextContent("&CONTROL");

    await user.click(screen.getByRole("button", { name: "Back to structure" }));
    expect(
      screen.getByRole("region", { name: "Structure workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Recommendation results" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Recommendation" }));
    expect(
      screen.getByRole("region", { name: "Recommendation results" }),
    ).toBeInTheDocument();
  });

  it("announces scientific warnings returned with a recommendation", async () => {
    const user = userEvent.setup();
    const core = new CoreStub(Promise.resolve(capabilities));
    core.inspectionResults = [Promise.resolve(inspection)];
    core.preparedResults = [
      Promise.resolve(
        prepared({
          ...computationResult,
          warnings: ["Review smearing before production use."],
        }),
      ),
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
    const tableSelect = screen.getByLabelText("Pseudopotential table");
    expect(
      Array.from(
        tableSelect.querySelectorAll("option"),
        (option) => option.value,
      ),
    ).toEqual([
      "",
      "pseudodojo-pbesol-efficiency-sr",
      "sssp-pbesol-efficiency-sr",
    ]);
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

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Runtime assets unavailable");
    expect(alert).toHaveTextContent("Runtime assets are unavailable.");
    const status = screen.getByRole("status", { name: "Workbench status" });
    expect(status).toHaveTextContent("Needs attention");
    expect(status).not.toHaveTextContent("Ready");
    expect(status).not.toHaveTextContent("Runtime assets are unavailable.");
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
      await screen.findByRole("heading", { name: "Loading Workbench" }),
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
