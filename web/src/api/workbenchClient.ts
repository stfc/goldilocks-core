import type { components } from "./schema";
import { z } from "zod";

export type StructureSource = components["schemas"]["StructureSourceRequest"];
export type StructureInspection =
  components["schemas"]["StructureInspectionResponse"];
export type GuidedRequest = components["schemas"]["GuidedRequest"];
export type Recommendation = components["schemas"]["RecommendationResponse"];

const Vector3Schema = z.tuple([z.number(), z.number(), z.number()]);
const IntentSchema = z
  .object({
    code: z.string(),
    task: z.string(),
    functional: z.string(),
    pseudo_accuracy: z.enum(["efficiency", "precision"]),
  })
  .loose();
const HintsSchema = z
  .object({
    k_spacing: z.number().nullable().optional(),
    k_grid: Vector3Schema.nullable().optional(),
    smearing_type: z.string().nullable().optional(),
    smearing_width_ry: z.number().nullable().optional(),
    spin_polarized: z.boolean().nullable().optional(),
    spin_orbit_coupling: z.boolean().nullable().optional(),
    pseudo_accuracy: z.enum(["efficiency", "precision"]).nullable().optional(),
    pseudo_type: z.string().nullable().optional(),
    relativistic_mode: z.string().nullable().optional(),
    conv_thr: z.number().nullable().optional(),
    mixing_beta: z.number().nullable().optional(),
    electron_maxstep: z.number().int().nullable().optional(),
    use_vdw: z.boolean().nullable().optional(),
    vdw_method: z.string().nullable().optional(),
  })
  .loose();
const StructureSchema = z
  .object({
    schema_version: z.number().int(),
    formula: z.string(),
    reduced_formula: z.string(),
    site_count: z.number().int().nonnegative(),
    periodicity: z.tuple([z.boolean(), z.boolean(), z.boolean()]),
    source: z
      .object({
        name: z.string(),
        format: z.string(),
        sha256: z.string().regex(/^[0-9a-f]{64}$/),
        size_bytes: z.number().int().nonnegative(),
      })
      .loose(),
    lattice: z
      .object({
        vectors_angstrom: z.tuple([
          Vector3Schema,
          Vector3Schema,
          Vector3Schema,
        ]),
        lengths_angstrom: Vector3Schema,
        angles_degrees: Vector3Schema,
        volume_angstrom3: z.number().positive(),
      })
      .loose(),
    sites: z.array(
      z
        .object({
          fractional_coordinates: Vector3Schema,
          cartesian_coordinates_angstrom: Vector3Schema,
          species: z.array(
            z
              .object({
                symbol: z.string(),
                label: z.string(),
                occupancy: z.number().positive(),
                oxidation_state: z.number().nullable().optional(),
              })
              .loose(),
          ),
        })
        .loose(),
    ),
  })
  .loose();
const PseudoTableSchema = z
  .object({
    id: z.string(),
    version: z.string(),
    provider: z.string(),
    upstream_table: z.string(),
    functional: z.string(),
    accuracy: z.enum(["efficiency", "precision"]),
    relativistic: z.string(),
    licence: z.string(),
    citation: z.string(),
    elements: z.array(z.string()),
    default: z.boolean(),
  })
  .loose();
const GeneratedFileSchema = z
  .object({
    path: z.string(),
    role: z.string(),
    content: z.string(),
    sha256: z.string().regex(/^[0-9a-f]{64}$/),
  })
  .loose();
const SelectedPseudoSchema = z
  .object({
    relativistic: z.string().nullable(),
    element: z.string(),
    filename: z.string(),
    sha256: z.string().regex(/^[0-9a-f]{64}$/),
    functional: z.string().nullable(),
    ecutwfc_ry: z.number().nullable(),
    ecutrho_ry: z.number().nullable(),
    provenance: z.record(z.string(), z.unknown()),
    warnings: z.array(z.string()),
  })
  .loose();
const StructureInspectionSchema = z
  .object({
    structure: StructureSchema,
    canonical_cif: z.string(),
    defaults: z.object({ intent: IntentSchema, hints: HintsSchema }).loose(),
    pseudo_tables: z.array(PseudoTableSchema),
  })
  .loose();
const RecommendationDecisionsSchema = z.object({
  k_grid: z.tuple([z.number().int(), z.number().int(), z.number().int()]),
  k_shift: z.tuple([z.number().int(), z.number().int(), z.number().int()]),
  k_mesh_type: z.string(),
  spin_polarized: z.boolean(),
  spin_orbit_coupling: z.boolean(),
  smearing_type: z.string().nullable(),
  smearing_width_ry: z.number().nullable(),
  use_vdw: z.boolean(),
  pseudo_table_id: z.string(),
  pseudo_functional: z.string(),
  pseudo_accuracy: z.enum(["efficiency", "precision"]),
  pseudo_relativistic: z.string(),
});
const RuntimeModelSchema = z.object({
  name: z.string().nullable(),
  version: z.string().nullable(),
  model_type: z.string().nullable(),
  target: z.string().nullable(),
  feature_set: z.string().nullable(),
  source: z.string().nullable(),
  revision: z.string().nullable(),
});
const RuntimeAssetSchema = z.object({
  id: z.string(),
  version: z.string(),
  files: z.array(
    z.object({
      role: z.string(),
      path: z.string(),
      sha256: z
        .string()
        .regex(/^[0-9a-f]{64}$/)
        .nullable(),
      size_bytes: z.number().int().nullable(),
    }),
  ),
});
const RuntimeProvenanceSchema = z.object({
  goldilocks_core_version: z.string(),
  models: z.array(RuntimeModelSchema),
  model_assets: z.array(RuntimeAssetSchema),
});
const RecommendationSchema = z
  .object({
    schema_version: z.number().int(),
    review_digest: z.string().regex(/^[0-9a-f]{64}$/),
    structure: StructureSchema,
    canonical_cif: z.string(),
    intent: IntentSchema,
    hints: HintsSchema,
    decisions: RecommendationDecisionsSchema,
    runtime: RuntimeProvenanceSchema,
    records: z.record(z.string(), z.unknown()),
    generated_files: z.array(GeneratedFileSchema),
    selection: z
      .object({
        table: PseudoTableSchema,
        files: z.array(SelectedPseudoSchema),
        warnings: z.array(z.string()),
      })
      .loose(),
    warnings: z.array(z.string()),
  })
  .loose();
const ErrorEnvelopeSchema = z.object({
  error: z.object({
    kind: z.string(),
    message: z.string(),
    retryable: z.boolean().optional(),
    details: z.record(z.string(), z.unknown()).optional(),
  }),
});

export type FailureKind = string;

export class WorkbenchFailure extends Error {
  constructor(
    readonly kind: FailureKind,
    message: string,
    readonly retryable: boolean,
    readonly details: Readonly<Record<string, unknown>> = {},
    readonly status: number | null = null,
    readonly rawResponse?: unknown,
  ) {
    super(message);
    this.name = "WorkbenchFailure";
  }
}

export interface ArchiveDownload {
  readonly blob: Blob;
  readonly filename: string;
}

export interface WorkbenchClient {
  inspect(source: StructureSource): Promise<StructureInspection>;
  review(request: GuidedRequest): Promise<Recommendation>;
  archive(
    request: GuidedRequest,
    reviewDigest: string,
  ): Promise<ArchiveDownload>;
}

export class HttpWorkbenchClient implements WorkbenchClient {
  constructor(
    private readonly fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {}

  inspect(source: StructureSource): Promise<StructureInspection> {
    return this.requestJson(
      "/api/workbench/structure",
      { source },
      parseStructureInspection,
    );
  }

  review(request: GuidedRequest): Promise<Recommendation> {
    return this.requestJson(
      "/api/workbench/recommendation",
      request,
      parseRecommendation,
    );
  }

  async archive(
    request: GuidedRequest,
    reviewDigest: string,
  ): Promise<ArchiveDownload> {
    const response = await this.request("/api/workbench/archive", {
      ...request,
      review_digest: reviewDigest,
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().startsWith("application/zip")) {
      const decoded = await decodeResponse(response);
      throw new WorkbenchFailure(
        "invalid_response",
        "The server returned an invalid archive response.",
        false,
        {},
        response.status,
        decoded.payload,
      );
    }
    return {
      blob: await response.blob(),
      filename: archiveFilename(response.headers.get("content-disposition")),
    };
  }

  private async requestJson<T>(
    path: string,
    body: unknown,
    parse: (value: unknown) => T,
  ): Promise<T> {
    const response = await this.request(path, body);
    const decoded = await decodeResponse(response);
    if (!decoded.isJson) {
      throw new WorkbenchFailure(
        "invalid_response",
        "The server returned unreadable JSON.",
        false,
        {},
        response.status,
        decoded.payload,
      );
    }
    const payload = decoded.payload;
    try {
      return parse(payload);
    } catch {
      throw new WorkbenchFailure(
        "invalid_response",
        "The server response does not match the Workbench contract.",
        false,
        {},
        response.status,
        payload,
      );
    }
  }

  private async request(path: string, body: unknown): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (error) {
      throw new WorkbenchFailure(
        "network_error",
        error instanceof Error
          ? `Cannot reach the Goldilocks server: ${error.message}`
          : "Cannot reach the Goldilocks server.",
        true,
      );
    }
    if (!response.ok) {
      throw await failureFrom(response);
    }
    return response;
  }
}

async function failureFrom(response: Response): Promise<WorkbenchFailure> {
  const decoded = await decodeResponse(response);
  const payload = decoded.payload;
  const parsed = ErrorEnvelopeSchema.safeParse(payload);
  if (parsed.success) {
    return new WorkbenchFailure(
      parsed.data.error.kind,
      parsed.data.error.message,
      parsed.data.error.retryable ?? response.status >= 500,
      parsed.data.error.details ?? {},
      response.status,
      payload,
    );
  }
  return new WorkbenchFailure(
    "http_error",
    `The Goldilocks server rejected the request (${String(response.status)}).`,
    response.status >= 500,
    { status: response.status },
    response.status,
    payload,
  );
}

async function decodeResponse(
  response: Response,
): Promise<{ readonly payload: unknown; readonly isJson: boolean }> {
  const text = await response.text();
  try {
    return { payload: JSON.parse(text) as unknown, isJson: true };
  } catch {
    return { payload: text, isJson: false };
  }
}

function parseStructureInspection(value: unknown): StructureInspection {
  return StructureInspectionSchema.parse(value) as StructureInspection;
}

function parseRecommendation(value: unknown): Recommendation {
  return RecommendationSchema.parse(value) as Recommendation;
}

function archiveFilename(disposition: string | null): string {
  const match = /filename=(?:"([^"]+)"|([^;]+))/i.exec(disposition ?? "");
  const candidate = (
    match?.[1] ??
    match?.[2] ??
    "goldilocks-calculation.zip"
  ).trim();
  if (
    candidate.length === 0 ||
    candidate.includes("/") ||
    candidate.includes("\\") ||
    !candidate.toLowerCase().endsWith(".zip")
  ) {
    return "goldilocks-calculation.zip";
  }
  return candidate;
}
