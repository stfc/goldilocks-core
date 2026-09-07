import { Tabs } from "@mantine/core";
import { useState } from "react";

import type { ComputationResult } from "../api/coreClient";
import { artifactDigest } from "./artifacts";
import { GeneratedInputPreview } from "./GeneratedInputPreview";

export function GeneratedInputReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const files = result.records.generated_files ?? [];
  const file =
    files.find((candidate) => candidate.path === selectedPath) ?? files[0];
  const inputData = result.records.dft_input_data;
  return (
    <section className="review-section generated-review">
      <header>
        <span className="review-section__index">A</span>
        <div>
          <h3>Generated inputs</h3>
          <p>{files.length} files</p>
        </div>
      </header>
      {file === undefined ? (
        <p className="no-files">No generated input files.</p>
      ) : (
        <Tabs
          value={file.path}
          onChange={setSelectedPath}
          classNames={{ list: "file-tabs", tab: "file-tabs__tab" }}
        >
          <Tabs.List aria-label="Generated input files">
            {files.map((candidate) => (
              <Tabs.Tab key={candidate.path} value={candidate.path}>
                {candidate.path.split("/").at(-1)}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          {files.map((candidate) => (
            <Tabs.Panel key={candidate.path} value={candidate.path}>
              {candidate.path === file.path ? (
                <GeneratedInputPreview
                  path={file.path}
                  content={file.content}
                  digest={
                    inputData === undefined
                      ? undefined
                      : artifactDigest(inputData.artifacts, file.path)
                  }
                />
              ) : null}
            </Tabs.Panel>
          ))}
        </Tabs>
      )}
    </section>
  );
}
