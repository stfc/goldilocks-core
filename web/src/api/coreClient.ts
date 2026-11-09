import type { components } from "./schema";

// Request bodies are generated from openapi.json (FastAPI infers a real
// schema from these pydantic models). Response bodies are NOT generated:
// every route in src/goldilocks_core/server/http.py returns a bare
// dict/TypedDict (typed `Any`), so FastAPI has nothing to build an
// OpenAPI response schema from and openapi-typescript resolves every
// 200 response to `unknown`. The response types below are hand-authored
// to mirror the real Python shapes; see the comment above each group for
// its source of truth.
export type StructureInput = components["schemas"]["InlineStructureDocument"];
export type ComputeRequest = components["schemas"]["ComputeRequestDocument"];
export type CalcTask = ComputeRequest["task"];
export type MagneticOrderingsRequest =
  components["schemas"]["MagneticOrderingsRequestDocument"];

export type Source = "human" | "ml" | "llm" | "heuristic";
export type FieldStatus = "resolved" | "unavailable" | "blocked";

/** Mirrors a published record, `resolution.ResolvedField` as
 * `records_document` projects it: a resolved record carries every
 * `resolution.Provenance` field. */
export interface ResolvedField<T = unknown> {
  readonly status: FieldStatus;
  readonly value?: T | null;
  readonly source?: Source | null;
  readonly field_sources?: Readonly<Record<string, Source>> | null;
  /** The records whose answers this record's rule followed, by name. */
  readonly derived_from?: readonly string[];
  /** The advisor's rationale, where it gives one. */
  readonly source_note?: string | null;
  /** The model that decided the value or one of its settings (a
   * `field_sources` entry `ml`). */
  readonly model?: ModelEvidence | null;
  /** What to cite for the value (a model's or the table's citation). */
  readonly citations?: readonly string[];
  readonly reason?: string | null;
  readonly blocked_by?: string | null;
}

/** Mirrors `resolution.Warning`. */
export interface AdvisorWarning {
  readonly code: string;
  readonly level: "info" | "warning" | "error";
  readonly category: string;
  readonly message: string;
}

/** Mirrors `resolution.ModelEvidence`: what a registered model returned,
 * verbatim (#156). */
export interface ModelEvidence {
  /** goldilocks-ml's id, e.g. `metallicity.is_metal.cgcnn@crystal_graph.v1`. */
  readonly model_id: string;
  /** The installed release, `<id>@<version>`. */
  readonly asset: string;
  readonly target_contract: string;
  readonly value: unknown;
  /** As returned: a classifier's `score`/`threshold`, QRF95's `interval`. */
  readonly details: Readonly<Record<string, unknown>>;
  readonly warnings: readonly AdvisorWarning[];
}

/** One entry of a response's top-level `warnings` (`resolution
 * .collect_warnings`): a record's warning, naming the record it came from
 * (`nscf_parallelisation` for a dos task's nscf step,
 * `bands_parallelisation` for a band task's bands step, `phonon` for a
 * phonon task's ph step). */
export interface RecordWarning extends AdvisorWarning {
  readonly record: string;
}

// ---------------------------------------------------------------------
// GET /capabilities -- mirrors capabilities.py's `Capabilities` TypedDict
// and the Setting/Fact projections `_settings()`/`_facts()` build.
// ---------------------------------------------------------------------

/** Where a setting's resolved value is published (#187): `record` names
 * the record of the decision the setting feeds, `path` the keys leading to
 * the setting's own value inside that record's `value` -- `[]` for the
 * value itself, `null` where the record holds no value of the setting (an
 * input-only knob such as `extra_bands`, which only shifts `nbnd`). */
export interface ResolvedIn {
  readonly record: string;
  readonly path: readonly string[] | null;
}

/** `tasks` are the tasks a setting applies to; a request for any other
 * task is refused. `steps`/`programs` are the steps (the names
 * `steps.<step>.<key>` takes) and programs a `per_step` setting applies to,
 * `null` for a `system` or `task` setting, which is set once per task.
 * `structure_specific` says whether a value is a judgement about the
 * structure it was set for (its elements, magnetism, geometry, size or
 * k-mesh) rather than a method, accuracy or job choice; opening another
 * structure clears it from the draft (#188). `resolved_in` is the only way
 * to its resolved value: a setting's key need not name its record or the
 * record's field (#187). */
export interface Setting {
  readonly key: string;
  readonly group: string;
  readonly type: string;
  readonly enum?: readonly string[];
  readonly unit: string | null;
  readonly default?: unknown;
  readonly enum_from?: string;
  readonly codes: readonly string[];
  readonly tasks: readonly string[];
  readonly steps: readonly string[] | null;
  readonly programs: readonly string[] | null;
  readonly scope: "system" | "task" | "per_step";
  readonly structure_specific: boolean;
  readonly resolved_in: ResolvedIn;
  readonly ml_target: string | null;
  readonly approaches: readonly Source[];
  readonly description: string;
}

export interface Fact {
  readonly key: string;
  readonly type: string;
  readonly values: readonly string[] | null;
  readonly ml_target: string | null;
  readonly approaches: readonly Source[];
  readonly overridable: boolean;
  readonly description: string;
}

export interface CodeInfo {
  readonly id: string;
  readonly name: string;
  readonly tasks: readonly string[];
}

export interface TaskInfo {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly codes: readonly string[];
  readonly step_count: number;
  readonly executables: readonly string[];
}

export interface PseudopotentialTable {
  readonly id: string;
  readonly provider: string;
  readonly version: string;
  readonly functional: string;
  readonly relativistic: string;
  readonly accuracy: string;
  readonly elements: readonly string[];
  readonly licence: string;
  readonly citation: string;
  readonly default: boolean;
}

export interface HpcProfile {
  readonly id: string;
  readonly name: string;
  readonly scheduler: string;
  readonly partitions: readonly string[];
}

export interface Capabilities {
  readonly core_version: string;
  readonly vocabulary_version: string;
  readonly codes: readonly CodeInfo[];
  readonly tasks: readonly TaskInfo[];
  readonly facts: readonly Fact[];
  readonly settings: readonly Setting[];
  readonly pseudopotential_tables: readonly PseudopotentialTable[];
  readonly hpc_profiles: readonly HpcProfile[];
  readonly models: readonly Readonly<Record<string, unknown>>[];
  readonly warnings: readonly AdvisorWarning[];
  readonly sources: readonly Source[];
}

/** `capabilities().vocabulary_version` this client was built against.
 * Bumped in lockstep with `capabilities.VOCABULARY_VERSION` -- guards
 * against exactly the failure mode that made this rewrite necessary:
 * a frontend build silently drifting from the backend contract it
 * talks to, discovered only by runtime breakage deep in a form. */
const SUPPORTED_VOCABULARY_VERSION = "5";

// ---------------------------------------------------------------------
// POST /inspect -- mirrors inputs/structure.py's `StructureInspection`.
// ---------------------------------------------------------------------

export interface SpeciesOccupancy {
  readonly symbol: string;
  readonly label: string;
  readonly occupancy: number;
  readonly oxidation_state: number | null;
}

export interface StructureSite {
  readonly fractional_coordinates: readonly [number, number, number];
  readonly cartesian_coordinates_angstrom: readonly [number, number, number];
  /** The site's label (a CIF's `_atom_site_label`), which keys
   * `starting_magnetization`. */
  readonly label: string;
  readonly species: readonly SpeciesOccupancy[];
}

export interface LatticeDocument {
  readonly vectors_angstrom: readonly [
    readonly [number, number, number],
    readonly [number, number, number],
    readonly [number, number, number],
  ];
  readonly lengths_angstrom: readonly [number, number, number];
  readonly angles_degrees: readonly [number, number, number];
  readonly volume_angstrom3: number;
}

export interface StructureDocument {
  readonly schema_version: number;
  readonly formula: string;
  readonly reduced_formula: string;
  readonly site_count: number;
  readonly lattice: LatticeDocument;
  readonly periodicity: readonly [boolean, boolean, boolean];
  readonly sites: readonly StructureSite[];
}

export interface StructureSourceDocument {
  readonly origin: "inline" | "path" | "generated";
  readonly name: string;
  readonly format: string;
  readonly content: string | null;
  readonly sha256: string | null;
  readonly size_bytes: number | null;
}

export interface StructureInspection {
  readonly source: StructureSourceDocument;
  readonly structure: StructureDocument;
  readonly canonical_cif: string;
  readonly schema_version: number;
}

// ---------------------------------------------------------------------
// POST /explain, POST /run -- mirror server/_handlers.py's return shapes.
// Neither carries a `schema_version` field (unlike /inspect): only
// `InlineStructureDocument`'s consumer (`normalize_structure(...)
// .inspection`) has ever set one.
// ---------------------------------------------------------------------

/** One step of a `RecordLayout`: its purpose (`scf`, `nscf`, `dos`,
 * `bands`, `relax`, `vc-relax`, `ph`, `q2r`, `phonon_dos`, `dispersion`)
 * and its records. A step without records, such as a band task's `bands_x`
 * or a phonon task's `d3hess`, has no entry. */
export interface StepLayout {
  readonly name: string;
  readonly records: readonly string[];
}

/** Mirrors `service.RecordLayout`: the tier and step of each record of a
 * response, by name (#187). `analysis` holds what the structure alone
 * decides, `system` what every step of the task shares, then each step's
 * own records in run order -- the task's one `job` with its first step, a
 * `dos` task's nscf decisions under their `nscf_` names, a `band` task's
 * bands-step path as `k_path` and its other decisions under their `bands_`
 * names, and a phonon task's `fft_grid` (and a relaxation's `relax`) with
 * its first step, then its `ph`, `q2r` and `phonon_dos` steps' records under
 * their own names and its `dispersion` step's path as `k_path`, the name
 * the band task's path has. Every record is in exactly one list. */
export interface RecordLayout {
  readonly analysis: readonly string[];
  readonly system: readonly string[];
  readonly steps: readonly StepLayout[];
}

/** One reason `/run` refuses a draft (`checks.Finding` on the wire, #151):
 * a stable `code`, the setting or fact keys it concerns (`fields`, as
 * `/capabilities` names them), the full `message`, the `summary` of the
 * decision it asks for (at most 200 characters, shown first, #223), and
 * `remedies`, each a complete override patch that resolves it, where `null`
 * clears that override. An `advice.blocked` finding names a decision that
 * could not be made, its root cause the message; it has no fields and no
 * remedy. */
export interface BlockingFinding {
  readonly code: string;
  readonly fields: readonly string[];
  readonly message: string;
  readonly summary: string;
  readonly remedies: readonly Readonly<Record<string, unknown>>[];
}

export interface ExplainResult {
  readonly records: Readonly<Record<string, ResolvedField>>;
  readonly warnings: readonly RecordWarning[];
  /** The findings `/run` would refuse to generate input files for (the
   * task's `check()` verdict, one per root cause in first-seen order);
   * empty when those checks pass. */
  readonly blocking: readonly BlockingFinding[];
  readonly layout: RecordLayout;
}

export interface RunResult {
  readonly files: readonly string[];
  readonly records: Readonly<Record<string, ResolvedField>>;
  readonly warnings: readonly RecordWarning[];
  readonly layout: RecordLayout;
}

// ---------------------------------------------------------------------
// POST /magnetic-orderings -- mirrors service/_magnetic_orderings.py's
// `report_to_json`/`candidate_to_json`. A candidate carries no structure
// of its own: its `overrides` (`{magnetic_ordering: label}`), merged on
// top of the draft's, generate it from the structure that was listed
// (`run`/`runArchive`), through the same magnetic step as
// `magnetic_ordering=afm` (#170).
// ---------------------------------------------------------------------

export interface MagneticOrderingCandidate {
  readonly label: string;
  readonly formula: string;
  readonly natoms: number;
  readonly energy_per_atom_ev: number | null;
  readonly status: string | null;
  readonly is_recommended: boolean;
  readonly overrides: Readonly<Record<string, unknown>>;
}

export interface MagneticOrderingsResult {
  readonly ranked: boolean;
  readonly candidates: readonly MagneticOrderingCandidate[];
  readonly warnings: readonly AdvisorWarning[];
}

/** A ranking job's status (`GET /magnetic-orderings/rank/{job_id}`, #261):
 * how many rankings are ahead of it while it waits, how many candidates
 * are relaxed while it runs (`null` before the relaxations start), then the
 * ranked listing or why it failed. */
export type RankingJob =
  | {
      readonly job_id: string;
      readonly state: "queued";
      readonly position: number;
    }
  | {
      readonly job_id: string;
      readonly state: "running";
      readonly progress: {
        readonly done: number;
        readonly total: number;
      } | null;
    }
  | {
      readonly job_id: string;
      readonly state: "done";
      readonly report: MagneticOrderingsResult;
    }
  | {
      readonly job_id: string;
      readonly state: "failed";
      readonly error: string;
    };

export interface ArchiveDownload {
  readonly blob: Blob;
  readonly filename: string;
}

export class CoreFailure extends Error {
  constructor(
    readonly kind: string,
    message: string,
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
  inspectStructure(input: StructureInput): Promise<StructureInspection>;
  /** Advice-only preview: never generates files, and still succeeds when
   * `run` would refuse with `advice_incomplete` (the tri-state
   * "diagnosis is always available" promise) -- `blocking` then lists
   * the findings `run` would refuse with. */
  explain(request: ComputeRequest): Promise<ExplainResult>;
  /** Lists candidate magnetic orderings (FM plus any AFM candidates),
   * unranked. Aborting `signal` abandons the request: the promise then
   * rejects with the abort reason (fetch's `AbortError`), not a
   * `CoreFailure`. The server still finishes the enumeration it started. */
  magneticOrderings(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<MagneticOrderingsResult>;
  /** Queues an mMACE ranking of the candidates by relaxed energy per atom;
   * resolves to the new job's status. `signal` as for `magneticOrderings`. */
  submitRanking(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<RankingJob>;
  /** The ranking job's status. A job the server does not hold (cancelled,
   * long finished, or from before a restart) rejects with a `CoreFailure`
   * of kind `unknown_ranking`. */
  rankingStatus(jobId: string, signal?: AbortSignal): Promise<RankingJob>;
  /** Cancels the ranking job: the server drops it, killing its process if
   * it runs. */
  cancelRanking(jobId: string): Promise<void>;
  /** Executes the pipeline and returns the JSON summary (file list +
   * records + warnings), not the files themselves. */
  run(request: ComputeRequest): Promise<RunResult>;
  /** Executes the pipeline and returns the generated input bundle as a
   * zip. Runs the pipeline a second time server-side -- there is no
   * single call that returns both the summary and the archive (v1's
   * multipart response is gone); callers that need both should call
   * `explain` for the summary/preview and `runArchive` only once the
   * user actually wants the files. */
  runArchive(request: ComputeRequest): Promise<ArchiveDownload>;
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
    const capabilities = await parseJson<Capabilities>(response);
    if (capabilities.vocabulary_version !== SUPPORTED_VOCABULARY_VERSION) {
      throw new CoreFailure(
        "incompatible_vocabulary",
        `Goldilocks Core reports vocabulary_version ${capabilities.vocabulary_version}, ` +
          `but this Workbench build expects ${SUPPORTED_VOCABULARY_VERSION}. ` +
          "The frontend and backend were built against different contracts -- " +
          "regenerate the Workbench's API types against this server.",
        { serverVocabularyVersion: capabilities.vocabulary_version },
      );
    }
    return capabilities;
  }

  async inspectStructure(input: StructureInput): Promise<StructureInspection> {
    const response = await this.request("/inspect", {
      body: JSON.stringify(input),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parseVersionedJson<StructureInspection>(response);
  }

  async explain(request: ComputeRequest): Promise<ExplainResult> {
    const response = await this.request("/explain", {
      body: JSON.stringify(request),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parseJson<ExplainResult>(response);
  }

  async magneticOrderings(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<MagneticOrderingsResult> {
    const response = await this.request("/magnetic-orderings", {
      body: JSON.stringify(request),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
      signal: signal ?? null,
    });
    return parseJson<MagneticOrderingsResult>(response);
  }

  async submitRanking(
    request: MagneticOrderingsRequest,
    signal?: AbortSignal,
  ): Promise<RankingJob> {
    const response = await this.request("/magnetic-orderings/rank", {
      body: JSON.stringify(request),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
      signal: signal ?? null,
    });
    return parseJson<RankingJob>(response);
  }

  async rankingStatus(
    jobId: string,
    signal?: AbortSignal,
  ): Promise<RankingJob> {
    const response = await this.request(
      `/magnetic-orderings/rank/${encodeURIComponent(jobId)}`,
      {
        headers: { Accept: "application/json" },
        method: "GET",
        signal: signal ?? null,
      },
    );
    return parseJson<RankingJob>(response);
  }

  async cancelRanking(jobId: string): Promise<void> {
    await this.request(
      `/magnetic-orderings/rank/${encodeURIComponent(jobId)}`,
      { method: "DELETE" },
    );
  }

  async run(request: ComputeRequest): Promise<RunResult> {
    const response = await this.request("/run", {
      body: JSON.stringify({ ...request, respond_with: "json" }),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parseJson<RunResult>(response);
  }

  async runArchive(request: ComputeRequest): Promise<ArchiveDownload> {
    const response = await this.request("/run", {
      body: JSON.stringify({ ...request, respond_with: "archive" }),
      headers: {
        Accept: "application/zip",
        "Content-Type": "application/json",
      },
      method: "POST",
    });
    return parseArchive(response, request);
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, init);
    } catch (error) {
      // The caller aborted it: neither a failure to reach Core nor one to
      // retry, so the abort reason propagates as fetch raised it.
      if (init.signal?.aborted) throw error;
      throw new CoreFailure(
        "network_error",
        error instanceof Error
          ? `Cannot reach Goldilocks Core: ${error.message}`
          : "Cannot reach Goldilocks Core.",
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
    throw invalidResponse(
      response.status,
      "returned an invalid JSON response",
      rawResponse,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw invalidResponse(response.status, "returned unreadable JSON");
  }
}

async function parseVersionedJson<T>(response: Response): Promise<T> {
  const payload = await parseJson<unknown>(response);
  requireSchemaVersion(payload, response.status);
  return payload as T;
}

function requireSchemaVersion(payload: unknown, status: number): void {
  if (
    payload === null ||
    typeof payload !== "object" ||
    !("schema_version" in payload) ||
    payload.schema_version !== 1
  ) {
    throw invalidResponse(
      status,
      "returned an incompatible schema version",
      payload,
    );
  }
}

async function ensureSuccess(response: Response): Promise<void> {
  if (response.ok) return;
  const rawResponse = await decodeResponse(response);
  if (isErrorEnvelope(rawResponse)) {
    const { error } = rawResponse;
    throw new CoreFailure(
      error.kind,
      error.message,
      error.details ?? {},
      response.status,
      rawResponse,
    );
  }
  throw new CoreFailure(
    "http_error",
    `The Goldilocks Core server rejected the request (${String(response.status)}).`,
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

/** The findings a refused `/run` (`advice_incomplete`) carries in its error
 * envelope's `details.findings` (#151): the same findings `/explain`
 * returns as its verdict. An entry that is not a finding is left out, and
 * any other failure has none. */
export function findingsOf(failure: CoreFailure): readonly BlockingFinding[] {
  const findings = failure.details.findings;
  return Array.isArray(findings) ? findings.filter(isBlockingFinding) : [];
}

function isBlockingFinding(value: unknown): value is BlockingFinding {
  return (
    value !== null &&
    typeof value === "object" &&
    "code" in value &&
    typeof value.code === "string" &&
    "message" in value &&
    typeof value.message === "string" &&
    "summary" in value &&
    typeof value.summary === "string" &&
    "fields" in value &&
    Array.isArray(value.fields) &&
    value.fields.every((field) => typeof field === "string") &&
    "remedies" in value &&
    Array.isArray(value.remedies) &&
    value.remedies.every(isOverridePatch)
  );
}

function isOverridePatch(
  value: unknown,
): value is Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// The wire error envelope, `{"error": ...}` (server/http.py's
// `expected_failure_handler`): `ExpectedFailure.public_error()`'s
// `{kind, message}`, plus `details` where a failure has structured data
// (`AdviceIncomplete.public_error()`'s findings, which `findingsOf` reads;
// the validation and readiness handlers add their own).
function isErrorEnvelope(value: unknown): value is {
  readonly error: {
    readonly kind: string;
    readonly message: string;
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

async function parseArchive(
  response: Response,
  request: ComputeRequest,
): Promise<ArchiveDownload> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("application/zip")) {
    throw invalidResponse(
      response.status,
      "returned an invalid archive response",
    );
  }
  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    throw invalidResponse(response.status, "returned unreadable archive data");
  }
  // No Content-Disposition header is sent (server/http.py's /run archive
  // branch returns a bare `Response(..., media_type="application/zip")`)
  // -- synthesize a reasonably informative name client-side instead.
  return { blob, filename: `${safeArchiveStem(request)}.zip` };
}

function safeArchiveStem(request: ComputeRequest): string {
  const name = request.structure_name.replace(/[^a-zA-Z0-9._-]+/g, "_");
  const task = request.task;
  return name.length > 0 ? `${name}-${task}` : `goldilocks-${task}`;
}

function invalidResponse(
  status: number,
  reason: string,
  rawResponse?: unknown,
): CoreFailure {
  return new CoreFailure(
    "invalid_response",
    `Goldilocks Core ${reason}.`,
    {},
    status,
    rawResponse,
  );
}
