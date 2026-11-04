import { describe, expect, it } from "vitest";

import type { RecordLayout } from "../../src/api/coreClient";
import {
  analysisRecordNames,
  readOnlyAdvisorRecords,
} from "../../src/workspace/recordGroups";
import { capabilities } from "../support/workbenchFixtures";

const scf: RecordLayout = {
  analysis: ["composition", "is_metal", "needs_soc", "symmetry"],
  system: ["functional", "pseudopotentials", "relativistic", "magnetic"],
  steps: [{ name: "scf", records: ["k_sampling", "n_irr_k", "job"] }],
};

const dos: RecordLayout = {
  ...scf,
  steps: [
    { name: "scf", records: ["k_sampling", "n_irr_k", "job"] },
    { name: "nscf", records: ["nscf_k_sampling", "nscf_n_irr_k"] },
    { name: "dos", records: ["dos"] },
  ],
};

const shown = new Set([
  "functional",
  "magnetic",
  "k_sampling",
  "n_irr_k",
  "job",
  "dos",
]);

describe("analysisRecordNames", () => {
  it("lists the analysis tier's records other than the facts", () => {
    expect(analysisRecordNames(scf, capabilities.facts)).toEqual([
      "composition",
      "symmetry",
    ]);
  });
});

describe("readOnlyAdvisorRecords", () => {
  it("lists a one-step task's unshown records without a step", () => {
    expect(
      readOnlyAdvisorRecords(
        { ...scf, steps: [{ name: "scf", records: ["k_sampling", "nbnd"] }] },
        shown,
      ),
    ).toEqual({
      ungrouped: ["pseudopotentials", "relativistic", "nbnd"],
      steps: [],
    });
  });

  it("keeps each step's unshown records under the step of a multi-step task", () => {
    expect(readOnlyAdvisorRecords(dos, shown)).toEqual({
      ungrouped: ["pseudopotentials", "relativistic"],
      steps: [{ name: "nscf", records: ["nscf_k_sampling", "nscf_n_irr_k"] }],
    });
  });
});
