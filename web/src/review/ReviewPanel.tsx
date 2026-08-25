import { ArrowLeft, Download, LoaderCircle } from "lucide-react";

import type { ComputationResult } from "../api/coreClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";
import { GeneratedInputReview } from "./GeneratedInputReview";
import { PseudopotentialReview } from "./PseudopotentialReview";
import "./ReviewPanel.css";

export function ReviewPanel({
  onShowStructure,
}: {
  readonly onShowStructure: () => void;
}) {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const result = snapshot.reviewed?.result ?? null;

  return (
    <section
      id="recommendation-panel"
      className="review-panel"
      aria-label="Recommendation results"
      aria-busy={snapshot.operation === "compute"}
    >
      <header className="review-heading">
        <div>
          <span>03</span>
          <h2>Recommendation</h2>
        </div>
        <button
          className="panel-navigation"
          type="button"
          aria-label="Back to structure"
          onClick={onShowStructure}
        >
          <ArrowLeft aria-hidden="true" size={15} />
          Structure
        </button>
      </header>

      {result === null ? (
        snapshot.operation === "compute" ? (
          <div className="review-empty review-empty--loading" role="status">
            <LoaderCircle
              className="spinning-icon"
              aria-hidden="true"
              size={18}
            />
            <strong>Computing recommendation</strong>
          </div>
        ) : (
          <div className="review-empty">
            <div className="review-empty__diagram" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <strong>No recommendation</strong>
          </div>
        )
      ) : (
        <>
          {snapshot.outOfDate ? (
            <div
              className="stale-banner"
              role="status"
              aria-label="Recommendation notice"
              aria-live="polite"
              aria-atomic="true"
            >
              <p>
                Your settings changed. Update the recommendation before
                downloading.
              </p>
            </div>
          ) : null}
          <div className="download-bar">
            <button
              className="download-action"
              type="button"
              disabled={
                snapshot.reviewed?.archive == null ||
                snapshot.outOfDate ||
                snapshot.operation !== null
              }
              onClick={() =>
                void workspace.dispatch({ type: "review.download" })
              }
            >
              Download input files (.zip)
              <Download aria-hidden="true" size={14} />
            </button>
            {snapshot.lastDownload === null || snapshot.outOfDate ? null : (
              <p
                className="archive-receipt"
                role="status"
                aria-label="Archive status"
                aria-live="polite"
              >
                {snapshot.lastDownload.filename} is ready
              </p>
            )}
          </div>
          <GeneratedInputReview result={result} />
          <RecommendationSummary result={result} />
          <PseudopotentialReview result={result} />
          <RecordReview result={result} />
          <Warnings result={result} />
        </>
      )}
    </section>
  );
}

function RecommendationSummary({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const selected = result.records.selection?.pseudopotentials ?? [];
  const wavefunction = maximum(
    selected.map((item) => item.ecutwfc_ry),
  );
  const density = maximum(selected.map((item) => item.ecutrho_ry));
  const intent = result.draft.intent;
  return (
    <section className="review-section recommendation-summary">
      <header>
        <span className="review-section__index">B</span>
        <div>
          <h3>Recommended setup</h3>
          <p>{intent.functional} · Quantum ESPRESSO</p>
        </div>
      </header>
      <dl className="recommendation-metrics">
        <div>
          <dt>K-grid</dt>
          <dd>{result.records.k_points?.grid.join(" × ") ?? "Not returned"}</dd>
        </div>
        <div>
          <dt>Wavefunction</dt>
          <dd>
            {wavefunction === null
              ? "Table default"
              : `${String(wavefunction)} Ry`}
          </dd>
        </div>
        <div>
          <dt>Charge density</dt>
          <dd>
            {density === null ? "Table default" : `${String(density)} Ry`}
          </dd>
        </div>
        <div>
          <dt>Spin</dt>
          <dd>
            {result.records.advice?.magnetism.spin_polarized
              ? "Polarized"
              : "Unpolarized"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function RecordReview({ result }: { readonly result: ComputationResult }) {
  const records = Object.entries(result.records);
  return (
    <section className="review-section record-review">
      <header>
        <span className="review-section__index">D</span>
        <div>
          <h3>Scientific records</h3>
          <p>{records.length} records</p>
        </div>
      </header>
      <div className="record-list">
        {records.map(([name, value]) => (
          <details key={name} className="record-card">
            <summary>
              <span>{readableName(name)}</span>
              <code>{name}</code>
            </summary>
            <RecordValue value={value} />
          </details>
        ))}
      </div>
    </section>
  );
}

function RecordValue({ value }: { readonly value: unknown }) {
  if (value === null || typeof value !== "object") {
    return <p className="record-scalar">{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    return <pre className="record-json">{JSON.stringify(value, null, 2)}</pre>;
  }
  return (
    <dl className="record-facts">
      {Object.entries(value).map(([key, fact]) => (
        <div key={key}>
          <dt>{readableName(key)}</dt>
          <dd>{formatFact(fact)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Warnings({ result }: { readonly result: ComputationResult }) {
  const selection = result.records.selection;
  const warnings = [
    ...new Set([
      ...result.warnings,
      ...(selection?.warnings ?? []),
      ...(selection?.pseudopotentials.flatMap((item) => item.warnings) ?? []),
    ]),
  ];
  if (warnings.length === 0) return null;
  return (
    <section
      className="warning-list"
      role="status"
      aria-label="Scientific warnings"
      aria-live="polite"
      aria-atomic="true"
    >
      <h3>Warnings</h3>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </section>
  );
}

function maximum(values: readonly (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0 ? null : Math.max(...present);
}

function readableName(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatFact(value: unknown): string {
  if (value === null) return "—";
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return JSON.stringify(value);
}
