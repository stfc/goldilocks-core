// Typed failure vocabulary for the Core seam.
//
// `CoreFailure` is the only failure shape Workbench modules consume. The HTTP
// adapter (and any fake) is responsible for converting raw transport errors
// into this shape; nothing above the seam inspects HTTP status codes or raw
// bodies.

export type CoreFailureKind =
  | 'invalid_request'
  | 'stage_error'
  | 'not_found'
  | 'server_busy'
  | 'unavailable'
  | 'unexpected';

export interface CoreFailure {
  kind: CoreFailureKind;
  message: string;
  status: number;
  details: unknown;
  raw: unknown;
}

/** A structured transport failure envelope as produced by the backend. */
interface FailureEnvelope {
  error?: {
    kind?: string;
    message?: string;
    status?: number;
    details?: unknown;
  };
}

/** FastAPI's default validation error body (when the envelope is absent). */
interface ValidationDetailBody {
  detail?: Array<{ loc?: unknown; msg?: string; type?: string }>;
}

function isFailureEnvelope(value: unknown): value is FailureEnvelope {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as FailureEnvelope).error === 'object'
  );
}

/** True when a value is already a mapped ``CoreFailure``. */
function isCoreFailure(value: unknown): value is CoreFailure {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<CoreFailure>;
  return (
    typeof candidate.kind === 'string' &&
    typeof candidate.message === 'string' &&
    typeof candidate.status === 'number'
  );
}

function isValidationDetail(value: unknown): value is ValidationDetailBody {
  if (typeof value !== 'object' || value === null) return false;
  const detail = (value as ValidationDetailBody).detail;
  return (
    Array.isArray(detail) &&
    detail.length > 0 &&
    typeof detail[0] === 'object' &&
    detail[0] !== null
  );
}

function kindOf(raw: string | undefined): CoreFailureKind {
  switch (raw) {
    case 'invalid_request':
    case 'stage_error':
    case 'not_found':
    case 'server_busy':
    case 'unavailable':
    case 'unexpected':
      return raw;
    default:
      return 'unexpected';
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Unknown failure.';
}

/**
 * Convert an unknown failure source into a `CoreFailure`. Structured backend
 * envelopes are mapped field-by-field; anything else (network failures, thrown
 * errors, empty responses) becomes an `unavailable`/`unexpected` failure with
 * the original value preserved in `raw`.
 */
export function toCoreFailure(value: unknown): CoreFailure {
  // Idempotent: an already-mapped CoreFailure is passed through unchanged. The
  // adapter maps a transport failure once and throws it; a caller that catches
  // and re-normalises (e.g. the Workspace store) must not degrade a structured
  // failure into an opaque `unavailable`.
  if (isCoreFailure(value)) {
    return value;
  }
  if (isFailureEnvelope(value)) {
    const detail = value.error;
    return {
      kind: kindOf(detail?.kind),
      message: detail?.message ?? 'Unknown Core failure.',
      status: detail?.status ?? 0,
      details: detail?.details ?? null,
      raw: value,
    };
  }
  // FastAPI/Pydantic validation failures that reach the client without the
  // structured envelope (older backend, a proxy, or a strict schema) still
  // carry useful `loc`/`msg` diagnostics. Map them to invalid_request instead
  // of discarding them as an opaque `unavailable` failure.
  if (isValidationDetail(value)) {
    const items = value.detail ?? [];
    const first = items[0];
    const location = Array.isArray(first?.loc)
      ? first.loc.filter((part) => part !== 'body').join('.')
      : '';
    const message = first?.msg ?? 'Invalid request body.';
    return {
      kind: 'invalid_request',
      message: location ? `${message} at ${location}` : message,
      status: 422,
      details: items,
      raw: value,
    };
  }
  if (value instanceof Error) {
    return {
      kind: 'unavailable',
      message: value.message,
      status: 0,
      details: null,
      raw: value,
    };
  }
  return {
    kind: 'unavailable',
    message: messageOf(value),
    status: 0,
    details: null,
    raw: value,
  };
}

/** Build a local failure not produced by the transport (e.g. empty response). */
export function localFailure(
  kind: CoreFailureKind,
  message: string,
  details: unknown = null,
): CoreFailure {
  return { kind, message, status: 0, details, raw: null };
}
