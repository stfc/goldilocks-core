// What the Workbench shows of the structure -> /explain -> preview /run
// pipeline, derived from a `WorkspaceSnapshot` alone. Every /explain and
// preview outcome is keyed by the structure and draft revision it was sent
// for (`PipelineKey`), and only the current draft's outcomes count: a failure
// or archive of an earlier draft or structure never decides what is shown,
// sent or saved (#150).
import type {
  ArchiveDownload,
  BlockingFinding,
  CoreFailure,
  ExplainResult,
} from "../api/coreClient";
import { findingsOf } from "../api/coreClient";
import type {
  PipelineOutcome,
  WorkspaceOperation,
  WorkspaceSnapshot,
} from "./workspace";

function ofCurrentDraft<T>(
  snapshot: WorkspaceSnapshot,
  outcome: PipelineOutcome<T> | null,
): PipelineOutcome<T> | null {
  if (outcome === null) return null;
  const { input, revision } = outcome.key;
  return input === snapshot.structureInput && revision === snapshot.revision
    ? outcome
    : null;
}

/** How the current draft's `/explain` settled, or null while it has no
 * outcome (not sent yet, or in flight). */
export function currentExplain(
  snapshot: WorkspaceSnapshot,
): PipelineOutcome<ExplainResult> | null {
  return ofCurrentDraft(snapshot, snapshot.explain);
}

/** How the current draft's preview `/run` settled, or null while it has no
 * outcome. */
export function currentPreview(
  snapshot: WorkspaceSnapshot,
): PipelineOutcome<ArchiveDownload> | null {
  return ofCurrentDraft(snapshot, snapshot.preview);
}

/** The archive fetched for the current draft, or null until it arrives. The
 * generated-inputs preview shows it, and `review.download` saves it and
 * nothing else. */
export function currentArchive(
  snapshot: WorkspaceSnapshot,
): ArchiveDownload | null {
  const preview = currentPreview(snapshot);
  return preview?.status === "result" ? preview.value : null;
}

/** The findings of the current draft (#151): its `/explain` verdict's, or,
 * while that verdict lets it through, those its refused preview `/run`
 * returned. The Bundle card lists them, each control their `fields` name
 * shows them, and their remedies patch the draft. */
export function currentFindings(
  snapshot: WorkspaceSnapshot,
): readonly BlockingFinding[] {
  const explain = currentExplain(snapshot);
  if (explain?.status === "result" && explain.value.blocking.length > 0) {
    return explain.value.blocking;
  }
  const preview = currentPreview(snapshot);
  return preview?.status === "failure" ? findingsOf(preview.failure) : [];
}

/** Whether the current draft's `/explain` is due: a structure is open,
 * nothing is in flight and the draft has no outcome yet. A failure is an
 * outcome, so it is not sent again until the draft changes or Retry clears
 * it. */
export function explainDue(snapshot: WorkspaceSnapshot): boolean {
  return (
    snapshot.structureInput !== null &&
    snapshot.draft !== null &&
    snapshot.operation === null &&
    currentExplain(snapshot) === null
  );
}

/** Whether the current draft's preview `/run` is due: its recommendation
 * arrived with an empty `blocking` verdict, nothing is in flight and no
 * preview has settled for it. A draft whose verdict blocks never gets a
 * `/run`. */
export function previewDue(snapshot: WorkspaceSnapshot): boolean {
  const explain = currentExplain(snapshot);
  return (
    snapshot.operation === null &&
    explain?.status === "result" &&
    explain.value.blocking.length === 0 &&
    currentPreview(snapshot) === null
  );
}

/** A failure the workspace holds, and the operation `failure.retry` sends
 * again for it. */
export interface WorkspaceFailure {
  readonly operation: WorkspaceOperation;
  readonly failure: CoreFailure;
}

interface RecordedFailure {
  readonly failure: CoreFailure;
  readonly dismissed: boolean;
}

function failed<T>(outcome: PipelineOutcome<T> | null): RecordedFailure | null {
  return outcome?.status === "failure" ? outcome : null;
}

/** The failure recorded for `operation`, dismissed or not: loading
 * capabilities, the last structure that could not be opened, or the current
 * draft's `/explain` or preview. */
export function recordedFailure(
  snapshot: WorkspaceSnapshot,
  operation: WorkspaceOperation,
): RecordedFailure | null {
  switch (operation) {
    case "capabilities":
      return snapshot.startupFailure === null
        ? null
        : { failure: snapshot.startupFailure, dismissed: false };
    case "inspect":
      return snapshot.inspectFailure === null
        ? null
        : { failure: snapshot.inspectFailure.failure, dismissed: false };
    case "explain":
      return failed(currentExplain(snapshot));
    case "preview":
      return failed(currentPreview(snapshot));
  }
}

const BANNER_ORDER = [
  "capabilities",
  "inspect",
  "explain",
  "preview",
] as const satisfies readonly WorkspaceOperation[];

/** The failure the banner shows: the first undismissed one of loading
 * capabilities, opening a structure, and the current draft's `/explain` and
 * preview. Every failure offers Retry. */
export function bannerFailure(
  snapshot: WorkspaceSnapshot,
): WorkspaceFailure | null {
  for (const operation of BANNER_ORDER) {
    const recorded = recordedFailure(snapshot, operation);
    if (recorded !== null && !recorded.dismissed) {
      return { operation, failure: recorded.failure };
    }
  }
  return null;
}

/** Where the open structure's current draft is on its way to input files.
 * `computing` and `recomputing` wait for its recommendation (without and
 * with an earlier one on screen), `generating` for its archive; `blocked`
 * is a recommendation whose `/explain` verdict refuses input generation. */
export type BundleStatus =
  | { readonly kind: "empty" }
  | { readonly kind: "computing" }
  | { readonly kind: "recomputing" }
  | { readonly kind: "explainFailed"; readonly failure: CoreFailure }
  | {
      readonly kind: "blocked";
      readonly findings: readonly BlockingFinding[];
    }
  | { readonly kind: "generating" }
  | { readonly kind: "generationFailed"; readonly failure: CoreFailure }
  | { readonly kind: "ready"; readonly archive: ArchiveDownload };

export function bundleStatus(snapshot: WorkspaceSnapshot): BundleStatus {
  if (snapshot.structureInput === null) return { kind: "empty" };
  const explain = currentExplain(snapshot);
  if (explain === null) {
    return { kind: snapshot.reviewed === null ? "computing" : "recomputing" };
  }
  if (explain.status === "failure") {
    return { kind: "explainFailed", failure: explain.failure };
  }
  if (explain.value.blocking.length > 0) {
    return { kind: "blocked", findings: explain.value.blocking };
  }
  const preview = currentPreview(snapshot);
  if (preview === null) return { kind: "generating" };
  return preview.status === "result"
    ? { kind: "ready", archive: preview.value }
    : { kind: "generationFailed", failure: preview.failure };
}

/** Whether Download can save the current draft's archive. */
export interface DownloadState {
  readonly enabled: boolean;
  /** Why Download is disabled; null while it is enabled. */
  readonly reason: string | null;
}

export function downloadState(snapshot: WorkspaceSnapshot): DownloadState {
  const status = bundleStatus(snapshot);
  return status.kind === "ready"
    ? { enabled: true, reason: null }
    : { enabled: false, reason: disabledReason(status) };
}

function disabledReason(
  status: Exclude<BundleStatus, { readonly kind: "ready" }>,
): string {
  switch (status.kind) {
    case "empty":
      return "Load a structure to generate input files.";
    case "computing":
      return "Waiting for the recommendation.";
    case "recomputing":
      return "Waiting for the recommendation for the current settings.";
    case "explainFailed":
      return `The recommendation for the current settings failed: ${status.failure.message}`;
    case "blocked":
      return `Input files cannot be generated for the current settings: ${summaries(status.findings)}`;
    case "generating":
      return "Generating the input files for the current settings.";
    case "generationFailed": {
      const findings = findingsOf(status.failure);
      return `Input generation failed for the current settings: ${findings.length === 0 ? status.failure.message : summaries(findings)}`;
    }
  }
}

/** The findings' summaries: the full messages are the Bundle card's, behind
 * each finding's details toggle (#223). */
function summaries(findings: readonly BlockingFinding[]): string {
  return findings.map((finding) => finding.summary).join(" ");
}

/** Whether something waits for the user: capabilities or a structure that
 * could not be loaded, or a current draft whose recommendation or input
 * generation failed (dismissed or not) or whose verdict refuses it. */
export function needsAttention(snapshot: WorkspaceSnapshot): boolean {
  if (snapshot.startupFailure !== null || snapshot.inspectFailure !== null) {
    return true;
  }
  const { kind } = bundleStatus(snapshot);
  return (
    kind === "explainFailed" ||
    kind === "blocked" ||
    kind === "generationFailed"
  );
}
