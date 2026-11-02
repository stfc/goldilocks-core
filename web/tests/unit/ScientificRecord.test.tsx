import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ResolvedField } from "../../src/api/coreClient";
import { buildArchive, buildDosArchive } from "../support/workbenchFixtures";
import { GeneratedInputReview } from "../../src/review/GeneratedInputReview";
import { ScientificRecord } from "../../src/review/ScientificRecord";

describe("ScientificRecord", () => {
  it("renders an unavailable field's reason", () => {
    const field: ResolvedField = {
      status: "unavailable",
      reason: "No pseudopotential table matches this structure.",
    };
    render(<ScientificRecord field={field} />, { wrapper: MantineProvider });

    expect(
      screen.getByText(/No pseudopotential table matches this structure\./),
    ).toBeInTheDocument();
  });

  it("renders a blocked field's upstream cause", () => {
    const field: ResolvedField = {
      status: "blocked",
      blocked_by: "pseudo_table",
    };
    render(<ScientificRecord field={field} />, { wrapper: MantineProvider });

    expect(screen.getByText(/pseudo_table/)).toBeInTheDocument();
  });

  it("renders a resolved field's source, nested value, and per-field sources", () => {
    const field: ResolvedField = {
      status: "resolved",
      value: { grid: [4, 6, 8], shift: [1, 0, 1], mesh_type: "monkhorst-pack" },
      source: "human",
      field_sources: { grid: "human", shift: "heuristic" },
    };
    render(<ScientificRecord field={field} />, { wrapper: MantineProvider });

    expect(screen.getAllByText("Your override").length).toBeGreaterThan(0);
    expect(screen.getByText("4, 6, 8")).toBeInTheDocument();
    expect(screen.getByText("monkhorst-pack")).toBeInTheDocument();
    expect(screen.getByText("Per-field sources")).toBeInTheDocument();
    expect(screen.getByText("Heuristic default")).toBeInTheDocument();
  });

  it("renders a record's own nested warnings inline", () => {
    const field: ResolvedField = {
      status: "resolved",
      value: {
        grid: [4, 6, 8],
        warnings: [
          {
            code: "kmesh.dense",
            level: "warning",
            category: "kmesh",
            message: "Check convergence for this mesh.",
          },
        ],
      },
      source: "heuristic",
    };
    render(<ScientificRecord field={field} />, { wrapper: MantineProvider });

    expect(
      screen.getByText("Check convergence for this mesh."),
    ).toBeInTheDocument();
  });
});

/** What the Bundle card passes while an archive is on its way. */
const PENDING = "Generating the input files for the current settings…";

describe("GeneratedInputReview", () => {
  it("says why there are no files while it has no archive", () => {
    // #150: the placeholder promised files even after generation failed;
    // the card now passes what its status says.
    render(
      <GeneratedInputReview
        archive={null}
        placeholder="No input files were generated: generation failed for the current settings."
      />,
      { wrapper: MantineProvider },
    );

    expect(
      screen.getByText(
        "No input files were generated: generation failed for the current settings.",
      ),
    ).toBeInTheDocument();
  });

  it("unzips a real archive and previews each file with its manifest digest", async () => {
    const user = userEvent.setup();
    const archive = buildArchive();
    render(<GeneratedInputReview archive={archive} placeholder={PENDING} />, {
      wrapper: MantineProvider,
    });

    // Files are ordered by their manifest role -- the rendered QE input
    // first, then the pseudopotential -- each collapsed by default
    // behind an accordion row rather than a tab.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /scf\.in/ }),
      ).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /scf\.in/ }));

    expect(
      screen.getByRole("region", { name: "Generated input scf.in" }),
    ).toHaveTextContent("&CONTROL");
    expect(screen.getByText("cccccccccc")).toBeInTheDocument();
  });

  it("lists the table's licence right after the pseudopotentials and shows its text", async () => {
    const user = userEvent.setup();
    const archive = buildArchive();
    render(<GeneratedInputReview archive={archive} placeholder={PENDING} />, {
      wrapper: MantineProvider,
    });

    const licence = await screen.findByRole("button", {
      name: /licences\/pseudodojo-pbesol-efficiency-sr\.txt/,
    });
    const paths = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((text) => /\.(in|upf|txt|json)/.test(text));
    expect(paths.map((text) => text.replace(/[0-9a-f]{10}$/, ""))).toEqual([
      "scf.in",
      "pseudo/Si.upf",
      "licences/pseudodojo-pbesol-efficiency-sr.txt",
      "goldilocks.json",
    ]);
    await user.click(licence);

    expect(
      screen.getByRole("region", {
        name: "Generated input licences/pseudodojo-pbesol-efficiency-sr.txt",
      }),
    ).toHaveTextContent("PseudoDojo pseudopotentials are CC BY 4.0.");
  });

  it("lists the inputs in the order their steps run, not by path", async () => {
    // #222: a dos bundle listed dos.in, nscf.in, scf.in, the reverse of the
    // order the job runs them in.
    render(
      <GeneratedInputReview
        archive={buildDosArchive()}
        placeholder={PENDING}
      />,
      { wrapper: MantineProvider },
    );

    await screen.findByRole("button", { name: /^scf\.in/ });
    const paths = screen
      .getAllByRole("button")
      .map((button) => button.textContent.replace(/[0-9a-f]{10}$/, ""));
    expect(paths).toEqual([
      "scf.in",
      "nscf.in",
      "dos.in",
      "submit.sh",
      "pseudo/Si.upf",
      "goldilocks.json",
    ]);
  });

  it("shows a pseudopotential's entries instead of its raw file content", async () => {
    const user = userEvent.setup();
    const archive = buildArchive();
    render(<GeneratedInputReview archive={archive} placeholder={PENDING} />, {
      wrapper: MantineProvider,
    });

    await user.click(await screen.findByRole("button", { name: /Si\.upf/ }));

    expect(screen.getByText("SHA-256")).toBeInTheDocument();
    expect(screen.queryByText("UPF content")).not.toBeInTheDocument();
  });
});
