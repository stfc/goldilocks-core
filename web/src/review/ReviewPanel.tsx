import { useState } from "react";
import { Download, LoaderCircle } from "lucide-react";

import type { Recommendation } from "../api/workbenchClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";

export function ReviewPanel() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const review = snapshot.review;

  return (
    <aside
      className="review-panel"
      aria-label="Recommendation review"
      aria-live="polite"
      aria-busy={snapshot.operation === "review"}
    >
      <header className="review-heading">
        <div>
          <span>03</span>
          <h2>Review</h2>
        </div>
        <span
          className={`review-state${snapshot.reviewStale ? " review-state--stale" : ""}`}
        >
          {review === null
            ? snapshot.operation === "review"
              ? "Computing"
              : "Awaiting"
            : snapshot.reviewStale
              ? "Stale"
              : "Current"}
        </span>
      </header>

      {review === null ? (
        snapshot.operation === "review" ? (
          <div className="review-empty review-empty--loading" role="status">
            <LoaderCircle
              className="spinning-icon"
              aria-hidden="true"
              size={18}
            />
            <strong>Computing recommendation</strong>
            <p>Evaluating Core records and generating reproducible inputs.</p>
          </div>
        ) : (
          <div className="review-empty">
            <div className="review-empty__diagram" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <strong>No recommendation yet</strong>
            <p>
              Inspect a structure, review the scientific defaults, then generate
              a reproducible calculation.
            </p>
          </div>
        )
      ) : (
        <>
          {snapshot.reviewStale ? (
            <div className="stale-banner">
              <strong>Review out of date</strong>
              <span>Recompute before creating an archive.</span>
            </div>
          ) : null}
          <RecommendationSummary review={review} />
          <RecordReview review={review} />
          <PseudoReview review={review} />
          <GeneratedInputReview review={review} />
          <Warnings review={review} />
          <section className="archive-card">
            <div>
              <span className="archive-card__label">Reproducible bundle</span>
              <h3>Calculation archive</h3>
              <p>
                Inputs, selected UPFs, checksums, citations, and provenance.
              </p>
            </div>
            <button
              className="archive-action"
              type="button"
              disabled={snapshot.reviewStale || snapshot.operation !== null}
              onClick={() =>
                void workspace.dispatch({ type: "archive.download" })
              }
            >
              {snapshot.operation === "archive"
                ? "Building archive"
                : "Download .zip"}
              {snapshot.operation === "archive" ? (
                <LoaderCircle
                  className="spinning-icon"
                  aria-hidden="true"
                  size={13}
                />
              ) : (
                <Download aria-hidden="true" size={13} />
              )}
            </button>
            {snapshot.archive === null ? null : (
              <p
                className={`archive-receipt${snapshot.archiveStale ? " archive-receipt--stale" : ""}`}
              >
                {snapshot.archiveStale
                  ? "Previous archive is stale"
                  : snapshot.archive.filename}
              </p>
            )}
          </section>
        </>
      )}
    </aside>
  );
}

function RecommendationSummary({
  review,
}: {
  readonly review: Recommendation;
}) {
  const wavefunction = maximum(
    review.selection.files.map((file) => file.ecutwfc_ry),
  );
  const density = maximum(
    review.selection.files.map((file) => file.ecutrho_ry),
  );
  return (
    <section className="review-section recommendation-summary">
      <header>
        <span className="review-section__index">A</span>
        <div>
          <h3>Recommended setup</h3>
          <p>{review.intent.functional} · Quantum ESPRESSO</p>
        </div>
      </header>
      <dl className="recommendation-metrics">
        <div>
          <dt>K-grid</dt>
          <dd>{review.decisions.k_grid.join(" × ")}</dd>
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
            {review.decisions.spin_polarized ? "Polarized" : "Unpolarized"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function RecordReview({ review }: { readonly review: Recommendation }) {
  const records = Object.entries(review.records);
  return (
    <section className="review-section record-review">
      <header>
        <span className="review-section__index">B</span>
        <div>
          <h3>Scientific records</h3>
          <p>{records.length} immutable results from Core</p>
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

function PseudoReview({ review }: { readonly review: Recommendation }) {
  const table = review.selection.table;
  return (
    <section className="review-section pseudo-review">
      <header>
        <span className="review-section__index">C</span>
        <div>
          <h3>Pseudopotentials</h3>
          <p>
            {table.provider} · {table.version}
          </p>
        </div>
      </header>
      <div className="pseudo-table-id">
        <span>{table.upstream_table}</span>
        <code>{table.id}</code>
      </div>
      <ul className="pseudo-files">
        {review.selection.files.map((file) => (
          <li key={file.sha256}>
            <span className="element-badge">{file.element}</span>
            <div>
              <strong>{file.filename}</strong>
              <span>
                {file.relativistic ?? "unknown"} · {file.ecutwfc_ry ?? "—"} /{" "}
                {file.ecutrho_ry ?? "—"} Ry
              </span>
            </div>
            <code title={file.sha256}>{file.sha256.slice(0, 8)}</code>
          </li>
        ))}
      </ul>
      <p className="licence-line">
        <span>Licence</span>
        <strong>{table.licence}</strong>
      </p>
      <details className="citation">
        <summary>Citation and provenance</summary>
        <p>{table.citation}</p>
      </details>
    </section>
  );
}

function GeneratedInputReview({ review }: { readonly review: Recommendation }) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const file =
    review.generated_files.find(
      (candidate) => candidate.path === selectedPath,
    ) ?? review.generated_files[0];
  return (
    <section className="review-section generated-review">
      <header>
        <span className="review-section__index">D</span>
        <div>
          <h3>Generated inputs</h3>
          <p>{review.generated_files.length} deterministic files</p>
        </div>
      </header>
      {file === undefined ? (
        <p className="no-files">No generated input files.</p>
      ) : (
        <>
          <div
            className="file-tabs"
            role="group"
            aria-label="Generated input files"
          >
            {review.generated_files.map((candidate) => (
              <button
                key={candidate.path}
                type="button"
                aria-pressed={candidate.path === file.path}
                onClick={() => {
                  setSelectedPath(candidate.path);
                }}
              >
                {candidate.path.split("/").at(-1)}
              </button>
            ))}
          </div>
          <div className="code-frame">
            <div>
              <span>{file.path}</span>
              <code>{file.sha256.slice(0, 10)}</code>
            </div>
            <pre aria-label={`Generated input ${file.path}`} tabIndex={0}>
              {file.content}
            </pre>
          </div>
        </>
      )}
    </section>
  );
}

function Warnings({ review }: { readonly review: Recommendation }) {
  const warnings = [
    ...new Set([
      ...review.warnings,
      ...review.selection.warnings,
      ...review.selection.files.flatMap((file) => file.warnings),
    ]),
  ];
  if (warnings.length === 0) return null;
  return (
    <section className="warning-list" aria-label="Scientific warnings">
      <h3>Review warnings</h3>
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
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return JSON.stringify(value);
}
