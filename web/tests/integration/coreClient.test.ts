import { describe, expect, it, vi } from "vitest";

import {
  CoreFailure,
  HttpCoreClient,
  findingsOf,
  type BlockingFinding,
  type ComputeRequest,
  type MagneticOrderingsRequest,
} from "../../src/api/coreClient";
import {
  capabilities,
  explainResult,
  inspection,
  runResult,
  structureInput,
} from "../support/workbenchFixtures";

const request: ComputeRequest = {
  structure_content: structureInput.structure_content,
  structure_name: structureInput.structure_name,
  structure_format: "cif",
  code: "quantum_espresso",
  task: "scf_single_point",
  hpc: null,
  overrides: {},
  fetch_missing: false,
};

const npoolFinding: BlockingFinding = {
  code: "parallelisation.npool_does_not_divide_ntasks",
  fields: ["npool", "ntasks"],
  message:
    "npool=7 does not divide ntasks=64, and pw.x refuses that layout. Unset npool for the default, or set npool to a divisor of ntasks.",
  summary:
    "npool must divide the job's task count: choose a divisor, or leave npool automatic.",
  remedies: [{ npool: null }],
};

describe("HttpCoreClient", () => {
  describe("capabilities", () => {
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

    it("rejects a vocabulary_version the frontend wasn't built against", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          Response.json({ ...capabilities, vocabulary_version: "3" }),
        );
      const client = new HttpCoreClient("", fetcher);

      await expect(client.capabilities()).rejects.toMatchObject({
        kind: "incompatible_vocabulary",
      });
    });

    it("rejects a response with the wrong content type", async () => {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify(capabilities), {
          headers: { "Content-Type": "text/plain" },
        }),
      );
      const client = new HttpCoreClient("", fetcher);

      await expect(client.capabilities()).rejects.toMatchObject({
        kind: "invalid_response",
        message: "Goldilocks Core returned an invalid JSON response.",
      });
    });

    it("reports a network failure", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockRejectedValue(new TypeError("connection refused"));
      const client = new HttpCoreClient("", fetcher);

      await expect(client.capabilities()).rejects.toMatchObject({
        name: "CoreFailure",
        kind: "network_error",
        message: "Cannot reach Goldilocks Core: connection refused",
        status: null,
      });
    });

    it("converts a Core error envelope into one typed failure", async () => {
      const payload = {
        error: {
          kind: "advice_incomplete",
          message:
            "cannot generate a runnable input: pseudopotential unavailable",
          details: { attempt: 2 },
        },
      };
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(payload, { status: 424 }));
      const client = new HttpCoreClient("", fetcher);

      const failure = await client
        .capabilities()
        .catch((error: unknown) => error);

      expect(failure).toBeInstanceOf(CoreFailure);
      expect(failure).toMatchObject({
        kind: "advice_incomplete",
        message: payload.error.message,
        details: { attempt: 2 },
        status: 424,
        rawResponse: payload,
      });
    });
  });

  describe("findingsOf", () => {
    it("reads the findings of a refused /run and leaves out what is not one", async () => {
      // #151: advice_incomplete carries the gate's findings, each with its
      // remedies, under details.findings.
      const payload = {
        error: {
          kind: "advice_incomplete",
          message: `cannot generate a runnable input: ${npoolFinding.message}`,
          details: {
            findings: [
              npoolFinding,
              { ...npoolFinding, fields: [7] },
              { ...npoolFinding, remedies: [["npool", null]] },
              {
                code: npoolFinding.code,
                fields: npoolFinding.fields,
                message: npoolFinding.message,
                remedies: npoolFinding.remedies,
              },
              { code: "advice.blocked", fields: [], remedies: [] },
              "npool=7",
              null,
            ],
          },
        },
      };
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(payload, { status: 422 }));
      const client = new HttpCoreClient("", fetcher);

      const failure = await client
        .run(request)
        .catch((error: unknown) => error);

      expect(failure).toBeInstanceOf(CoreFailure);
      expect(findingsOf(failure as CoreFailure)).toEqual([npoolFinding]);
    });

    it.each([
      { details: {} },
      { details: { findings: "npool=7" } },
      { details: { attempt: 2 } },
    ])(
      "finds no findings in a failure whose details are $details",
      ({ details }) => {
        expect(
          findingsOf(new CoreFailure("advice_incomplete", "x", details)),
        ).toEqual([]);
      },
    );
  });

  describe("inspectStructure", () => {
    it("posts the flattened structure body and requires a schema version", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(inspection));
      const client = new HttpCoreClient("", fetcher);

      await expect(client.inspectStructure(structureInput)).resolves.toEqual(
        inspection,
      );
      expect(fetcher).toHaveBeenCalledWith("/inspect", {
        body: JSON.stringify(structureInput),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });

    it("rejects a response missing schema_version", async () => {
      const withoutVersion: Record<string, unknown> = { ...inspection };
      delete withoutVersion.schema_version;
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(withoutVersion));
      const client = new HttpCoreClient("", fetcher);

      await expect(
        client.inspectStructure(structureInput),
      ).rejects.toMatchObject({
        kind: "invalid_response",
        message: "Goldilocks Core returned an incompatible schema version.",
      });
    });
  });

  describe("explain", () => {
    it("posts to /explain and returns records, warnings and blocking, no schema_version required", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(explainResult));
      const client = new HttpCoreClient("", fetcher);

      await expect(client.explain(request)).resolves.toEqual(explainResult);
      expect(fetcher).toHaveBeenCalledWith("/explain", {
        body: JSON.stringify(request),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });

    it("returns the findings /run would refuse with as a successful verdict", async () => {
      const blocked = {
        ...explainResult,
        blocking: [npoolFinding],
      };
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(blocked));
      const client = new HttpCoreClient("", fetcher);

      await expect(client.explain(request)).resolves.toEqual(blocked);
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(fetcher).toHaveBeenCalledWith("/explain", expect.anything());
    });

    it("surfaces advice_incomplete without ever having called /run", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          Response.json(
            { error: { kind: "advice_incomplete", message: "incomplete" } },
            { status: 424 },
          ),
        );
      const client = new HttpCoreClient("", fetcher);

      await expect(client.explain(request)).rejects.toMatchObject({
        kind: "advice_incomplete",
      });
      expect(fetcher).toHaveBeenCalledWith("/explain", expect.anything());
    });
  });

  describe("magneticOrderings", () => {
    const orderingsRequest: MagneticOrderingsRequest = {
      structure_content: structureInput.structure_content,
      structure_name: structureInput.structure_name,
      structure_format: "cif",
      rank_with_mmace: false,
    };

    it("posts to /magnetic-orderings with the caller's abort signal", async () => {
      const listing = { ranked: false, candidates: [], warnings: [] };
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(listing));
      const client = new HttpCoreClient("", fetcher);
      const controller = new AbortController();

      await expect(
        client.magneticOrderings(orderingsRequest, controller.signal),
      ).resolves.toEqual(listing);
      expect(fetcher).toHaveBeenCalledWith("/magnetic-orderings", {
        body: JSON.stringify(orderingsRequest),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        method: "POST",
        signal: controller.signal,
      });
    });

    it("rejects an aborted request with the abort, not a network failure", async () => {
      // #149: the Workbench aborts a listing whose structure was replaced;
      // that is not a failure to report, nor one to retry.
      const controller = new AbortController();
      controller.abort();
      const fetcher = vi
        .fn<typeof fetch>()
        .mockRejectedValue(controller.signal.reason);
      const client = new HttpCoreClient("", fetcher);

      const failure = await client
        .magneticOrderings(orderingsRequest, controller.signal)
        .catch((error: unknown) => error);

      expect(failure).toBe(controller.signal.reason);
      expect(failure).toMatchObject({ name: "AbortError" });
    });
  });

  describe("run", () => {
    it("posts to /run with respond_with: json and returns the file list", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(runResult));
      const client = new HttpCoreClient("", fetcher);

      await expect(client.run(request)).resolves.toEqual(runResult);
      expect(fetcher).toHaveBeenCalledWith("/run", {
        body: JSON.stringify({ ...request, respond_with: "json" }),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });
  });

  describe("runArchive", () => {
    it("posts to /run with respond_with: archive and returns a synthesized filename", async () => {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
        new Response("zip bytes", {
          headers: { "Content-Type": "application/zip" },
        }),
      );
      const client = new HttpCoreClient("", fetcher);

      const archive = await client.runArchive(request);

      expect(archive.filename).toBe("Si.cif-scf_single_point.zip");
      await expect(archive.blob.text()).resolves.toBe("zip bytes");
      expect(fetcher).toHaveBeenCalledWith("/run", {
        body: JSON.stringify({ ...request, respond_with: "archive" }),
        headers: {
          Accept: "application/zip",
          "Content-Type": "application/json",
        },
        method: "POST",
      });
    });

    it("rejects an archive response with the wrong content type", async () => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          Response.json({ files: [], records: {}, warnings: [] }),
        );
      const client = new HttpCoreClient("", fetcher);

      await expect(client.runArchive(request)).rejects.toMatchObject({
        kind: "invalid_response",
        message: "Goldilocks Core returned an invalid archive response.",
      });
    });
  });
});
