import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { computationResult } from "../support/workbenchFixtures";
import { GeneratedInputReview } from "../../src/review/GeneratedInputReview";
import { PseudopotentialReview } from "../../src/review/PseudopotentialReview";
import { ScientificRecord } from "../../src/review/ScientificRecord";

describe("scientific record presentation", () => {
  it("keeps sampling shifts, override provenance, and warnings readable", () => {
    render(
      <ScientificRecord
        name="k_points"
        result={{
          ...computationResult,
          records: {
            k_points: {
              grid: [4, 6, 8],
              shift: [1, 0, 1],
              mesh_type: "monkhorst-pack",
              provenance: {
                source: "user_hint",
                reason: "Explicit grid supplied by the user.",
                confidence: null,
                data_source: null,
                details: { internal: { grid: [4, 6, 8] } },
                warnings: ["Check convergence for this mesh."],
              },
            },
          },
        }}
      />,
      { wrapper: MantineProvider },
    );
    expect(screen.getByText("4 × 6 × 8")).toBeInTheDocument();
    expect(screen.getByText("1 0 1")).toBeInTheDocument();
    expect(
      screen.getByText("Half-grid shift on flagged axes"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/includes Γ/)).not.toBeInTheDocument();
    expect(screen.getByText("Your override")).toBeInTheDocument();
    expect(
      screen.getByText("Explicit grid supplied by the user."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Check convergence for this mesh."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/internal/)).not.toBeInTheDocument();
  });

  it("shows publication digests and byte sizes from the archive manifest", () => {
    render(
      <>
        <ScientificRecord name="dft_input_data" result={computationResult} />
        <GeneratedInputReview result={computationResult} />
        <PseudopotentialReview result={computationResult} />
      </>,
      { wrapper: MantineProvider },
    );

    expect(screen.getByText("cccccccccc")).toBeInTheDocument();
    expect(screen.getByText("dddddddd")).toHaveAttribute(
      "title",
      "d".repeat(64),
    );
    expect(
      screen.getByText("inputs/qe.in · input · 11 bytes"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("pseudo/Si.upf · pseudopotential · 128 bytes"),
    ).toBeInTheDocument();
  });

  it.each([
    { name: "missing", manifest: {} },
    {
      name: "malformed",
      manifest: {
        files: {
          "inputs/qe.in": null,
          "pseudo/Si.upf": { sha256: 42, size_bytes: "128" },
        },
      },
    },
  ])(
    "keeps file review usable with $name manifest metadata",
    ({ manifest }) => {
      const inputData = computationResult.records.dft_input_data;
      if (inputData === undefined)
        throw new Error("Missing input data fixture");
      const result = {
        ...computationResult,
        records: {
          ...computationResult.records,
          dft_input_data: {
            ...inputData,
            manifest: { ...inputData.manifest, files: manifest.files },
          },
        },
      };
      render(
        <>
          <ScientificRecord name="dft_input_data" result={result} />
          <GeneratedInputReview result={result} />
          <PseudopotentialReview result={result} />
        </>,
        { wrapper: MantineProvider },
      );

      expect(screen.getByText("inputs/qe.in · input")).toBeInTheDocument();
      expect(
        screen.getByText("pseudo/Si.upf · pseudopotential"),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Generated input inputs/qe.in" }),
      ).toHaveTextContent("&CONTROL /");
      expect(screen.getByText("Si.upf")).toBeInTheDocument();
      expect(screen.queryByText("cccccccccc")).not.toBeInTheDocument();
      expect(screen.queryByText("dddddddd")).not.toBeInTheDocument();
      expect(screen.queryByText(/bytes/)).not.toBeInTheDocument();
    },
  );
});
