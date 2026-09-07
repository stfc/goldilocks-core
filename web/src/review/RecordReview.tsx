import { Accordion, Code, Group, Stack, Text, Title } from "@mantine/core";

import type { ComputationResult } from "../api/coreClient";
import { ScientificRecord } from "./ScientificRecord";

export function RecordReview({
  result,
}: {
  readonly result: ComputationResult;
}) {
  const records = Object.entries(result.records);
  return (
    <Stack component="section" gap="xs" miw={0}>
      <Group component="header" justify="space-between">
        <Title order={3}>Scientific records</Title>
        <Text size="sm" c="dimmed">
          {records.length} records
        </Text>
      </Group>
      <Accordion multiple order={4}>
        {records.map(([name, value]) => (
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
              <Accordion order={5} mt="sm">
                <Accordion.Item value="json">
                  <Accordion.Control>
                    Raw {readableName(name)} record (JSON)
                  </Accordion.Control>
                  <Accordion.Panel>
                    <Code
                      block
                      role="region"
                      mah={400}
                      tabIndex={0}
                      aria-label={`Raw ${readableName(name)} record`}
                    >
                      {JSON.stringify(value, null, 2)}
                    </Code>
                  </Accordion.Panel>
                </Accordion.Item>
              </Accordion>
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
