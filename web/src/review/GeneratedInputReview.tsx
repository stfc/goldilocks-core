import { useState } from "react";

import type { ComputationResult } from "../api/coreClient";
import { artifactDigest } from "./artifacts";

export function GeneratedInputReview({
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
          <p>{files.length} files</p>
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
            {files.map((candidate) => (
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
