import { strToU8, zipSync } from "fflate";
import { describe, expect, it, vi } from "vitest";

import {
  CoreFailure,
  HttpCoreClient,
  type ComputationResult,
  type ComputeRequest,
} from "../../src/api/coreClient";
import {
  capabilities,
  computationResult as inputDataResult,
  inspection,
  source,
} from "../support/workbenchFixtures";

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
  records: {
    generated_files: [
      { path: "inputs/qe.in", role: "input", content: "&CONTROL\n/" },
    ],
  },
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

function preparedResponse(
  result: unknown,
  archive?: BlobPart,
  filename = "goldilocks-inputs.zip",
): Response {
  const form = new FormData();
  form.set(
    "result",
    new Blob([JSON.stringify(result)], { type: "application/json" }),
    "result.json",
  );
  if (archive !== undefined) {
    form.set(
      "archive",
      new Blob([archive], { type: "application/zip" }),
      filename,
    );
  }
  const response = new Response(null, {
    headers: { "Content-Type": "multipart/form-data; boundary=test" },
  });
  vi.spyOn(response, "formData").mockResolvedValue(form);
  return response;
}

function manifestArchive(manifest: string): ArrayBuffer {
  return zipSync({
    "goldilocks.json": new Uint8Array(strToU8(manifest)),
    "pseudo/Si.upf": new Uint8Array(strToU8("UPF content")),
  }).buffer as ArrayBuffer;
}

describe("HttpCoreClient", () => {
  it("contains an archive filename supplied by an untrusted response", async () => {
    const client = new HttpCoreClient(
      "",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          preparedResponse(
            computationResult,
            "reviewed ZIP bytes",
            "../escape.zip",
          ),
        ),
    );

    const prepared = await client.compute(request);

    expect(prepared.archive?.filename).toBe("goldilocks-inputs.zip");
    await expect(prepared.archive?.blob.text()).resolves.toBe(
      "reviewed ZIP bytes",
    );
  });

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
        kind: "temporary_failure",
        message: "Temporary Core failure.",
        retryable: true,
        details: { attempt: 2 },
      },
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(payload, { status: 503 }));
    const client = new HttpCoreClient("", fetcher);

    const failure = await client
      .inspectStructure(source)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(CoreFailure);
    expect(failure).toMatchObject({
      kind: "temporary_failure",
      message: "Temporary Core failure.",
      retryable: true,
      details: { attempt: 2 },
      status: 503,
      rawResponse: payload,
    });
  });

  it("loads Capabilities as generated Core types", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(capabilities));
    const client = new HttpCoreClient("/core", fetcher);

    await expect(client.capabilities()).resolves.toEqual(capabilities);
    expect(fetcher).toHaveBeenCalledWith("/core/capabilities", {
      headers: { Accept: "application/json" },
      method: "GET",
    });
  });

  it("rejects an incompatible reviewed result schema version", async () => {
    const incompatible = { ...computationResult, schema_version: 2 };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(preparedResponse(incompatible));
    const client = new HttpCoreClient("", fetcher);

    await expect(client.compute(request)).rejects.toMatchObject({
      kind: "invalid_response",
      message: "Goldilocks Core returned an incompatible schema version.",
      retryable: false,
      status: 200,
      rawResponse: incompatible,
    });
  });

  it("rejects a computation response with the wrong content type", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json({
        error: { kind: "unexpected", message: "not multipart" },
      }),
    );
    const client = new HttpCoreClient("", fetcher);

    await expect(client.compute(request)).rejects.toMatchObject({
      kind: "invalid_response",
      message: "Goldilocks Core returned an invalid computation response.",
      retryable: false,
    });
  });

  it("returns one reviewed result with its exact ZIP", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        preparedResponse(computationResult, "zip bytes", "silicon-inputs.zip"),
      );
    const client = new HttpCoreClient("", fetcher);

    const prepared = await client.compute(request);

    expect(prepared.result).toEqual(computationResult);
    expect(prepared.archive?.filename).toBe("silicon-inputs.zip");
    await expect(prepared.archive?.blob.text()).resolves.toBe("zip bytes");
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/compute", {
      body: JSON.stringify(request),
      headers: {
        Accept: "multipart/form-data",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
  });

  it("enriches input data from the archive without replacing canonical result metadata", async () => {
    const manifest = {
      task: "archive-task",
      intent: { functional: "archive-functional" },
      files: {
        "inputs/qe.in": { sha256: "a".repeat(64), size_bytes: 11 },
        "pseudo/Si.upf": { sha256: "b".repeat(64), size_bytes: 128 },
      },
    };
    const archive = manifestArchive(JSON.stringify(manifest));
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        preparedResponse(inputDataResult, archive, "silicon-inputs.zip"),
      );
    const prepared = await new HttpCoreClient("", fetcher).compute(request);

    expect(prepared.result.task).toBe(inputDataResult.task);
    const reviewed = prepared.result.records.dft_input_data?.manifest;
    expect(reviewed?.files).toEqual(manifest.files);
    expect(reviewed?.intent.functional).toBe("PBEsol");
    expect(prepared.archive?.filename).toBe("silicon-inputs.zip");
    await expect(prepared.archive?.blob.arrayBuffer()).resolves.toEqual(
      archive,
    );
  });

  it.each([
    ["unreadable ZIP", "not a ZIP"],
    ["missing manifest", zipSync({}).buffer as ArrayBuffer],
    ["unreadable manifest JSON", manifestArchive("{")],
    ["null manifest", manifestArchive("null")],
    ["array manifest", manifestArchive("[]")],
  ])("rejects an input-data archive with %s", async (_reason, archive) => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(preparedResponse(inputDataResult, archive));

    await expect(
      new HttpCoreClient("", fetcher).compute(request),
    ).rejects.toMatchObject({
      name: "CoreFailure",
      kind: "invalid_response",
      retryable: false,
      status: 200,
    });
  });

  it("accepts a selected-record result without an archive", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(preparedResponse(inputDataResult));
    const client = new HttpCoreClient("", fetcher);

    await expect(client.compute(request)).resolves.toEqual({
      result: inputDataResult,
      archive: null,
    });
  });

  it("inspects an inline Structure Source through the Core operation", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(inspection));
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
