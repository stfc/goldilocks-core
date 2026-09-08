import { Group, Stack, Tabs, Text, Title } from "@mantine/core";
import { useState } from "react";

import type { ComputationResult } from "../api/coreClient";
import { artifactMetadata } from "./artifacts";
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
    <Stack component="section" gap="xs" miw={0}>
      <Group component="header" justify="space-between">
        <Title order={3}>Generated inputs</Title>
        <Text size="sm" c="dimmed">
          {files.length} files
        </Text>
      </Group>
      {file === undefined ? (
        <Text c="dimmed">No generated input files.</Text>
      ) : (
        <Tabs value={file.path} onChange={setSelectedPath}>
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
                      : (artifactMetadata(inputData.manifest, file.path)
                          ?.sha256 ?? null)
                  }
                />
              ) : null}
            </Tabs.Panel>
          ))}
        </Tabs>
      )}
    </Stack>
  );
}
