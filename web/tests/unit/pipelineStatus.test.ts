import { describe, expect, it } from "vitest";

import type { BlockingFinding } from "../../src/api/coreClient";
import { CoreFailure } from "../../src/api/coreClient";
import {
  bannerFailure,
  bundleStatus,
  currentArchive,
  currentFindings,
  downloadState,
  explainDue,
  needsAttention,
  previewDue,
} from "../../src/workspace/pipelineStatus";
import type {
  PipelineKey,
  WorkspaceSnapshot,
} from "../../src/workspace/workspace";
import {
  buildArchive,
  capabilities,
  draft,
  explainResult,
  inspection,
  structureInput,
} from "../support/workbenchFixtures";

const REVISION = 4;
const current: PipelineKey = { input: structureInput, revision: REVISION };
const olderRevision: PipelineKey = {
  input: structureInput,
  revision: REVISION - 1,
};
/** The same text in another StructureInput object: another structure. */
const otherInput: PipelineKey = {
  input: { ...structureInput },
  revision: REVISION,
};
const archive = buildArchive("Si.cif-scf_single_point.zip");
const reason: BlockingFinding = {
  code: "occupations.fixed_needs_tot_magnetization",
  fields: ["occupations", "tot_magnetization"],
  message:
    "occupations=fixed on a collinear spin-polarized run needs an integer tot_magnetization of the electron count's parity, and none was set or derived. Set occupations=smearing, or set tot_magnetization.",
  summary:
    "Fixed occupations on this spin-polarized run need an integer tot_magnetization: set one, or switch occupations to smearing.",
  remedies: [{ occupations: "smearing" }],
};
const npoolReason: BlockingFinding = {
  code: "parallelisation.npool_does_not_divide_ntasks",
  fields: ["npool", "ntasks"],
  message:
    "npool=7 does not divide ntasks=64, and pw.x refuses that layout. Unset npool for the default, or set npool to a divisor of ntasks.",
  summary:
    "npool must divide the job's task count: choose a divisor, or leave npool automatic.",
  remedies: [{ npool: null }],
};
/** A /run refused with `npoolReason`, and an entry that is no finding. */
const refusedWithFindings = new CoreFailure(
  "advice_incomplete",
  "cannot generate a runnable input: npool=7 does not divide ntasks=64.",
  { findings: [npoolReason, { message: "no code" }] },
  422,
);
const refusedRun = new CoreFailure(
  "generation_error",
  "Rutile TiO2 cannot be generated.",
  {},
  422,
);
const rejectedExplain = new CoreFailure(
  "invalid_setting",
  "is_metal must be metal or non_metal.",
  {},
  422,
);

/** An open Si structure at draft revision 4 with nothing settled yet. */
function snapshot(fields: Partial<WorkspaceSnapshot> = {}): WorkspaceSnapshot {
  return {
    capabilities,
    startupFailure: null,
    structureInput,
    inspection,
    inspectFailure: null,
    draft,
    clearedOverrides: [],
    revision: REVISION,
    reviewed: null,
    explain: null,
    preview: null,
    operation: null,
    magneticOrderings: null,
    ...fields,
  };
}

function explained(
  key: PipelineKey,
  blocking: readonly BlockingFinding[] = [],
) {
  const value = { ...explainResult, blocking };
  return { key, status: "result", value } as const;
}

function explainFailed(key: PipelineKey, dismissed = false) {
  return {
    key,
    status: "failure",
    failure: rejectedExplain,
    dismissed,
  } as const;
}

function previewed(key: PipelineKey) {
  return { key, status: "result", value: archive } as const;
}

function previewFailed(key: PipelineKey, dismissed = false) {
  return { key, status: "failure", failure: refusedRun, dismissed } as const;
}

/** A recommendation for the current draft, whose preview is `preview`. */
function generated(
  preview: WorkspaceSnapshot["preview"],
): Partial<WorkspaceSnapshot> {
  return { reviewed: explainResult, explain: explained(current), preview };
}

describe("bundleStatus", () => {
  it.each([
    {
      state: "no structure is open",
      fields: { structureInput: null, inspection: null, draft: null },
      kind: "empty",
    },
    {
      state: "the first recommendation is on its way",
      fields: {},
      kind: "computing",
    },
    {
      state: "the review is of an older revision",
      fields: { reviewed: explainResult, explain: explained(olderRevision) },
      kind: "recomputing",
    },
    {
      state: "the review is of another structure input",
      fields: { reviewed: explainResult, explain: explained(otherInput) },
      kind: "recomputing",
    },
    {
      state: "only an older revision's /explain failed",
      fields: {
        reviewed: explainResult,
        explain: explainFailed(olderRevision),
      },
      kind: "recomputing",
    },
    {
      state: "the current draft's /explain failed",
      fields: { reviewed: explainResult, explain: explainFailed(current) },
      kind: "explainFailed",
    },
    {
      state: "the current draft's /explain failed and was dismissed",
      fields: { explain: explainFailed(current, true) },
      kind: "explainFailed",
    },
    {
      state: "the current verdict blocks",
      fields: {
        reviewed: explainResult,
        explain: explained(current, [reason]),
      },
      kind: "blocked",
    },
    {
      state: "the preview is on its way",
      fields: generated(null),
      kind: "generating",
    },
    {
      state: "only an older revision's preview failed",
      fields: generated(previewFailed(olderRevision)),
      kind: "generating",
    },
    {
      state: "the preview is of another structure input",
      fields: generated(previewed(otherInput)),
      kind: "generating",
    },
    {
      state: "the current draft's preview failed",
      fields: generated(previewFailed(current)),
      kind: "generationFailed",
    },
    {
      state: "the current draft's preview failed and was dismissed",
      fields: generated(previewFailed(current, true)),
      kind: "generationFailed",
    },
    {
      state: "the current draft's archive arrived",
      fields: generated(previewed(current)),
      kind: "ready",
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly kind: string;
  }[])("is $kind when $state", ({ fields, kind }) => {
    expect(bundleStatus(snapshot(fields)).kind).toBe(kind);
  });

  it("carries the failure and the verdict's findings", () => {
    expect(bundleStatus(snapshot({ explain: explainFailed(current) }))).toEqual(
      { kind: "explainFailed", failure: rejectedExplain },
    );
    expect(
      bundleStatus(snapshot({ explain: explained(current, [reason]) })),
    ).toEqual({ kind: "blocked", findings: [reason] });
    expect(bundleStatus(snapshot(generated(previewFailed(current))))).toEqual({
      kind: "generationFailed",
      failure: refusedRun,
    });
    expect(bundleStatus(snapshot(generated(previewed(current))))).toEqual({
      kind: "ready",
      archive,
    });
  });
});

describe("downloadState", () => {
  it.each([
    {
      state: "no structure",
      fields: { structureInput: null, inspection: null, draft: null },
      reason: "Load a structure to generate input files.",
    },
    {
      state: "the first recommendation is on its way",
      fields: {},
      reason: "Waiting for the recommendation.",
    },
    {
      state: "the review is of an older revision",
      fields: { reviewed: explainResult, explain: explained(olderRevision) },
      reason: "Waiting for the recommendation for the current settings.",
    },
    {
      state: "the current /explain failed",
      fields: { explain: explainFailed(current, true) },
      reason:
        "The recommendation for the current settings failed: is_metal must be metal or non_metal.",
    },
    {
      state: "the verdict blocks",
      fields: { explain: explained(current, [reason, npoolReason]) },
      reason: `Input files cannot be generated for the current settings: ${reason.summary} ${npoolReason.summary}`,
    },
    {
      state: "the preview is on its way",
      fields: generated(null),
      reason: "Generating the input files for the current settings.",
    },
    {
      state: "the current preview failed",
      fields: generated(previewFailed(current, true)),
      reason:
        "Input generation failed for the current settings: Rutile TiO2 cannot be generated.",
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly reason: string;
  }[])("is disabled with a reason when $state", ({ fields, reason }) => {
    expect(downloadState(snapshot(fields))).toEqual({
      enabled: false,
      reason,
    });
  });

  it("gives the messages of a refused preview's findings, not its remedies", () => {
    const refused = generated({
      key: current,
      status: "failure",
      failure: refusedWithFindings,
      dismissed: false,
    });

    expect(downloadState(snapshot(refused))).toEqual({
      enabled: false,
      reason: `Input generation failed for the current settings: ${npoolReason.summary}`,
    });
  });

  it("is enabled, with no reason, once the current draft's archive arrived", () => {
    const ready = snapshot(generated(previewed(current)));

    expect(downloadState(ready)).toEqual({ enabled: true, reason: null });
    expect(currentArchive(ready)).toBe(archive);
    expect(currentArchive(snapshot(generated(previewed(olderRevision))))).toBe(
      null,
    );
  });
});

describe("bannerFailure", () => {
  const unavailable = new CoreFailure(
    "assets_unavailable",
    "Runtime assets are unavailable.",
  );
  const unreadable = new CoreFailure(
    "invalid_structure",
    "Unreadable structure.",
    {},
    422,
  );

  it("shows a capabilities failure, which nothing else can replace", () => {
    expect(
      bannerFailure(
        snapshot({
          capabilities: null,
          structureInput: null,
          inspection: null,
          draft: null,
          startupFailure: unavailable,
        }),
      ),
    ).toEqual({ operation: "capabilities", failure: unavailable });
  });

  it("shows a structure that could not be opened before the open structure's failure", () => {
    const failed = snapshot({
      inspectFailure: {
        input: { ...structureInput, structure_name: "broken.cif" },
        failure: unreadable,
      },
      explain: explainFailed(current),
    });

    expect(bannerFailure(failed)).toEqual({
      operation: "inspect",
      failure: unreadable,
    });
    expect(bannerFailure({ ...failed, inspectFailure: null })).toEqual({
      operation: "explain",
      failure: rejectedExplain,
    });
  });

  it.each([
    {
      state: "the current preview failed",
      fields: generated(previewFailed(current)),
      shown: { operation: "preview", failure: refusedRun },
    },
    {
      state: "the current preview failure was dismissed",
      fields: generated(previewFailed(current, true)),
      shown: null,
    },
    {
      state: "only an older revision's /explain failed",
      fields: { explain: explainFailed(olderRevision) },
      shown: null,
    },
    {
      state: "only another structure input's preview failed",
      fields: generated(previewFailed(otherInput)),
      shown: null,
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly shown: ReturnType<typeof bannerFailure>;
  }[])("shows $shown when $state", ({ fields, shown }) => {
    expect(bannerFailure(snapshot(fields))).toEqual(shown);
  });
});

describe("needsAttention", () => {
  it.each([
    { state: "nothing has settled yet", fields: {}, attention: false },
    {
      state: "the current draft's archive arrived",
      fields: generated(previewed(current)),
      attention: false,
    },
    {
      state: "capabilities could not be loaded",
      fields: {
        capabilities: null,
        structureInput: null,
        inspection: null,
        draft: null,
        startupFailure: new CoreFailure("network_error", "No Core."),
      },
      attention: true,
    },
    {
      state: "a structure could not be opened",
      fields: {
        inspectFailure: {
          input: otherInput.input,
          failure: new CoreFailure("invalid_structure", "Unreadable."),
        },
      },
      attention: true,
    },
    {
      state: "the current /explain failed and was dismissed",
      fields: { explain: explainFailed(current, true) },
      attention: true,
    },
    {
      state: "the current verdict blocks",
      fields: { explain: explained(current, [reason]) },
      attention: true,
    },
    {
      state: "the current preview failed",
      fields: generated(previewFailed(current)),
      attention: true,
    },
    {
      state: "only an older revision's preview failed",
      fields: generated(previewFailed(olderRevision)),
      attention: false,
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly attention: boolean;
  }[])("is $attention when $state", ({ fields, attention }) => {
    expect(needsAttention(snapshot(fields))).toBe(attention);
  });
});

describe("explainDue and previewDue", () => {
  it.each([
    { state: "the draft has no outcome", fields: {}, due: true },
    {
      state: "a request is in flight",
      fields: { operation: "explain" },
      due: false,
    },
    {
      state: "the current draft's /explain failed",
      fields: { explain: explainFailed(current, true) },
      due: false,
    },
    {
      state: "only an older revision's /explain failed",
      fields: { explain: explainFailed(olderRevision) },
      due: true,
    },
    {
      state: "no structure is open",
      fields: { structureInput: null, inspection: null, draft: null },
      due: false,
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly due: boolean;
  }[])("sends /explain ($due) when $state", ({ fields, due }) => {
    expect(explainDue(snapshot(fields))).toBe(due);
  });

  it.each([
    {
      state: "the current recommendation arrived without blocking reasons",
      fields: generated(null),
      due: true,
    },
    {
      state: "the current verdict blocks",
      fields: { explain: explained(current, [reason]) },
      due: false,
    },
    {
      state: "the recommendation is of an older revision",
      fields: { explain: explained(olderRevision) },
      due: false,
    },
    {
      state: "the current draft's preview failed",
      fields: generated(previewFailed(current, true)),
      due: false,
    },
    {
      state: "only an older revision's preview failed",
      fields: generated(previewFailed(olderRevision)),
      due: true,
    },
    {
      state: "a request is in flight",
      fields: { ...generated(null), operation: "inspect" },
      due: false,
    },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
    readonly due: boolean;
  }[])("sends the preview /run ($due) when $state", ({ fields, due }) => {
    expect(previewDue(snapshot(fields))).toBe(due);
  });
});

describe("currentFindings", () => {
  it("is the current verdict's findings, whatever the preview did", () => {
    expect(
      currentFindings(
        snapshot({ explain: explained(current, [reason, npoolReason]) }),
      ),
    ).toEqual([reason, npoolReason]);
  });

  it("is the findings a refused preview returned, malformed entries left out", () => {
    const preview = {
      key: current,
      status: "failure",
      failure: refusedWithFindings,
      dismissed: true,
    } as const;

    expect(currentFindings(snapshot(generated(preview)))).toEqual([
      npoolReason,
    ]);
  });

  it.each([
    { state: "nothing has settled", fields: {} },
    {
      state: "the verdict blocks an older revision",
      fields: { explain: explained(olderRevision, [reason]) },
    },
    {
      state: "a preview of an older revision was refused",
      fields: generated({
        key: olderRevision,
        status: "failure",
        failure: refusedWithFindings,
        dismissed: false,
      }),
    },
    {
      state: "the preview failed without findings",
      fields: generated(previewFailed(current)),
    },
    { state: "the archive arrived", fields: generated(previewed(current)) },
  ] satisfies readonly {
    readonly state: string;
    readonly fields: Partial<WorkspaceSnapshot>;
  }[])("is empty when $state", ({ fields }) => {
    expect(currentFindings(snapshot(fields))).toEqual([]);
  });
});
