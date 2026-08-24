import type { ComputationResult } from "../api/coreClient";
import { artifactDigest } from "./artifacts";

export function PseudopotentialReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
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
          <p>
            {table.provider} · {table.version ?? "unversioned"}
          </p>
        </div>
      </header>
      <div className="pseudo-table-id">
        <span>
          {table.functional} · {table.accuracy}
        </span>
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
              {digest === null ? null : (
                <code title={digest}>{digest.slice(0, 8)}</code>
              )}
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
