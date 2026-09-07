import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { computationResult } from "../support/workbenchFixtures";
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
});
