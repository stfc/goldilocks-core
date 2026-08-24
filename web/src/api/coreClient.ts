import type { components, operations } from "./schema";

export type Capabilities = components["schemas"]["Capabilities"];
export type StructureSource = components["schemas"]["InlineStructureSource"];
export type StructureInspection = components["schemas"]["StructureInspection"];
export type CalculationDraft = components["schemas"]["CalculationDraft"];
export type ComputationResult = components["schemas"]["ComputationResult"];
export type ComputeRequest = Omit<
  operations["compute_compute_post"]["requestBody"]["content"]["application/json"],
  "output"
>;
export type MemoryOutput = components["schemas"]["MemoryOutput"];
export type ArchiveOutput = components["schemas"]["HttpArchiveOutput"];
export type ComputeOutput = MemoryOutput | ArchiveOutput;

export interface ArchiveDownload {
  readonly blob: Blob;
  readonly filename: string;
}

export class CoreFailure extends Error {
  constructor(
    readonly kind: string,
    message: string,
    readonly retryable: boolean,
    readonly details: Readonly<Record<string, unknown>> = {},
    readonly status: number | null = null,
    readonly rawResponse?: unknown,
  ) {
    super(message);
    this.name = "CoreFailure";
  }
}

export interface CoreClient {
  capabilities(): Promise<Capabilities>;
  inspectStructure(source: StructureSource): Promise<StructureInspection>;
  compute(
    request: ComputeRequest,
    output: MemoryOutput,
  ): Promise<ComputationResult>;
  compute(
    request: ComputeRequest,
    output: ArchiveOutput,
  ): Promise<ArchiveDownload>;
}

export class HttpCoreClient implements CoreClient {
  private readonly baseUrl: string;

  constructor(
    baseUrl = "",
    private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async capabilities(): Promise<Capabilities> {
    const response = await this.request("/capabilities", {
      headers: { Accept: "application/json" },
      method: "GET",
    });
    return (await response.json()) as Capabilities;
  }

  compute(
    request: ComputeRequest,
    output: MemoryOutput,
  ): Promise<ComputationResult>;
  compute(
    request: ComputeRequest,
    output: ArchiveOutput,
  ): Promise<ArchiveDownload>;
  async compute(
    request: ComputeRequest,
    output: ComputeOutput,
  ): Promise<ComputationResult | ArchiveDownload> {
    const response = await this.request("/compute", {
      body: JSON.stringify({ ...request, output }),
      headers: {
        Accept:
          output.kind === "archive" ? "application/zip" : "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    if (output.kind === "archive") {
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.toLowerCase().startsWith("application/zip")) {
        const rawResponse = await decodeResponse(response);
        throw new CoreFailure(
          "invalid_response",
          "Goldilocks Core returned an invalid archive response.",
          false,
          {},
          response.status,
          rawResponse,
        );
      }
      return {
        blob: await response.blob(),
        filename: archiveFilename(
          response.headers.get("content-disposition"),
        ),
      };
    }
    return parseVersionedJson<ComputationResult>(response);
  }

  async inspectStructure(
    source: StructureSource,
  ): Promise<StructureInspection> {
    const response = await this.request("/inspect", {
      body: JSON.stringify({ source }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parseVersionedJson<StructureInspection>(response);
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, init);
    } catch (error) {
      throw new CoreFailure(
        "network_error",
        error instanceof Error
          ? `Cannot reach Goldilocks Core: ${error.message}`
          : "Cannot reach Goldilocks Core.",
        true,
      );
    }
    await ensureSuccess(response);
    return response;
  }
}

async function parseVersionedJson<T>(response: Response): Promise<T> {
  let payload: unknown;
  try {
    payload = (await response.json()) as unknown;
  } catch {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned unreadable JSON.",
      false,
      {},
      response.status,
    );
  }
  if (
    payload === null ||
    typeof payload !== "object" ||
    !("schema_version" in payload) ||
    payload.schema_version !== 1
  ) {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned an incompatible schema version.",
      false,
      {},
      response.status,
      payload,
    );
  }
  return payload as T;
}

async function ensureSuccess(response: Response): Promise<void> {
  if (response.ok) return;
  const rawResponse = await decodeResponse(response);
  if (isErrorEnvelope(rawResponse)) {
    const { error } = rawResponse;
    throw new CoreFailure(
      error.kind,
      error.message,
      error.retryable ?? response.status >= 500,
      error.details ?? {},
      response.status,
      rawResponse,
    );
  }
  throw new CoreFailure(
    "http_error",
    `The Goldilocks Core server rejected the request (${String(response.status)}).`,
    response.status >= 500,
    { status: response.status },
    response.status,
    rawResponse,
  );
}

async function decodeResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function isErrorEnvelope(
  value: unknown,
): value is {
  readonly error: {
    readonly kind: string;
    readonly message: string;
    readonly retryable?: boolean | null;
    readonly details?: Readonly<Record<string, unknown>> | null;
  };
} {
  if (value === null || typeof value !== "object" || !("error" in value)) {
    return false;
  }
  const error = value.error;
  return (
    error !== null &&
    typeof error === "object" &&
    "kind" in error &&
    typeof error.kind === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}

function archiveFilename(disposition: string | null): string {
  const match = /filename=(?:"([^"]+)"|([^;]+))/i.exec(disposition ?? "");
  const candidate = (match?.[1] ?? match?.[2] ?? "goldilocks-inputs.zip").trim();
  if (
    candidate.length === 0 ||
    candidate.includes("/") ||
    candidate.includes("\\") ||
    !candidate.toLowerCase().endsWith(".zip")
  ) {
    return "goldilocks-inputs.zip";
  }
  return candidate;
}
