import { describe, expect, it, vi } from "vitest";

import {
  CoreFailure,
  HttpCoreClient,
  type Capabilities,
  type ComputationResult,
  type ComputeRequest,
  type StructureInspection,
  type StructureSource,
} from "./coreClient";

const capabilities: Capabilities = {
  core_version: "1.2.3",
  default_intent: {
    code: "quantum_espresso",
    task: "scf_single_point",
    functional: "PBEsol",
    pseudo_accuracy: "efficiency",
  },
  default_hints: {},
  target_codes: ["quantum_espresso"],
  models: [],
  pseudopotential_sets: [],
  tasks: [],
};

const source: StructureSource = {
  kind: "inline",
  name: "Si.cif",
  format: "cif",
  content: "data_Si",
};

const inspection: StructureInspection = {
  schema_version: 1,
  canonical_cif: "data_Si",
  source: {
    origin: "inline",
    name: "Si.cif",
    format: "cif",
    content: "data_Si",
    sha256: "a".repeat(64),
    size_bytes: 7,
  },
  structure: {
    schema_version: 1,
    formula: "Si1",
    reduced_formula: "Si",
    site_count: 1,
    periodicity: [true, true, true],
    lattice: {
      vectors_angstrom: [
        [4, 0, 0],
        [0, 4, 0],
        [0, 0, 4],
      ],
      lengths_angstrom: [4, 4, 4],
      angles_degrees: [90, 90, 90],
      volume_angstrom3: 64,
    },
    sites: [],
  },
};

const request: ComputeRequest = {
  draft: {
    structure: source,
    intent: capabilities.default_intent,
    hints: capabilities.default_hints,
  },
  selection: { preset: "generate" },
};

const computationResult: ComputationResult = {
  schema_version: 1,
  task: "scf_single_point",
  task_revision: "1",
  selection: { preset: "generate" },
  publication: null,
  warnings: [],
  records: { generated_files: [{ path: "inputs/qe.in", role: "input", content: "&CONTROL\n/" }] },
  draft: {
    structure: inspection,
    intent: capabilities.default_intent,
    hints: {
      conv_thr: null,
      electron_maxstep: null,
      k_grid: null,
      k_spacing: null,
      mixing_beta: null,
      pseudo_accuracy: null,
      pseudo_type: null,
      relativistic_mode: null,
      smearing_type: null,
      smearing_width_ry: null,
      spin_orbit_coupling: null,
      spin_polarized: null,
      use_vdw: null,
      vdw_method: null,
    },
    pseudo_metadata: null,
    pseudo_root: null,
    pseudo_table: null,
    kmesh_model: null,
  },
};

describe("HttpCoreClient", () => {
  it("rejects JSON operations with the wrong content type", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(capabilities), {
        headers: { "Content-Type": "text/plain" },
      }),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(client.capabilities()).rejects.toMatchObject({
      kind: "invalid_response",
      message: "Goldilocks Core returned an invalid JSON response.",
      retryable: false,
      rawResponse: capabilities,
    });
  });

  it("reports a retryable network failure", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("connection refused"));
    const client = new HttpCoreClient("", fetcher);

    await expect(client.capabilities()).rejects.toMatchObject({
      name: "CoreFailure",
      kind: "network_error",
      message: "Cannot reach Goldilocks Core: connection refused",
      retryable: true,
      status: null,
    });
  });

  it("converts a Core error envelope into one typed failure", async () => {
    const payload = {
      error: {
        kind: "server_busy",
        message: "The computation slot is busy.",
        retryable: true,
        details: { retry_after_seconds: 0.5 },
      },
    };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(payload, { status: 503 }),
    );
    const client = new HttpCoreClient("", fetcher);

    const failure = await client
      .inspectStructure(source)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(CoreFailure);
    expect(failure).toMatchObject({
      kind: "server_busy",
      message: "The computation slot is busy.",
      retryable: true,
      details: { retry_after_seconds: 0.5 },
      status: 503,
      rawResponse: payload,
    });
  });

  it("loads Capabilities as generated Core types", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(capabilities),
    );
    const client = new HttpCoreClient("/core", fetcher);

    await expect(client.capabilities()).resolves.toEqual(capabilities);
    expect(fetcher).toHaveBeenCalledWith("/core/capabilities", {
      headers: { Accept: "application/json" },
      method: "GET",
    });
  });

  it("rejects an incompatible top-level result schema version", async () => {
    const incompatible = { ...computationResult, schema_version: 2 };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(incompatible),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(
      client.compute(request, { kind: "memory" }),
    ).rejects.toMatchObject({
      kind: "invalid_response",
      message: "Goldilocks Core returned an incompatible schema version.",
      retryable: false,
      status: 200,
      rawResponse: incompatible,
    });
  });

  it("rejects a successful archive response with the wrong content type", async () => {
    const payload = { error: { kind: "unexpected", message: "not a zip" } };
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(payload),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(
      client.compute(request, { kind: "archive" }),
    ).rejects.toMatchObject({
      kind: "invalid_response",
      retryable: false,
      rawResponse: payload,
    });
  });

  it("returns a ZIP download with its response filename", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response("zip bytes", {
        headers: {
          "Content-Disposition": 'attachment; filename="silicon-inputs.zip"',
          "Content-Type": "application/zip",
        },
      }),
    );
    const client = new HttpCoreClient("", fetcher);

    const archive = await client.compute(request, { kind: "archive" });

    expect(archive.filename).toBe("silicon-inputs.zip");
    await expect(archive.blob.text()).resolves.toBe("zip bytes");
    expect(fetcher.mock.calls[0]).toEqual([
      "/compute",
      {
        body: JSON.stringify({ ...request, output: { kind: "archive" } }),
        headers: {
          Accept: "application/zip",
          "Content-Type": "application/json",
        },
        method: "POST",
      },
    ]);
  });

  it("computes the generation Preset as memory JSON", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(computationResult),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(
      client.compute(request, { kind: "memory" }),
    ).resolves.toEqual(computationResult);
    expect(fetcher).toHaveBeenCalledWith("/compute", {
      body: JSON.stringify({ ...request, output: { kind: "memory" } }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("inspects an inline Structure Source through the Core operation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(inspection),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(client.inspectStructure(source)).resolves.toEqual(inspection);
    expect(fetcher).toHaveBeenCalledWith("/inspect", {
      body: JSON.stringify({ source }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });
});
