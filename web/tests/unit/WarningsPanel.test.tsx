import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecordWarning } from "../../src/api/coreClient";
import { WarningsPanel } from "../../src/review/WarningsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WarningsPanel", () => {
  it("lists every warning when records repeat a code", () => {
    // #152: a dos task's scf and nscf steps each raise an npool notice,
    // and one record can raise one code per element.
    const warnings: RecordWarning[] = [
      {
        code: "parallelisation.npool_load_imbalance",
        level: "info",
        category: "parallelisation",
        message: "npool=32 does not divide the 47 k-point/spin pairs evenly.",
        record: "parallelisation",
      },
      {
        code: "parallelisation.npool_load_imbalance",
        level: "info",
        category: "parallelisation",
        message: "npool=64 does not divide the 286 k-point/spin pairs evenly.",
        record: "nscf_parallelisation",
      },
      {
        code: "hubbard.u_value_missing",
        level: "warning",
        category: "hubbard",
        message: "No published Hubbard U value exists for Cf (5f).",
        record: "hubbard",
      },
      {
        code: "hubbard.u_value_missing",
        level: "warning",
        category: "hubbard",
        message: "No published Hubbard U value exists for Es (5f).",
        record: "hubbard",
      },
    ];
    const consoleError = vi.spyOn(console, "error");

    render(<WarningsPanel warnings={warnings} />, { wrapper: MantineProvider });

    for (const warning of warnings) {
      expect(screen.getByText(warning.message)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("listitem")).toHaveLength(warnings.length);
    // React reports colliding keys ("Encountered two children with the
    // same key") through console.error.
    expect(consoleError).not.toHaveBeenCalled();
  });
});
