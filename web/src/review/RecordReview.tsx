import { Accordion, Code, Group, Stack, Text, Title } from "@mantine/core";

import type { ComputationResult } from "../api/coreClient";
import { ScientificRecord } from "./ScientificRecord";

export function RecordReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const records = Object.keys(result.records);
  return (
    <Stack component="section" gap="xs" miw={0}>
      <Group component="header" justify="space-between">
        <Title order={3}>Scientific records</Title>
        <Text size="sm" c="dimmed">
          {records.length} records
        </Text>
      </Group>
      <Accordion multiple order={4}>
        {records.map((name) => (
          <Accordion.Item key={name} value={name} className="record-card">
            <Accordion.Control>
              <Group justify="space-between">
                <span>{readableName(name)}</span>
                <Code>{name}</Code>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <ScientificRecord
                name={name as keyof ComputationResult["records"]}
                result={result}
              />
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </Stack>
  );
}

function readableName(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
