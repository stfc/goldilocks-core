import { useState } from "react";
import { Download, LoaderCircle } from "lucide-react";

import type { ComputationResult } from "../api/coreClient";
import { useWorkspace, useWorkspaceSnapshot } from "../workspace/useWorkspace";

type InputArtifact = NonNullable<
  ComputationResult["records"]["dft_input_data"]
>["artifacts"][number];

export function ReviewPanel() {
  const workspace = useWorkspace();
  const snapshot = useWorkspaceSnapshot();
  const result = snapshot.reviewed?.result ?? null;

  return (
    <aside
      className="review-panel"
      aria-label="Recommendation review"
      aria-live="polite"
      aria-busy={snapshot.operation === "compute"}
    >
      <header className="review-heading">
        <div>
          <span>03</span>
          <h2>Review</h2>
        </div>
        <span
          className={`review-state${snapshot.outOfDate ? " review-state--stale" : ""}`}
        >
          {result === null
            ? snapshot.operation === "compute"
              ? "Computing"
              : "Awaiting"
            : snapshot.outOfDate
              ? "Out of date"
              : "Current"}
        </span>
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
            <p>Evaluating Core Records and generating reproducible inputs.</p>
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
              Inspect a structure, review the scientific defaults, then compute
              reproducible DFT Input Data.
            </p>
          </div>
        )
      ) : (
        <>
          {snapshot.outOfDate ? (
            <div className="stale-banner">
              <strong>Review out of date</strong>
              <span>Recompute before creating an archive.</span>
            </div>
          ) : null}
          <RecommendationSummary result={result} />
          <RecordReview result={result} />
          <PseudoReview result={result} />
          <GeneratedInputReview result={result} />
          <Warnings result={result} />
          <section className="archive-card">
            <div>
              <span className="archive-card__label">Ready-to-run Output</span>
              <h3>Calculation archive</h3>
              <p>
                Inputs, selected UPFs, checksums, citations, and provenance.
              </p>
            </div>
            <button
              className="archive-action"
              type="button"
              disabled={snapshot.outOfDate || snapshot.operation !== null}
              onClick={() =>
                void workspace.dispatch({ type: "review.download" })
              }
            >
              {snapshot.operation === "download"
                ? "Building archive"
                : "Download .zip"}
              {snapshot.operation === "download" ? (
                <LoaderCircle
                  className="spinning-icon"
                  aria-hidden="true"
                  size={13}
                />
              ) : (
                <Download aria-hidden="true" size={13} />
              )}
            </button>
            {snapshot.lastDownload === null ? null : (
              <p
                className={`archive-receipt${snapshot.downloadOutOfDate ? " archive-receipt--stale" : ""}`}
              >
                {snapshot.downloadOutOfDate
                  ? "Previous archive is out of date"
                  : snapshot.lastDownload.filename}
              </p>
            )}
          </section>
        </>
      )}
    </aside>
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
        <span className="review-section__index">A</span>
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

function PseudoReview({ result }: { readonly result: ComputationResult }) {
  const inputData = result.records.dft_input_data;
  const selection = result.records.selection;
  if (inputData === undefined || selection === undefined) return null;
  const table = inputData.pseudopotential_set;
  return (
    <section className="review-section pseudo-review">
      <header>
        <span className="review-section__index">C</span>
        <div>
          <h3>Pseudopotentials</h3>
          <p>{table.provider} · {table.version ?? "unversioned"}</p>
        </div>
      </header>
      <div className="pseudo-table-id">
        <span>{table.functional} · {table.accuracy}</span>
        <code>{table.id}</code>
      </div>
      <ul className="pseudo-files">
        {selection.pseudopotentials.map((item) => {
          const digest = artifactDigest(inputData.artifacts, item.filename);
          return (
            <li key={item.element}>
              <span className="element-badge">{item.element}</span>
              <div>
                <strong>{item.filename ?? "Filename unavailable"}</strong>
                <span>
                  {item.relativistic ?? "unknown"} · {item.ecutwfc_ry ?? "—"} /{" "}
                  {item.ecutrho_ry ?? "—"} Ry
                </span>
              </div>
              {digest === null ? null : <code title={digest}>{digest.slice(0, 8)}</code>}
            </li>
          );
        })}
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

function GeneratedInputReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const files = result.records.generated_files ?? [];
  const file =
    files.find((candidate) => candidate.path === selectedPath) ?? files[0];
  return (
    <section className="review-section generated-review">
      <header>
        <span className="review-section__index">D</span>
        <div>
          <h3>Generated inputs</h3>
          <p>{files.length} deterministic files</p>
        </div>
      </header>
      {file === undefined ? (
        <p className="no-files">No generated input files.</p>
      ) : (
        <>
          <div className="file-tabs" role="group" aria-label="Generated input files">
            {files.map((candidate) => (
              <button
                key={candidate.path}
                type="button"
                aria-pressed={candidate.path === file.path}
                onClick={() => { setSelectedPath(candidate.path); }}
              >
                {candidate.path.split("/").at(-1)}
              </button>
            ))}
          </div>
          <div className="code-frame">
            <div>
              <span>{file.path}</span>
              {result.records.dft_input_data === undefined ? null : (
                <code>
                  {artifactDigest(
                    result.records.dft_input_data.artifacts,
                    file.path,
                  )?.slice(0, 10) ?? "unlisted"}
                </code>
              )}
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

function artifactDigest(
  artifacts: readonly InputArtifact[],
  filename: string | null,
): string | null {
  if (filename === null) return null;
  return (
    artifacts.find(
      (artifact) =>
        artifact.path === filename || artifact.path.endsWith(`/${filename}`),
    )?.sha256 ?? null
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
