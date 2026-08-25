import type { operations } from "./schema";

type CapabilitiesOperation = operations["capabilities_capabilities_get"];
type InspectOperation = operations["inspect_inspect_post"];
type ComputeOperation = operations["compute_compute_post"];
type ComputeDocument =
  ComputeOperation["requestBody"]["content"]["application/json"];

export type Capabilities =
  CapabilitiesOperation["responses"][200]["content"]["application/json"];
export type StructureSource =
  InspectOperation["requestBody"]["content"]["application/json"]["source"];
export type StructureInspection =
  InspectOperation["responses"][200]["content"]["application/json"];
export type CalculationDraft = ComputeDocument["draft"];
type ComputeResponse =
  ComputeOperation["responses"][200]["content"]["multipart/form-data"];
export type ComputationResult = ComputeResponse["result"];
export type ComputeRequest = ComputeDocument;

export interface ArchiveDownload {
  readonly blob: Blob;
  readonly filename: string;
}

export interface PreparedComputation {
  readonly result: ComputationResult;
  readonly archive: ArchiveDownload | null;
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
  compute(request: ComputeRequest): Promise<PreparedComputation>;
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
    return parseJson<Capabilities>(response);
  }

  async compute(request: ComputeRequest): Promise<PreparedComputation> {
    const response = await this.request("/compute", {
      body: JSON.stringify(request),
      headers: {
        Accept: "multipart/form-data",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parsePreparedComputation(response);
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

async function parseJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    const rawResponse = await decodeResponse(response);
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned an invalid JSON response.",
      false,
      {},
      response.status,
      rawResponse,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned unreadable JSON.",
      false,
      {},
      response.status,
    );
  }
}

async function parseVersionedJson<T>(response: Response): Promise<T> {
  const payload = await parseJson<unknown>(response);
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

async function parsePreparedComputation(
  response: Response,
): Promise<PreparedComputation> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned an invalid computation response.",
      false,
      {},
      response.status,
    );
  }

  let form: FormData;
  try {
    form = await response.formData();
  } catch {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned unreadable computation data.",
      false,
      {},
      response.status,
    );
  }

  const resultPart = form.get("result");
  if (!(resultPart instanceof Blob)) {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core omitted the reviewed computation.",
      false,
      {},
      response.status,
    );
  }

  let result: ComputationResult;
  try {
    const payload = JSON.parse(await resultPart.text()) as unknown;
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
    result = payload as ComputationResult;
  } catch (error) {
    if (error instanceof CoreFailure) throw error;
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned unreadable result JSON.",
      false,
      {},
      response.status,
    );
  }

  const archivePart = form.get("archive");
  if (archivePart === null) return { result, archive: null };
  if (!(archivePart instanceof Blob) || archivePart.type !== "application/zip") {
    throw new CoreFailure(
      "invalid_response",
      "Goldilocks Core returned an invalid prepared archive.",
      false,
      {},
      response.status,
    );
  }
  const filename =
    "name" in archivePart && typeof archivePart.name === "string"
      ? safeArchiveFilename(archivePart.name)
      : "goldilocks-inputs.zip";
  return {
    result,
    archive: { blob: archivePart, filename },
  };
}

function safeArchiveFilename(candidate: string): string {
  return candidate.length > 0 &&
    !candidate.includes("/") &&
    !candidate.includes("\\") &&
    candidate.toLowerCase().endsWith(".zip")
    ? candidate
    : "goldilocks-inputs.zip";
}
